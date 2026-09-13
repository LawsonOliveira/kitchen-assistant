"""Drive the classic Dona Sálvia CLI in a pty for eval trials (PLAN.md open question 13).

The API server gives orchestrator no `clarify` tool, so trials use what Dona Maria uses: `hermes --cli` inside the orchestrator
container, rendered with pyte. One CliSession is one Hermes session. The parsing helpers read the rendered lines.
"""

import fcntl
import os
import pty
import re
import select
import signal
import struct
import termios
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COLS, ROWS = 150, 60
KEYS = {"enter": "\r", "down": "\x1b[B", "up": "\x1b[A", "ctrl_c": "\x03"}
BUSY_MARKER = "Ctrl+C cancel"  # shown in the status area while a turn runs
_SESSION = re.compile(r"Session:\s+(\d{8}_\d{6}_[0-9a-f]{6})")
_REPLY_HEADER = re.compile(r"^\s*─\s{2}\S.*?\s─{3,}\s*$")  # " ─  🍲 Dona Sálvia  ────"
_RULE = re.compile(r"^\s*─{10,}\s*$")
_CHOICE = re.compile(r"^(❯ )?(\d+)\. (.*)$")


def session_id(lines: list[str]) -> str | None:
    return next((match.group(1) for line in lines if (match := _SESSION.search(line))), None)


def replies(lines: list[str]) -> list[str]:
    """Bodies of Dona Sálvia's reply boxes, in order."""
    bodies, body = [], None
    for line in lines:
        if body is None:
            if _REPLY_HEADER.match(line):
                body = []
        elif _RULE.match(line):
            bodies.append("\n".join(body).strip())
            body = None
        else:
            body.append(line.rstrip()[1:] if line.startswith(" ") else line.rstrip())
    return bodies


def parse_clarify(lines: list[str]) -> dict | None:
    """The question being answered in an open clarify box: its text, choices (without "Other"), the highlighted
    choice and the position of "Other"."""
    starts = [index for index, line in enumerate(lines) if "Hermes needs your input" in line]
    if not starts:
        return None
    question, labels, selected, active = [], [], 0, False
    for line in lines[starts[-1] + 1:]:
        if line.lstrip().startswith("╰"):
            break
        text = line.strip().removeprefix("│").removesuffix("│").strip()
        if text.startswith("▸ "):
            question, labels, active = [text[2:]], [], True
        elif text.startswith(("· ", "✓ ")):
            if active and labels:
                break
            active = False
        elif active and (match := _CHOICE.match(text)):
            if match.group(1):
                selected = int(match.group(2)) - 1
            labels.append(match.group(3))
        elif active and labels:
            labels[-1] += " " + text  # a long choice wraps
        elif active:
            question.append(text)
    if not active:
        return None
    other = next((index for index, label in enumerate(labels) if label.startswith("Other")), None)
    choices = [label.removesuffix(" (Recommended)") for label in labels if not label.startswith("Other")]
    return {"question": " ".join(question), "choices": choices, "selected": selected, "other": other}


def keys_to(selected: int, target: int) -> list[str]:
    step = "down" if target > selected else "up"
    return [step] * abs(target - selected) + ["enter"]


def clarify_actions(clarify: dict, index) -> list[tuple]:
    """How to answer a parsed clarify: move to a choice index, or type ("other", text) after selecting "Other" — or
    directly, when the prompt has no buttons."""
    if not isinstance(index, tuple):
        return [("keys", keys_to(clarify["selected"], index))]
    if clarify["other"] is None:
        return [("text", index[1])]
    return [("keys", keys_to(clarify["selected"], clarify["other"])), ("text", index[1])]


class CliSession:
    """One `hermes --cli` process in a pty; call close() when the trial ends."""

    def __init__(self):
        import pyte

        self.screen = pyte.HistoryScreen(COLS, ROWS, history=50000)
        self.stream = pyte.ByteStream(self.screen)
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(REPO)
            os.environ.update(TERM="xterm-256color", COLUMNS=str(COLS), LINES=str(ROWS))
            os.execvp("docker", ["docker", "compose", "exec", "-it", "-u", "hermes", "-w", "/workspace", "orchestrator", "hermes", "--cli"])
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
        self.alive, self.last_change, self._last_text = True, time.time(), ""

    def _pump(self, seconds: float) -> None:
        end = time.time() + seconds
        while self.alive and time.time() < end:
            ready, _, _ = select.select([self.fd], [], [], 0.2)
            if not ready:
                continue
            try:
                data = os.read(self.fd, 65536)
            except OSError:
                data = b""
            if not data:
                self.alive = False
                return
            self.stream.feed(data)
            text = re.sub(r"\d", "", "\n".join(self.lines()))  # timers tick every second; they are not progress
            if text != self._last_text:
                self._last_text, self.last_change = text, time.time()

    def lines(self) -> list[str]:
        return [line.rstrip() for line in self.screen.display]

    def history(self) -> list[str]:
        top = ["".join(line[x].data for x in range(COLS)).rstrip() for line in self.screen.history.top]
        return top + self.lines()

    def send_text(self, text: str) -> None:
        os.write(self.fd, text.encode())
        self._pump(0.3)
        os.write(self.fd, b"\r")
        self.last_change = time.time()

    def press(self, keys: list[str]) -> None:
        for key in keys:
            os.write(self.fd, KEYS[key].encode())
            self._pump(0.3)
        self.last_change = time.time()

    def wait(self, quiet_seconds: float = 6, timeout_seconds: float = 900) -> str:
        """Pump output until orchestrator is idle or a clarify box is open: "idle", "clarify", "exited" or "timeout"."""
        started = time.time()
        self._pump(8)
        while time.time() - started < timeout_seconds:
            if not self.alive:
                return "exited"
            if time.time() - self.last_change >= quiet_seconds:
                if parse_clarify(self.lines()):
                    return "clarify"
                if not any(BUSY_MARKER in line for line in self.lines()):
                    return "idle"
            self._pump(2)
        return "timeout"

    def close(self) -> None:
        """/quit first: killing the host-side `docker compose exec` leaves `hermes --cli` running inside orchestrator."""
        if self.alive:
            try:
                self.send_text("/quit")
                self._pump(10)
            except OSError:
                pass
        if self.alive:
            try:
                os.kill(self.pid, signal.SIGTERM)
                self._pump(2)
            except OSError:
                pass
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass
