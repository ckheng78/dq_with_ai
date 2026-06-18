# Session Notes — DQ with AI

## Session date: 2026-06-18 (branch: v4_enhancements)

### What was built / changed

### Modified: `core/db.py`

- Added `import re` and `from datetime import datetime`
- Expanded `_DATE_FORMAT_TYPES` from 7 to 14 entries: added `YYYY-MM-DD HH:MM:SS`, `YYYY/MM/DD`, `YYYY/MM/DD HH:MM:SS`, `MM-DD-YYYY`, `MM-DD-YYYY HH:MM:SS`, `DD-MM-YYYY HH:MM:SS`, `TIME`
- Added corresponding `_date_exprs` cases for all 7 new formats; `TIME` uses `TRY_CAST(col AS TIME)`; new HH:MM:SS variants use the same COALESCE pattern as existing slash-separator datetime types
- Added module-level constants `_AUTO_DETECT_FORMATS` (ordered list of `(display_name, strptime_pattern)`) and `_CURRENCY_RE` regex
- Added `_try_strptime(val, fmt) -> bool` private helper
- Added `auto_detect_column_types(samples: dict[str, list[str]]) -> dict[str, str]` — pure Python, no DB queries; reuses the sample values already collected by `get_csv_sample_values`

### Modified: `ui/file_loader.py`

- Added `from core.db import auto_detect_column_types`
- Expanded `_DATE_FORMATS` to 15 entries (all new formats in logical groups)
- `FileOptionsDialog`: removed the "Date format" dropdown row — dialog is now 3 rows (encoding, delimiter, engine); `_ok` no longer includes `date_format` in the result dict
- `FieldSelectorDialog`: changed constructor params from `detected_dates: set, default_date_format: str` to `detected_types: dict`; pre-population uses `_detected.get(col, "VARCHAR")` instead of checking set membership
- `_pick_files`: removed `detect_date_columns` DB call; replaced with `auto_detect_column_types(samples)` (no extra DB round-trip); updated `FieldSelectorDialog` call, `register_csv` call (no `date_format` arg), and list-display string (no `fmt_tag`)

### Key design decisions recorded

1. **Detection is Python-side on already-collected samples** — `get_csv_sample_values` was already called with `n_rows=5000, n_distinct=16`; running `auto_detect_column_types` on those samples adds zero extra DB queries and no perceptible latency, even for 8 GB files.
2. **DMY before MDY in detection priority** — for dates where day ≤ 12 (genuinely ambiguous), DMY wins. International business data is predominantly DMY. Users can override per-column in the dropdown.
3. **Integer and non-2dp numeric → VARCHAR** — SAP codes, employee numbers, infotypes are integers or have more than 2 decimal places; they must not be cast to CURRENCY or NUMERIC. Only values matching `^\-?\d+\.\d{2}$` exactly are classified as CURRENCY.
4. **Backward compat unchanged** — `detect_date_columns` method on `Database` retained but no longer called by the load flow. Old workflows with `date_format` in JSON still work via the `register_csv` fallback path. New workflows always store `date_format: "Auto"`.
