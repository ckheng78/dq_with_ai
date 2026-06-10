import duckdb
import os


class Database:
    def __init__(self):
        self.con = duckdb.connect(database=":memory:")
        self._registered_tables = []

    def register_csv(self, name: str, path: str):
        safe_path = path.replace("\\", "/")
        self.con.execute(
            f"CREATE OR REPLACE VIEW \"{name}\" AS SELECT * FROM read_csv_auto('{safe_path}', header=true)"
        )
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
