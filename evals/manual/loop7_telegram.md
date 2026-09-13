# Loop 7 manual checklist — Telegram channel and Dona Fifi skin

Expected outcomes were written before the implementation (PLAN.md Loop 7 Tests). Record each run below the table
with the date, the outcome and anything unexpected.

Setup: `.env` has `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_USERS` (the owner's numeric Telegram user id); `make up`;
business state reset to the seeded spreadsheet.

| # | Action | Expected outcome |
|---|---|---|
| 1 | A Telegram account that is not in `TELEGRAM_ALLOWED_USERS` sends "oi" | no reply at all |
| 2 | Allowlisted owner asks for a dish that needs research | only "digitando…", the fixed progress messages ("🔎 Tô procurando receitas…", "🧮 Fazendo as contas…") and then the verified answer; no partial text, no tool names |
| 3 | Owner uploads `evals/scenarios/fixtures/despensa_tomate_price.xlsx` | the upload is not blocked by the input guard; Dona Fifi shows a diff with exactly the Tomate price row; buttons Confirmar / Cancelar |
| 4 | Owner taps Confirmar | `SELECT * FROM current_ingredient_prices WHERE ingredient = 'Tomate'` shows the new price |
| 5 | Owner uploads `evals/scenarios/fixtures/despensa_no_precos.xlsx` | an import error in plain Portuguese; `pantry_imports` has no new `applied` row; prices unchanged |
| 6 | `make import-pantry FILE=data/despensa_dona_maria.xlsx`, then the owner tells Dona Fifi "atualizei a planilha" | a diff with no changes |
| 7 | Reference dish over Telegram (PLAN.md Loop 1: 4 portions, 400 g arroz, 600 g peito de frango, 10 g alho, 30 ml óleo, sal) | three prices R$ 7,90 / R$ 9,90 / R$ 10,90 with the pricing explanation; choosing one asks Confirmar as buttons; the dish is accepted and priced |
| 8 | `make chat` in a terminal of at least 95 columns | the Dona Fifi banner (sign and grandma stirring a pot, in color), PT-BR welcome, thinking verbs such as "mexendo a panela" |

## Runs

- 2026-09-13 (agent): row 8 done — `make test-skin` passes and the CLI at 150 columns shows the DONA FIFI logo, the
  grandma hero, the PT-BR welcome and the 🍲 Dona Fifi reply label. Telegram wiring checked: the bot token answers
  `getMe`, the allowlist is one numeric id, fifi's gateway logs "Connected to Telegram (polling mode)", and received
  files are cached in `$HERMES_HOME/cache/documents` (`gateway/platforms/base.py`), the `fifi_documents` volume that
  costs-mcp imports from. Rows 1–7 need messages sent from Telegram accounts: pending the owner.
