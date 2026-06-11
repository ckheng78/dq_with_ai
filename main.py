import json
import os
import sys


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "settings.json")

REQUIRED_DIRS = ["data", "rules", "joins", "reports", "config", "workflows"]


def ensure_folders():
    for folder in REQUIRED_DIRS:
        path = os.path.join(BASE_DIR, folder)
        os.makedirs(path, exist_ok=True)


def load_config() -> dict:
    if not os.path.isfile(CONFIG_PATH):
        print(f"Config file not found: {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    ensure_folders()
    config = load_config()
    from app import App
    app = App(config)
    app.mainloop()
