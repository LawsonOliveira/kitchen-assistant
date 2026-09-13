"""Minimal A2A v1.0 JSON-RPC client (stdlib only), matching what Hermes' a2a plugin serves.

One `SendMessage` per call, always with a fresh contextId: researcher and experts must stay
stateless across requests (PLAN.md D5).
"""

import json
import socket
import urllib.error
import urllib.request
import uuid


class A2AError(RuntimeError):
    """Any failure talking to a peer. Callers must surface it, never swallow it."""


class A2AAuthError(A2AError):
    """The peer rejected our credential (401) or does not trust our identity (403)."""


class A2ATimeout(A2AError):
    """The peer did not answer within the timeout."""


def _reply_text(result: dict) -> str:
    payload = result.get("task") or result.get("message") or result
    for artifact in payload.get("artifacts") or []:
        text = "".join(part.get("text", "") for part in artifact.get("parts") or [])
        if text:
            return text
    message = (payload.get("status") or {}).get("message") or payload
    return "".join(part.get("text", "") for part in message.get("parts") or [])


def send_message(peer_url: str, token: str, text: str, timeout_s: float) -> str:
    body = {
        "jsonrpc": "2.0",
        "id": uuid.uuid4().hex,
        "method": "SendMessage",
        "params": {
            "message": {
                "role": "ROLE_USER",
                "parts": [{"text": text, "mediaType": "text/plain"}],
                "messageId": uuid.uuid4().hex,
                "contextId": "ctx-" + uuid.uuid4().hex[:16],
            }
        },
    }
    request = urllib.request.Request(
        peer_url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "A2A-Version": "1.0", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            reply = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise A2AAuthError(f"{peer_url} rejected the call (HTTP {error.code})") from error
        raise A2AError(f"{peer_url} failed with HTTP {error.code}") from error
    except (TimeoutError, socket.timeout) as error:
        raise A2ATimeout(f"{peer_url} did not answer within {timeout_s}s") from error
    except urllib.error.URLError as error:
        if isinstance(error.reason, (TimeoutError, socket.timeout)):
            raise A2ATimeout(f"{peer_url} did not answer within {timeout_s}s") from error
        raise A2AError(f"{peer_url} unreachable: {error.reason}") from error
    if "error" in reply:
        raise A2AError(f"{peer_url} returned a JSON-RPC error: {reply['error'].get('message', reply['error'])}")
    return _reply_text(reply.get("result") or {})
