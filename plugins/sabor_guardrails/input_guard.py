"""Input guard on fifi (D11): the owner's message plus fifi's last message (≤ 500 chars) get a Haiku verdict once per
turn; allow and uncertain let the turn run, block answers with the scope message, and any failure blocks with the
infrastructure message. The gateway note of a spreadsheet saved inside SABOR_IMPORT_DIR is removed before
classification, so an import is never blocked.
"""

import os
import re
from collections import namedtuple

from .messages import INFRA_BLOCK_MESSAGE, SCOPE_BLOCK_MESSAGE

LAST_MESSAGE_CHARS = 500
Decision = namedtuple("Decision", "action message")  # action: "next" (run the model call) or "block"
# Exact gateway wording for a binary document (gateway/run.py in the pinned Hermes).
_DOCUMENT_NOTE = re.compile(
    r"\[The user sent a document: '(?P<name>[^']*)'\. It is saved at: (?P<path>\S+?)\. "
    r"Its text is not inlined here \(it's a binary format such as PDF or DOCX\)\. "
    r"To read it, extract the document's text yourself — for example with the terminal tool or the "
    r"ocr-and-documents skill — before answering, instead of asking the user to paste the contents\.\]")


def strip_import_note(message: str, import_dir: str) -> str:
    root = os.path.normpath(import_dir)

    def strip_if_import(match: re.Match) -> str:
        path = os.path.normpath(match["path"])
        inside = os.path.dirname(path) == root or path.startswith(root + os.sep)
        return "" if inside and path.lower().endswith(".xlsx") else match.group(0)

    return _DOCUMENT_NOTE.sub(strip_if_import, message).strip()


def decide(owner_message: str, last_assistant_message: str, classify, *, api_call_count: int, import_dir: str) -> Decision:
    if api_call_count != 0:  # one verdict per owner turn, not per model call
        return Decision("next", None)
    try:
        message = strip_import_note(owner_message or "", import_dir)
        if not message:
            return Decision("next", None)
        content = (f"Dona Fifi's last message:\n{(last_assistant_message or '')[:LAST_MESSAGE_CHARS]}\n\n"
                   f"Owner's new message:\n{message}")
        verdict = classify(content).verdict
    except Exception:  # timeout, network, unparseable output or a bug: never let an unverified turn through
        return Decision("block", INFRA_BLOCK_MESSAGE)
    return Decision("block", SCOPE_BLOCK_MESSAGE) if verdict == "block" else Decision("next", None)
