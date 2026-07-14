"""Rough token estimate for the tool-boundary payload.

The MCP server cannot see Copilot/GPT-4o's full token usage (system prompt, chat
history, model reasoning live on the cloud side). What it *can* estimate is the
size of what flows through our tools — the order slip and tool args/results. We
report that as an approximate "planning" figure, clearly labelled as a
tool-boundary estimate, not the whole session.

Uses tiktoken if available, else a chars/4 heuristic — no hard dependency.
"""

import json

try:
    import tiktoken  # type: ignore

    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:  # pragma: no cover - tiktoken optional
    _ENC = None


def estimate(obj) -> int:
    text = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    if _ENC is not None:
        return len(_ENC.encode(text))
    return max(1, len(text) // 4)
