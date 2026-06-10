# Plan: DQ with AI — Data Quality Application

## Context

Business users need to run recurring data quality checks on large CSV datasets without knowing SQL. The application accepts natural language join and rule instructions, uses a local Ollama LLM to convert them to SQL, executes the SQL via DuckDB against the CSVs, and produces HTML reports. Designed for an air-gapped Windows 10 laptop running Anaconda — no internet required after setup.

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
│   ├── file_loader.py         # File picker + CSV preview (Treeview, first 100 rows)
│   ├── join_editor.py         # NL join input → translate → preview → save
│   ├── rule_editor.py         # Rule list; NL per rule → translate → run all → save
│   └── report_viewer.py       # Show output paths; "Open in browser" buttons
├── core/
│   ├── db.py                  # DuckDB: register CSVs as views, join, rules, export
│   ├── llm.py                 # Ollama client: NL→SQL with system prompt
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
- `register_csv(name, path)` → `CREATE OR REPLACE VIEW name AS SELECT * FROM read_csv_auto('path')` (lazy, no memory load)
- `execute_join(sql)` → stores result as `joined_table` view
- `execute_rule(sql)` → returns `list[dict]` of violating rows
- `get_preview(table, n=100)` → `list[dict]`
- `export_joined_csv(path)` → `COPY (SELECT * FROM joined_table) TO path`

### `core/llm.py`
- Reads Ollama config from `settings.json`
- `translate_join(nl, table_names, col_hints)` → SQL string
- `translate_rule(nl, table_name, col_hints)` → SQL string
- Sends only column names + 3 sample rows to Ollama (not full data)
- Raises `LLMConnectionError` on unreachable endpoint

### `core/rules.py`
- `RuleResult` dataclass: `{name, nl_description, sql, violation_count, violating_rows}`
- `run_all_rules(rules, db)` → `list[RuleResult]`

### `core/reporter.py`
- `generate_summary(results, output_dir)` → timestamped HTML path
- `generate_detail(result, output_dir)` → timestamped HTML path

### `persistence/join_store.py` / `rule_store.py`
- `save(data, dir)` → writes `<type>_<timestamp>.json`
- `load_latest(dir)` → content of newest JSON file, or `None`
- SQL is the canonical persisted artifact; `nl_description` stored for readability only

---

## Configuration Schema (`config/settings.json`)

```json
{
  "version": 1,
  "ollama": {
    "endpoint": "http://localhost:11434",
    "model": "sqlcoder",
    "timeout_seconds": 60,
    "system_prompt_join": "You are a SQL expert. Convert the user's natural language join instruction into a valid DuckDB SQL SELECT statement. Return ONLY the SQL, no explanation.",
    "system_prompt_rule": "You are a SQL expert. Convert the user's natural language data quality rule into a DuckDB SQL SELECT that returns ONLY violating rows. Return ONLY the SQL, no explanation."
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
  "tables": ["customers", "orders"],
  "nl_instruction": "Join customers and orders on customer_id",
  "sql": "SELECT c.*, o.order_date FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id"
}
```

**`rules/rules_<timestamp>.json`:**
```json
{
  "version": 1, "created_at": "...",
  "rules": [
    {"name": "null_email", "nl_description": "...", "sql": "SELECT * FROM joined_table WHERE email IS NULL"}
  ]
}
```

---

## Implementation Steps

1. **Scaffolding** → create all folders, `config/settings.json`, `main.py` (folder checks + launch), bare `app.py` with `ttk.Notebook`
2. **`core/db.py`** → DuckDB integration; verify: register 2 small test CSVs, run hand-written join + rule SQL
3. **`core/llm.py`** → Ollama client; verify: translate a simple NL instruction against a running Ollama instance
4. **Persistence** → `join_store.py` + `rule_store.py`; verify round-trip save/load
5. **UI panels** → `file_loader.py`, `join_editor.py`, `rule_editor.py` wired into `app.py` tabs
6. **Reporting** → Jinja2 templates + `core/reporter.py` + `ui/report_viewer.py`
7. **Recurring workflow** → startup detection in `app.py`: if both `\rules` and `\joins` non-empty, offer auto-run dialog
8. **Error handling + progress** → `LLMConnectionError` dialog, DuckDB error dialog, `ttk.Progressbar` on background threads
9. **End-to-end test** with real-size CSV files

---

## Key Design Decisions

- **8GB CSV handling**: CSVs are registered as DuckDB views (`read_csv_auto`), never loaded into Python. JOIN result is also a view until explicitly exported. Only violating rows (small subset) are returned to Python for rendering.
- **LLM trust gate**: UI always shows generated SQL to the user before execution. No SQL runs silently. A "Regenerate" button allows re-prompting.
- **Recurring path**: loaded SQL from JSON is used directly — no re-translation needed. The LLM is only invoked for new instructions.
- **Background threads**: long DuckDB operations run in `threading.Thread`; results posted back via `queue.Queue` to keep Tkinter responsive.

---

## Verification

1. Load two CSVs via the file picker; confirm preview shows correct rows/columns
2. Enter NL join instruction; confirm generated SQL is reasonable; execute; confirm preview of joined table
3. Add 2–3 NL rules; translate each; run all; confirm violation counts match manual inspection
4. Generate reports; open in browser; confirm summary totals and detail rows are correct
5. Save rules and joins; restart app; confirm auto-run dialog appears; confirm reports match Step 4
6. Test with a large CSV (≥500MB) and confirm the app remains responsive during execution
