# Session Notes — DQ with AI

## Session date: 2026-06-11

## What was built / changed

### Modified: `ui/derived_fields_editor.py`

**Regex category (new)**
- Added `"Regex"` to `_CATEGORIES` and `_OPERATIONS`
- 3 operations: `Match`, `Extract`, `Replace`
- `Match` → `CAST(regexp_matches("field", 'pattern') AS VARCHAR)`
- `Extract` → `regexp_extract("field", 'pattern')`
- `Replace` → `regexp_replace("field", 'pattern', 'replacement')`
- Input widgets: field combobox + pattern entry (Replace also has a replacement entry with `→` label)

**Date category — Years between + TODAY support**
- Added `"Years between"` to Date operations → `DATEDIFF('year', field1, field2)`
- New `date_cb(key, width)` helper in `_rebuild_inputs`: builds a combobox with `["TODAY"] + cols` as values (default = `cols[0]`); state follows row enabled/disabled
- New `date_ref(v)` helper in `_build_expression`: returns `CURRENT_DATE` if `v == "TODAY"`, else `qf(v)` (quoted column name)
- `Days between`, `Months between`, `Years between` now use `date_cb` for both sides so either side can be TODAY
- DuckDB note: `DATEDIFF('year', ...)` counts calendar year boundaries, not exact elapsed years. For age calculation set field1 = birth date column, field2 = TODAY

**Consolidated `_build_expression` for date-diff ops**
- Replaced three separate if-blocks with one: `if op in ("Days between", "Months between", "Years between")`
- Unit lookup dict: `{"Days between": "day", "Months between": "month", "Years between": "year"}`

### Modified: `ui/rule_editor.py`

**SQL box now editable**
- Removed `self._sql_box.bind("<Key>", lambda e: "break")` — was blocking all keyboard input
- Changed background from `#f0f0f0` to `white` to visually signal the box is editable
- Updated label from `"Generated SQL (review before running):"` to `"Generated SQL (edit if needed, then save):"`
- No other changes needed — `_save_sql_to_rule` already reads whatever text is in the box, so user edits flow through to the rule automatically

---

## Key design decisions recorded

1. **`date_cb` vs `field_cb`** — date-diff ops use a separate combobox helper that prepends "TODAY" to the values list; `date_ref` in `_build_expression` maps the string literal "TODAY" to `CURRENT_DATE`; column names go through `qf()` as usual. Edge case: a column literally named "TODAY" would be treated as `CURRENT_DATE` — acceptable given naming conventions.
2. **SQL box editable by default** — user can hand-edit the LLM-generated SQL before saving; "Save SQL to Rule" is the explicit commit step, so accidental edits don't silently affect execution.
3. **DuckDB regex support** — `regexp_matches`, `regexp_extract`, `regexp_replace` are all native DuckDB functions; no extensions required. `Match` output is cast to VARCHAR so it can be stored as a derived column without type issues.

---

## Previous session: 2026-06-10

### What was built / changed

- New `ui/derived_fields_editor.py`: `DerivedFieldsEditorFrame` (tab 5) with `DerivedFieldRow` supporting 4 categories and 15 operations; "Adv" toggle for free-form DuckDB expressions
- `core/db.py`: `_rebuild_joined_table()` as single composition point; `apply_derived_fields`; `execute_join` resets both lists
- `app.py`: 7-tab flow; `_on_derived_fields_applied` callback; `rule_editor.set_fields` called after derived fields applied
- `ui/rule_editor.py`: joined_table preview treeview; LLM retry (5 attempts, SELECT guard, 5 s sleep); macOS Tk text NORMAL+key-bind pattern for read-only display
- Navigation button labels updated across file_loader, join_editor, filter_editor
