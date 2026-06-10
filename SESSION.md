# Session Notes — DQ with AI

## Session date: 2026-06-10

## What was built / changed

### New file: `ui/derived_fields_editor.py`
- `DerivedFieldRow`: one row per derived column; checkbox enables it; name Entry (default `derived_N`); Category + Op Comboboxes; `_rebuild_inputs()` destroys/recreates dynamic input widgets on op change; "Adv" Checkbutton swaps builder frame with free-form DuckDB expression Entry via `grid_remove()`/`grid()`
- `_build_expression(op, inputs)`: 15 operations across 4 categories — String (Upper, Lower, Length, Substring, Concatenate), Date (Extract Year/Month/Day, Days between, Months between), Numeric (Add, Subtract, Multiply, Divide, Round), Conditional (If/Then/Else). Uses `NULLIF(..., 0)` for Divide. Returns `None` on bad input.
- `DerivedFieldsEditorFrame`: scrollable canvas; 3 initial rows on `set_columns()`; "+ Add Field" button; "Next: Define Rules →" at top-right; `_apply_and_proceed` calls `db.apply_derived_fields(derived)`

### Modified: `core/db.py`
- Added `self._join_filter_conditions: list[str] = []` and `self._join_derived_exprs: list[tuple[str,str]] = []` in `__init__`
- New `_rebuild_joined_table()`: single composition point — base SQL → WHERE filter → SELECT * + derived cols
- `apply_join_filters` now stores conditions and delegates to `_rebuild_joined_table`
- New `apply_derived_fields(derived)`: stores `(name, expr)` pairs and delegates to `_rebuild_joined_table`
- `execute_join` resets both lists so a new join starts clean

### Modified: `app.py`
- 7 tabs: Load Files → Pre-Join Filters → Define Join → Post-Join Filters → **Derived Fields** → Define Rules → Reports
- `_on_postjoin_filtered` → calls `derived_fields_editor.set_columns(...)`, goes to tab 4
- New `_on_derived_fields_applied` → goes to tab 5, calls `rule_editor.set_fields(...)`
- `_restart` includes `derived_fields_editor.db = self._db` and `range(1, 7)`

### Modified: `ui/rule_editor.py`
- **SQL box fix (macOS)**: keep `tk.Text` permanently in `NORMAL` state; `bind("<Key>", lambda e: "break")` to block editing. Removes all `config(state=...)` calls on `_sql_box`.
- **LLM retry**: worker thread loops up to 5 attempts; validates `sql.strip().upper().startswith("SELECT")`; `time.sleep(5)` between failed attempts; connection errors abort immediately; lambda default-arg pattern (`lambda s=sql: ...`) to avoid closure bug
- **Preview treeview**: `ttk.Treeview` with vsb+hsb at bottom of right panel; `_refresh_preview()` called from `set_fields()`

### Modified: `ui/join_editor.py`
- Button: `"Next: Post-Join Filters →"`

### Modified: `ui/filter_editor.py`
- `PostJoinFilterFrame` button: `"Next: Derived Fields →"`

### Modified: `ui/file_loader.py`
- Button: `"Next: Pre-Join Filters →"`

### Modified: `PLAN.md`
- Reflects 7-tab flow, all new components, 3 new design decisions, 9-step verification checklist

---

## Pending commit (staged but not yet committed)

```bash
git add PLAN.md app.py core/db.py ui/file_loader.py ui/filter_editor.py ui/join_editor.py ui/rule_editor.py ui/derived_fields_editor.py
git commit -m "$(cat <<'EOF'
Add derived fields panel, joined_table preview in rules, and LLM retry

- Add ui/derived_fields_editor.py: DerivedFieldsEditorFrame (tab 5)
  with DerivedFieldRow supporting 4 categories and 15 operations
  (Concatenate, Upper, Lower, Length, Substring, Extract Year/Month/Day,
  Days/Months between, Add, Subtract, Multiply, Divide, Round,
  If/Then/Else). Each row has an "Adv" toggle that replaces the builder
  with a free-form DuckDB expression entry for power users.

- db.py: refactor joined_table rebuild into _rebuild_joined_table() so
  apply_join_filters and apply_derived_fields both delegate to it.
  Re-running either step never loses the other. execute_join resets
  _join_filter_conditions and _join_derived_exprs on each new join.

- app.py: insert tab 5 "Derived Fields" between Post-Join Filters and
  Define Rules; shift Define Rules to tab 6, Reports to tab 7; add
  _on_derived_fields_applied callback; rule_editor.set_fields now called
  after derived fields are applied so derived columns appear in the list.

- rule_editor.py: add joined_table preview treeview at bottom of the
  right panel (same scrollbar pattern as Define Join); refreshed by
  _refresh_preview() on set_fields so it reflects all transformations.

- rule_editor.py: LLM translation retry — up to 5 attempts with 5 s
  sleep between each; validates extracted SQL starts with SELECT before
  accepting; connection/HTTP errors abort immediately.

- rule_editor.py: keep SQL review box in NORMAL state permanently and
  block input via <Key> binding — fixes macOS Tk rendering bug where
  state=DISABLED overrides background/foreground colours making text
  invisible against a white background.

- Fix stale navigation button labels:
    file_loader:   "Next: Pre-Join Filters →"
    join_editor:   "Next: Post-Join Filters →"
    filter_editor: PostJoinFilterFrame → "Next: Derived Fields →"

- Update PLAN.md: 7-tab flow, new derived_fields_editor.py section,
  updated db.py methods, rule_editor additions, 3 new design decisions,
  9-step verification checklist.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Key design decisions recorded

1. **`_rebuild_joined_table()` as single composition point** — avoids either filter or derived step silently erasing the other when re-run
2. **LLM retry with SELECT guard** — hallucinated non-SELECT output is retried up to 5× with 5 s sleep; HTTP/connection errors abort immediately to avoid wasting retries on infra failure
3. **macOS tk.Text NORMAL+key-bind pattern** — `state=DISABLED` on macOS overrides background/foreground at OS level; keeping NORMAL and blocking `<Key>` is the only reliable fix
