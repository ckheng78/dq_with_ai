# Session Notes — DQ with AI

## Session date: 2026-06-13 (branch: v2_enhancements)

### What was built / changed

### Modified: `ui/file_loader.py`

- `_pick_files`: changed `get_csv_sample_values` call to `n_rows=5000, n_distinct=16` — samples more rows while staying bounded (one CSV read, reads only the first 5 000 rows of the file)
- After `register_csv`, builds `distinct_values` dict: `{f"{safe_name}_{col}": sorted(vals) for col, vals in samples.items() if col in selected_cols and 0 < len(vals) <= 15}` — `n_distinct=16` (limit+1) means `len==16` signals "too many distinct values", those columns are excluded
- `FieldSelectorDialog` preview label sliced to `vals[:3]` — display unchanged even though sample now holds up to 16 values
- `_proceed`: merges `distinct_values` across all loaded files and passes as second argument to `on_loaded` callback (callback signature changed from `(table_names)` to `(table_names, distinct_values)`)

### Modified: `app.py`

- New state `self._wf_distinct_values: dict = {}` initialised in `__init__` and reset in `_restart`
- `_on_files_loaded(self, table_names, distinct_values)`: stores `_wf_distinct_values`; passes to `filter_editor.set_tables`
- `_on_joined`: passes `self._wf_distinct_values` to `postjoin_filter_editor.set_joined_table` — both filter panels share the same pre-computed dict, no additional DB queries

### Modified: `ui/filter_editor.py`

- `FilterRow.__init__`: new `distinct_values: list = None` param; stored as `self._distinct_values`
- `FilterRow._rebuild_value`: for `equals`/`not equals`, if `self._distinct_values` is non-empty renders a `state="readonly"` Combobox (values pre-sorted from file load sample); otherwise plain Entry unchanged
- `FilterRow._set_val_state`: when enabling a row (`state="normal"`), Combobox children receive `state="readonly"` instead of `"normal"` to preserve the read-only constraint
- `FilterEditorFrame.set_tables(table_names, distinct_values=None)`: stores dict; passes `distinct_values.get(field, [])` for string-type fields to each `FilterRow`; date/numeric/currency fields receive `[]` (no dropdown)
- `PostJoinFilterFrame.set_joined_table(table_names, distinct_values=None)`: same pattern; reuses the dict passed from `app.py` — avoids querying the joined view (which would force a join execution over the full source files)

### Key design decisions recorded

1. **Sample at file-load time, not at filter-panel time** — querying `SELECT DISTINCT col FROM view` on a 4 GB CSV view streams the entire file for every string column; doing it at load time within a bounded `LIMIT 5000` read keeps the filter panel instant.
2. **`n_distinct=16` (limit+1) sentinel** — collecting one extra value lets the caller detect "more than 15 distinct values exist" without reading beyond the sample. `len(vals) == 16` means skip; `len(vals) <= 15` means show dropdown.
3. **Combobox state is `"readonly"`** — prevents users from typing values not in the list; the dropdown is a complete enumeration from the sample, not just a hint. Falls back to plain Entry when distinct values are absent (high-cardinality columns, date/numeric columns, Edit path).
4. **Edit path receives no distinct values** — `set_tables` and `set_joined_table` default to `distinct_values=None` → plain Entry for all `equals`/`not equals` rows. Acceptable: saved filter values are still pre-populated correctly via `_val1.set()` on the shared StringVar.
5. **Single dict shared between both filter panels** — `App._wf_distinct_values` is set once in `_on_files_loaded` and passed to both `FilterEditorFrame` and `PostJoinFilterFrame`; no duplication or re-computation.

---

## Session date: 2026-06-12 (continued)

### What was built / changed

### Modified: `core/llm.py`

- `_extract_sql`: added step 5 — `re.sub(r'\bREGEX_LIKE\b', 'REGEXP_MATCHES', ...)` to silently correct a DuckDB non-existent function name that Qwen occasionally hallucinates from MySQL/Oracle training data

### Modified: `config/settings.json`

- `system_prompt_rule`: appended DuckDB regex function reference block listing `REGEXP_MATCHES`, `REGEXP_LIKE`, `REGEXP_EXTRACT` with descriptions and an explicit "Do NOT use REGEX_LIKE, RLIKE" warning; added a regex worked example (email pattern check)

### Modified: `core/db.py`

- Added `_type_cast_expr(col, type)` → `"NUMERIC"` → `TRY_CAST AS DOUBLE`; `"CURRENCY"` → `TRY_CAST AS DECIMAL(18,2)`
- Added `_DATE_FORMAT_TYPES` module-level set — all valid date format strings; used by `register_csv` to detect date overrides
- Added `detect_date_columns(path, ...)` public method — wraps `_detect_date_columns`; returns list of column names that pass the threshold; used by `file_loader` to pre-populate the type picker
- `register_csv` accepts `column_types: dict[str, str]` kwarg; columns with an explicit override skip auto-detection; `NUMERIC`/`CURRENCY` → `_type_cast_expr`; date format strings → `_date_exprs`; `VARCHAR` → no cast; columns absent from `column_types` fall through to `_detect_date_columns` (old workflow compat)
- `get_column_types` extended: `DOUBLE` → `'numeric'`; `DECIMAL(...)` → `'currency'`; `DATE` → `'date'`; everything else → `'string'`
- `_build_filter_condition`: added `greater_than` (`TRY_CAST AS DOUBLE > val`), `less_than` (`TRY_CAST AS DOUBLE < val`), `between_numeric` (`TRY_CAST AS DOUBLE BETWEEN val AND val2`)

### Modified: `ui/file_loader.py`

- `_COL_TYPES` changed from `["VARCHAR", "DATE", "NUMERIC", "CURRENCY"]` to `["VARCHAR"] + _DATE_FORMATS + ["NUMERIC", "CURRENCY"]` — date format expanded into all individual format options
- `FieldSelectorDialog` rebuilt from single Listbox → scrollable canvas of per-row widgets; each row: checkbox + column name + samples label + type Combobox
- Constructor gains `default_date_format: str = "Auto"` param; detected date columns pre-populated with `default_date_format`; non-detected columns default to `"VARCHAR"`
- `_ok`: stores `column_types` dict (col → exact dropdown value, no lowercasing); exposed as `dlg.column_types`
- `_pick_files`: calls `db.detect_date_columns()` before opening dialog; passes `default_date_format=opts["date_format"]`; stores `column_types` in `_loaded_files`
- `get_file_configs`: includes `column_types` in returned dict
- `populate_from_workflow`: reads `column_types` with `{}` fallback; stores in `_loaded_files`

### Modified: `ui/filter_editor.py`

- Added `_NUMERIC_OPS`: `greater than`, `less than`, `between`, `equals`, `not equals`, `is empty`, `is not empty`
- `_OP_KEY` / `_KEY_OP` extended for `greater_than`, `less_than`; `_KEY_OP["between_numeric"] = "between"` added for reverse-mapping
- `FilterRow.__init__`: uses `_NUMERIC_OPS` when `field_type in ("numeric", "currency")`
- `_rebuild_value`: `greater than` / `less than` → plain Entry; `between` on numeric/currency → two Entries without date hint
- `get_filter()`: emits `between_numeric` operator key when field type is numeric/currency and selected op is "between"

### Modified: `app.py`

- Both `register_csv` call sites (Run path and Edit path) now pass `column_types=fc.get("column_types", {})`

### Key design decisions recorded

1. **NUMERIC/CURRENCY default to explicit opt-in** — auto-detecting numeric would misclassify SAP codes (cost centres, infotype numbers, etc.) that look like integers but must stay VARCHAR. Users must explicitly promote a column.
2. **CURRENCY = DECIMAL(18,2), no stripping** — source data contains no thousand separators or currency symbols, so `TRY_CAST AS DECIMAL(18,2)` is sufficient. No regex stripping needed.
3. **Date format expanded per-column** — the file-level date format in `FileOptionsDialog` is now a detection hint; the per-column dropdown in `FieldSelectorDialog` is the authoritative type. This allows different columns in the same file to have different date formats (edge case, but supported).
4. **`between_numeric` operator key** — `FilterRow.get_filter()` emits this key (not `"between"`) when field type is numeric/currency so `_build_filter_condition` generates numeric comparisons rather than DATE comparisons. `_KEY_OP` reverse-maps it to `"between"` for pre-population on the Edit path.
5. **Two-pronged LLM regex fix** — post-processing correction in `_extract_sql` (safety net) plus system prompt update (reduces hallucination at source). The correction only targets `REGEX_LIKE` (clearly wrong); `REGEXP_LIKE` (valid DuckDB partial-match function) is left untouched.

---

## Session date: 2026-06-12

### What was built / changed

### Modified: `ui/filter_editor.py`

- Added `equals` / `not equals` to `_STRING_OPS` — exact single-value match; same Entry widget as `contains` but no wildcard hint
- Added `is empty` / `is not empty` to both `_STRING_OPS` and `_DATE_OPS` — no value entry; shows `(no value needed)` label
- Updated `_OP_KEY` / `_KEY_OP` for all four new operators
- `_rebuild_value()` handles `is empty`/`is not empty` first (no widget), then `equals`/`not equals` (plain Entry)

### Modified: `core/db.py`

- `_build_filter_condition`: `is_empty`/`is_not_empty` handled before the `if not val` guard (they need no value); `equals`/`not_equals` added with `IS NULL` guard on negation to match existing `not_contains`/`not_select` behaviour
- Added `_date_exprs(col, fmt)` → `(detect_condition, cast_expression)` — maps each supported format name to DuckDB SQL fragments; `DD/MM/YYYY HH:MM:SS` / `MM/DD/YYYY HH:MM:SS` use `COALESCE(strptime_ts, strptime_date)::DATE` to handle mixed date-only and datetime values
- `_detect_date_columns` now accepts `date_format` parameter and returns `dict[str, str]` (`{col: cast_expression}`) instead of `set[str]`; uses `_date_exprs` for the detection COUNT query
- `register_csv` accepts `date_format="Auto"` keyword arg; passes it to `_detect_date_columns`; uses the returned dict directly in the view's SELECT (replaces the hardcoded `TRY_CAST(col AS DATE)`)
- Supported formats: `Auto`, `YYYY-MM-DD`, `DD/MM/YYYY`, `MM/DD/YYYY`, `DD/MM/YYYY HH:MM:SS`, `MM/DD/YYYY HH:MM:SS`, `DD-MM-YYYY`

### Modified: `ui/file_loader.py`

- Added `_DATE_FORMATS` list
- `FileOptionsDialog`: added "Date format" dropdown (row 3); combobox widths widened to 22 to fit longer format strings
- `_pick_files`: splits `csv_opts` (encoding/delimiter/engine) from `date_format` before calling `get_csv_sample_values`; passes `date_format` separately to `register_csv`; listbox entry appends `dfmt=...` tag when format is not Auto
- `get_file_configs`: includes `date_format` in returned dict
- `populate_from_workflow`: reads `date_format` with `"Auto"` fallback for backward compat; stores in `_loaded_files`; shows `dfmt=` tag in listbox

### Modified: `app.py`

- Both `register_csv` calls (Run and Edit paths) now pass `date_format=fc.get("date_format", "Auto")`

### Modified: `data/PA0000.csv`, `data/PA0001.csv`, `data/PA0002.csv`

- PA0000 dates reformatted to `DD/MM/YYYY`
- PA0001 dates reformatted to `MM/DD/YYYY HH:MM:SS` (with ` 00:00:00` suffix)
- PA0002 dates (BEGDA, ENDDA, GBDAT) reformatted to `DD-MM-YYYY`; empty GBDAT on row 12 preserved

### Key design decisions recorded

1. **User-specified date format (no auto-detection)** — avoids the fundamental ambiguity between `dd/mm` and `mm/dd` when all day/month values ≤ 12. User selects per file at load time; `Auto` retains existing ISO-only behaviour.
2. **Filter UI unchanged for date values** — once a column is cast to `DATE` in the view, `CAST('YYYY-MM-DD' AS DATE)` comparisons work regardless of the original CSV format. No hint label or input handling needed.
3. **`is_empty`/`is_not_empty` before the `not val` guard** — these operators need no value, so they must be evaluated before the `if not val: return None` early exit in `_build_filter_condition`.
4. **`DD-MM-YYYY` added on demand** — not in the original plan; added because a test file used dash-separated dates. Single `_date_exprs` branch with `'%d-%m-%Y'` strptime pattern.

---

## Session date: 2026-06-11 (continued)

## What was built / changed

### New: `persistence/workflow_store.py`

- `save(workflow, workflows_dir)` — serialises a full workflow dict to `workflows/<name>.json`; overwrites on save; sets `created_at` on first save and always updates `updated_at`
- `load_all(workflows_dir)` — returns all workflow JSON files sorted by `updated_at` descending

### New: `ui/workflow_launcher.py`

- `WorkflowLauncher` — modal `Toplevel` shown on every app startup
- Lists saved workflows (name, last-updated date, rule count) with **Run** and **Edit** per row
- **+ New Workflow** button (also fires if user closes the dialog via the window × button)
- Calls back to `App` with `on_new`, `on_run`, or `on_edit`

### New: `README.md`

- Rollback instructions: `git checkout v0.1-stable` (stable tag) or recreate a branch from it

### Modified: `app.py`

- Replaced `_check_recurring` startup logic with `_show_launcher` → `WorkflowLauncher`
- Added per-tab state accumulators: `_wf_pre_filters`, `_wf_join`, `_wf_post_filters`, `_wf_derived`, `_wf_rules`, `_current_workflow_name`; each `_on_*` callback stores its slice
- `_on_joined` no longer prompts "Save Join?"; `_on_rules_run` no longer prompts "Save Rules?" — both replaced by a single "Save Workflow?" prompt (name dialog) after rules run
- `_save_workflow(name)` — assembles all six slices into one dict and calls `workflow_store.save()`
- `_run_workflow(workflow)` — headless re-run: registers CSVs, applies filters, executes join, applies derived fields, runs rules, generates reports; progress dialog with status labels; runs in background thread
- `_edit_workflow(workflow)` — same DB operations in background thread; on completion, `_finish_edit_workflow` populates all tab UIs without repeating DB work, enables all tabs, jumps to tab 6
- `_restart()` now resets all `_wf_*` state and shows the launcher again
- Removed imports of `join_store` and `rule_store`

### Modified: `ui/file_loader.py`

- `get_file_configs(base_dir)` — returns `[{name, path (relative), encoding, delimiter, engine, selected_columns}]` for workflow save
- `populate_from_workflow(file_configs, base_dir)` — updates Listbox and preview tabs without calling `db.register_csv()` (CSVs already registered by the time this runs in the edit path)

### Modified: `ui/filter_editor.py`

- Added `_KEY_OP` reverse mapping (`stored_key → display_op`)
- `load_filters(filters)` added to both `FilterEditorFrame` and `PostJoinFilterFrame` — matches saved filters by field name, enables the row, sets operator and values

### Modified: `ui/join_editor.py`

- `get_join_config()` now includes `"conditions"` list: `[{secondary, conditions: [{bool_op, left, op, right}]}]` alongside the existing `tables/master/sql` fields
- `load_join_config(config)` — sets master, waits for `_rebuild_rules()` trace to fire, then clears default condition rows and restores saved conditions for each `JoinRuleWidget`

### Modified: `ui/derived_fields_editor.py`

- `load_derived_fields(derived_list)` — restores each derived field in **Adv mode** (free-form expression entry) using the stored expression string; adds rows if the saved list is longer than the default 3

### Modified: `ui/rule_editor.py`

- **Bug fix**: `_update_run_btn()` now also enables/disables `_next_btn` ("Next: Reports →"); previously the button stayed disabled until rules had already been run once

### Modified: `core/reporter.py`

- `generate_violation_csv(result, output_dir)` — writes `violations_<rule>_<timestamp>.csv` with stdlib `csv`; header row = column names; all violating rows written (no row cap)

### Modified: `app.py` (reports)

- `_generate_and_show_reports` generates a violation CSV alongside each HTML detail report and passes both path lists to `report_viewer.set_reports()`

### Modified: `ui/report_viewer.py`

- `set_reports()` now accepts `(summary_path, detail_paths, csv_paths)`
- Detail listbox shows `os.path.basename(path)` instead of full paths
- Two buttons replace the old single "Open Selected Detail Report": **Open HTML Report** and **Open Violation CSV**
- Both operate on the selected listbox entry

### Modified: `config/settings.json` + `main.py`

- Added `"workflows_dir": "workflows"` to paths
- `"workflows"` added to `REQUIRED_DIRS` in `main.py`

---

## Key design decisions recorded

1. **Single workflow JSON per named workflow** — overwrite on save; no timestamped versioning. `created_at` preserved on first save, `updated_at` always refreshed. Keeps the launcher list clean.
2. **Edit path uses Adv mode for derived fields** — rather than reconstructing the category/operation/inputs UI state from a SQL expression string, derived fields are restored in free-form "Adv" mode. The expression is round-trippable and the user can always switch back to the builder manually.
3. **DB operations in background thread for both Run and Edit paths** — both use `threading.Thread` + `self.after()` to keep the UI responsive; a progress dialog with a status label gives feedback during each step.
4. **Relative file paths in workflow JSON** — stored as `os.path.relpath(abs_path, base_dir)` so the workflow JSON is portable if the project folder is moved.
5. **`_KEY_OP` reverse map in filter_editor** — `_OP_KEY` maps display → stored key; `_KEY_OP = {v: k for k, v in _OP_KEY.items()}` maps back for pre-population. Added at module level alongside `_OP_KEY`.
6. **`conditions` saved in join config** — the raw join conditions (secondary table, bool_op, left col, operator, right col) are saved alongside the compiled SQL so the JoinEditorFrame can be fully reconstructed visually during the Edit path. The SQL alone is sufficient for the Run path.
7. **Violation CSV has no row cap** — the HTML detail report has `report_max_detail_rows` to keep the browser snappy; the CSV gets all rows so users can do full analysis in Excel.

---

## Previous session: 2026-06-11 (earlier)

### What was built / changed

### Modified: `ui/derived_fields_editor.py`

**Regex category (new)**
- Added `"Regex"` to `_CATEGORIES` and `_OPERATIONS`
- 3 operations: `Match`, `Extract`, `Replace`
- `Match` → `CAST(regexp_matches("field", 'pattern') AS VARCHAR)`
- `Extract` → `regexp_extract("field", 'pattern')`
- `Replace` → `regexp_replace("field", 'pattern', 'replacement')`

**Date category — Years between + TODAY support**
- Added `"Years between"` to Date operations → `DATEDIFF('year', field1, field2)`
- `date_cb` helper prepends "TODAY" to column list; `date_ref` maps "TODAY" → `CURRENT_DATE`
- `Days between`, `Months between`, `Years between` all use `date_cb` on both sides

### Modified: `ui/rule_editor.py`

**SQL box now editable**
- Removed key-bind that blocked input; background changed to white; label updated
- `_save_sql_to_rule` already reads the box content so no further changes needed

---

## Previous session: 2026-06-10

### What was built / changed

- New `ui/derived_fields_editor.py`: `DerivedFieldsEditorFrame` (tab 5) with `DerivedFieldRow` supporting 4 categories and 15 operations; "Adv" toggle for free-form DuckDB expressions
- `core/db.py`: `_rebuild_joined_table()` as single composition point; `apply_derived_fields`; `execute_join` resets both lists
- `app.py`: 7-tab flow; `_on_derived_fields_applied` callback; `rule_editor.set_fields` called after derived fields applied
- `ui/rule_editor.py`: joined_table preview treeview; LLM retry (5 attempts, SELECT guard, 5 s sleep); macOS Tk text NORMAL+key-bind pattern for read-only display
- Navigation button labels updated across file_loader, join_editor, filter_editor
