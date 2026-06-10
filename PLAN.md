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
│   ├── file_loader.py         # File picker + per-file options dialog + CSV preview
│   ├── join_editor.py         # Visual join builder (dropdowns, no LLM)
│   ├── rule_editor.py         # Rule list; NL per rule → LLM → SQL → run all
│   └── report_viewer.py       # Show output paths; "Open in browser" buttons
├── core/
│   ├── db.py                  # DuckDB: register CSVs as views, join, rules, export
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

## Core Module Responsibilities

### `core/db.py`
- `register_csv(name, path, *, encoding, delimiter, engine)` → lazy DuckDB view with:
  - All columns read as VARCHAR first (`all_varchar=true`) to prevent type misdetection
  - Each column auto-detected for DATE via `TRY_CAST` sampling (≥80% of non-empty values must parse)
  - All columns renamed `tablename_fieldname` immediately at view creation — globally unique across tables
  - Encoding, delimiter, and engine (C = standard / Python = `ignore_errors=true`) passed through to DuckDB
- `execute_join(sql)` → stores result as `joined_table` view
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
- After loading, columns displayed as `tablename_fieldname` (rename happens in `db.register_csv`)
- Preview Treeview uses pixel-width columns (`len(col) * 9`) with `stretch=False` + horizontal scrollbar

### `ui/join_editor.py`
- No LLM. SQL is generated directly from dropdown selections.
- User picks the **master table** from a dropdown; remaining tables become secondaries in load order
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
- "Available fields (joined_table)" listbox (monospace font, scrollable) populated after join executes
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

---

## Key Design Decisions

- **8GB CSV handling**: CSVs are registered as DuckDB views (`read_csv_auto`), never loaded into Python. JOIN result is also a view until explicitly exported. Only violating rows (small subset) are returned to Python for rendering.
- **Column renaming on load**: Every field is renamed `tablename_fieldname` at view creation. This makes all column names globally unique across tables, eliminating ambiguity in join conditions and rule SQL without needing table qualifiers.
- **Visual join builder (no LLM for joins)**: Joins are defined via dropdown conditions (left field / operator / right field) rather than natural language. This is deterministic, instant, and avoids LLM reliability issues for a structured operation.
- **LLM only for rules**: The LLM (Ollama `my_qwen`) is used only to translate natural language DQ rules into SQL. The SQL is always shown to the user before execution. A "Regenerate" button allows re-prompting.
- **LLM response extraction**: `_extract_sql()` strips markdown fences, anchors to the first SQL keyword, and truncates at the last semicolon — making the pipeline robust to preamble and trailing commentary from the model.
- **Recurring path**: Saved SQL from JSON is used directly on repeat runs — no re-translation needed.
- **Background threads**: Long DuckDB operations run in `threading.Thread`; results posted back via `self.after(0, ...)` to keep Tkinter responsive. Exception variables captured as lambda defaults (`lambda e=exc: ...`) to avoid Python 3 closure scoping bugs.
- **Per-file load options**: Encoding, delimiter, and engine are specified per file at load time via a modal dialog, accommodating mixed-encoding or non-standard CSV sources.

---

## Verification

1. Load two CSVs via the file picker (set encoding/delimiter/engine in the dialog); confirm preview shows renamed columns (`tablename_fieldname`)
2. In Join tab: select master table; define join conditions via dropdowns; execute; confirm preview of joined table
3. In Rules tab: confirm field list shows all joined columns; add 2–3 NL rules; translate each; run all; confirm violation counts match manual inspection
4. Generate reports; open in browser; confirm summary totals and detail rows are correct
5. Save rules and joins; restart app; confirm auto-run dialog appears; confirm reports match Step 4
6. Test with a large CSV (≥500MB) and confirm the app remains responsive during execution
