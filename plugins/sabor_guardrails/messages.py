"""Fixed owner-facing messages (PLAN.md Shared definitions): produced by our code, never by a model."""

SCOPE_BLOCK_MESSAGE = "Só consigo te ajudar com cozinha e cardápio 🙂"
INFRA_BLOCK_MESSAGE = "Tive um probleminha técnico, tenta de novo em instantes"
COST_CAP_MESSAGE = "Essa conversa ficou comprida demais pra mim agora. Vamos recomeçar por partes?"
MEMORY_BLOCK_MESSAGE = "memória recusada"  # a tool result the model sees, never the owner
PROGRESS = {
    "ask_recipe_expert": "🔎 Tô procurando receitas…",
    "ask_cost_expert": "🧮 Fazendo as contas…",
    "ask_marketing_expert": "✍️ Escrevendo a descrição do prato…",
}
