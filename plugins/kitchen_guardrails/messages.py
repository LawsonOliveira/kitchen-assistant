"""Fixed owner-facing messages (PLAN.md Shared definitions): produced by our code, never by a model."""

SCOPE_BLOCK_MESSAGE = "Só consigo te ajudar com cozinha e cardápio 🙂"
INFRA_BLOCK_MESSAGE = "Tive um probleminha técnico, tenta de novo em instantes"
# An amount that did not come from a tool result: the answer is dropped, and she hears why in her own terms.
NUMBER_BLOCK_MESSAGE = "Preciso conferir esse número com as contas antes de te falar. Me dá um instante?"
# A claim the menu cannot promise is not an off-topic message: she hears that the text is being rewritten (probe B).
CLAIM_BLOCK_MESSAGE = "Esse texto promete uma coisa que o cardápio não pode prometer. Vou reescrever essa parte, tá?"
COST_CAP_MESSAGE = "Essa conversa ficou comprida demais pra mim agora. Vamos recomeçar por partes?"
MEMORY_BLOCK_MESSAGE = "memória recusada"  # a tool result the model sees, never the owner
PROGRESS = {
    "ask_recipe_expert": "🔎 Tô procurando receitas…",
    "ask_cost_expert": "🧮 Fazendo as contas…",
    "ask_marketing_expert": "✍️ Escrevendo a descrição do prato…",
}
