---
name: recipe-normalization
description: Normalize a web recipe to the Sabor da Maria contract.
---

# Recipe normalization

Use this whenever a recipe from `research` must become the recipe contract
(`contracts/recipe.schema.json`) before it is sent to Dona Sálvia.

1. **Pantry names.** Call `get_pantry` once and copy the exact pantry name into `pantry_match`
   (e.g. "arroz" -> "Arroz branco tipo 1", "frango" -> "Peito de frango"). If nothing in the pantry is the same
   ingredient, set `pantry_match` to null and keep the recipe's own name. Never match different ingredients.
2. **Units.** Keep the recipe's measure and map it to the contract unit — never convert it yourself:
   g, kg, ml, l; "unidade" -> unit; "xícara" -> cup; "colher de sopa" -> tablespoon; "colher de chá" -> teaspoon;
   "dente" -> clove; "pitada" -> pinch; "fio" -> drizzle; "lata" -> can; "pacote" -> package;
   "a gosto" -> to_taste with quantity null. Fractions become decimals (1/2 -> 0.5).
3. **Water.** Leave tap water out of `ingredients`: it is not bought, so it is neither a pantry item nor a
   missing one.
4. **Quantities.** Copy them from the page. If a quantity is missing, do not guess: put the ingredient with
   unit to_taste only when the page says "a gosto"; otherwise add a question to `questions_for_owner`.
5. **Yield and time.** `yield_portions` and `prep_time_minutes` come from the page (or from the owner's words;
   an owner-dictated recipe has `source_url` "owner", never a made-up URL). If the page omits the yield,
   use 1 and add the question "Quantas porções essa receita rende na sua marmita?".
6. **Requirements.** Equipment and techniques from the preparation steps, only from the vocabulary:
   oven, pressure_cooker, blender, mixer, air_fryer, food_processor, microwave, grill, deep_fryer,
   stove_burners>=N (count the pans used at the same time), technique:fresh_pasta, technique:bechamel,
   technique:meat_doneness, technique:deep_frying, technique:bread_baking, technique:caramel,
   technique:tempering_chocolate, fridge_space_liters>=N. Anything else becomes other:<short text>.
   Do not add max_batch_time_minutes: the costs service derives it from prep_time_minutes.
