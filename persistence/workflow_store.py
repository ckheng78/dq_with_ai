import json
import os
from datetime import datetime


def save(workflow: dict, workflows_dir: str) -> str:
    os.makedirs(workflows_dir, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in workflow["name"])
    path = os.path.join(workflows_dir, f"{safe_name}.json")
    now = datetime.now().isoformat()
    data = dict(workflow)
    if "created_at" not in data:
        data["created_at"] = now
    data["updated_at"] = now
    data["version"] = 1
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


def load_all(workflows_dir: str) -> list[dict]:
    if not os.path.isdir(workflows_dir):
        return []
    result = []
    for fname in os.listdir(workflows_dir):
        if fname.endswith(".json"):
            try:
                with open(os.path.join(workflows_dir, fname), "r", encoding="utf-8") as fh:
                    result.append(json.load(fh))
            except Exception:
                pass
    result.sort(key=lambda w: w.get("updated_at", ""), reverse=True)
    return result
