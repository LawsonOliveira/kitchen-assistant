"""Fixed progress strings for slow expert calls (D38): no model text reaches the owner mid-turn."""

from .messages import PROGRESS


def progress_message(tool_name: str) -> str | None:
    return PROGRESS.get(tool_name)
