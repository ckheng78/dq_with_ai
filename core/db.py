import duckdb


_DATE_DETECT_SAMPLE = 200
_DATE_DETECT_THRESHOLD = 0.8  # 80% of non-empty values must parse as DATE


def _csv_opts(encoding: str, delimiter: str, engine: str) -> str:
    delim_sql = "\\t" if delimiter == "\t" else delimiter.replace("'", "''")
    ignore_errors = "true" if engine == "Python" else "false"
    return (
        f"header=true, all_varchar=true, "
        f"encoding='{encoding}', delim='{delim_sql}', ignore_errors={ignore_errors}"
    )


def _detect_date_columns(con, safe_path: str, columns: list[str], opts: str) -> set[str]:
    date_cols = set()
    for col in columns:
        row = con.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE TRY_CAST("{col}" AS DATE) IS NOT NULL) AS hits,
                COUNT(*) FILTER (WHERE "{col}" IS NOT NULL AND TRIM("{col}") != '') AS non_empty
            FROM (
                SELECT "{col}"
                FROM read_csv_auto('{safe_path}', {opts})
                LIMIT {_DATE_DETECT_SAMPLE}
            )
        """).fetchone()
        hits, non_empty = row
        if non_empty > 0 and hits / non_empty >= _DATE_DETECT_THRESHOLD:
            date_cols.add(col)
            print(f"[DB] '{col}' detected as DATE ({hits}/{non_empty} samples matched)")
        else:
            print(f"[DB] '{col}' kept as VARCHAR ({hits}/{non_empty} samples matched date)")
    return date_cols


class Database:
    def __init__(self):
        self.con = duckdb.connect(database=":memory:")
        self._registered_tables: list[str] = []
        self._table_base_sql: dict[str, str] = {}  # original SELECT SQL before pre-join filters
        self._join_base_sql: str = ""               # original JOIN SQL before post-join filters

    def get_csv_columns(self, path: str, *,
                        encoding: str = "utf-8", delimiter: str = ",", engine: str = "C") -> list[str]:
        safe_path = path.replace("\\", "/")
        opts = _csv_opts(encoding, delimiter, engine)
        return [
            row[0] for row in self.con.execute(
                f"DESCRIBE SELECT * FROM read_csv_auto('{safe_path}', {opts})"
            ).fetchall()
        ]

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

    def register_csv(self, name: str, path: str, *,
                     encoding: str = "utf-8", delimiter: str = ",", engine: str = "C",
                     selected_columns: list[str] = None):
        safe_path = path.replace("\\", "/")
        opts = _csv_opts(encoding, delimiter, engine)

        if selected_columns is not None:
            columns = list(selected_columns)
        else:
            columns = [
                row[0] for row in self.con.execute(
                    f"DESCRIBE SELECT * FROM read_csv_auto('{safe_path}', {opts})"
                ).fetchall()
            ]
        print(f"[DB] Registering '{name}': {len(columns)} columns (enc={encoding}, delim={delimiter!r}, engine={engine})")
        date_cols = _detect_date_columns(self.con, safe_path, columns, opts)

        select_parts = []
        for col in columns:
            alias = f"{name}_{col}"
            if col in date_cols:
                select_parts.append(f'TRY_CAST("{col}" AS DATE) AS "{alias}"')
            else:
                select_parts.append(f'"{col}" AS "{alias}"')

        base_sql = (
            f'SELECT {", ".join(select_parts)} '
            f"FROM read_csv_auto('{safe_path}', {opts})"
        )
        self.con.execute(f'CREATE OR REPLACE VIEW "{name}" AS {base_sql}')
        self._table_base_sql[name] = base_sql

        print(f"[DB] '{name}' ready. Date columns: {sorted(date_cols) or 'none'}")
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

    def get_sample_rows(self, table_name: str, n: int = 3) -> list[dict]:
        cols, rows = self.get_preview(table_name, n)
        return [dict(zip(cols, row)) for row in rows]

    def get_column_types(self, table_name: str) -> dict[str, str]:
        """Returns {col_name: 'date' | 'string'} for a registered table."""
        result = self.con.execute(f'DESCRIBE "{table_name}"').fetchall()
        return {row[0]: ("date" if row[1].upper() == "DATE" else "string") for row in result}

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

        if not val:
            return None

        qf = f'"{field}"'

        def esc(v: str) -> str:
            return v.replace("'", "''")

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
        return None

    def apply_join_filters(self, filters: list[dict]):
        """Rebuild joined_table view with WHERE clauses from active post-join filters."""
        if not self._join_base_sql:
            return
        conditions = [
            c for f in filters
            if (c := self._build_filter_condition(f)) is not None
        ]
        if conditions:
            where = " AND ".join(conditions)
            sql = f"SELECT * FROM ({self._join_base_sql}) WHERE {where}"
            print(f"[POST-JOIN FILTER] WHERE {where}")
        else:
            sql = self._join_base_sql
        self.con.execute(f"CREATE OR REPLACE VIEW joined_table AS {sql}")

    def execute_join(self, sql: str):
        self._join_base_sql = sql
        self.con.execute(f"CREATE OR REPLACE VIEW joined_table AS {sql}")

    def get_joined_preview(self, n: int = 100) -> tuple[list[str], list[tuple]]:
        return self.get_preview("joined_table", n)

    def execute_rule(self, sql: str) -> tuple[list[str], list[tuple]]:
        result = self.con.execute(sql).fetchall()
        cols = [desc[0] for desc in self.con.description]
        return cols, result

    def get_joined_row_count(self) -> int:
        return self.con.execute("SELECT COUNT(*) FROM joined_table").fetchone()[0]

    def export_joined_csv(self, output_path: str):
        safe_path = output_path.replace("\\", "/")
        self.con.execute(f"COPY (SELECT * FROM joined_table) TO '{safe_path}' (HEADER, DELIMITER ',')")

    def close(self):
        self.con.close()
