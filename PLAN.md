# Plan: DQ with AI — Data Quality Application

## Context

Business users need to run recurring data quality checks on large CSV datasets without knowing SQL. The application accepts natural language rule instructions, uses a local Ollama LLM to convert them to SQL, executes the SQL via DuckDB against the CSVs, and produces HTML reports. Table joins are defined visually via dropdown conditions (no LLM involved). Designed for an air-gapped Windows 10 laptop running Anaconda — no internet required after setup.

---

## Tech Stack

| Concern | Choice | Reason |
|---|---|---|
| GUI | Tkinter | Ships with Anaconda/Python, no extra packages, sufficient widget set |
| SQL Engine | DuckDB | Reads 8GB CSVs via lazy views without loading into Python memory |
| LLM Client | `requests` (stdlib) | Simple POST to Ollama REST API; no SDK needed |
| Templating | Jinja2 | Included in Anaconda; clean HTML templates separate from logic |
| Persistence | JSON | Human-readable, zero extra dependencies |

---

## Folder / File Structure

```
dq_with_ai/
├── main.py                    # Entry point; folder checks; launches App
├── app.py                     # Root Tk window; tab orchestration; workflow routing
├── ui/
│   ├── workflow_launcher.py   # Startup dialog: list saved workflows + New/Run/Edit actions
│   ├── file_loader.py         # File picker + per-file options + field selector + CSV preview
│   ├── filter_editor.py       # Pre-join and post-join filter panels
│   ├── join_editor.py         # Visual join builder (dropdowns, no LLM)
│   ├── derived_fields_editor.py  # Derived fields panel (computed columns from joined_table)
│   ├── rule_editor.py         # Rule list; NL per rule → LLM → SQL → run all
│   └── report_viewer.py       # Show output paths; "Open in browser" + "Open CSV" buttons
├── core/
│   ├── db.py                  # DuckDB: register CSVs as views, filters, join, rules, export
│   ├── llm.py                 # Ollama client: NL→SQL with system prompt (rules only)
│   ├── rules.py               # Run all rules; return RuleResult dataclasses
│   └── reporter.py            # Jinja2 HTML + violation CSV generation
├── persistence/
│   └── workflow_store.py      # save/load_all for workflows JSON files (overwrites by name)
├── templates/
│   ├── summary.html.j2
│   └── detail.html.j2
├── config/
│   └── settings.json          # Ollama endpoint, model, paths, system prompts
├── data/                      # User drops CSVs here
├── workflows/                 # Saved workflow JSON files (one per named workflow)
├── rules/                     # Legacy saved DQ rule JSON files (no longer written by app)
├── joins/                     # Legacy saved join rule JSON files (no longer written by app)
└── reports/                   # Generated HTML, violation CSVs, joined CSV export
```

---

## Startup and Workflow Flow

On launch, `WorkflowLauncher` appears as a modal dialog before any tab is accessible:

- **+ New Workflow** → enables tab 1, user walks through all tabs manually
- **Run** (saved workflow) → headless background execution (load files → filters → join → derived fields → rules) with a progress dialog; lands on Reports tab
- **Edit** (saved workflow) → same DB operations in background, then all tabs pre-populated; lands on tab 6 (Rules)

After rules run, user is prompted to save/overwrite the workflow by name. All six steps are captured in one JSON file.

## Tab Flow (New Workflow path)

```
1. Load Files → 2. Pre-Join Filters → 3. Define Join → 4. Post-Join Filters → 5. Derived Fields → 6. Define Rules → 7. Reports
```

Each tab is disabled until the preceding step completes. "Next" navigation buttons sit at the top-right of each panel.

---

## Core Module Responsibilities

### `core/db.py`

**CSV registration:**
- `get_csv_sample_values(path, *, encoding, delimiter, engine, n_rows=200, n_distinct=3)` → `(list[str], dict[str, list[str]])` — single `SELECT * LIMIT n_rows` query; returns column names plus up to 3 distinct non-empty sample values per column
- `detect_date_columns(path, *, encoding, delimiter, engine, date_format="Auto")` → `list[str]` — public helper that runs `_detect_date_columns` against the file and returns names of columns passing the threshold; used to pre-populate the per-column type picker in `FieldSelectorDialog`
- `register_csv(name, path, *, encoding, delimiter, engine, date_format="Auto", selected_columns=None, column_types=None)` → lazy DuckDB view with:
  - Columns filtered to `selected_columns` if provided; otherwise all columns used
  - All columns read as VARCHAR first (`all_varchar=true`) to prevent type misdetection
  - `column_types` dict maps original column name → type string (`"VARCHAR"`, `"Auto"`, `"YYYY-MM-DD"`, `"DD/MM/YYYY"`, `"MM/DD/YYYY"`, `"DD/MM/YYYY HH:MM:SS"`, `"MM/DD/YYYY HH:MM:SS"`, `"DD-MM-YYYY"`, `"NUMERIC"`, `"CURRENCY"`); columns with an explicit override skip date auto-detection entirely
  - Columns without any override in `column_types` fall through to `_detect_date_columns` with the file-level `date_format` (backward compat for old workflows where `column_types` is absent)
  - `NUMERIC` → `TRY_CAST(col AS DOUBLE)`; `CURRENCY` → `TRY_CAST(col AS DECIMAL(18,2))`; date formats → `_date_exprs(col, fmt)`; `VARCHAR` → no cast
  - All columns renamed `tablename_fieldname` immediately at view creation — globally unique across tables
  - Base SELECT SQL stored in `_table_base_sql[name]` for filter reapplication
- `_type_cast_expr(col, type)` → cast SQL fragment for `"numeric"` (DOUBLE) and `"currency"` (DECIMAL(18,2))
- `_DATE_FORMAT_TYPES` — module-level set of all valid date format strings; used in `register_csv` to detect date overrides
- `_date_exprs(col, fmt)` → `(detect_condition, cast_expression)` — maps a format name to the DuckDB SQL fragments used for detection and view creation; supports `Auto` / `YYYY-MM-DD` (`TRY_CAST`), `DD/MM/YYYY`, `MM/DD/YYYY`, `DD/MM/YYYY HH:MM:SS`, `MM/DD/YYYY HH:MM:SS` (`COALESCE` of timestamp + date strptime), `DD-MM-YYYY`
- `_detect_date_columns(con, safe_path, columns, opts, date_format)` → `dict[str, str]` — returns `{col: cast_expression}` for columns that exceed the threshold; previously returned `set[str]`

**Filtering:**
- `get_column_types(table_name)` → `{col_name: 'date' | 'numeric' | 'currency' | 'string'}` from `DESCRIBE` — DuckDB type `DATE` → `'date'`; `DOUBLE` → `'numeric'`; `DECIMAL(...)` → `'currency'`; everything else → `'string'`
- `apply_filters(filters)` — rebuilds each individual table's view as `SELECT * FROM (base_sql) WHERE <conditions>`; tables with no active filters are restored to bare `base_sql`
- `apply_join_filters(filters)` — stores conditions in `_join_filter_conditions`; calls `_rebuild_joined_table`
- `_build_filter_condition(f)` (static) — generates a single SQL WHERE fragment from a filter dict:
  - `is_empty` / `is_not_empty`: `(field IS NULL OR field = '')` / `(field IS NOT NULL AND field != '')` — no value needed; handled before the empty-value guard
  - `equals` / `not_equals`: exact string match; `not_equals` includes `OR field IS NULL`
  - `contains` / `not_contains`: LIKE/NOT LIKE with `*`→`%`, `?`→`_` wildcard translation
  - `select` / `not_select`: IN / NOT IN with comma-separated value list
  - `earlier_than` / `later_than` / `between`: `CAST(... AS DATE)` comparisons (user inputs ISO `YYYY-MM-DD`; column is already typed DATE in the view)
  - `greater_than` / `less_than`: `TRY_CAST(field AS DOUBLE) > val` / `< val` — for NUMERIC and CURRENCY columns
  - `between_numeric`: `TRY_CAST(field AS DOUBLE) BETWEEN val AND val2` — emitted by `FilterRow.get_filter()` when field type is numeric/currency and operator is "between"

**Derived fields:**
- `apply_derived_fields(derived)` — stores `(name, expression)` pairs in `_join_derived_exprs`; calls `_rebuild_joined_table`
- `_rebuild_joined_table()` — always rebuilds `joined_table` from `_join_base_sql` in a fixed sequence: apply WHERE filter conditions, then SELECT \* plus derived column expressions; ensures re-running either step never loses the other

**Join and rules:**
- `execute_join(sql)` → stores `_join_base_sql = sql`; resets `_join_filter_conditions` and `_join_derived_exprs`; creates `joined_table` view
- `execute_rule(sql)` → returns `(cols, rows)` of violating rows
- `get_preview(table, n=100)` → `(cols, rows)`
- `get_joined_preview(n=100)` → delegates to `get_preview("joined_table", n)`
- `get_joined_row_count()` → `int` — `SELECT COUNT(*) FROM joined_table`
- `export_joined_csv(path)` → `COPY (SELECT * FROM joined_table) TO path`

### `core/llm.py`
- Reads Ollama config from `settings.json`
- `translate_rule(nl, col_hints)` → SQL string (rules only; joins no longer use LLM)
- POSTs to `/api/chat` with a `messages` list (`role: system` + `role: user`); `stream: false`; hardcoded `options`: `temperature: 0`, `num_predict: 200`, `stop: [";", "```", "\n\n"]` (the `options` block in `settings.json` is not read by `LLMClient`)
- `_call(system_prompt, user_message)` → extracts raw text from `data["message"]["content"]`, calls `_extract_sql` internally, and returns the extracted SQL string (or `None`)
- `_extract_sql(text)` → `str | None` — post-processes the raw LLM response:
  1. Strips ` ```sql ` and ` ``` ` fences via `re.sub`
  2. Finds the first `\bSELECT\b` match; returns `None` if absent
  3. Truncates at the first `;` (not last) to discard anything following the statement
  4. Returns `None` if the result contains more than one `SELECT` (rejects back-to-back queries)
  5. Replaces `REGEX_LIKE` → `REGEXP_MATCHES` (case-insensitive) — `REGEX_LIKE` does not exist in DuckDB; LLM occasionally hallucinates this MySQL/Oracle name
- `_validate_sql_columns(sql, valid_columns)` → `bool` — extracts SAP-style column candidates matching `\bPA\w+\b` and checks each against the set of uppercased valid column names; prints a rejection message and returns `False` on the first unknown candidate
- `translate_rule` contains the retry loop: up to 5 attempts; calls `_call` (which internally calls `_extract_sql`); validates `SELECT` guard; validates column names via `_validate_sql_columns`; sleeps 5 s between failed attempts; raises `LLMConnectionError` after all attempts are exhausted
- Full debug logging printed to terminal: URL, model, prompt, raw response, extracted SQL
- Raises `LLMConnectionError` on unreachable endpoint or timeout

### `core/rules.py`
- `RuleResult` dataclass: `{name, nl_description, sql, violation_count, columns, violating_rows}`
- `run_all_rules(rules, db)` → `list[RuleResult]`

### `core/reporter.py`
- `generate_summary(results, total_rows, output_dir, templates_dir)` → timestamped HTML path; passes `total_rows` to the template for context
- `generate_detail(result, max_rows, output_dir, templates_dir)` → timestamped HTML path; truncates displayed rows to `max_rows` (from `config["ui"]["report_max_detail_rows"]`)
- `generate_violation_csv(result, output_dir)` → timestamped CSV path (`violations_<rule>_<timestamp>.csv`); writes all violating rows with no row cap; uses stdlib `csv`

### `persistence/workflow_store.py`
- `save(workflow, workflows_dir)` → writes `workflows/<safe_name>.json`; overwrites if same name; sets `created_at` on first save, always updates `updated_at`
- `load_all(workflows_dir)` → list of all workflow dicts sorted by `updated_at` descending

### Legacy persistence
- `join_store.py` and `rule_store.py` have been deleted from the codebase; legacy `joins/` and `rules/` directories remain on disk but are no longer written by the app

---

## UI Module Responsibilities

### `ui/file_loader.py`
- `get_file_configs(base_dir)` → list of `{name, path (relative to base_dir), encoding, delimiter, engine, date_format, selected_columns, column_types}` for workflow save
- `populate_from_workflow(file_configs, base_dir)` → updates Listbox and preview tabs without re-registering CSVs (used by the Edit path after DB setup is done in the background thread); reads `date_format` with `"Auto"` fallback and `column_types` with `{}` fallback for old workflows
- `FileOptionsDialog` — modal popup per file: encoding, delimiter (Comma/Tab/Semicolon/Pipe), engine (C/Python), date format (Auto / YYYY-MM-DD / DD/MM/YYYY / MM/DD/YYYY / DD/MM/YYYY HH:MM:SS / MM/DD/YYYY HH:MM:SS / DD-MM-YYYY) — date format here is the detection hint used to pre-populate the per-column type picker
- `FieldSelectorDialog` — shown after options are confirmed; rebuilt as a scrollable canvas of per-row widgets (replaces single Listbox):
  - Each row: checkbox (include/exclude) + column name + sample values label + type dropdown
  - Type dropdown values: `VARCHAR`, `Auto`, `YYYY-MM-DD`, `DD/MM/YYYY`, `MM/DD/YYYY`, `DD/MM/YYYY HH:MM:SS`, `MM/DD/YYYY HH:MM:SS`, `DD-MM-YYYY`, `NUMERIC`, `CURRENCY`
  - Detected date columns pre-populated with the file-level date format (from `FileOptionsDialog`); all other columns pre-populated with `VARCHAR`
  - **Select All** / **Clear All** buttons; validates at least 1 field selected
  - `result`: `list[str]` of selected column names; `column_types`: `dict[str, str]` of col → type for selected columns
  - Accepts `detected_dates: set` and `default_date_format: str` constructor params
- Load flow: options dialog → `db.detect_date_columns()` + `db.get_csv_sample_values(n_rows=5000, n_distinct=16)` → field/type selector → `db.register_csv(..., column_types=..., selected_columns=...)`
- After registration, builds `distinct_values` dict (`tablename_fieldname → sorted list`) for every selected column that yielded ≤ 15 distinct values in the 5 000-row sample; stored in `_loaded_files[name]["distinct_values"]`; `n_distinct=16` (limit+1) lets the caller detect "too many" without reading more of the file
- `FieldSelectorDialog` preview label shows `vals[:3]` even though the sample now collects up to 16 distinct values
- `_proceed` merges `distinct_values` across all loaded files and passes the merged dict as the second argument to the `on_loaded` callback
- Loaded files list shows `name  [enc=..., delim=..., engine=..., fields=N/M]`; appends `dfmt=...` when date format is not Auto
- Preview Treeview uses pixel-width columns (`len(col) * 9`) with `stretch=False` + horizontal scrollbar

### `ui/filter_editor.py`
Contains two panels that share `FilterRow`:

**`FilterRow`** — one row per field:
- Accepts optional `distinct_values: list[str]` constructor param; stored as `self._distinct_values`
- Checkbox enables/disables the filter; operator and value inputs are grayed out when disabled
- Operator options depend on field type:
  - String: `contains`, `not contains`, `equals`, `not equals`, `select`, `not select`, `is empty`, `is not empty`
  - Date: `earlier than`, `later than`, `between`, `is empty`, `is not empty`
  - Numeric / Currency: `greater than`, `less than`, `between`, `equals`, `not equals`, `is empty`, `is not empty`
- Value area rebuilds on operator change:
  - is empty / is not empty → label `(no value needed)`, no entry
  - equals / not equals → `state="readonly"` Combobox pre-populated with `distinct_values` if available (VARCHAR fields with ≤ 15 distinct values from the load-time sample); falls back to plain Entry when `distinct_values` is empty
  - contains / not contains → Entry + wildcard hint `(* = any chars, ? = one char)`
  - select / not select → Entry + `(comma-separated)` hint
  - earlier/later than → Entry + `YYYY-MM-DD` hint
  - greater than / less than → plain Entry (numeric value)
  - between (date) → two Entries joined by "to" + `YYYY-MM-DD` hint
  - between (numeric/currency) → two Entries joined by "to", no hint label
- `_set_val_state`: when re-enabling a Combobox child, sets `state="readonly"` (not `"normal"`) to preserve the read-only constraint
- `get_filter()` emits operator key `between_numeric` (not `between`) when field type is numeric/currency and operator is "between"; `_KEY_OP` maps `between_numeric` → `"between"` for pre-population on Edit path
- All value reads use `self._val1` / `self._val2` (StringVar) — `get_filter()` and `load_filters()` work identically for both Entry and Combobox since both bind to the same StringVar

**`FilterEditorFrame`** (tab 2 — Pre-Join Filters):
- Scrollable canvas of `FilterRow` widgets grouped by table name with bold section headers
- "Next: Define Join →" button at top-right
- `set_tables(table_names, distinct_values=None)` — accepts pre-computed distinct values dict; passes `distinct_values.get(field, [])` to each string-type `FilterRow`
- On proceed: calls `db.apply_filters(filters)` — rebuilds each individual table's view
- `load_filters(filters)` — pre-populates from saved workflow (matches by field name, sets operator + values)

**`PostJoinFilterFrame`** (tab 4 — Post-Join Filters):
- Same structure as `FilterEditorFrame`; `set_joined_table(table_names, distinct_values=None)` queries `joined_table` and groups fields by `tablename_` prefix; accepts the same pre-computed `distinct_values` dict from the file load step
- "Next: Derived Fields →" button at top-right
- On proceed: calls `db.apply_join_filters(filters)` — stores conditions; `_rebuild_joined_table` applies them
- `load_filters(filters)` — same pre-population logic as `FilterEditorFrame`

### `ui/derived_fields_editor.py`
Contains `_build_expression` plus two classes:

**`_build_expression(op, inputs)`** — translates a category/operation/inputs dict into a DuckDB SQL expression string. Supports 19 operations across 5 categories:
- String: `Concatenate`, `Upper`, `Lower`, `Length`, `Substring`
- Date: `Extract Year`, `Extract Month`, `Extract Day`, `Days between`, `Months between`, `Years between`; date-diff ops accept `TODAY` on either side (mapped to `CURRENT_DATE`)
- Numeric: `Add`, `Subtract`, `Multiply`, `Divide`, `Round` (second operand is a field or a numeric literal)
- Conditional: `If / Then / Else` → `CASE WHEN field op 'val' THEN 'x' ELSE 'y' END`
- Regex: `Match` → `CAST(regexp_matches(...) AS VARCHAR)`, `Extract` → `regexp_extract(...)`, `Replace` → `regexp_replace(...)`; all use native DuckDB functions, no extensions required

**`DerivedFieldRow`** — one row per derived field:
- Checkbox enables/disables the row; all inputs grayed out when disabled
- Output name Entry (pre-filled `derived_N`)
- Category Combobox → Operation Combobox (values update on category change)
- Dynamic input area rebuilt on operation change (field pickers, text entries, operator selector)
- "Adv" Checkbutton — hides the builder inputs and shows a free-form DuckDB expression Entry

**`DerivedFieldsEditorFrame`** (tab 5 — Derived Fields):
- Scrollable canvas with 3 initial `DerivedFieldRow` widgets; "+ Add Field" appends more
- "Next: Define Rules →" button at top-right
- On proceed: calls `db.apply_derived_fields(derived)` — stores expressions; `_rebuild_joined_table` appends them as `SELECT *, expr AS "name" FROM (...)`
- Rule editor field list is populated **after** this step so derived columns appear in it
- `load_derived_fields(derived_list)` — restores each field in Adv mode using saved expression string; expands rows list if needed

### `ui/join_editor.py`
- No LLM. SQL is generated directly from dropdown selections.
- User picks the **master table** from a dropdown; remaining tables become secondaries in load order
- "Next: Post-Join Filters →" navigation button at top-right of the panel
- `get_join_config()` returns `{tables, master, sql, conditions}`; the `conditions` list saves raw per-secondary condition data for UI reconstruction in the Edit path
- `load_join_config(config)` — sets master (fires `_rebuild_rules()` trace synchronously), then clears default condition rows and restores saved ones for each `JoinRuleWidget`
- One `JoinRuleWidget` per secondary table, stacked vertically:
  - Label: `Rule N: <accumulated_left> LEFT JOIN <secondary>`
  - One or more `ConditionRow`: `[AND/OR?] [left_col ▼] [operator ▼] [right_col ▼] [×]`
  - Left-col dropdown shows only accumulated columns (master + all previously joined secondaries)
  - Right-col dropdown shows only the current secondary's columns
  - Each non-first condition has its own AND/OR selector
- Rules area wrapped in a Canvas with horizontal scrollbar
- Condition row combobox widths auto-sized from longest field name (capped at 60 chars)
- Generated SQL is printed to terminal for visibility before execution
- Persisted join config stores `{tables, master, sql}`; no `nl_instruction`

### `ui/workflow_launcher.py`
- `WorkflowLauncher` modal `Toplevel`: shown on every startup; lists workflows with Run/Edit buttons; "New Workflow" skips straight to tab 1; closing the dialog is equivalent to New Workflow

### `ui/rule_editor.py`
- "Next: Reports →" navigation button at top-right of the panel; enabled as soon as any rule has SQL (same condition as "Run All Rules")
- "Available fields (joined_table)" LabelFrame:
  - "Filter by table:" Combobox — filters listbox to fields with `tablename_` prefix; "All tables" shows everything
  - Scrollable Listbox in Courier 11 font
  - Populated with `joined_table` columns **after** derived fields are applied (so derived columns appear)
- Rule list Listbox uses `exportselection=False` to prevent selection loss on focus change
- LLM translation: calls `llm.translate_rule(nl, col_hints)` in a background thread; retry logic (5 attempts, SELECT guard, column validation, 5 s sleep) is encapsulated inside `translate_rule` — the UI layer only handles success (show SQL) or exception (show error dialog)
- "Regenerate" re-invokes `translate_rule` if the user wants a fresh attempt
- **SQL box is editable**: kept in `tk.NORMAL` state with no key binding. Users can hand-edit LLM-generated SQL directly in the box; "Save SQL to Rule" is the explicit commit step. Background is `white` to visually signal editability. (Note: an earlier implementation used `<Key>` returning `"break"` to make it read-only without triggering macOS colour overrides — that constraint no longer applies since editability is the desired behaviour.)
- **joined_table preview**: Treeview at the bottom of the right panel (same scrollbar pattern as Define Join); populated by `_refresh_preview()` called from `set_fields()` — reflects the final joined + filtered + derived column set

---

## Configuration Schema (`config/settings.json`)

```json
{
  "version": 1,
  "ollama": {
    "endpoint": "http://localhost:11434",
    "model": "my_qwen",
    "timeout_seconds": 60,
    "options": { "temperature": 0.1, "top_p": 0.9 },
    "system_prompt_rule": "You are a DuckDB SQL generator. ..."
  },
  "paths": {
    "data_dir": "data",
    "rules_dir": "rules",
    "joins_dir": "joins",
    "reports_dir": "reports",
    "workflows_dir": "workflows"
  },
  "ui": {
    "preview_row_limit": 100,
    "report_max_detail_rows": 10000
  }
}
```

Notes:
- `ollama.options` is present in `settings.json` but is **not read by `LLMClient`**; the payload options (`temperature: 0`, `num_predict: 200`, stop tokens) are hardcoded in `llm.py`
- `system_prompt_join` has been removed from `settings.json` (joins are now built visually)

System prompts are in config so they can be tuned without touching code.

---

## Persistence Schemas

**`workflows/<name>.json`** (primary — replaces separate join/rule files):
```json
{
  "version": 1,
  "name": "HR Monthly Check",
  "created_at": "2026-06-11T...",
  "updated_at": "2026-06-11T...",
  "files": [
    {
      "name": "PA0000",
      "path": "data/PA0000.csv",
      "encoding": "utf-8",
      "delimiter": ",",
      "engine": "C",
      "date_format": "DD/MM/YYYY",
      "selected_columns": ["PA0000_PERNR", "PA0000_EMAIL", "PA0000_GBDAT", "PA0000_SALARY"],
      "column_types": {
        "PA0000_PERNR": "VARCHAR",
        "PA0000_EMAIL": "VARCHAR",
        "PA0000_GBDAT": "DD/MM/YYYY",
        "PA0000_SALARY": "CURRENCY"
      }
    }
  ],
  "pre_join_filters": [
    {"field": "PA0000_STATUS", "table": "PA0000", "operator": "select", "value": "A,I", "value2": ""}
  ],
  "join": {
    "tables": ["PA0000", "PA0001"],
    "master": "PA0000",
    "sql": "SELECT * FROM \"PA0000\"\nLEFT JOIN \"PA0001\" ON ...",
    "conditions": [
      {
        "secondary": "PA0001",
        "conditions": [{"bool_op": null, "left": "PA0000_PERNR", "op": "=", "right": "PA0001_PERNR"}]
      }
    ]
  },
  "post_join_filters": [],
  "derived_fields": [
    {"name": "age", "expression": "DATEDIFF('year', \"PA0002_GBDAT\", CURRENT_DATE)"}
  ],
  "rules": [
    {"name": "null_email", "nl_description": "...", "sql": "SELECT * FROM joined_table WHERE PA0000_EMAIL IS NULL"}
  ]
}
```

File paths are stored relative to the project root (`base_dir`) so the workflow JSON is portable if the project folder is moved.

**Legacy files** (`joins/join_<timestamp>.json`, `rules/rules_<timestamp>.json`) — still present on disk from earlier sessions but no longer written or read by the app.

---

## Key Design Decisions

- **8GB CSV handling**: CSVs are registered as DuckDB views (`read_csv_auto`), never loaded into Python. JOIN result is also a view until explicitly exported. Only violating rows (small subset) are returned to Python for rendering.
- **Column renaming on load**: Every field is renamed `tablename_fieldname` at view creation. This makes all column names globally unique across tables, eliminating ambiguity in join conditions and rule SQL without needing table qualifiers.
- **Field selection at load time**: Users choose which columns to include per file via `FieldSelectorDialog`. Sample values (up to 3 distinct per column) are shown as a preview to guide selection. Only selected columns are included in the registered view.
- **Two-stage filtering**: Pre-join filters operate on individual table views (rebased from `_table_base_sql`). Post-join filters operate on `joined_table` (rebased from `_join_base_sql`). Both use the same `_build_filter_condition` logic. Re-applying filters always starts from the stored base SQL, preventing condition stacking across sessions.
- **Derived fields layer**: After post-join filtering, users can define computed columns (String / Date / Numeric / Conditional / Regex categories, 19 operations, plus a free-form DuckDB expression fallback). Expressions are stored in `_join_derived_exprs` and appended by `_rebuild_joined_table` as a second wrapping SELECT, so re-running post-join filters never loses derived columns. Date-diff operations accept `TODAY` on either side; `date_ref` in `_build_expression` maps the string `"TODAY"` to `CURRENT_DATE`.
- **`_rebuild_joined_table` as single source of truth**: Both `apply_join_filters` and `apply_derived_fields` delegate to this method, which always rebuilds the full `joined_table` view from `_join_base_sql` → WHERE filter → derived SELECT. This prevents any ordering dependency between the two steps.
- **Visual join builder (no LLM for joins)**: Joins are defined via dropdown conditions (left field / operator / right field) rather than natural language. This is deterministic, instant, and avoids LLM reliability issues for a structured operation.
- **LLM only for rules**: The LLM (Ollama `my_qwen`) is used only to translate natural language DQ rules into SQL. The SQL is always shown to the user before execution. A "Regenerate" button allows re-prompting.
- **`/api/chat` instead of `/api/generate`**: Using the chat endpoint with a `messages` array (system + user roles) prevents KV context bleed between calls — `/api/generate` carries a `context` token array in its response that bleeds prior state into subsequent requests. Temperature is hardcoded to `0` in the payload `options` to eliminate stochastic sampling; `num_predict: 200` and stop tokens `[";", "```", "\n\n"]` keep output short and terminate at natural SQL boundaries.
- **LLM retry on invalid SQL**: The retry loop lives inside `translate_rule` (not in the UI layer). `_call` posts to the Ollama API and internally calls `_extract_sql`, returning the extracted SQL (or `None`). The retry loop validates: the returned SQL must be non-None; it must start with `SELECT`; `_validate_sql_columns` must pass. Failure on any check sleeps 5 s and retries, up to 5 total attempts. Connection/timeout errors abort immediately. `LLMConnectionError` is raised after all attempts are exhausted.
- **`_validate_sql_columns` for SAP column hallucination**: Qwen was generating syntactically valid SQL referencing column names that do not exist in `joined_table` (memorised SAP infotype fields from training data). `_validate_sql_columns` extracts all `\bPA\w+\b` token candidates (SAP-style column names) and rejects the SQL if any are absent from the valid column set, triggering a retry.
- **`_extract_sql` hardening**: Strips fences via `re.sub` (not `re.search` on fence content, which missed unclosed fences); truncates at the *first* semicolon (not last) to prevent accepting two statements; returns `None` (not empty string) on extraction failure so callers can distinguish no-SQL from empty-SQL; rejects output containing more than one `SELECT` to prevent paired wrong+correct query responses from slipping through.
- **Workflow as single unit of persistence**: All six steps (files, pre-join filters, join, post-join filters, derived fields, rules) are saved together in one named JSON. Overwrite-on-save keeps the `workflows/` directory clean. The old separate `joins/` and `rules/` saves are legacy.
- **Run vs Edit paths**: The Run path is fully headless — DB operations in a background thread, progress dialog, lands on Reports. The Edit path does the same DB setup in a background thread, then populates all tab UIs on the main thread; user lands on tab 6 and can adjust anything.
- **Relative file paths in workflow JSON**: Stored as `os.path.relpath(abs_path, base_dir)` so workflows survive a folder rename or move.
- **Violation CSV per rule**: Generated alongside the HTML detail report; no row cap (unlike the HTML which has `report_max_detail_rows`). Users can open directly in Excel for full investigation.
- **Background threads**: Long DuckDB operations run in `threading.Thread`; results posted back via `self.after(0, ...)` to keep Tkinter responsive. Exception variables captured as lambda defaults (`lambda e=exc: ...`) to avoid Python 3 closure scoping bugs.
- **Per-file load options**: Encoding, delimiter, engine, and date format are specified per file at load time via a modal dialog, accommodating mixed-encoding or non-standard CSV sources.
- **Per-file date format**: The date format in `FileOptionsDialog` is now a detection hint only — it drives `detect_date_columns()` to pre-populate the per-column type picker. The authoritative type for each column is the value stored in `column_types` in the workflow JSON. Old workflows without `column_types` fall through to the original file-level auto-detection path unchanged.
- **Per-column type selection**: Users set each column's type individually in `FieldSelectorDialog` via a dropdown: `VARCHAR`, any date format, `NUMERIC`, or `CURRENCY`. All fields default to `VARCHAR` or the detected date format; users must explicitly promote a column to `NUMERIC` or `CURRENCY`. This prevents numeric-looking SAP codes (e.g., cost centre, infotype) from being misinterpreted as numbers. `NUMERIC` casts to `DOUBLE`; `CURRENCY` casts to `DECIMAL(18,2)` (no thousands separator or symbol stripping required since source data doesn't use them).
- **Filter operators extended**: `is empty` / `is not empty` (both String and Date) check `IS NULL OR = ''`; no value entry required. `equals` / `not equals` provide exact single-value matching as an alternative to the multi-value `select` operator. `greater than` / `less than` / `between` added for NUMERIC and CURRENCY columns; `between` on a numeric/currency field emits the `between_numeric` operator key so `_build_filter_condition` uses `TRY_CAST(... AS DOUBLE)` comparisons rather than DATE comparisons.
- **LLM regex function correction**: `_extract_sql` silently replaces `REGEX_LIKE` → `REGEXP_MATCHES` after extraction. `REGEX_LIKE` does not exist in DuckDB; the LLM occasionally hallucinates it from MySQL/Oracle training data. The system prompt was also updated with an explicit DuckDB regex function reference (`REGEXP_MATCHES`, `REGEXP_LIKE`, `REGEXP_EXTRACT`) and a worked example to reduce the hallucination at the source.
- **Filter dropdown for low-cardinality VARCHAR columns**: When `equals` or `not equals` is selected on a string field with ≤ 15 distinct values, the value input becomes a `state="readonly"` Combobox showing the known values. Values are collected at file-load time from a 5 000-row sample (`get_csv_sample_values(n_rows=5000, n_distinct=16)`); querying `n_distinct=16` (limit+1) lets the caller detect "too many" without reading more. This avoids any additional DB queries when the filter panel opens — critical for 4 GB source files where a full `SELECT DISTINCT` on a CSV view would stream the entire file. Derived columns and the Edit path receive no distinct values and fall back to plain Entry. The same dict is reused for both Pre-Join and Post-Join filter panels, stored in `App._wf_distinct_values`.

---

## Verification

### New workflow path
1. Launch app — `WorkflowLauncher` appears (no saved workflows → only "+ New Workflow" shown)
2. Click "+ New Workflow" → tab 1 enabled
3. Load two CSVs (set encoding/delimiter/engine; pick a subset of fields); confirm preview shows only the selected `tablename_fieldname` columns
4. In Pre-Join Filters: enable a `contains` filter on a string field; for a string field with few values (e.g. STATUS), switch to `equals` — confirm a Combobox appears with the known values; select one and confirm the filter applies correctly; enable a date range filter; confirm "Next: Define Join →" proceeds
5. In Define Join: select master table; define conditions; execute; confirm joined table preview; "Next: Post-Join Filters →" is enabled
6. In Post-Join Filters: enable a filter on a joined field; confirm "Next: Derived Fields →" proceeds
7. In Derived Fields: test each category (String, Date with TODAY, Numeric, Conditional, Regex, Adv); "Next: Define Rules →" populates field list with derived columns
8. In Define Rules: add 2–3 NL rules; translate; save SQL; confirm "Next: Reports →" enables as soon as first SQL is saved; click it; confirm violation counts
9. In Reports: for each rule, confirm both "Open HTML Report" and "Open Violation CSV" work; confirm CSV contains all violation rows with correct header
10. When prompted, save the workflow under a name; confirm `workflows/<name>.json` is created

### Run path
11. Restart app — `WorkflowLauncher` shows saved workflow; click **Run**; confirm progress dialog shows steps; confirm reports match Step 8

### Edit path
12. Restart app; click **Edit** on the saved workflow; confirm all tabs pre-populated (filters checked, join conditions restored, derived fields shown in Adv mode, rules loaded); modify one rule; run all; save workflow; confirm JSON is overwritten (check `updated_at`)

### Large-file test
13. Test with a large CSV (≥500MB) and confirm the app remains responsive during execution on both Run and New Workflow paths
