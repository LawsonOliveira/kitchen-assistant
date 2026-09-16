"""The account behind a number (probes A–C): the ledger returns it as a display string and the guard puts it in front
of the question that shows its result, because three rounds of prompt changes did not make the model copy it.

Deterministic and conservative: an account is used only when the question already shows the amount it ends in, and
only when the question does not explain itself already.
"""

from .grounding import extract_brl

MAX_ACCOUNTS = 2  # two lines of arithmetic is the most she can read between one pan and the next


def _result_amount(chain: str) -> str:
    """The amount an account arrives at: the one after the last "=", which is what the question repeats."""
    amounts = extract_brl(chain.rsplit("=", 1)[-1])
    return next(iter(amounts), "")


def _operation(chain: str) -> str:
    """The arithmetic itself ("R$ 2,72 ÷ 0,90"), which is what repeats when she words the account her own way."""
    return " ".join(chain.split("=", 1)[0].split())


def with_account(question: str, chains: list[str]) -> str | None:
    """The question with the accounts that explain it, or None when there is nothing to add."""
    useful = [chain for chain in chains
              if _operation(chain) not in question and (amount := _result_amount(chain)) and amount in question]
    if not useful:
        return None
    return ". ".join(useful[:MAX_ACCOUNTS]) + ". " + question


class RememberedAccounts:
    """Accounts already put in front of a question in this session: the price question and the click that follows it
    are two steps of the same decision, and Dona Maria read the arithmetic once (owner, live session)."""

    def __init__(self):
        self._shown: set[str] = set()

    def unseen(self, chains: list[str]) -> list[str]:
        return [chain for chain in chains if chain not in self._shown]

    def remember(self, chains: list[str]) -> None:
        self._shown.update(chains)


def clarify_with_account(args: dict, chains: list[str], shown: "RememberedAccounts | None" = None) -> dict | None:
    """The clarify arguments with each question explained, or None when no question needed it."""
    questions = (args or {}).get("questions")
    chains = shown.unseen(chains) if shown else chains
    if not isinstance(questions, list) or not chains:
        return None
    rewritten, changed, used = [], False, []
    for entry in questions:
        text = entry.get("question") if isinstance(entry, dict) else None
        explained = with_account(text, chains) if isinstance(text, str) else None
        rewritten.append({**entry, "question": explained} if explained else entry)
        if explained:
            changed = True
            used += [chain for chain in chains if _operation(chain) in explained]
    if shown and used:
        shown.remember(used)
    return {**args, "questions": rewritten} if changed else None
