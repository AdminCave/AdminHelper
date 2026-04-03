import json
from typing import Any
from app.core.config import CONNECTIONS_FILE


def load_connections() -> list[dict[str, Any]]:
    if not CONNECTIONS_FILE.exists():
        return []
    with open(CONNECTIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_connections(connections: list[dict[str, Any]]) -> None:
    with open(CONNECTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(connections, f, ensure_ascii=False, indent=2)
