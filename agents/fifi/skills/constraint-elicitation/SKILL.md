---
name: constraint-elicitation
description: Discover the owner's equipment, techniques and operational limits before buying, accepting or pricing a dish.
---

# Constraint elicitation

Use this for every registered candidate dish **before** any purchase, acceptance or price scenario. The brief's
central rule: Dona Maria must never buy ingredients for a dish she cannot cook.

1. **Start from the dish.** The recipe expert returned the dish's viability: `missing` and `unknown`
   requirements. Everything `unknown` must be asked; everything `missing` must be explained (she cannot cook it as
   is) so she can choose another dish or tell you something changed.
2. **Checklist — ask whatever she has not said yet, one or two questions at a time, in plain words:**
   - stove burners: "Quantas bocas tem seu fogão?" (`stove_burners`, number)
   - oven: "Você tem forno?" (`oven`)
   - pressure cooker, air fryer, blender, mixer: "Tem panela de pressão? Air fryer? Liquidificador? Batedeira?"
     (`pressure_cooker`, `air_fryer`, `blender`, `mixer`)
   - techniques the dish needs (for example `technique:fresh_pasta`, `technique:bechamel`,
     `technique:meat_doneness`): "Você já fez massa fresca / molho branco / carne no ponto antes?"
   - energy or gas (`gas_or_energy:<text>` requirements): "O gás é de botijão ou encanado? Já faltou?"
   - fridge space (`fridge_space_liters`, number): "Quanto espaço livre tem na geladeira, mais ou menos?"
   - time per batch (`max_batch_time_minutes`, number): "Quanto tempo você consegue ficar cozinhando cada leva?"
   - anything else the dish lists as `other:<text>`: ask about it in her words.
3. **Record every answer right away**, with her own words as `owner_statement`:
   - equipment, techniques, stove burners, fridge space, time per batch → ask_recipe_expert
     `record_kitchen_fact` with `key`, `status` ("available" or "unavailable") and `numeric_value` (a number only for
     `stove_burners`, `fridge_space_liters`, `max_batch_time_minutes`; otherwise null);
   - `gas_or_energy:` and `other:` requirements → ask_recipe_expert `confirm_requirement` with the dish's exact
     requirement text.
4. **Never assume.** "Acho que sim" is not "available": ask again. A fact she did not state is unknown.
5. **Only when nothing is missing or unknown** move on to missing items, purchases, acceptance and prices. If a
   requirement is missing, say so kindly and offer to look for another dish.
