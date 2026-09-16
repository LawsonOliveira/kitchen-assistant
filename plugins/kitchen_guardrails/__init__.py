"""Guardrails plugin (PLAN.md Loop 4; D10–D13, D15, D37, D38; open question 10).

All agents: tool allowlist in pre_tool_call (the only fail-closed hook) and the per-turn cost cap.
orchestrator only: input guard (llm_execution middleware), output verifier (transform_llm_output), memory write guard,
the Confirmar click check for ask_* requests, and fixed progress messages. Hermes hooks and middleware fail open,
so every guard catches its own errors and blocks with a fixed message.
"""

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from . import account, approval, classifier, cost_cap, input_guard, memory_guard, output_guard, pending, progress, tool_policy
from .grounding import SessionGrounding
from .messages import COST_CAP_MESSAGE, INFRA_BLOCK_MESSAGE

log = logging.getLogger(__name__)
SKIPPED_PLATFORMS = {"subagent", "curator"}  # delegate children and Hermes' curator are not owner turns
COST_CAP_ERROR = {"code": "turn_cost_cap_reached", "message": "the owner turn's cost cap was reached"}


def _emit(kind: str, name: str, **fields) -> None:
    """Best-effort telemetry through kitchen_observability; the guard never depends on it."""
    try:
        import sys

        emit = next((module.emit for key, module in list(sys.modules.items())
                     if key.endswith("kitchen_observability.emit") and hasattr(module, "emit")), None)
        if emit:
            emit(kind, name, **fields)
    except Exception:
        log.debug("guard event not emitted", exc_info=True)


VERDICT_MEMORY = 50  # the last owner messages judged, enough for a conversation and bounded for a long-lived gateway


def _said(last_assistant: str, owner: str) -> str:
    """The exchange the classifier reads: a bare "sim" means nothing without the question above it."""
    return " ".join((last_assistant or "").split()).casefold()[-200:] + "\n" + " ".join((owner or "").split()).casefold()


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text")
    return ""


def _owner_and_last_assistant(request: dict) -> tuple[str, str]:
    """The owner's newest message and orchestrator's message before it, from the provider request."""
    messages = (request or {}).get("messages") or []
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") == "user" and _text(message.get("content")):
            previous = next((_text(m.get("content")) for m in reversed(messages[:index]) if m.get("role") == "assistant"), "")
            return _text(message.get("content")), previous
    return "", ""


def _synthetic(text: str, model: str):
    """A provider response our code wrote (NOTES.md §1): the turn ends with this text and no tool call."""
    from anthropic.types import Message, TextBlock, Usage

    return Message(id="msg_kitchen_guardrails", type="message", role="assistant", model=model or "kitchen-guardrails",
                   content=[TextBlock(type="text", text=text)], stop_reason="end_turn", stop_sequence=None,
                   usage=Usage(input_tokens=0, output_tokens=0))


def _first_json_object(text: str) -> dict:
    try:
        data = json.JSONDecoder().raw_decode(text[text.index("{"):])[0]
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def register(ctx) -> None:
    role = os.environ.get("KITCHEN_AGENT_ROLE", "")
    timeout_s = classifier.guard_timeout_seconds(os.environ)  # raises: the plugin refuses to load
    costs = cost_cap.SessionCosts(Decimal(os.environ["KITCHEN_TURN_COST_CAP_USD"]), agent=role)
    cost_cap.ACTIVE = costs
    ledger, groundings = tool_policy.ClickLedger(), {}
    open_state, shown_accounts, approvals, verdicts = pending.Pending(), {}, approval.Approvals(), {}
    guard_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="kitchen-input-guard")
    import_dir = os.environ.get("KITCHEN_IMPORT_DIR", "/opt/data/cache/documents")

    def classify_with(prompt_file: str):
        return lambda content: classifier.classify(ctx.llm, prompt_file, content, timeout_s)

    def cost_cap_reply() -> str:
        if role == "orchestrator":
            return COST_CAP_MESSAGE
        return json.dumps({"result": {"error": COST_CAP_ERROR}, "questions_for_owner": [], "cost_usd_spent": 0.0})

    def llm_execution(request=None, next_call=None, api_call_count=0, platform="", session_id="", model="", **_):
        guard = None
        try:
            if role == "orchestrator" and platform not in SKIPPED_PLATFORMS and api_call_count == 1:
                # PL9 lever 4: the classification (2–5 s) runs alongside the first model call; a block discards the answer,
                # whose tool calls have not run yet. One owner message gets one verdict: Hermes may start the turn again
                # after an API retry, and asking twice gave two different answers for the same sentence (C92).
                owner, last_assistant = _owner_and_last_assistant(request)
                decided = verdicts.get(_said(last_assistant, owner))
                if not owner:
                    guard = None
                elif decided is not None:
                    decision = decided
                    return _synthetic(decision.message, model) if decision.action == "block" else next_call(request)
                else:
                    # The cockpit should light the guard while it classifies, not only when it answers.
                    _emit("guard_input", "input_guard", status="running", session_id=session_id,
                          prompt_hash=classifier.prompt_hash("input_guard.md"))
                    guard = guard_pool.submit(input_guard.decide, owner, last_assistant, classify_with("input_guard.md"),
                                              api_call_count=api_call_count, import_dir=import_dir)
            if platform != "curator" and not costs.allows_next_call(session_id):
                _emit("error", "turn_cost_cap_reached", status="blocked", session_id=session_id,
                      preview=json.dumps(costs.breakdown(session_id))[:200])
                return _synthetic(cost_cap_reply(), model)
        except Exception:
            log.exception("kitchen_guardrails: guard failed before the model call; blocking")
            return _synthetic(INFRA_BLOCK_MESSAGE if role == "orchestrator" else cost_cap_reply(), model)
        response = next_call(request)
        if guard is None:
            return response
        try:
            decision = guard.result()
        except Exception:
            log.exception("kitchen_guardrails: input guard failed; blocking")
            decision = input_guard.Decision("block", INFRA_BLOCK_MESSAGE)
        owner, _ = _owner_and_last_assistant(request)
        if owner:
            # Keyed by what she typed: a restarted turn comes back with a new trace and sometimes a new session (C92).
            verdicts[_said(_owner_and_last_assistant(request)[1], owner)] = decision
            for old in list(verdicts)[:-VERDICT_MEMORY]:
                verdicts.pop(old, None)
        _emit("guard_input", "input_guard", status="blocked" if decision.action == "block" else "ok",
              session_id=session_id, prompt_hash=classifier.prompt_hash("input_guard.md"))
        return _synthetic(decision.message, model) if decision.action == "block" else response

    def pre_llm_call(session_id="", turn_id="", user_message="", platform="", parent_session_id="", **_):
        if platform == "subagent":
            if parent_session_id:
                costs.link_child(session_id, parent_session_id)
            return None
        received = None
        if role == "orchestrator" and user_message:
            groundings.setdefault(session_id, SessionGrounding()).add_owner_message(str(user_message))
        if role != "orchestrator":  # an A2A request carries what is left of the owner turn's budget
            remaining = (_first_json_object(user_message or "").get("trace") or {}).get("turn_cost_remaining_usd")
            received = Decimal(str(remaining)) if isinstance(remaining, (int, float)) else None
        costs.begin(session_id, turn_id or "turn", received)
        return None

    def subagent_start(parent_session_id="", child_session_id="", **_):
        if parent_session_id and child_session_id:
            costs.link_child(child_session_id, parent_session_id)

    def post_api_request(session_id="", model="", response=None, **_):
        usage = (response or {}).get("usage") or {}
        tokens_in = sum(int(usage.get(key) or 0) for key in ("input_tokens", "cache_read_tokens", "cache_write_tokens"))
        try:
            usd = cost_cap.cost_of_call(model, tokens_in, int(usage.get("output_tokens") or 0), cost_cap.PRICES)
        except ValueError:
            log.error("kitchen_guardrails: no price for %r; counting the whole cap so the turn stops", model)
            usd = costs.cap.cap
        costs.add_own(session_id, usd)

    def pre_tool_call(tool_name="", args=None, session_id="", **_):
        try:
            if tool_name in tool_policy.ASK_TOOLS:
                approvals.remember_request(session_id, args or {})
            decision = tool_policy.decide(role, tool_name)
            if decision is None and role == "orchestrator":
                decision = tool_policy.check_click(ledger, session_id, tool_name, args)
                if decision is None and tool_name == "memory":
                    decision = memory_guard.check_memory_write(args or {}, classify_with("memory_guard.md"))
                    _emit("guard_memory", "memory_guard", status="blocked" if decision else "ok", session_id=session_id,
                          prompt_hash=classifier.prompt_hash("memory_guard.md"))
                if decision is None and (message := progress.progress_message(tool_name)):
                    _show_progress(message)
                if decision is None:
                    decision = tool_policy.check_repeat(ledger, session_id, tool_name, args)
                if decision is None:
                    decision = tool_policy.check_one_decision(tool_name, args)
                if decision is None and tool_name == "clarify":
                    # The ledger wrote the account; the model keeps paraphrasing it, so the code puts it in front of
                    # the question that shows its result (probes A-C, didactic clarity stuck at 2).
                    questions = [{**entry, "question": approvals.with_evidence(session_id, entry.get("question", ""))}
                                 if isinstance(entry, dict) else entry for entry in (args or {}).get("questions") or []]
                    shown = {**(args or {}), "questions": questions} if questions else (args or {})
                    explained = account.clarify_with_account(shown, groundings.setdefault(session_id, SessionGrounding()).chains,
                                                             shown_accounts.setdefault(session_id, account.RememberedAccounts()))
                    if explained is None and questions and questions != ((args or {}).get("questions") or []):
                        explained = shown
                    if explained is not None:
                        return {"action": "modify", "args": explained}
            if decision is not None:
                _emit("tool_call", tool_name, status="blocked", session_id=session_id, preview=decision["message"][:200])
            return decision
        except Exception:
            log.exception("kitchen_guardrails: tool policy failed; blocking %s", tool_name)
            return {"action": "block", "message": tool_policy.BLOCKED_MESSAGE}

    def post_tool_call(tool_name="", result=None, session_id="", **_):
        """clarify is an inline agent tool: Hermes fires post_tool_call for it, never transform_tool_result."""
        if tool_name != "clarify":
            return
        try:
            ledger.record_clarify(session_id, result)
        except Exception:
            log.exception("kitchen_guardrails: could not record the clarify answer")

    def transform_tool_result(tool_name="", args=None, result=None, session_id="", **_):
        try:
            if tool_name in tool_policy.ASK_TOOLS or tool_name.startswith("mcp__ledger__"):
                groundings.setdefault(session_id, SessionGrounding()).add_from_tool_result(result)
                open_state.read_tool_result(session_id, result)
                approvals.remember_result(session_id, result)
                if tool_name in tool_policy.ASK_TOOLS:
                    data = _first_json_object(result if isinstance(result, str) else json.dumps(result))
                    error = data.get("error") if isinstance(data.get("error"), dict) else {}
                    if (args or {}).get("owner_confirmation") and error.get("code") in tool_policy.NOT_SENT_ERRORS:
                        ledger.refund(session_id)  # the click was checked, but the request never reached the expert
                    spent = data.get("cost_usd_spent")
                    if isinstance(spent, (int, float)) and spent > 0:
                        costs.add_reported(session_id, Decimal(str(spent)), agent=tool_name.removeprefix("ask_"))
        except Exception:
            log.exception("kitchen_guardrails: could not record %s result", tool_name)
        return None

    def transform_llm_output(response_text="", session_id="", platform="", **_):
        if platform in SKIPPED_PLATFORMS:
            return None
        reviewed = output_guard.review(response_text, groundings.setdefault(session_id, SessionGrounding()),
                                       classify_with("output_policy.md"), platform=platform)
        if reviewed == response_text:  # a blocked reply is our own message; only her own answer gets the question
            reviewed = pending.with_next_question(open_state, session_id, reviewed)
        _emit("guard_output", "output_guard", status="ok" if reviewed == response_text else "blocked", session_id=session_id,
              prompt_hash=classifier.prompt_hash("output_policy.md"))
        return reviewed

    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("subagent_start", subagent_start)
    ctx.register_hook("post_api_request", post_api_request)
    ctx.register_middleware("llm_execution", llm_execution)
    if role == "orchestrator":
        ctx.register_hook("post_tool_call", post_tool_call)
        ctx.register_hook("transform_tool_result", transform_tool_result)
        ctx.register_hook("transform_llm_output", transform_llm_output)


def _show_progress(message: str) -> None:
    """Fixed progress string to the CLI and the gateway chat through the running agent (NOTES.md §4)."""
    try:
        from agent.subagent_lifecycle import get_active_subagent_parent

        agent = get_active_subagent_parent()
        if agent is not None:
            agent._emit_status(message)
    except Exception:
        log.debug("progress message not shown", exc_info=True)
