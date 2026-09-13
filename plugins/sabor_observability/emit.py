"""Loop 0 stub: every event is one JSON line on stdout. Loop 5 sends the same events to the cockpit and Langfuse."""

import json
import os
import sys
from datetime import datetime, timezone


def emit(kind: str, name: str, **fields) -> dict:
    event = {
        "agent": os.environ.get("SABOR_AGENT_ROLE", "unknown"),
        "kind": kind,
        "name": name,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **fields,
    }
    print(json.dumps(event, ensure_ascii=False, default=str), file=sys.stdout, flush=True)
    return event
