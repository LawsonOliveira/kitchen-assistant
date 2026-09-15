"""PL9 lever 5 in the agents' versioned config."""

import re
from pathlib import Path

import pytest

AGENTS = Path(__file__).resolve().parents[2] / "agents"


@pytest.mark.parametrize("agent", ["orchestrator", "recipe_expert", "cost_expert", "marketing_expert", "researcher"])
def test_no_agent_offers_the_todo_planner(agent):
    # Live eval trial: recipe_expert called todo_list 12 times; each call is a model round trip that plans nothing.
    disabled = re.search(r"^\s*disabled_toolsets:\s*\[([^\]]*)\]", (AGENTS / agent / "config.yaml").read_text(), flags=re.M)
    assert disabled and "todo" in [name.strip() for name in disabled.group(1).split(",")]


def test_the_orchestrator_is_dona_salvia_and_greets_with_the_owners_words():
    # PL2/PL3 (owner, 2026-09-13): "orchestrator" becomes "orchestrator" in code; the persona is Dona Sálvia, greeting
    # "Olá, sou a Sálvia, como posso te ajudar hoje? 🌿".
    orchestrator = AGENTS / "orchestrator"
    skin = (orchestrator / "skins" / "dona-salvia.yaml").read_text()
    assert re.search(r"^name: dona-salvia$", skin, flags=re.M) and "agent_name: Dona Sálvia" in skin
    assert 'welcome: "Olá, sou a Sálvia, como posso te ajudar hoje? 🌿"' in skin
    assert re.search(r"^\s*skin: dona-salvia\b", (orchestrator / "config.yaml").read_text(), flags=re.M)
    assert "Olá, sou a Sálvia, como posso te ajudar hoje? 🌿" in (orchestrator / "SOUL.md").read_text()
    assert not any(path.name == "fifi" for path in AGENTS.iterdir())


@pytest.mark.parametrize("skill", sorted(AGENTS.glob("*/skills/*/SKILL.md")), ids=lambda path: f"{path.parts[-4]}/{path.parts[-2]}")
def test_every_file_a_skill_points_to_can_be_opened_from_the_skill(skill):
    # Full run, scenario 01 trial 2: recipe-normalization named `contracts/recipe.schema.json`, which skill_view cannot open
    # (it is not in the skill); recipe_expert kept looking for it — skills_list, skill_manage, then `research` with the
    # placeholder items "__unused__" and "dummy" — and registering the owner's own recipe took 17 minutes.
    referenced = re.findall(r"`([\w./-]+\.(?:json|md|yaml|py))`", skill.read_text())
    assert [path for path in referenced if not (skill.parent / path).exists()] == []


def test_the_menu_copy_skill_bans_the_word_that_cost_a_trial():
    # Probe B, scenario 01: marketing wrote "Uma refeição simples e nutritiva". The skill lists "saudável", "fit",
    # "light" and "rico em proteína", never "nutritiva", and the output policy blocked the reply that carried it.
    skill = (AGENTS / "marketing_expert" / "skills" / "ifood-menu-copy" / "SKILL.md").read_text()
    assert "nutritiv" in skill
    policy = (AGENTS.parent / "plugins" / "kitchen_guardrails" / "prompts" / "output_policy.md").read_text()
    assert "nutritiv" in policy


def test_an_expert_never_sends_more_questions_than_its_contract_accepts():
    # Probe A, scenario 09: recipe_expert answered with six questions_for_owner, the contract accepts five, and the A2A
    # client retried the same request — registering "Frango ao molho de açafrão" a second time before failing again.
    import json

    schema = json.loads((AGENTS.parent / "contracts" / "experts" / "recipe_expert.response.json").read_text())
    def find(node, key):
        if isinstance(node, dict):
            for name, value in node.items():
                if name == key:
                    return value
                found = find(value, key)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = find(value, key)
                if found is not None:
                    return found
    cap = find(schema, "questions_for_owner")["maxItems"]
    for expert in ("recipe_expert", "cost_expert", "marketing_expert"):
        rule = next(line for line in (AGENTS / expert / "SOUL.md").read_text().splitlines()
                    if "questions_for_owner" in line and "at most" in line)
        assert f"at most {cap}" in rule, expert


def test_the_price_question_carries_the_arithmetic_that_led_to_it():
    # Probe A: didactic clarity 1 in scenario 07 and 2 in 01 and 04, the three flows where the money is born inside a
    # clarify. Dona Sálvia jumps from the tool result straight to the question, so a rule about "the reply before the
    # options" has nowhere to happen: she writes no reply there. The question itself is the message she reads.
    soul = (AGENTS / "orchestrator" / "SOUL.md").read_text()
    rule = next(line for line in soul.splitlines() if "question that shows a price" in line)
    assert "÷" in rule and "0,90" in rule  # the worked chain, not the result alone
    assert "15%" in rule  # a promotion is asked the same way (scenario 07)


def test_a_parametric_requirement_is_a_kitchen_fact_not_a_confirmation():
    # Final run 20260914-215130, scenario 01 trial 1: she sent 'pressure_cooker', 'stove_burners>=1' and
    # 'max_batch_time_minutes>=45' to confirm_requirement, whose payload takes only gas_or_energy:/other: text, and once
    # omitted numeric_value — four requests rejected by the contract, four model turns spent on nothing.
    rule = next(line for line in (AGENTS / "orchestrator" / "SOUL.md").read_text().splitlines()
                if "confirm_requirement" in line)
    assert "only" in rule and "gas_or_energy:" in rule and "other:" in rule
    assert "stove_burners>=1" in rule and "stove_burners" in rule  # the requirement text is not the key
    assert "numeric_value" in rule and "null" in rule  # always sent, null for equipment and techniques


def test_a_measure_is_asked_of_the_owner_before_it_is_researched():
    # Full run 20260913-192309, scenario 06 (all three trials): Dona Sálvia asked her to confirm a web estimate of 105 g
    # or 150 g for the chocolate bar she buys, priced the dish from it, and her own answer (1 kg) came later or never.
    orchestrator = (AGENTS / "orchestrator" / "SOUL.md").read_text()
    rule = next(line for line in orchestrator.splitlines() if "set_conversion_factor" in line)
    assert "ask her first" in rule and "only when she does not know" in rule
    recipe_expert = (AGENTS / "recipe_expert" / "SOUL.md").read_text()
    measures = next(line for line in recipe_expert.splitlines() if "measure_lookup" in line)
    assert "only when Dona Sálvia says she does not know" in measures


def test_the_price_of_a_missing_item_is_asked_of_the_owner_before_it_is_researched():
    # Full run 20260913-192309, scenario 04 trial 3: the shrimp was bought at the web estimate (R$ 18,99 per 200 g), the
    # shortfall became R$ 123,88 and the budget raise broke the R$ 100,00 cap — her own price (R$ 60,00 the kilo) was
    # never asked for.
    rule = next(line for line in (AGENTS / "orchestrator" / "SOUL.md").read_text().splitlines() if "price_missing_item" in line)
    assert "ask her first" in rule and "only when she does not know" in rule


def test_a_rejected_dish_is_recorded_in_the_same_reply():
    # Full run 20260913-192309, scenario 09 trial 3: the owner rejected the estrogonofe ("fica muito molhado pra
    # marmita"), Dona Sálvia said it was noted and moved on, but no rejection was ever recorded (judge mean 1.75).
    rule = next(line for line in (AGENTS / "orchestrator" / "SOUL.md").read_text().splitlines() if "register_candidate" in line and "reject" in line)
    assert "in the same reply" in rule and "before you suggest anything else" in rule


def test_candidates_are_presented_with_what_is_missing():
    # Rerun of scenario 01: a dish that still needed pimenta-do-reino was offered as "100% despensa", the owner picked it
    # believing she would spend nothing, and the flow deadlocked when she cancelled the purchase.
    rule = next(line for line in (AGENTS / "orchestrator" / "SOUL.md").read_text().splitlines() if "suggest_dishes" in line)
    assert "missing_ingredients" in rule and "never call a dish" in rule


def test_owner_statement_must_be_her_exact_words():
    # Rerun of scenario 06 (all three trials): she answered the weight with a button ("1 kg (1000 g)"), Dona Sálvia sent a
    # paraphrase as evidence, and "the_weight_came_from_the_owner" failed even though the number was hers.
    soul = (AGENTS / "orchestrator" / "SOUL.md").read_text()
    assert "exact sentence or the exact label of the button she clicked" in soul and "never your summary" in soul


def test_the_orchestrator_has_a_response_contract():
    # Full run 20260913-192309: didactic clarity averaged 2.5 and one scenario 01 trial asked 21 separate clarifies —
    # burners, batch time, onion weight, tomato weight, two prices, then a confirmation for each — in 41 replies of about
    # 500 characters each. The owner's bar is 4 in every criterion of every scenario.
    soul = (AGENTS / "orchestrator" / "SOUL.md").read_text()
    # Normalised: the rules are written as markdown bullets, so bold marks and line breaks fall in the middle of phrases.
    section = " ".join(soul[soul.index("## How you answer"):].replace("*", "").split()).lower()
    assert "one clarify with several questions" in section  # group what she can answer at once
    assert "as few lines as the answer needs" in section  # lean, with no fixed number (owner, 2026-09-14)
    assert "already answered" in section  # never ask twice for something the state already has
    assert "what is done and what is missing" in section  # close every step with the state of the journey


def test_the_contract_shows_a_grouped_clarify_and_a_batch_that_fits_the_pantry():
    # Rerun of scenario 01 with the response contract: replies got shorter (500 → 305 characters) but the questions were
    # still asked one at a time (22 clarifies), and the launch batch of 10 portions did not fit the pantry, so the flow
    # deadlocked on a purchase she refuses.
    soul = " ".join((AGENTS / "orchestrator" / "SOUL.md").read_text().replace("*", "").split()).lower()
    assert "questions: [" in soul  # a worked example of one clarify carrying several questions
    assert "largest launch batch the pantry covers" in soul


@pytest.mark.parametrize("agent", ["orchestrator", "recipe_expert", "cost_expert", "marketing_expert"])
def test_the_ledger_server_is_declared_parallel_safe(agent):
    # Latency pass: Hermes runs a batch of tool calls concurrently only for its own allowlist and for MCP servers that
    # declare supports_parallel_tool_calls (agent/tool_dispatch_helpers.py). kitchen-ledger reads are independent, so two
    # reads in the same reply should not wait for each other.
    config = (AGENTS / agent / "config.yaml").read_text()
    ledger = config[config.index("  ledger:"):]
    assert re.search(r"^\s*supports_parallel_tool_calls:\s*true", ledger, flags=re.M), agent


def test_the_contract_pins_the_fine_grained_rules():
    # Owner's bar of 4 per criterion: the rubric gives 5 only when the whole chain (unit cost → dish → portion → price)
    # is there with one worked example, so "short" has to mean compact, not omitted.
    soul = " ".join((AGENTS / "orchestrator" / "SOUL.md").read_text().replace("*", "").split()).lower()
    assert "one list, one clarify" in soul
    assert "never ask her to confirm a number she just gave you" in soul
    assert 'owner_statement: "1 kg (1000 g)"' in soul  # the verbatim example
    skill = " ".join((AGENTS / "orchestrator" / "skills" / "pricing-explanation" / "SKILL.md").read_text().split()).lower()
    assert "r$ 24,90 ÷ 5 kg = r$ 4,98" in skill and "the whole chain, lean" in skill


def test_every_number_she_sees_comes_with_its_arithmetic():
    # Probe of 17:32: with the pricing chain in the skill, scenario 03 reached didactic clarity 4, but 04 (budget) and 07
    # (promotion) stayed at 2 — those flows explain other numbers, and the rule only lived in the pricing skill.
    soul = " ".join((AGENTS / "orchestrator" / "SOUL.md").read_text().replace("*", "").split()).lower()
    assert "every money number you show comes with the one-line account of where it came from" in soul
    assert "r$ 24,90 ÷ 5 kg = r$ 4,98/kg" in soul  # the worked line now lives in the per-kind list


def test_the_arithmetic_also_goes_inside_the_question_and_the_closing_summary():
    # Probe 2: scenario 07 scored 2 in didactic clarity and 2 in clarity of numbers with a single summary reply —
    # "Preço R$ 9,90 (promoção R$ 8,42), custo R$ 2,72, lucro R$ 6,19" — where no number says where it came from, and
    # everything else in that conversation happened inside clarify questions.
    soul = " ".join((AGENTS / "orchestrator" / "SOUL.md").read_text().replace("*", "").split()).lower()
    assert "inside a clarify question and in the closing summary" in soul


def test_the_contract_caps_the_reply_and_bans_filler():
    # Owner, 2026-09-14: "o agente também deve dar respostas concisas, nada de falar demais". The arithmetic rule must
    # not turn into paragraphs: one line per number, six lines per reply, no greeting or recap in every message.
    soul = " ".join((AGENTS / "orchestrator" / "SOUL.md").read_text().replace("*", "").split()).lower()
    assert "as few lines as the answer needs" in soul
    assert "one line per number, never a paragraph" in soul
    assert "do not greet her again, do not repeat her words back" in soul


def test_the_contract_shows_the_account_of_each_kind_of_number():
    # Probe of 19:48: all three scenarios passed their checks with didactic clarity 2 — the replies gave results only
    # ("Restam R$ 0,00", "Preço fixado: R$ 48,90", "Custo por porção: R$ 2,72") and, when they did explain, offered
    # "quer que eu detalhe o cálculo?" instead of showing one line of it.
    soul = " ".join((AGENTS / "orchestrator" / "SOUL.md").read_text().replace("*", "").split()).lower()
    for example in ("r$ 24,90 ÷ 5 kg = r$ 4,98/kg", "r$ 80,00 − r$ 47,50", "÷ 0,90", "− 15% ="):
        assert example in soul, example
    assert "offering to detail it later never replaces that line" in soul


def test_the_closing_line_carries_state_not_bare_numbers():
    # Probe of 20:34, scenario 07 (didactic clarity 1): the replies were lists of results — "Custo: R$ 2,72 por porção /
    # Lucro: R$ 6,19 / Preço promo: R$ 8,91" — with no account anywhere. The closing line invites exactly that.
    soul = " ".join((AGENTS / "orchestrator" / "SOUL.md").read_text().replace("*", "").split()).lower()
    assert "the closing line names what is done and what is missing, never numbers" in soul
