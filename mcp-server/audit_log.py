"""Append-only local audit log — solution-design.md §13.

One line per tool invocation: timestamp, tool name, input summary, outcome.
Never logs raw PHI-shaped values, only the request parameters we already
treat as safe (modality, counts, ids) and a short outcome string.
"""

import json
from datetime import datetime, timezone

import config


def log_call(tool: str, input_summary: dict, outcome: str) -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "input": input_summary,
        "outcome": outcome,
    }
    with open(config.LOG_DIR / "agent.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
