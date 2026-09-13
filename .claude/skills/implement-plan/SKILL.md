---
name: implement-plan
description: "Implement a PLAN.md exactly as written, loop by loop. Queue any open questions instead of stopping to ask; keep implementing whatever doesn't depend on them; surface the whole queue at once only when nothing else is implementable."
disable-model-invocation: true
---

Implement the referenced plan (default: `PLAN.md` at the repo root; use the path the user
gave if they gave one) **strictly as written**. This skill does not redesign the plan. If you
think a decision in it is wrong, that belief is itself an open question to queue — never a
silent unilateral change.

## State to track

- **Progress, in the plan file itself.** Check off (`- [x]`) each step and each Definition of
  Done item in `PLAN.md` as you complete and verify it. This is the source of truth for what's
  done — don't rely on your own turn-by-turn narration for it, and don't mark something done
  before its test actually passed.
- **The open-questions queue, in the plan's "Open questions" section.** Every doubt goes there
  the moment it comes up — never held only in your head, never asked immediately in the middle
  of implementation.

## Process

1. Read the whole plan before writing any code: requirements, every loop, the dependency map,
   and the tests defined for each loop.
2. Work loops in dependency order (per the "Depends on" lines / Mermaid map): a loop starts
   only once every loop it depends on is fully checked off and its tests pass. Within a loop,
   do the steps marked *(sequential)* in order; steps marked *(parallel with each other)* can be
   done in any order, or dispatched to subagents if truly independent.
3. After finishing a loop's steps, run exactly the tests that loop defines before checking off
   its Definition of Done. A step is not done until its test passed — not until the code was
   written.
4. When something is genuinely ambiguous, missing, or contradicts the plan — a decision the
   plan never made, a fact only the user has, two parts of the plan disagreeing — do not stop
   and ask right away:
   - Append it to the queue: what step is blocked, the precise question, and your best-guess
     default if you have one.
   - Skip only the piece of work that depends on that specific answer. Keep implementing
     everything else — other steps in the same loop, other loops that don't depend on it.
   - Never quietly guess on something you flagged and move on as if it were resolved. If you
     must leave something in place to keep going, stub it visibly (e.g. `# TODO(open question
     N): ...`) rather than a silent assumption.
5. Keep going until the frontier is empty: every step not blocked by a queued question is
   implemented and its loop's tests pass.
6. **Queue empty at that point:** the plan is fully implemented. Run the full test suite (the
   plan's global Definition of Done), report the result, and stop.
7. **Queue non-empty:** present every queued question together, in one batch, formatted as:

   ```
   ❓ **Q1** — blocks <loop/step>: <the question>
   ➡️ default if unanswered: <your best guess, or "none — this stays blocked">
   ```

   Then wait. Don't dribble questions out one at a time, and don't ask new ones mid-batch —
   collect everything blocked at this point into the same round. When the user answers,
   record the answers in the plan, unblock the dependent steps, and resume from step 2. If
   answering surfaces new questions, queue those the same way and keep implementing what's
   now unblocked; only open a new batch once the frontier is empty again.
