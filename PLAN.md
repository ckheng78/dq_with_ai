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
│   ├── workflow_store.py      # save/load_all for workflows JSON files (overwrites by name)
│   ├── join_store.py          # Legacy — no longer called by main app
│   └── rule_store.py          # Legacy — no longer called by main app
├── templates/
│   ├── summary.html.j2
│   └── detail.html.j2
├── config/
│   └── settings.json          # Ollama endpoint, model, paths, system prompts
├── data/                      # User drops CSVs here
├── workflows/                 # Saved workflow JSON files (one per named workflow)
├── rules/                     # Legacy saved DQ rule JSON files
├── joins/                     # Legacy saved join rule JSON files
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
- `get_csv_columns(path, *, encoding, delimiter, engine)` → `list[str]` — reads column headers via `DESCRIBE` without registering the table
- `get_csv_sample_values(path, *, encoding, delimiter, engine, n_rows=200, n_distinct=3)` → `(list[str], dict[str, list[str]])` — single `SELECT * LIMIT n_rows` query; returns column names plus up to 3 distinct non-empty sample values per column
- `register_csv(name, path, *, encoding, delimiter, engine, selected_columns=None)` → lazy DuckDB view with:
  - Columns filtered to `selected_columns` if provided; otherwise all columns used
  - All columns read as VARCHAR first (`all_varchar=true`) to prevent type misdetection
  - Each column auto-detected for DATE via `TRY_CAST` sampling (≥80% of non-empty values must parse)
  - All columns renamed `tablename_fieldname` immediately at view creation — globally unique across tables
  - Encoding, delimiter, and engine (C = standard / Python = `ignore_errors=true`) passed through to DuckDB
  - Base SELECT SQL stored in `_table_base_sql[name]` for filter reapplication

**Filtering:**
- `get_column_types(table_name)` → `{col_name: 'date' | 'string'}` from `DESCRIBE`
- `apply_filters(filters)` — rebuilds each individual table's view as `SELECT * FROM (base_sql) WHERE <conditions>`; tables with no active filters are restored to bare `base_sql`
- `apply_join_filters(filters)` — stores conditions in `_join_filter_conditions`; calls `_rebuild_joined_table`
- `_build_filter_condition(f)` (static) — generates a single SQL WHERE fragment from a filter dict:
  - `contains` / `not_contains`: LIKE/NOT LIKE with `*`→`%`, `?`→`_` wildcard translation
  - `select` / `not_select`: IN / NOT IN with comma-separated value list
  - `earlier_than` / `later_than` / `between`: `CAST(... AS DATE)` comparisons

**Derived fields:**
- `apply_derived_fields(derived)` — stores `(name, expression)` pairs in `_join_derived_exprs`; calls `_rebuild_joined_table`
- `_rebuild_joined_table()` — always rebuilds `joined_table` from `_join_base_sql` in a fixed sequence: apply WHERE filter conditions, then SELECT \* plus derived column expressions; ensures re-running either step never loses the other

**Join and rules:**
- `execute_join(sql)` → stores `_join_base_sql = sql`; resets `_join_filter_conditions` and `_join_derived_exprs`; creates `joined_table` view
- `execute_rule(sql)` → returns `(cols, rows)` of violating rows
- `get_preview(table, n=100)` → `(cols, rows)`
- `export_joined_csv(path)` → `COPY (SELECT * FROM joined_table) TO path`

### `core/llm.py`
- Reads Ollama config from `settings.json`
- `translate_rule(nl, col_hints)` → SQL string (rules only; joins no longer use LLM)
- POSTs to `/api/chat` with a `messages` list (`role: system` + `role: user`); `stream: false`; hardcoded `options`: `temperature: 0`, `num_predict: 200`, `stop: [";", "```", "\n\n"]`
- Raw text extracted from `data["message"]["content"]` (not `data["response"]`)
- `_extract_sql(text)` → `str | None` — post-processes the raw LLM response:
  1. Strips ` ```sql ` and ` ``` ` fences via `re.sub`
  2. Finds the first `\bSELECT\b` match; returns `None` if absent
  3. Truncates at the first `;` (not last) to discard anything following the statement
  4. Returns `None` if the result contains more than one `SELECT` (rejects back-to-back queries)
- `_validate_sql_columns(sql, valid_columns)` → `bool` — extracts SAP-style column candidates matching `\bPA\w+\b` and checks each against the set of uppercased valid column names; prints a rejection message and returns `False` on the first unknown candidate
- `translate_rule` contains the retry loop: up to 5 attempts; calls `_call` then `_extract_sql`; validates `SELECT` guard; validates column names via `_validate_sql_columns`; sleeps 5 s between failed attempts; raises `LLMConnectionError` after all attempts are exhausted
- Full debug logging printed to terminal: URL, model, prompt, raw response, extracted SQL
- Raises `LLMConnectionError` on unreachable endpoint or timeout

### `core/rules.py`
- `RuleResult` dataclass: `{name, nl_description, sql, violation_count, violating_rows}`
- `run_all_rules(rules, db)` → `list[RuleResult]`

### `core/reporter.py`
- `generate_summary(results, output_dir)` → timestamped HTML path
- `generate_detail(result, output_dir)` → timestamped HTML path
- `generate_violation_csv(result, output_dir)` → timestamped CSV path (`violations_<rule>_<timestamp>.csv`); writes all violating rows with no row cap; uses stdlib `csv`

### `persistence/workflow_store.py`
- `save(workflow, workflows_dir)` → writes `workflows/<safe_name>.json`; overwrites if same name; sets `created_at` on first save, always updates `updated_at`
- `load_all(workflows_dir)` → list of all workflow dicts sorted by `updated_at` descending

### `persistence/join_store.py` / `rule_store.py` (legacy)
- No longer called by the main app; kept for reference only

---

## UI Module Responsibilities

### `ui/file_loader.py`
- `get_file_configs(base_dir)` → list of `{name, path (relative to base_dir), encoding, delimiter, engine, selected_columns}` for workflow save
- `populate_from_workflow(file_configs, base_dir)` → updates Listbox and preview tabs without re-registering CSVs (used by the Edit path after DB setup is done in the background thread)
- `FileOptionsDialog` — modal popup per file: encoding, delimiter (Comma/Tab/Semicolon/Pipe), engine (C/Python)
- `FieldSelectorDialog` — shown after options are confirmed; lists all CSV columns in a multi-select Listbox with up to 3 distinct sample values per row for preview; **Select All** / **Clear All** buttons; validates at least 1 field selected; columns are shown as `{name:<padded>  "val1",  "val2",  "val3"`
- Load flow: options dialog → `db.get_csv_sample_values()` → field selector → `db.register_csv(..., selected_columns=...)`
- Loaded files list shows `name  [enc=..., delim=..., engine=..., fields=N/M]`
- Preview Treeview uses pixel-width columns (`len(col) * 9`) with `stretch=False` + horizontal scrollbar

### `ui/filter_editor.py`
Contains two panels that share `FilterRow`:

**`FilterRow`** — one row per field:
- Checkbox enables/disables the filter; operator and value inputs are grayed out when disabled
- Operator options depend on field type:
  - String: `contains`, `not contains`, `select`, `not select`
  - Date: `earlier than`, `later than`, `between`
- Value area rebuilds on operator change:
  - contains / not contains → Entry + wildcard hint `(* = any chars, ? = one char)`
  - select / not select → Entry + `(comma-separated)` hint
  - earlier/later than → Entry + `YYYY-MM-DD` hint
  - between → two Entries joined by "to" + `YYYY-MM-DD` hint

**`FilterEditorFrame`** (tab 2 — Pre-Join Filters):
- Scrollable canvas of `FilterRow` widgets grouped by table name with bold section headers
- "Next: Define Join →" button at top-right
- On proceed: calls `db.apply_filters(filters)` — rebuilds each individual table's view
- `load_filters(filters)` — pre-populates from saved workflow (matches by field name, sets operator + values)

**`PostJoinFilterFrame`** (tab 4 — Post-Join Filters):
- Same structure as `FilterEditorFrame`; `set_joined_table(table_names)` queries `joined_table` and groups fields by `tablename_` prefix
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
    "system_prompt_join": "(unused — joins are now built visually)",
    "system_prompt_rule": "You are a DuckDB SQL generator. You output one SELECT statement and nothing else. No explanation. No markdown. No preamble. No comments. No extra conditions. Only the exact SQL that answers the user request.\n\nExample:\nUser: find all records where STATUS = 'A'\nSQL: SELECT * FROM joined_table WHERE STATUS = 'A'\n\nNow generate SQL for the user request below. Output only the SQL."
  },
  "paths": {
    "data_dir": "data",
    "rules_dir": "rules",
    "joins_dir": "joins",
    "reports_dir": "reports"
  },
  "ui": {
    "preview_row_limit": 100,
    "report_max_detail_rows": 10000
  }
}
```

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
      "selected_columns": ["PA0000_PERNR", "PA0000_EMAIL"]
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
- **LLM retry on invalid SQL**: The retry loop lives inside `translate_rule` (not in the UI layer). After each `_call`, the result is validated: `_extract_sql` must return a non-None value; it must start with `SELECT`; `_validate_sql_columns` must pass. Failure on any check sleeps 5 s and retries, up to 5 total attempts. Connection/timeout errors abort immediately. `LLMConnectionError` is raised after all attempts are exhausted.
- **`_validate_sql_columns` for SAP column hallucination**: Qwen was generating syntactically valid SQL referencing column names that do not exist in `joined_table` (memorised SAP infotype fields from training data). `_validate_sql_columns` extracts all `\bPA\w+\b` token candidates (SAP-style column names) and rejects the SQL if any are absent from the valid column set, triggering a retry.
- **`_extract_sql` hardening**: Strips fences via `re.sub` (not `re.search` on fence content, which missed unclosed fences); truncates at the *first* semicolon (not last) to prevent accepting two statements; returns `None` (not empty string) on extraction failure so callers can distinguish no-SQL from empty-SQL; rejects output containing more than one `SELECT` to prevent paired wrong+correct query responses from slipping through.
- **Workflow as single unit of persistence**: All six steps (files, pre-join filters, join, post-join filters, derived fields, rules) are saved together in one named JSON. Overwrite-on-save keeps the `workflows/` directory clean. The old separate `joins/` and `rules/` saves are legacy.
- **Run vs Edit paths**: The Run path is fully headless — DB operations in a background thread, progress dialog, lands on Reports. The Edit path does the same DB setup in a background thread, then populates all tab UIs on the main thread; user lands on tab 6 and can adjust anything.
- **Relative file paths in workflow JSON**: Stored as `os.path.relpath(abs_path, base_dir)` so workflows survive a folder rename or move.
- **Violation CSV per rule**: Generated alongside the HTML detail report; no row cap (unlike the HTML which has `report_max_detail_rows`). Users can open directly in Excel for full investigation.
- **Background threads**: Long DuckDB operations run in `threading.Thread`; results posted back via `self.after(0, ...)` to keep Tkinter responsive. Exception variables captured as lambda defaults (`lambda e=exc: ...`) to avoid Python 3 closure scoping bugs.
- **Per-file load options**: Encoding, delimiter, and engine are specified per file at load time via a modal dialog, accommodating mixed-encoding or non-standard CSV sources.

---

## Verification

### New workflow path
1. Launch app — `WorkflowLauncher` appears (no saved workflows → only "+ New Workflow" shown)
2. Click "+ New Workflow" → tab 1 enabled
3. Load two CSVs (set encoding/delimiter/engine; pick a subset of fields); confirm preview shows only the selected `tablename_fieldname` columns
4. In Pre-Join Filters: enable a `contains` filter on a string field and a date range filter; confirm "Next: Define Join →" proceeds
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
