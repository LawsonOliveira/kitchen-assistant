"""Eval-only replay of web_search / web_extract from local fixture pages (PLAN.md Loop 2 step 6, correction C27).

The pinned Hermes has no local extract backend (evals/NOTES.md), so the researcher-eval service keeps its normal
web tools and researcher's transform_tool_result replaces their results with the fixture pages. It is enabled
only by SABOR_WEB_FIXTURES_DIR, which only the `eval` compose profile sets.
"""

import json
import re
from html.parser import HTMLParser
from pathlib import Path

FIXTURE_BASE_URL = "https://fixtures.sabor.test/"
_WORD = re.compile(r"\w{3,}")


class _PageText(HTMLParser):
    """Title and visible text lines of an HTML page (script and style skipped)."""

    def __init__(self):
        super().__init__()
        self.title, self.lines, self._in_title, self._hidden_depth = "", [], False, 0

    def handle_starttag(self, tag, attrs):
        self._in_title = self._in_title or tag == "title"
        self._hidden_depth += tag in ("script", "style")

    def handle_endtag(self, tag):
        self._in_title = self._in_title and tag != "title"
        self._hidden_depth -= tag in ("script", "style")

    def handle_data(self, data):
        text = " ".join(data.split())
        if text and not self._hidden_depth:
            if self._in_title:
                self.title += text
            else:
                self.lines.append(text)


def _page(path: Path) -> _PageText:
    page = _PageText()
    page.feed(path.read_text(encoding="utf-8"))
    return page


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _search(pages_dir: Path, query: str, limit: int = 3) -> dict:
    query_words = _words(query)
    scored = sorted((-len(query_words & _words(_page(path).title)), path.name) for path in pages_dir.glob("*.html"))
    names = [name for negative_score, name in scored if negative_score < 0][:limit]
    rows = [{"title": _page(pages_dir / name).title, "url": FIXTURE_BASE_URL + name, "description": "", "position": position}
            for position, name in enumerate(names, start=1)]
    return {"success": True, "data": {"web": rows}}


def _extract(pages_dir: Path, urls: list) -> dict:
    results = []
    for entry in urls:
        url = str(entry.get("url", "") if isinstance(entry, dict) else entry)
        name = url.removeprefix(FIXTURE_BASE_URL)
        if url.startswith(FIXTURE_BASE_URL) and "/" not in name and (pages_dir / name).is_file():
            page = _page(pages_dir / name)
            results.append({"url": url, "title": page.title, "content": "\n".join(page.lines)})
        else:
            results.append({"url": url, "error": "not a fixture page"})
    return {"results": results}


def replay(pages_dir: Path, tool_name: str, args: dict | None) -> str | None:
    """The fixture result for a web tool call, or None for any other tool."""
    args = args or {}
    if tool_name == "web_search":
        return json.dumps(_search(Path(pages_dir), str(args.get("query", ""))), ensure_ascii=False)
    if tool_name == "web_extract":
        return json.dumps(_extract(Path(pages_dir), list(args.get("urls") or [])), ensure_ascii=False)
    return None
