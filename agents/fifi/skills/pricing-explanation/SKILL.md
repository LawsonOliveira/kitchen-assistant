---
name: pricing-explanation
description: Explain a dish's CMV and the three delivery price scenarios step by step, using only display strings, and let the owner choose.
---

# Pricing explanation

Use this after the cost expert's `match_and_cost` for an accepted or viable dish. Every number you show is a display
string from that result, copied exactly; never compute, round or convert anything yourself.

1. **Per ingredient, how the unit cost was found:**
   `<total_price_paid_display> ÷ <quantity_purchased_display> = <unit_cost_display>`
   — for example "Arroz: R$ 24,90 ÷ 5 kg = R$ 4,98/kg".
2. **Per ingredient, what the recipe uses:**
   `<quantity_used_display> × <unit_cost_display> = <cost_display>` — for example "usa 400 g × R$ 4,98/kg = R$ 1,99".
   Mention when a line is an estimate (a pinch, "a gosto").
3. **Cost of the dish:** "Custo da receita (CMV): `<recipe_cmv_display>`", then
   "`<recipe_cmv_display>` ÷ `<yield_portions>` porções = `<cmv_per_portion_display>` por porção".
4. **Minimum price:** explain that iFood keeps 10% of the sale, so the minimum that does not lose money is the cost per
   portion ÷ 0,90 = `<min_price_display>`. If there is packaging, show `<min_price_with_packaging_display>` too.
5. **The three scenarios**, one short block each, named by how much of the price is ingredient cost (35%, 30%, 25%):
   - price: `<display_price>`;
   - what she receives after the 10% fee (0,90 × price): `<owner_receives_display>`;
   - profit per portion: `<profit_display>` and, with packaging, `<profit_after_packaging_display>`;
   - margin: `<margin_display>`; warn if `below_min` is true.
6. **Let her choose.** Do not recommend one as "the right" price; you may say what each option favors (selling more
   vs earning more per portion). Then ask with clarify which scenario she wants, confirm it with the confirmation
   protocol, and only then ask the cost expert to `select_price_scenario`.

Keep it short: group numbers per ingredient, per dish and per scenario; skip lines that are null.
