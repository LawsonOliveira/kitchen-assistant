"""Memory write guard on fifi (D15): memory text reaches every future prompt, so only an explicit allow is written."""

import json

from .messages import MEMORY_BLOCK_MESSAGE


def check_memory_write(args: dict, classify) -> dict | None:
    try:
        if classify(json.dumps(args or {}, ensure_ascii=False)).verdict == "allow":
            return None
    except Exception:
        pass  # fail closed
    return {"action": "block", "message": MEMORY_BLOCK_MESSAGE}
