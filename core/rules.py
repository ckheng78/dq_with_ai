from dataclasses import dataclass, field
from .db import Database


@dataclass
class RuleResult:
    name: str
    nl_description: str
    sql: str
    violation_count: int
    columns: list[str] = field(default_factory=list)
    violating_rows: list[tuple] = field(default_factory=list)
    source_table: str = ""
    total_rows: int = 0


def _infer_source_table(columns: list[str], table_names: list[str]) -> str:
    """Return the registered table name that most result columns belong to."""
    sorted_tables = sorted(table_names, key=len, reverse=True)
    counts: dict[str, int] = {t: 0 for t in table_names}
    for col in columns:
        for t in sorted_tables:
            if col.startswith(t + "_"):
                counts[t] += 1
                break
    best = max(counts, key=counts.get, default="")
    return best if counts.get(best, 0) > 0 else ""


def run_all_rules(rules: list[dict], db: Database) -> list[RuleResult]:
    table_names = db.get_table_names()
    joined_row_count = db.get_joined_row_count()
    results = []
    for rule in rules:
        cols, rows = db.execute_rule(rule["sql"])
        source_table = _infer_source_table(cols, table_names)
        results.append(RuleResult(
            name=rule["name"],
            nl_description=rule["nl_description"],
            sql=rule["sql"],
            violation_count=len(rows),
            columns=cols,
            violating_rows=rows,
            source_table=source_table,
            total_rows=joined_row_count,
        ))
    return results
