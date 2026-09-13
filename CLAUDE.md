# CLAUDE.md — Sabor da Maria (iFood challenge)

## What this project is
A conversational agent (Hermes Agent, Nous Research) that takes Dona Maria from pantry
to menu: researches real recipes on the web, elicits constraints (utensils, skills,
operations), matches ingredients against the pantry, and computes CMV (cost of goods
sold) + delivery selling price.

- Brief: [desafio-senior-ai-engineer.md](desafio-senior-ai-engineer.md) — source of truth for scope.
- Data: [data/despensa_dona_maria.xlsx](data/despensa_dona_maria.xlsx) — sheets `Despensa` and `Precos`.
- Budget for extra ingredients: R$ 80.00. Platform fee: 10% of the sale price.
- Pricing rules: `unit_cost = total_price_paid / quantity_purchased`;
  `CMV = Σ (quantity_used × unit_cost)`; `P ≥ CMV / 0.90`; `profit = 0.90·P − CMV`.

## Engineering principles (Karpathy style)

**1. The shortest code that solves the problem.** If it fits in 50 readable lines,
don't write 300 with layers. Cleverness is debt; clarity is an asset.

**2. No premature abstraction.** Only extract a function/class after the third real
repetition. Don't build a `BaseAgentFactoryProvider` for one use case. A bit of
duplication is cheaper than the wrong abstraction.

**3. Few dependencies.** Every new import has to justify itself. Prefer stdlib + what
Hermes Agent already provides. Pulling in a whole library for a three-line calculation
is a no.

**4. Small files, read top to bottom.** One file = one responsibility, ideally under
300 lines. The whole repo should fit in an LLM's context — that's a design requirement
here, not an accident.

**5. Look at the data before writing the logic.** Before parsing the spreadsheet, print
the sheets, the types, the units, the weird cases (mismatched units between sheets, an
ingredient that only exists in one of them). Data bugs get solved by looking, not
guessing.

**6. Verify empirically, always.** Run the code, print the numbers, check the CMV by
hand for at least one dish. No "should work." If you claim it passes, it's because you
ran it and watched it pass.

**7. Fail loud and early.** Explicit asserts and errors for incompatible units, missing
unit cost, negative quantities. Silence (`try/except: pass`, a magic default) hides a
pricing bug — which here means Dona Maria losing money.

**8. End-to-end baseline first, optimization later.** Get the full flow working ugly
(pantry → recipe → constraints → CMV → price) before improving prompts, memory, or
tooling. One perfectly polished isolated piece is worth nothing without the whole flow.

**9. One verified step at a time.** Small change → run it → check it → move on. Don't
stack five untested changes.

**10. Names say what the thing is.** `unit_cost_per_kg`, not `uc` or `helper2`.
Comments explain the *why* (the business rule, the decision), never the *what*.

## Conventions

- **Language**: code, names, and commits in English; docs, README, and the agent's
  chat messages in Portuguese (the end user is Dona Maria).
- **Money**: `Decimal`, never `float`. Round only at presentation time.
- **Units**: normalize to a base unit (g, ml, unit) on input; conversion lives in one
  place only.
- **Secrets**: in `.env`, never in the repo. Commit `.env.example`.
- **Tests**: at least the cost/price core must be covered — that's the part that lies
  silently.

## Decisions (record here, not just in chat)
Every architecture choice (model, tools/MCP, memory, skills) must be documented and
justified in the README — it's an explicit deliverable of the challenge. Record the
alternative you rejected and why, not just the choice you made.
