import duckdb


_DATE_DETECT_SAMPLE = 200
_DATE_DETECT_THRESHOLD = 0.8  # 80% of non-empty values must parse as DATE

# All valid date format strings a user can assign to a column.
_DATE_FORMAT_TYPES = {"Auto", "YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY",
                      "DD/MM/YYYY HH:MM:SS", "MM/DD/YYYY HH:MM:SS", "DD-MM-YYYY"}


def _type_cast_expr(col: str, col_type: str) -> str:
    """Returns a SELECT expression that casts col to the requested type."""
    qc = f'"{col}"'
    if col_type == "numeric":
        return f"TRY_CAST({qc} AS DOUBLE)"
    if col_type == "currency":
        return f"TRY_CAST({qc} AS DECIMAL(18,2))"
    return qc  # varchar — no cast


def _date_exprs(col: str, fmt: str) -> tuple[str, str]:
    """Returns (detect_condition, cast_expression) SQL fragments for a given date format."""
    qc = f'"{col}"'
    if fmt in ("Auto", "YYYY-MM-DD"):
        return f"TRY_CAST({qc} AS DATE) IS NOT NULL", f"TRY_CAST({qc} AS DATE)"
    if fmt == "DD/MM/YYYY":
        return f"TRY_STRPTIME({qc}, '%d/%m/%Y') IS NOT NULL", f"TRY_STRPTIME({qc}, '%d/%m/%Y')::DATE"
    if fmt == "MM/DD/YYYY":
        return f"TRY_STRPTIME({qc}, '%m/%d/%Y') IS NOT NULL", f"TRY_STRPTIME({qc}, '%m/%d/%Y')::DATE"
    if fmt == "DD/MM/YYYY HH:MM:SS":
        return (
            f"(TRY_STRPTIME({qc}, '%d/%m/%Y %H:%M:%S') IS NOT NULL OR TRY_STRPTIME({qc}, '%d/%m/%Y') IS NOT NULL)",
            f"COALESCE(TRY_STRPTIME({qc}, '%d/%m/%Y %H:%M:%S'), TRY_STRPTIME({qc}, '%d/%m/%Y'))::DATE",
        )
    if fmt == "MM/DD/YYYY HH:MM:SS":
        return (
            f"(TRY_STRPTIME({qc}, '%m/%d/%Y %H:%M:%S') IS NOT NULL OR TRY_STRPTIME({qc}, '%m/%d/%Y') IS NOT NULL)",
            f"COALESCE(TRY_STRPTIME({qc}, '%m/%d/%Y %H:%M:%S'), TRY_STRPTIME({qc}, '%m/%d/%Y'))::DATE",
        )
    if fmt == "DD-MM-YYYY":
        return f"TRY_STRPTIME({qc}, '%d-%m-%Y') IS NOT NULL", f"TRY_STRPTIME({qc}, '%d-%m-%Y')::DATE"
    return f"TRY_CAST({qc} AS DATE) IS NOT NULL", f"TRY_CAST({qc} AS DATE)"


def _csv_opts(encoding: str, delimiter: str, engine: str) -> str:
    delim_sql = "\\t" if delimiter == "\t" else delimiter.replace("'", "''")
    ignore_errors = "true" if engine == "Python" else "false"
    return (
        f"header=true, all_varchar=true, "
        f"encoding='{encoding}', delim='{delim_sql}', ignore_errors={ignore_errors}"
    )


def _detect_date_columns(con, safe_path: str, columns: list[str], opts: str,
                          date_format: str = "Auto") -> dict[str, str]:
    """Returns {col_name: cast_expression} for columns that pass the date threshold."""
    date_col_exprs: dict[str, str] = {}
    for col in columns:
        detect_expr, cast_expr = _date_exprs(col, date_format)
        row = con.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE {detect_expr}) AS hits,
                COUNT(*) FILTER (WHERE "{col}" IS NOT NULL AND TRIM("{col}") != '') AS non_empty
            FROM (
                SELECT "{col}"
                FROM read_csv_auto('{safe_path}', {opts})
                LIMIT {_DATE_DETECT_SAMPLE}
            )
        """).fetchone()
        hits, non_empty = row
        if non_empty > 0 and hits / non_empty >= _DATE_DETECT_THRESHOLD:
            date_col_exprs[col] = cast_expr
            print(f"[DB] '{col}' detected as DATE ({hits}/{non_empty} samples matched, fmt={date_format})")
        else:
            print(f"[DB] '{col}' kept as VARCHAR ({hits}/{non_empty} samples matched date)")
    return date_col_exprs


class Database:
    def __init__(self):
        self.con = duckdb.connect(database=":memory:")
        self._registered_tables: list[str] = []
        self._table_base_sql: dict[str, str] = {}
        self._join_base_sql: str = ""
        self._join_filter_conditions: list[str] = []
        self._join_derived_exprs: list[tuple[str, str]] = []

    def get_csv_sample_values(self, path: str, *,
                               encoding: str = "utf-8", delimiter: str = ",", engine: str = "C",
                               n_rows: int = 200, n_distinct: int = 3) -> tuple[list[str], dict[str, list[str]]]:
        """Returns (columns, {col: [up to n_distinct non-empty sample values]})."""
        safe_path = path.replace("\\", "/")
        opts = _csv_opts(encoding, delimiter, engine)
        result = self.con.execute(
            f"SELECT * FROM read_csv_auto('{safe_path}', {opts}) LIMIT {n_rows}"
        )
        cols = [desc[0] for desc in result.description]
        rows = result.fetchall()
        samples: dict[str, list[str]] = {}
        for col_idx, col in enumerate(cols):
            seen: list[str] = []
            for row in rows:
                val = row[col_idx]
                if val is not None:
                    s = str(val).strip()
                    if s and s not in seen:
                        seen.append(s)
                        if len(seen) >= n_distinct:
                            break
            samples[col] = seen
        return cols, samples

    def detect_date_columns(self, path: str, *,
                            encoding: str = "utf-8", delimiter: str = ",", engine: str = "C",
                            date_format: str = "Auto") -> list[str]:
        """Return column names that pass the date detection threshold (used to pre-populate the type picker)."""
        safe_path = path.replace("\\", "/")
        opts = _csv_opts(encoding, delimiter, engine)
        columns = [
            row[0] for row in self.con.execute(
                f"DESCRIBE SELECT * FROM read_csv_auto('{safe_path}', {opts})"
            ).fetchall()
        ]
        return list(_detect_date_columns(self.con, safe_path, columns, opts, date_format).keys())

    def register_csv(self, name: str, path: str, *,
                     encoding: str = "utf-8", delimiter: str = ",", engine: str = "C",
                     date_format: str = "Auto", selected_columns: list[str] = None,
                     column_types: dict[str, str] = None):
        """column_types maps original col name → 'varchar'|'date'|'numeric'|'currency'.
        Columns absent from the dict fall through to date detection then VARCHAR."""
        safe_path = path.replace("\\", "/")
        opts = _csv_opts(encoding, delimiter, engine)
        column_types = column_types or {}

        if selected_columns is not None:
            columns = list(selected_columns)
        else:
            columns = [
                row[0] for row in self.con.execute(
                    f"DESCRIBE SELECT * FROM read_csv_auto('{safe_path}', {opts})"
                ).fetchall()
            ]
        print(f"[DB] Registering '{name}': {len(columns)} columns (enc={encoding}, delim={delimiter!r}, engine={engine}, dfmt={date_format})")

        # Only columns without any explicit type run auto date-detection.
        auto_cols = [c for c in columns if c not in column_types]
        date_col_exprs = _detect_date_columns(self.con, safe_path, auto_cols, opts, date_format)

        select_parts = []
        for col in columns:
            alias = f"{name}_{col}"
            override = column_types.get(col)
            if override == "NUMERIC":
                select_parts.append(f'{_type_cast_expr(col, "numeric")} AS "{alias}"')
            elif override == "CURRENCY":
                select_parts.append(f'{_type_cast_expr(col, "currency")} AS "{alias}"')
            elif override in _DATE_FORMAT_TYPES:
                _, cast_expr = _date_exprs(col, override)
                select_parts.append(f'{cast_expr} AS "{alias}"')
            elif override == "VARCHAR":
                select_parts.append(f'"{col}" AS "{alias}"')
            elif col in date_col_exprs:
                # auto-detected (no explicit override — old workflows)
                select_parts.append(f'{date_col_exprs[col]} AS "{alias}"')
            else:
                select_parts.append(f'"{col}" AS "{alias}"')

        base_sql = (
            f'SELECT {", ".join(select_parts)} '
            f"FROM read_csv_auto('{safe_path}', {opts})"
        )
        self.con.execute(f'CREATE OR REPLACE VIEW "{name}" AS {base_sql}')
        self._table_base_sql[name] = base_sql

        print(f"[DB] '{name}' ready. Date columns: {sorted(date_col_exprs) or 'none'}")
        if name not in self._registered_tables:
            self._registered_tables.append(name)

    def get_table_names(self) -> list[str]:
        return list(self._registered_tables)

    def get_columns(self, table_name: str) -> list[str]:
        result = self.con.execute(f'DESCRIBE "{table_name}"').fetchall()
        return [row[0] for row in result]

    def get_preview(self, table_name: str, n: int = 100) -> tuple[list[str], list[tuple]]:
        result = self.con.execute(f'SELECT * FROM "{table_name}" LIMIT {n}').fetchall()
        cols = [desc[0] for desc in self.con.description]
        return cols, result

    def get_column_types(self, table_name: str) -> dict[str, str]:
        """Returns {col_name: 'date' | 'numeric' | 'currency' | 'string'} for a registered table."""
        result = self.con.execute(f'DESCRIBE "{table_name}"').fetchall()
        out = {}
        for col, dtype, *_ in result:
            dt = dtype.upper()
            if dt == "DATE":
                out[col] = "date"
            elif dt == "DOUBLE":
                out[col] = "numeric"
            elif dt.startswith("DECIMAL"):
                out[col] = "currency"
            else:
                out[col] = "string"
        return out

    def apply_filters(self, filters: list[dict]):
        """Rebuild each table's view with WHERE clauses derived from active filters."""
        by_table: dict[str, list[dict]] = {t: [] for t in self._registered_tables}
        for f in filters:
            if f["table"] in by_table:
                by_table[f["table"]].append(f)

        for table in self._registered_tables:
            base_sql = self._table_base_sql[table]
            conditions = [
                c for f in by_table[table]
                if (c := self._build_filter_condition(f)) is not None
            ]
            if conditions:
                where = " AND ".join(conditions)
                sql = f"SELECT * FROM ({base_sql}) WHERE {where}"
                print(f"[FILTER] {table}: WHERE {where}")
            else:
                sql = base_sql
            self.con.execute(f'CREATE OR REPLACE VIEW "{table}" AS {sql}')

    @staticmethod
    def _build_filter_condition(f: dict) -> str | None:
        field = f["field"]
        op    = f["operator"]
        val   = f.get("value", "").strip()
        val2  = f.get("value2", "").strip()

        qf = f'"{field}"'

        if op == "is_empty":
            return f'({qf} IS NULL OR {qf} = \'\')'
        if op == "is_not_empty":
            return f'({qf} IS NOT NULL AND {qf} != \'\')'

        if not val:
            return None

        def esc(v: str) -> str:
            return v.replace("'", "''")

        if op == "equals":
            return f"{qf} = '{esc(val)}'"
        if op == "not_equals":
            return f"({qf} != '{esc(val)}' OR {qf} IS NULL)"
        if op == "contains":
            pattern = val.replace("*", "%").replace("?", "_")
            if "%" not in pattern and "_" not in pattern:
                pattern = f"%{pattern}%"
            return f"{qf} LIKE '{esc(pattern)}'"
        if op == "not_contains":
            pattern = val.replace("*", "%").replace("?", "_")
            if "%" not in pattern and "_" not in pattern:
                pattern = f"%{pattern}%"
            return f"({qf} NOT LIKE '{esc(pattern)}' OR {qf} IS NULL)"
        if op == "select":
            items = [v.strip() for v in val.split(",") if v.strip()]
            if not items:
                return None
            in_list = ", ".join(f"'{esc(v)}'" for v in items)
            return f"{qf} IN ({in_list})"
        if op == "not_select":
            items = [v.strip() for v in val.split(",") if v.strip()]
            if not items:
                return None
            in_list = ", ".join(f"'{esc(v)}'" for v in items)
            return f"({qf} NOT IN ({in_list}) OR {qf} IS NULL)"
        if op == "earlier_than":
            return f"{qf} < CAST('{esc(val)}' AS DATE)"
        if op == "later_than":
            return f"{qf} > CAST('{esc(val)}' AS DATE)"
        if op == "between":
            if not val2:
                return None
            return f"{qf} BETWEEN CAST('{esc(val)}' AS DATE) AND CAST('{esc(val2)}' AS DATE)"
        if op == "greater_than":
            return f"TRY_CAST({qf} AS DOUBLE) > {esc(val)}"
        if op == "less_than":
            return f"TRY_CAST({qf} AS DOUBLE) < {esc(val)}"
        if op == "between_numeric":
            if not val2:
                return None
            return f"TRY_CAST({qf} AS DOUBLE) BETWEEN {esc(val)} AND {esc(val2)}"
        return None

    def apply_join_filters(self, filters: list[dict]):
        """Store post-join filter conditions and rebuild joined_table."""
        self._join_filter_conditions = [
            c for f in filters
            if (c := self._build_filter_condition(f)) is not None
        ]
        self._rebuild_joined_table()

    def apply_derived_fields(self, derived: list[dict]):
        """Store derived field expressions and rebuild joined_table."""
        self._join_derived_exprs = [
            (d["name"], d["expression"]) for d in derived
            if d.get("name") and d.get("expression")
        ]
        self._rebuild_joined_table()

    def _rebuild_joined_table(self):
        """Rebuild joined_table view from base SQL, applying filters then derived fields."""
        if not self._join_base_sql:
            return
        sql = self._join_base_sql
        if self._join_filter_conditions:
            where = " AND ".join(self._join_filter_conditions)
            sql = f"SELECT * FROM ({sql}) WHERE {where}"
            print(f"[POST-JOIN FILTER] WHERE {where}")
        if self._join_derived_exprs:
            extra = ", ".join(f'{expr} AS "{name}"' for name, expr in self._join_derived_exprs)
            sql = f"SELECT *, {extra} FROM ({sql})"
            print(f"[DERIVED] {[name for name, _ in self._join_derived_exprs]}")
        self.con.execute(f"CREATE OR REPLACE VIEW joined_table AS {sql}")

    def execute_join(self, sql: str):
        self._join_base_sql = sql
        self._join_filter_conditions = []
        self._join_derived_exprs = []
        self.con.execute(f"CREATE OR REPLACE VIEW joined_table AS {sql}")

    def get_joined_preview(self, n: int = 100) -> tuple[list[str], list[tuple]]:
        return self.get_preview("joined_table", n)

    def execute_rule(self, sql: str) -> tuple[list[str], list[tuple]]:
        result = self.con.execute(sql).fetchall()
        cols = [desc[0] for desc in self.con.description]
        return cols, result

    def get_joined_row_count(self) -> int:
        return self.con.execute("SELECT COUNT(*) FROM joined_table").fetchone()[0]

    def get_table_row_count(self, name: str) -> int:
        return self.con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]

    def export_joined_csv(self, output_path: str):
        safe_path = output_path.replace("\\", "/")
        self.con.execute(f"COPY (SELECT * FROM joined_table) TO '{safe_path}' (HEADER, DELIMITER ',')")

    def close(self):
        self.con.close()
