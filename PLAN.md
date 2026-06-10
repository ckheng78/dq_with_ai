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
├── app.py                     # Root Tk window; tab orchestration; startup routing
├── ui/
│   ├── file_loader.py         # File picker + per-file options + field selector + CSV preview
│   ├── filter_editor.py       # Pre-join and post-join filter panels
│   ├── join_editor.py         # Visual join builder (dropdowns, no LLM)
│   ├── rule_editor.py         # Rule list; NL per rule → LLM → SQL → run all
│   └── report_viewer.py       # Show output paths; "Open in browser" buttons
├── core/
│   ├── db.py                  # DuckDB: register CSVs as views, filters, join, rules, export
│   ├── llm.py                 # Ollama client: NL→SQL with system prompt (rules only)
│   ├── rules.py               # Run all rules; return RuleResult dataclasses
│   └── reporter.py            # Jinja2 HTML generation (summary + per-rule detail)
├── persistence/
│   ├── join_store.py          # save/load_latest for \joins JSON files
│   └── rule_store.py          # save/load_latest for \rules JSON files
├── templates/
│   ├── summary.html.j2
│   └── detail.html.j2
├── config/
│   └── settings.json          # Ollama endpoint, model, paths, system prompts
├── data/                      # User drops CSVs here
├── rules/                     # Saved DQ rule JSON files
├── joins/                     # Saved join rule JSON files
└── reports/                   # Generated HTML + joined CSV output
```

---

## Tab Flow

```
1. Load Files → 2. Pre-Join Filters → 3. Define Join → 4. Post-Join Filters → 5. Define Rules → 6. Reports
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
- `apply_join_filters(filters)` — rebuilds `joined_table` as `SELECT * FROM (_join_base_sql) WHERE <conditions>`; restores bare `_join_base_sql` if no filters active
- `_build_filter_condition(f)` (static) — generates a single SQL WHERE fragment from a filter dict:
  - `contains` / `not_contains`: LIKE/NOT LIKE with `*`→`%`, `?`→`_` wildcard translation
  - `select` / `not_select`: IN / NOT IN with comma-separated value list
  - `earlier_than` / `later_than` / `between`: `CAST(... AS DATE)` comparisons

**Join and rules:**
- `execute_join(sql)` → stores `_join_base_sql = sql`; creates `joined_table` view
- `execute_rule(sql)` → returns `(cols, rows)` of violating rows
- `get_preview(table, n=100)` → `(cols, rows)`
- `export_joined_csv(path)` → `COPY (SELECT * FROM joined_table) TO path`

### `core/llm.py`
- Reads Ollama config from `settings.json`
- `translate_rule(nl, col_hints)` → SQL string (rules only; joins no longer use LLM)
- `_extract_sql(text)` post-processes the raw LLM response:
  1. Extracts content from markdown code fences if present
  2. Anchors to the first SQL keyword (SELECT / WITH / etc.) to skip preamble
  3. Truncates at the last `;` to drop trailing commentary
- Full debug logging printed to terminal: URL, model, prompt, raw response, extracted SQL
- Raises `LLMConnectionError` on unreachable endpoint or timeout

### `core/rules.py`
- `RuleResult` dataclass: `{name, nl_description, sql, violation_count, violating_rows}`
- `run_all_rules(rules, db)` → `list[RuleResult]`

### `core/reporter.py`
- `generate_summary(results, output_dir)` → timestamped HTML path
- `generate_detail(result, output_dir)` → timestamped HTML path

### `persistence/join_store.py` / `rule_store.py`
- `save(data, dir)` → writes `<type>_<timestamp>.json`
- `load_latest(dir)` → content of newest JSON file, or `None`
- SQL is the canonical persisted artifact

---

## UI Module Responsibilities

### `ui/file_loader.py`
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

**`PostJoinFilterFrame`** (tab 4 — Post-Join Filters):
- Same structure as `FilterEditorFrame`; `set_joined_table(table_names)` queries `joined_table` and groups fields by `tablename_` prefix
- "Next: Define Rules →" button at top-right
- On proceed: calls `db.apply_join_filters(filters)` — rebuilds `joined_table` view
- Fields listbox on the rule editor is populated **after** this step so it reflects the filtered column set

### `ui/join_editor.py`
- No LLM. SQL is generated directly from dropdown selections.
- User picks the **master table** from a dropdown; remaining tables become secondaries in load order
- "Next: Define Join →" navigation button at top-right of the panel
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

### `ui/rule_editor.py`
- "Next: Reports →" navigation button at top-right of the panel
- "Available fields (joined_table)" LabelFrame:
  - "Filter by table:" Combobox — filters listbox to fields with `tablename_` prefix; "All tables" shows everything
  - Scrollable Listbox in Courier 11 font
  - Populated with `joined_table` columns **after** post-join filters are applied
- Rule list Listbox uses `exportselection=False` to prevent selection loss on focus change
- LLM used only here: NL description → Translate to SQL → user reviews → Save SQL to Rule
- "Regenerate" re-invokes LLM if the user wants a different SQL attempt

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
    "system_prompt_rule": "You are a SQL code generator for DuckDB. Output a single DuckDB SQL SELECT statement and nothing else. The query must select only the rows that violate the data quality rule against a table called 'joined_table'. Do not write any explanation, greeting, preamble, comment, or markdown. Your entire response must be valid SQL that can be executed directly. DO NOT INTERPRET THE SCHEMA."
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

**`joins/join_<timestamp>.json`:**
```json
{
  "version": 1, "created_at": "...",
  "tables": ["PA0000", "PA0001"],
  "master": "PA0000",
  "sql": "SELECT * FROM \"PA0000\"\nLEFT JOIN \"PA0001\" ON \"PA0000_PERNR\" = \"PA0001_PERNR\""
}
```

**`rules/rules_<timestamp>.json`:**
```json
{
  "version": 1, "created_at": "...",
  "rules": [
    {"name": "null_email", "nl_description": "...", "sql": "SELECT * FROM joined_table WHERE PA0000_EMAIL IS NULL"}
  ]
}
```

Filters are not persisted — they are re-applied interactively each session. The recurring path (saved join + rules) skips both filter panels and runs directly against unfiltered views.

---

## Key Design Decisions

- **8GB CSV handling**: CSVs are registered as DuckDB views (`read_csv_auto`), never loaded into Python. JOIN result is also a view until explicitly exported. Only violating rows (small subset) are returned to Python for rendering.
- **Column renaming on load**: Every field is renamed `tablename_fieldname` at view creation. This makes all column names globally unique across tables, eliminating ambiguity in join conditions and rule SQL without needing table qualifiers.
- **Field selection at load time**: Users choose which columns to include per file via `FieldSelectorDialog`. Sample values (up to 3 distinct per column) are shown as a preview to guide selection. Only selected columns are included in the registered view.
- **Two-stage filtering**: Pre-join filters operate on individual table views (rebased from `_table_base_sql`). Post-join filters operate on `joined_table` (rebased from `_join_base_sql`). Both use the same `_build_filter_condition` logic. Re-applying filters always starts from the stored base SQL, preventing condition stacking across sessions.
- **Visual join builder (no LLM for joins)**: Joins are defined via dropdown conditions (left field / operator / right field) rather than natural language. This is deterministic, instant, and avoids LLM reliability issues for a structured operation.
- **LLM only for rules**: The LLM (Ollama `my_qwen`) is used only to translate natural language DQ rules into SQL. The SQL is always shown to the user before execution. A "Regenerate" button allows re-prompting.
- **LLM response extraction**: `_extract_sql()` strips markdown fences, anchors to the first SQL keyword, and truncates at the last semicolon — making the pipeline robust to preamble and trailing commentary from the model.
- **Recurring path**: Saved SQL from JSON is used directly on repeat runs — no re-translation needed. Filters are not saved and are skipped in the recurring path.
- **Background threads**: Long DuckDB operations run in `threading.Thread`; results posted back via `self.after(0, ...)` to keep Tkinter responsive. Exception variables captured as lambda defaults (`lambda e=exc: ...`) to avoid Python 3 closure scoping bugs.
- **Per-file load options**: Encoding, delimiter, and engine are specified per file at load time via a modal dialog, accommodating mixed-encoding or non-standard CSV sources.

---

## Verification

1. Load two CSVs (set encoding/delimiter/engine; pick a subset of fields); confirm preview shows only the selected `tablename_fieldname` columns
2. In Pre-Join Filters: enable a `contains` filter on a string field and a date range filter; confirm "Next" proceeds and filters are reflected in the join preview
3. In Define Join: select master table; define conditions; execute; confirm joined table preview
4. In Post-Join Filters: enable a filter on a joined field; confirm "Next" populates the reduced rule-editor field list
5. In Define Rules: confirm field list shows filtered columns grouped by table; add 2–3 NL rules; translate each; run all; confirm violation counts match manual inspection
6. Generate reports; open in browser; confirm summary totals and detail rows are correct
7. Save rules and joins; restart app; confirm auto-run dialog appears (filters are skipped); confirm reports match Step 6
8. Test with a large CSV (≥500MB) and confirm the app remains responsive during execution
