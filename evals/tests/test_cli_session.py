"""Reading the classic CLI screen (PLAN.md open question 13): replies, clarify prompts, session id, keys to answer.

The canned screens are copied from the Loop 3–5 CLI runs (pyte rendering, 150 columns, Dona Fifi skin).
"""

import cli_session

BANNER = """│  claude-sonnet-5 · Nous Research  autonomous-ai-agents: claude-code, codex                                    │
│            /workspace             creative: architecture-diagram                                               │
│  Session: 20260913_181934_340f31  devops: sdlc-review                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
Oi, querida! Eu sou a Dona Fifi. Me conta o que tem na despensa que a gente monta o seu cardápio.""".splitlines()

REPLY = """● Quero sim, calcula o custo e me mostra os preços.
🧮 Fazendo as contas…
  ┊ ⚡ ask_cost_   12.2s
 ─  🍲 Dona Fifi  ───────────────────────────────────────────────────────────────────────────────────────────────
 Ótimo, saiu tudo certinho!
 - Arroz: comprou 5 kg por R$ 24,90 → R$ 4,98/kg. Usa 400 g → custo de R$ 1,99
 Qual você prefere?
 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 ⚕ claude-sonnet-5 │ ~30.1K/1M │ [░░░░░░░░░░] ~3% │ ◎ 82.7% │ ◷ 4.4s │ ↑ 78 t/s │ 13m │ ⏲ 28s │ ✓ 1s
❯ Turn these notes into a to-do list""".splitlines()

CLARIFY_TWO = """  ┊ ⚡ ask_recip   28.3s
╭─ Hermes needs your input ────────────────────────────────────────╮
│ 2 questions                                                      │
│ ▸ Sua cozinha tem pelo menos 2 bocas de fogão livres pra fazer   │
│   esse prato?                                                    │
│   ❯ 1. Sim, tenho 2 bocas ou mais (Recommended)                  │
│     2. Não, só tenho 1 boca                                      │
│     3. Other (type your answer)                                  │
│ · Consegue fazer o lote de lançamento (10 porções) em até 45     │
│   minutos de preparo?                                            │
╰──────────────────────────────────────────────────────────────────╯
  ❓ clarify  (  6.5s · ↓ 797 tok)
  ↑/↓ to select, Enter to lock, Tab next question  (113s)
? ❯""".splitlines()

CLARIFY_SECOND = """╭─ Hermes needs your input ────────────────────────────────────────╮
│ 2 questions                                                      │
│ ✓ Sua cozinha tem pelo menos 2 bocas de fogão livres pra fazer   │
│   esse prato?                                                    │
│     Sim, tenho 2 bocas ou mais (Recommended)                     │
│ ▸ Consegue fazer o lote de lançamento (10 porções) em até 45     │
│   minutos de preparo?                                            │
│   ❯ 1. Sim, dá tempo (Recommended)                               │
│     2. Não, demora mais que isso                                 │
│     3. Other (type your answer)                                  │
╰──────────────────────────────────────────────────────────────────╯""".splitlines()


def test_the_session_id_comes_from_the_banner():
    assert cli_session.session_id(BANNER) == "20260913_181934_340f31"


def test_reply_bodies_are_read_from_the_labeled_boxes_without_tool_lines():
    assert cli_session.replies(BANNER + REPLY) == [
        "Ótimo, saiu tudo certinho!\n- Arroz: comprou 5 kg por R$ 24,90 → R$ 4,98/kg. Usa 400 g → custo de R$ 1,99\nQual você prefere?"]


def test_the_active_clarify_question_with_its_choices_and_the_highlighted_one():
    assert cli_session.parse_clarify(CLARIFY_TWO) == {
        "question": "Sua cozinha tem pelo menos 2 bocas de fogão livres pra fazer esse prato?",
        "choices": ["Sim, tenho 2 bocas ou mais", "Não, só tenho 1 boca"], "selected": 0, "other": 2}
    assert cli_session.parse_clarify(CLARIFY_SECOND)["question"] == "Consegue fazer o lote de lançamento (10 porções) em até 45 minutos de preparo?"
    assert cli_session.parse_clarify(REPLY) is None


def test_keys_to_reach_a_choice_from_the_highlighted_one():
    assert cli_session.keys_to(selected=0, target=1) == ["down", "enter"]
    assert cli_session.keys_to(selected=2, target=0) == ["up", "up", "enter"]
    assert cli_session.keys_to(selected=1, target=1) == ["enter"]
