import json
import os
from datetime import datetime


def save(rules: list[dict], rules_dir: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(rules_dir, f"rules_{timestamp}.json")
    data = {
        "version": 1,
        "created_at": datetime.now().isoformat(),
        "rules": rules,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


def load_latest(rules_dir: str) -> list[dict] | None:
    if not os.path.isdir(rules_dir):
        return None
    files = [
        os.path.join(rules_dir, f)
        for f in os.listdir(rules_dir)
        if f.endswith(".json")
    ]
    if not files:
        return None
    newest = max(files, key=os.path.getmtime)
    with open(newest, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("rules", [])
