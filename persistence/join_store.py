import json
import os
from datetime import datetime


def save(join_config: dict, joins_dir: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(joins_dir, f"join_{timestamp}.json")
    data = {
        "version": 1,
        "created_at": datetime.now().isoformat(),
        **join_config,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


def load_latest(joins_dir: str) -> dict | None:
    if not os.path.isdir(joins_dir):
        return None
    files = [
        os.path.join(joins_dir, f)
        for f in os.listdir(joins_dir)
        if f.endswith(".json")
    ]
    if not files:
        return None
    newest = max(files, key=os.path.getmtime)
    with open(newest, "r", encoding="utf-8") as f:
        return json.load(f)
