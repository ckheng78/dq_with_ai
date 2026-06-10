import os
from datetime import datetime
from jinja2 import Environment, FileSystemLoader


def _get_env(templates_dir: str) -> Environment:
    return Environment(loader=FileSystemLoader(templates_dir), autoescape=True)


def generate_summary(results, total_rows: int, output_dir: str, templates_dir: str) -> str:
    env = _get_env(templates_dir)
    template = env.get_template("summary.html.j2")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    html = template.render(results=results, total_rows=total_rows, generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    path = os.path.join(output_dir, f"summary_{timestamp}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def generate_detail(result, max_rows: int, output_dir: str, templates_dir: str) -> str:
    env = _get_env(templates_dir)
    template = env.get_template("detail.html.j2")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c if c.isalnum() else "_" for c in result.name)
    html = template.render(
        result=result,
        rows=result.violating_rows[:max_rows],
        truncated=len(result.violating_rows) > max_rows,
        max_rows=max_rows,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    path = os.path.join(output_dir, f"detail_{safe_name}_{timestamp}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path
