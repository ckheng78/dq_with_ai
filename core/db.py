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
        self._registered_tables = []

    def register_csv(self, name: str, path: str, *,
                     encoding: str = "utf-8", delimiter: str = ",", engine: str = "C"):
        safe_path = path.replace("\\", "/")
        opts = _csv_opts(encoding, delimiter, engine)

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

        self.con.execute(
            f'CREATE OR REPLACE VIEW "{name}" AS '
            f'SELECT {", ".join(select_parts)} '
            f"FROM read_csv_auto('{safe_path}', {opts})"
        )

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

    def execute_join(self, sql: str):
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
