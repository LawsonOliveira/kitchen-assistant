"""The highlight of a node, checked by running the page's own code (owner, 2026-09-16).

The researcher stayed lit after it had finished, while its arrow had already gone dark: one `web_extract` span opened
and never closed (the fan-out branch ended with the request), and the node waited for a half that never came. The rule
is that an agent's request contains everything it starts, so the close of its `a2a_serve` span ends its highlight.

The block between the markers in services/cockpit/index.html is self-contained on purpose: this test extracts it and
runs it under node, so the page's logic is tested instead of a copy of it.
"""

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

INDEX = Path(__file__).resolve().parents[1] / "index.html"
BLOCK = re.compile(r"// --- highlight.*?// --- end highlight ---", re.S)
HARNESS = """
const PULSE_MS = 2500;
const fired = [];
globalThis.setTimeout = (fn) => { fired.push(fn); return fired.length; };
globalThis.clearTimeout = () => {};
function node() {
  const classes = new Set();
  return {classList: {add: (c) => classes.add(c), remove: (...cs) => cs.forEach((c) => classes.delete(c)),
                      has: (c) => classes.has(c)}, classes};
}
function settle() { while (fired.length) fired.shift()(); }
"""
CASES = {
    "the node stays lit while a span is open": """
        const el = node();
        pulse("researcher", el, "active", {kind: "tool_call", span_id: "a", status: "running"});
        settle();
        if (!el.classList.has("active")) throw new Error("the node went dark while the tool was still running");
    """,
    "a span that never closes does not keep the node lit": """
        const el = node();
        pulse("researcher", el, "active", {kind: "tool_call", span_id: "a", status: "running"});
        pulse("researcher", el, "active", {kind: "a2a_serve", span_id: "req", status: "ok"});
        settle();
        if (el.classList.has("active")) throw new Error("the researcher stayed lit after answering the request");
    """,
    "a sibling still working keeps the node lit": """
        const el = node();
        pulse("researcher", el, "active", {kind: "tool_call", span_id: "a", status: "running"});
        pulse("researcher", el, "active", {kind: "tool_call", span_id: "b", status: "running"});
        pulse("researcher", el, "active", {kind: "tool_call", span_id: "a", status: "ok"});
        settle();
        if (!el.classList.has("active")) throw new Error("the node went dark with a tool still running");
    """,
    "a late opening half does not light a span that already closed": """
        const el = node();
        pulse("researcher", el, "active", {kind: "tool_call", span_id: "a", status: "ok"});
        pulse("researcher", el, "active", {kind: "tool_call", span_id: "a", status: "running"});
        settle();
        if (el.classList.has("active")) throw new Error("a finished span was reopened by its own opening event");
    """,
}


@pytest.mark.skipif(shutil.which("node") is None, reason="node runs the page's own highlight code")
@pytest.mark.parametrize("name, case", CASES.items(), ids=list(CASES))
def test_the_highlight_follows_the_work(name, case, tmp_path):
    block = BLOCK.search(INDEX.read_text())
    assert block, "the highlight block markers are gone from index.html"
    script = tmp_path / "pulse.js"
    script.write_text(HARNESS + block.group(0) + "\n" + textwrap.dedent(case))
    done = subprocess.run(["node", str(script)], capture_output=True, text=True)
    assert done.returncode == 0, f"{name}: {done.stderr.strip()}"
