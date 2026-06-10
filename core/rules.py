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


def run_all_rules(rules: list[dict], db: Database) -> list[RuleResult]:
    results = []
    for rule in rules:
        cols, rows = db.execute_rule(rule["sql"])
        results.append(RuleResult(
            name=rule["name"],
            nl_description=rule["nl_description"],
            sql=rule["sql"],
            violation_count=len(rows),
            columns=cols,
            violating_rows=rows,
        ))
    return results
