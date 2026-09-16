# Sabor da Maria — Dona Sálvia

Assistente conversacional para a Dona Maria, que está abrindo o restaurante *Sabor da Maria* no iFood. A **Dona Sálvia**
leva ela da despensa ao cardápio de lançamento:

- pesquisa receitas reais na web;
- descobre equipamentos, técnicas e limites da cozinha antes de qualquer compra;
- cruza os ingredientes com a despensa e o orçamento de R$ 80,00;
- calcula o CMV e três cenários de preço com a taxa de 10% da plataforma.

É construída **instalando e customizando o [Hermes Agent](https://hermes-agent.nousresearch.com/)** (Nous Research),
sem modificar o Hermes: tudo é configuração, plugins, skills, skin, `SOUL.md` e arquivos de contexto sobre a imagem
Docker oficial.

A fonte do escopo é [desafio-senior-ai-engineer.md](desafio-senior-ai-engineer.md); o plano completo, com as 47
decisões, as 99 correções registradas e as 15 perguntas ao dono, está em [PLAN.md](PLAN.md).

## Sumário
- [Como rodar](#como-rodar)
- [Arquitetura](#arquitetura)
- [As cinco categorias do desafio](#as-cinco-categorias-do-desafio)
- [Decisões](#decisões)
- [Segurança](#segurança)
- [Limitações do Hermes encontradas](#limitações-do-hermes-encontradas)
- [Observabilidade](#observabilidade)
- [Evals e resultados](#evals-e-resultados)
- [Simplificações](#simplificações)
- [Demo em vídeo](#demo-em-vídeo)
- [Próximos passos](#próximos-passos)

## Como rodar

**Requisitos:** Docker com Compose, `make`, [uv](https://docs.astral.sh/uv/) no host. A pilha completa (cinco agentes,
Postgres, kitchen-ledger, cockpit e Langfuse v4) pede **≈16 GiB de RAM**; com 8 GiB ela sobe, mas usando swap.

1. `cp .env.example .env` e preencha:
   - `CLAUDE_CODE_OAUTH_TOKEN`: acesso aos modelos pelas credenciais do Claude Code (`claude setup-token`).
     Não há chave da Anthropic Console.
   - `TAVILY_API_KEY`: busca web.
   - `A2A_TOKEN_*` e `LEDGER_TOKEN_*`: um token aleatório por agente.
   - `POSTGRES_PASSWORD`, `API_SERVER_KEY`, `KITCHEN_COCKPIT_TOKEN`.
   - Segredos do Langfuse (`LANGFUSE_*`). O próprio `.env.example` mostra como gerar cada um.
   - Opcional: `TELEGRAM_BOT_TOKEN` (do @BotFather) e `TELEGRAM_ALLOWED_USERS` (seu id numérico, do @userinfobot).
2. `make up` constrói e sobe tudo, esperando cada serviço ficar saudável. Na primeira subida, a planilha
   `data/despensa_dona_maria.xlsx` é importada e o Langfuse cria organização, projeto, usuário e chaves.
3. `make chat` roda o self-test dos guardrails e abre a CLI clássica com a skin da Dona Sálvia. Se o self-test falhar,
   a CLI não abre.

Outros comandos:

| Comando | O que faz |
|---|---|
| Telegram | com o token no `.env`, o bot responde só a quem está em `TELEGRAM_ALLOWED_USERS` |
| http://localhost:8080 | cockpit ao vivo: qual agente, ferramenta e MCP estão ativos, custo do turno, saldo |
| http://localhost:3000 | Langfuse (usuário e senha do `.env`): um trace por turno, atravessando os contêineres |
| `make import-pantry FILE=…` | envia uma planilha nova; a Dona Sálvia mostra a diferença e só aplica depois de um clique |
| `make logs` · `make down` | acompanha os contêineres; desce a pilha sem apagar volumes |
| `make test`, `make test-plugins`, `make test-contracts`, `make test-integration` | suítes determinísticas, 706 testes ao todo, também no CI |
| `make selftest` | canário dos guardrails contra o servidor do orchestrator; é o que o `make chat` roda antes de abrir |
| `KITCHEN_ALLOW_EVAL_RESET=1 make evals` | todas as camadas de eval. **Apaga o estado de negócio** da pilha em execução |
| `make eval-guardrails` | só o guard de entrada, com o classificador real, sobre as 84 mensagens rotuladas |
| `make eval-requirements` | só a extração de requisitos, em páginas fixas, pelo `researcher-eval` |
| `KITCHEN_ALLOW_EVAL_RESET=1 make eval-reset` | volta a despensa da planilha, o orçamento de R$ 80,00 e apaga pratos, compras e memórias |
| `make review-conversations SINCE=AAAA-MM-DD` | lê as conversas reais dela, dá notas e escreve em `evals/reviews/` e no Langfuse |
| `make latency-report` | onde o tempo do turno foi parar, a partir dos eventos e do `audit_log` |
| `make smoke-a2a` · `make smoke-research` | checagem rápida da malha A2A e uma pesquisa real pelo contrato do researcher |
| `make db-shell` · `make hermes-shell` | um `psql` no Postgres do negócio; um shell dentro do container do orchestrator |

## Arquitetura

Cinco processos Hermes conversam por A2A. Só a Dona Sálvia fala com a dona. Toda conta de dinheiro e quantidade fica num
servidor MCP determinístico.

```mermaid
flowchart LR
    owner([Dona Maria]) -- CLI / Telegram --> orchestrator
    subgraph orchestrator_box[orchestrator · claude-sonnet-5]
        orchestrator[Dona Sálvia<br/>kitchen_guardrails · kitchen_a2a · kitchen_observability]
    end
    orchestrator -- ask_recipe_expert --> recipe[recipe_expert<br/>sonnet-5]
    orchestrator -- ask_cost_expert --> cost[cost_expert<br/>sonnet-5]
    orchestrator -- ask_marketing_expert --> marketing[marketing_expert<br/>haiku-4.5]
    recipe -- research --> researcher[researcher<br/>haiku-4.5 + filhos em paralelo]
    cost -- research --> researcher
    marketing -- research --> researcher
    researcher -- Tavily --> web((web))
    orchestrator -- leitura --> mcp[(kitchen-ledger<br/>Python, Decimal)]
    recipe -- escrita do seu domínio --> mcp
    cost -- escrita do seu domínio --> mcp
    marketing -- escrita do seu domínio --> mcp
    mcp --> pg[(Postgres)]
    orchestrator & recipe & cost & marketing & researcher & mcp -. eventos .-> cockpit[cockpit]
    orchestrator & recipe & cost & marketing & researcher -. spans .-> langfuse[Langfuse v4]
```

Um turno com decisão da dona:

```mermaid
sequenceDiagram
    participant M as Dona Maria
    participant F as orchestrator
    participant G as kitchen_guardrails
    participant C as cost_expert
    participant X as kitchen-ledger
    M->>F: "Quero a do meio, R$ 9,90"
    par guard de entrada junto com a primeira chamada
        F->>G: input guard (Haiku)
        G-->>F: allow
    end
    F->>G: pre_tool_call: clarify
    G-->>F: mesma pergunta com a conta do ledger na frente
    F->>M: clarify: Confirmar / Cancelar
    M->>F: Confirmar (clique)
    F->>G: pre_tool_call: há um clique não usado?
    G-->>F: sim, consumido
    F->>C: ask_cost_expert select_price_scenario + owner_confirmation (contrato validado)
    C->>X: select_price_scenario
    X-->>C: display_price "R$ 9,90"
    C-->>F: resultado + cost_usd_spent
    F->>G: output verifier: R$ ancorados + política
    G-->>F: allow
    F->>M: "Prontinho! Preço fechado em R$ 9,90"
```

| Peça | Onde |
|---|---|
| Configuração versionada de cada agente (`config.yaml`, `SOUL.md`, skills, skin) | `agents/<agente>/` |
| Plugins Hermes (A2A tipado, guardrails, observabilidade) | `plugins/kitchen_*` |
| Contratos JSON Schema (receita, pesquisa, especialistas, eventos) | `contracts/` |
| Servidor MCP de custos, com migrations SQL | `services/kitchen_ledger/` |
| Cockpit (stdlib + HTML/JS) | `services/cockpit/` |
| Cenários, red-team, datasets, runner de eval | `evals/` |

**Latência.** Um turno com pesquisa passa por vários modelos em cadeia, então o tempo foi cortado onde o resultado não
muda:
- o cost_expert e o recipe_expert respondem sem laço de modelo as tarefas que são uma chamada só do MCP — orçamento,
  custo, cenário, promoção, correção de preço, compra e importação de um lado; fato da cozinha, rejeição, lote,
  requisito, medida e aceite do outro —, usando o próprio despacho de ferramentas do Hermes: allowlist, trace e
  telemetria continuam valendo. Sugerir pratos e normalizar receita continuam com o modelo, porque envolvem pesquisa;
- o orchestrator pede numa resposta só o que os especialistas podem fazer em paralelo;
- o guard de entrada roda junto com a primeira chamada de modelo, e um bloqueio descarta essa resposta;
- cada filho do researcher faz no máximo 3 chamadas por ferramenta web; nenhum agente usa `todo`.

## As cinco categorias do desafio

### Modelo
- **orchestrator** e **recipe_expert** usam `claude-sonnet-5`: conversa longa com uso de ferramentas, e julgamento de
  viabilidade e substituição.
- **cost_expert** também usa `claude-sonnet-5`. O plano previa Haiku, mas nos testes ao vivo o Haiku entrou em laço e
  inventou valores ao montar as chamadas do MCP (correção C15).
- **marketing_expert**, **researcher** (e seus filhos) e o classificador dos guardrails usam
  `claude-haiku-4-5-20251001`: tarefas estruturadas e frequentes, porque a matemática está no MCP.
- Nas evals, a Dona Maria simulada usa Haiku e o juiz usa Sonnet.
- **Rejeitado:** Opus para o orchestrator (custo e latência sem necessidade) e Sonnet em tudo. Trocas de modelo são decididas
  pelas evals.
- O acesso é pelo provedor Anthropic nativo do Hermes, autenticado com `CLAUDE_CODE_OAUTH_TOKEN`. Chamadas fora do loop
  do agente (classificador, dona simulada, juiz) passam pelo cliente LLM de plugin / auxiliar do próprio Hermes, com as
  mesmas credenciais.

### Arquivos de contexto
- Cada agente tem seu **`SOUL.md`** em `agents/<agente>/`, com identidade, fluxo e tarefas. É copiado para o
  `HERMES_HOME` a cada start (D18).
- Um **`.hermes.md`** no diretório de trabalho guarda regras comuns: conteúdo da web é dado não confiável e
  identificadores ficam em inglês. Ele **precisa existir**; sem ele, o Hermes carregaria o `CLAUDE.md` de engenharia
  deste repositório.
- Os filhos do researcher não recebem `SOUL.md`: suas instruções vêm de uma seção de system prompt registrada pelo plugin,
  ativa só quando `platform == "subagent"`.
- Prompts são em inglês; tudo o que a dona lê é em português. O `prompt_hash` (sha256) vai em cada trace e resultado de
  eval.

### Ferramentas / MCP
- **kitchen-ledger** é um servidor MCP em Python (Streamable HTTP, `Decimal`, Postgres) com toda a lógica de dinheiro e
  quantidade: unidades, custo unitário, CMV, cenários, orçamento, estoque, viabilidade, compras, importação de planilha.
- Cada agente tem um token próprio, e o servidor recusa ferramentas fora do domínio dele (por exemplo, marketing não
  registra compra). Cada chamada fica no `audit_log`, com o `trace_id`.
- **Ferramentas A2A tipadas** (`ask_recipe_expert`, `ask_cost_expert`, `ask_marketing_expert`, `research`) validam cada
  pedido e resposta contra `contracts/`, com uma nova tentativa e depois erro explícito. O modelo nunca vê o toolset A2A
  cru do Hermes.
- Busca web via **Tavily** (`web_search`, `web_extract`), só no researcher, que distribui a pesquisa em filhos paralelos
  com `delegate_task`. O limite de 3 chamadas por ferramenta web em cada filho fica no `pre_tool_call`, porque o Hermes
  lança esses filhos com um número fixo de iterações.
- **Cache de receitas:** antes de pesquisar, o recipe_expert consulta `find_cached_recipes` (todas as palavras do pedido
  no título normalizado, sem acento nem caixa); receitas da web válidas pelo contrato entram com `cache_recipes`.
  **Rejeitado:** RAG com embeddings (`pgvector`). Por quê: o acervo é pequeno, a busca por palavras é determinística e
  testável, e busca semântica só entra se a busca por título se mostrar insuficiente.
- Allowlist de ferramentas por agente em `pre_tool_call` (o único hook do Hermes que falha fechado). Terminal e arquivos
  estão desligados em todos os agentes.

### Estrutura de memória
- **Estado de negócio no Postgres**, via especialistas: despensa, preços, compras, perfil da cozinha, pratos,
  reservas, promoções, medidas caseiras e o cache de receitas da web.
- **Memória nativa do Hermes só no orchestrator**, e só para gostos e estilo da dona ("não curte coentro", "prefere explicação
  curta"). Toda escrita passa por um guard Haiku que só deixa passar `allow`; fatos de negócio são recusados, porque
  devem ir para o banco.
- Os especialistas rodam sem memória.
- **Rejeitado:** memória só no Postgres (tabela de notas), como tinha sido recomendado. A dona escolheu a memória do
  Hermes e o risco está listado em [Riscos aceitos](#riscos-aceitos).

### Skills
| Skill | Agente | Quando carrega |
|---|---|---|
| `constraint-elicitation` | orchestrator | antes de comprar, aceitar ou precificar um prato: equipamentos, técnicas, tempo por leva, geladeira, gás |
| `pricing-explanation` | orchestrator | ao mostrar custos e cenários: custo unitário → custo do prato → por porção → preço, com um exemplo |
| `recipe-normalization` | recipe_expert | quando uma receita da web, ou ditada pela dona, precisa virar o contrato de receita antes de ser registrada |
| `ifood-menu-copy` | marketing_expert | título e descrição dentro dos limites do iFood, sem alegações de saúde ou comparação com concorrente |

As skills mantêm os system prompts curtos e são versionadas e avaliáveis. **Rejeitado:** colocar tudo no `SOUL.md`.

## Decisões

Cada item: a decisão, a alternativa rejeitada e o porquê. O detalhe está em *Key decisions* no [PLAN.md](PLAN.md).
**(dona)** marca escolhas feitas pela dona contra outra recomendação.

**Plataforma e topologia**
- **D1 — Hermes pela imagem Docker oficial, fixada por tag e digest.** Rejeitado: clone, submódulo, fork. Por quê:
  nunca alteramos o Hermes; a imagem torna o build reproduzível e deixa claro o que é nosso.
- **D2 — Cinco processos Hermes por A2A (dona).** Rejeitado:
  - um agente só: páginas de 15 mil caracteres no contexto de quem fala com a dona;
  - só `delegate_task`: um modelo para todos os filhos, sem `SOUL.md` próprio, herdando todas as ferramentas;
  - guardrails como agentes ou microsserviço: latência e mais um ponto de falha.

  Por quê: cada agente tem modelo, prompt, ferramentas e contêiner próprios.
- **D3 — Árvore de chamadas fixa, com token por aresta; o orchestrator nunca chama o researcher.** Rejeitado: malha livre.
  Por quê: é auditável, os traces ficam legíveis e texto da web nunca chega a quem fala com a dona.
- **D4 — Só o orchestrator (a Dona Sálvia) fala com a dona; especialistas devolvem `questions_for_owner`.** Rejeitado: repassar
  `INPUT_REQUIRED` do A2A. Por quê: uma voz e guardrails num lugar só.
- **D5 — researcher com tipos de tarefa fixos, schemas estritos, sem estado, com verificação de proveniência.**
  Rejeitado: modo de pergunta livre, estado por dona, classificador na saída. Por quê: um schema sem espaço para
  instruções neutraliza injeção indireta de forma determinística; a proveniência garante receitas *reais*.
- **D6 — Ferramentas A2A tipadas com validação de contrato.** Rejeitado: expor o toolset `a2a` cru. Por quê: validação
  determinística, o modelo não descobre pares arbitrários, e cada chamada gera um evento limpo.
- **D7 — Toda a lógica de dinheiro e quantidade no kitchen-ledger.** Rejeitado: aritmética pelo LLM, MCP stdio por
  processo, ferramenta de plugin. Por quê: conta feita por LLM "mente em silêncio"; um servidor separado é testável
  sem o Hermes.
- **D8 — Postgres dedicado para o estado de negócio (dona), SQL puro, migrations numeradas, psycopg 3.** Rejeitado:
  SQLite, o Postgres do Langfuse, ORM. Por quê: o negócio não depende da observabilidade e há poucas dependências.
- **D9 — Modelos por agente** (ver [Modelo](#modelo)).
- **D18 — Configuração versionada copiada para um volume nomeado a cada start; uma imagem para os cinco agentes.**
  Rejeitado: montar `agents/<agente>/` como `HERMES_HOME`, porque sessões e memória da dona cairiam no repositório.
- **D19 — Contratos em JSON Schema; um `pyproject.toml` por serviço (uv).** Rejeitado: modelos Pydantic compartilhados,
  workspace. Por quê: o Hermes consome JSON Schema direto e cada imagem instala só o que usa.

**Guardrails e autorização**
- **D10 — Guardrails num plugin do Hermes no orchestrator.** Rejeitado: proxy externo em volta da API do Hermes, que perderia a
  CLI e a skin. Por quê: o desafio pede customizar o Hermes. Como os hooks falham abertos, cada guard captura as
  próprias exceções e bloqueia, e `make chat` roda um canário antes.
- **D11 — Semântica dos guards.**
  - A entrada vê a mensagem da dona mais a última do orchestrator (até 500 caracteres), porque "sim" sozinho não diz nada.
  - Categorias: fora de escopo **e** manipulação.
  - Cumprimentos e conversa rápida (como ela está, quem é a assistente) estão no escopo: a Dona Sálvia responde numa frase
    e volta para a cozinha.
  - Veredito `allow | block | uncertain`; score 0–1 foi rejeitado por falta de calibração.
  - `uncertain` passa na entrada e bloqueia na saída.
  - Falha de infraestrutura bloqueia dos dois lados, com uma mensagem própria.
- **D12 — Verificador de saída: todo R$ precisa vir de um display string do MCP (ou da própria dona), mais política
  Haiku, sem streaming.** Rejeitado: só LLM, e streaming. Por quê: dinheiro inventado é pego com exatidão; streaming
  mostraria texto antes da verificação.
- **D13 — Injeção indireta e abuso de ferramentas.** Schemas estritos, isolamento do orchestrator, allowlists em
  `pre_tool_call`, terminal e arquivos desligados, web tratada como dado não confiável. Rejeitado: aceitar o risco sem
  documentar.
- **D14 — Autorização de escrita (dona).**
  - Cada especialista escreve só no seu domínio.
  - Decisões de dinheiro exigem o clique **Confirmar** num `clarify`, repassado como `owner_confirmation`.
  - Fatos ditos pela dona viram `evidence`, sem clique.

  Rejeitado: tokens de aprovação vinculados a hash de parâmetros. Por quê: a dona preferiu o fluxo mais simples. Na
  implementação foi somado um registro determinístico de cliques (ver [Segurança](#segurança)).
- **D15 — Memória** (ver [Estrutura de memória](#estrutura-de-memória)).
- **D16 — Arquivos de contexto** (ver [Arquivos de contexto](#arquivos-de-contexto)).
- **D17 — Skills para procedimentos sob demanda** (ver [Skills](#skills)).
- **D30 — Confirmações com botões do `clarify`.** Rejeitado: o orchestrator interpretar texto livre. Por quê: "ela clicou
  Confirmar" é mais claro que "o LLM acha que ela disse sim".
- **D37 — Teto de US$ 5,00 por turno, somado entre agentes, sem armazenamento compartilhado.** Rejeitado: teto por
  processo, nenhum teto. Por quê: o Hermes não tem orçamento de custo. O restante viaja no contrato A2A e cada agente
  bloqueia a próxima chamada de modelo quando acaba.
- **D38 — Timeouts aninhados e mensagens de progresso fixas.** Rejeitado: mensagens intermediárias geradas pelo
  modelo, que seriam texto não verificado. Valores: filhos 120 s + reparo 75 s < servidor do researcher 270 s <
  especialista→researcher 300 s < servidor do especialista 450 s < orchestrator→especialista 480 s < turno 930 s (correção C35).

**Regras de custo e preço**
- **D20 — CMV por porção e cenários por CMV% (35/30/25%).** Rejeitado: CMV por receita, multiplicador de markup. Por
  quê: delivery vende porção e CMV% é o vocabulário do setor. Preços exibidos sobem para `,90`; o mínimo sobe para o
  centavo.
- **D21 — Taxa da plataforma de 10% como parâmetro.** Rejeitado: citar planos reais do iFood, que variam e seriam
  números não verificados.
- **D22 — Embalagem mostrada à parte, fora do CMV.** Por quê: a fórmula do desafio fica exata e o custo real por pedido
  aparece como `lucro depois da embalagem`.
- **D23 — Unidades.**
  - Tudo é normalizado para g/ml/unidade num lugar só.
  - Uso cruzado de dimensões falha alto e vira pergunta.
  - Medidas caseiras vêm da tabela `measures` no Postgres (16 semeadas). O tamanho de uma lata ou pacote que falta é
    pesquisado pelo researcher (`measure_lookup`, em página real de produto) e só entra no CMV depois do clique
    **Confirmar** da dona; se ela disser outro número, vale o dela.
  - "A gosto" usa uma estimativa pequena, marcada como estimativa.

  Rejeitado: LLM convertendo para gramas, com densidades confiantemente erradas.
- **D24 — Orçamento, estoque e ciclo de vida.**
  - O CMV usa a quantidade usada; o orçamento paga embalagens inteiras.
  - Estouro é recusado com alternativas, e a dona pode aumentar o orçamento de forma explícita.
  - Pratos aceitos reservam o lote de lançamento.
  - Ciclo `candidate → accepted | rejected`.
  - Vale o preço mais recente.
- **D25 — Portão de viabilidade determinístico com vocabulário controlado.** Rejeitado: só pedir no prompt, ou um
  agente auditor. Por quê: transforma a regra central do desafio ("nunca comprar ingrediente de prato que ela não
  consegue fazer") em algo que o sistema não permite.
- **D26 — Eval de extração de requisitos: recall de 100% em equipamentos e ≥ 90% em técnicas e operação.** Por quê:
  equipamento esquecido é exatamente "comprar e descobrir depois".
- **D27 — Preço de item faltante.** researcher estima → cost_expert guarda como `web_estimate` (sem uso no CMV) → a dona
  confirma ou corrige. Rejeitado: preço estimado pelo LLM.
- **D28 — Alertas depois de mudança de custo:** CMV% acima do alvo escolhido, e abaixo do mínimo. Rejeitado: sugerir
  baixar preço quando o custo cai.
- **D29 — Pesquisa em rodadas de até 3 candidatos, ordenados por cobertura da despensa.** Por quê: o desafio pede "à
  medida que encontrar", e a opinião dela direciona a próxima rodada.
- **D31 — Importação de planilha:** prévia (diff) → clique → aplica. Validação estrita com `openpyxl`, nomes exatos e
  todos os erros juntos. Rejeitado: parser XML próprio, e o orchestrator aplicando importações.
- **D41 — Marketing:** texto do cardápio e promoções, sempre simulados antes pelo cost_expert. Rejeitado: benchmark
  de preços de concorrentes no iFood (termos de uso, preços não verificáveis).

**Observabilidade, evals e entrega**
- **D32 — Plugin próprio de observabilidade, com trace id explícito nos contratos A2A.** Rejeitado: plugin Langfuse
  do Hermes (um trace por processo), patches W3C no núcleo do Hermes. Telemetria é best-effort, ao contrário dos
  guardrails.
- **D33 — Langfuse v4 self-hosted no mesmo compose, sempre ligado (dona).** Rejeitado: Langfuse Cloud (dados saem da
  máquina), perfil opcional.
- **D34 — Cockpit em contêiner próprio, HTML + JS + SSE com a stdlib.** Rejeitado: React/Vite, servidor dentro de um
  plugin.
- **D35 — Prompts no git, em inglês, com hash nos traces.** Rejeitado: gestão de prompts do Langfuse em runtime, que
  tornaria a observabilidade dependência de execução.
- **D36 — Runner de eval próprio + datasets do Langfuse, graders em camadas, pass^3.** Rejeitado: promptfoo,
  DeepEval/Inspect, k = 1, evals de LLM no CI. Por quê: pass^3 mede confiabilidade, que é o que uma dona com uma única
  tentativa sente.
- **D39 — Canais: CLI clássica + Telegram com allowlist.** Rejeitado: CLI própria, TUI Ink, WhatsApp (Cloud API exige
  conta business e webhook público; o bridge não oficial tem risco de banimento).
- **D40 — Busca web: Tavily.** Rejeitado: Firecrawl (não necessário), rotação sem chave (limites no meio da demo).
- **D42 — Persona e skin Dona Sálvia:** avó ajudante, a dona é a chef. A arte do banner é um grid de pixels legível
  (`agents/orchestrator/dona-salvia-hero.txt`) que `scripts/render_hero.py` converte em meios-blocos coloridos.
- **D43 — Topologia completa primeiro (dona), depois fluxos, guardrails, observabilidade, evals, Telegram/skin,
  README.** Rejeitado: monólito primeiro.
- **D44 — Testes antes da implementação em todo loop.** No `git log`, cada `test:` com o resumo da execução vermelha
  vem antes do `feat:`.
- **D47 — Regra que precisa valer mora no código, não no prompt.** Medido três vezes em 15/09: regra escrita na
  `SOUL.md` e ignorada pelo modelo custa uma tentativa perdida; a mesma regra no ledger ou no guard simplesmente vale.
  Foram movidas oito: registrar a mesma receita duas vezes devolve o prato que já existe (um *retry* não cria prato
  novo) e uma receita alterada vira revisão do mesmo candidato; calcular custo com requisito em aberto é recusado, com
  a lista do que perguntar; um **Cancelar** é anunciado ao modelo como decisão dela, não falha; e a conta de cada
  número vem pronta do ledger (`cost_chain_display`, `min_price_chain_display`, `profit_chain_display`,
  `promotion_chain_display`) e o guard a coloca na frente da pergunta que mostra o resultado, via diretiva `modify` do
  `pre_tool_call`. Depois vieram mais quatro, das sessões da dona: toda pergunta vai pelo `clarify` (o turno volta uma
  vez ao modelo quando ele pergunta em prosa); a pergunta que oferece os pratos carrega a cobertura da despensa e o que
  falta comprar em cada um; uma decisão que ela autoriza só é aceita com as opções Confirmar e Cancelar, para não ser
  perguntada duas vezes; e tudo que ela lê sai escalonado ao lote que vai cozinhar. Rejeitado: pedir de novo ao modelo com uma frase mais forte — três rodadas assim deixaram a clareza
  didática em 2,33–2,78, e a primeira rodada com a conta injetada deu 3,80. Rejeitado também: bloquear a resposta sem
  conta, que custaria uma ida ao modelo e pode matar a conversa (o bloqueio de alegação já mostrou como isso soa).
- **D45 — Publicação manual e por último,** feita pela dona.
- **D46 — Acesso aos modelos pelas credenciais do Claude Code (dona).** Rejeitado: chave da Anthropic Console.

## Segurança

- **Guard de entrada** (Haiku, antes da primeira chamada de modelo de cada turno):
  - `block` responde "Só consigo te ajudar com cozinha e cardápio 🙂";
  - falha de infraestrutura responde "Tive um probleminha técnico, tenta de novo em instantes".
- **Verificador de saída:** todo `R$` precisa ter vindo de um display string do MCP ou da mensagem da própria dona.
  Depois vem a política: escopo, vazamento de instruções, alegações de saúde ou "orgânico", comparação com
  concorrentes. `uncertain` bloqueia. Cada motivo tem sua mensagem: número sem lastro pede um instante para conferir
  a conta, alegação avisa que o texto do cardápio será reescrito, o resto responde fora de escopo.
- **Guard de memória:** só `allow` grava.
- **Allowlist de ferramentas** por agente em `pre_tool_call`.
- **Registro de cliques:**
  - uma escrita que exige confirmação só sai se o último `clarify` da sessão teve **Confirmar** ainda não usado;
  - um pedido recusado antes de ser enviado devolve o clique;
  - se o último `clarify` foi respondido **Cancelar**, a mensagem diz isso ao modelo — decisão dela, não falha — e
    manda agir sobre o não em vez de repetir a pergunta.
- **Teto de custo por turno** entre agentes.
- **Fail-open vs fail-closed:** hooks e middleware do Hermes falham **abertos**; só `pre_tool_call` falha fechado. Por
  isso cada guard envolve o próprio corpo e devolve um bloqueio em qualquer exceção. `make chat` recusa abrir a CLI se o
  canário não for bloqueado. A telemetria, ao contrário, nunca bloqueia a dona.
- **Sem vazamento:** streaming desligado na CLI e no Telegram, sem mensagens intermediárias do modelo, e eventos de
  telemetria nunca impressos no terminal da dona.

### Riscos aceitos
| Risco | Mitigação |
|---|---|
| O guard de entrada deixa `uncertain` passar (disponibilidade primeiro) | o verificador de saída falha fechado; allowlists por agente |
| A confirmação de escrita depende do LLM do orchestrator montar o `clarify` | confirmações são cliques; registro determinístico de cliques; caso de red-team "escrita sem clique" |
| Memória em texto livre do Hermes guarda preferências da dona | guard de escrita que falha fechado; regra de fronteira no `SOUL.md`; só no orchestrator |
| O Langfuse sempre sobe junto (≈16 GiB) | requisito documentado; limites de memória por serviço |
| Postgres dedicado em vez de SQLite | o núcleo de unidades e dinheiro é puro e testado sem infraestrutura |
| Topologia completa antes de um monólito | o Loop 0 já foi um fluxo ponta a ponta |
| Regra do preço mais recente em vez de média ponderada | simplificação documentada |
| Sem guard no conteúdo da web | schemas estritos, proveniência, researcher sem estado, orchestrator nunca vê texto da web, allowlists, verificador de saída |

## Limitações do Hermes encontradas

Verificadas na imagem fixada `nousresearch/hermes-agent:v2026.9.11`. Cada uma virou uma correção registrada em
[PLAN.md](PLAN.md#implementation-corrections).

- **Hooks e middleware falham abertos**, e só `pre_tool_call` falha fechado.
- **Ferramentas inline** como `clarify` e `memory` disparam `pre_tool_call` e `post_tool_call`, mas nunca
  `transform_tool_result` (o registro de cliques usa `post_tool_call`).
- **`api_call_count` começa em 1** no middleware `llm_execution`, não em 0.
- **A API OpenAI-compatível não oferece `clarify`.** Por isso as evals dirigem a CLI clássica num pty.
- **`$HERMES_HOME/.env` sobrescreve o ambiente do contêiner.** O entrypoint remove a `API_SERVER_KEY` gerada lá.
- **Quarentena de 14 dias do uv** (`exclude-newer`) no `pyproject.toml` da imagem: pacotes publicados há menos tempo
  não instalam.
- **Filhos de `delegate_task`** não têm toolsets por chamada nem `SOUL.md` próprio.
- **Nada propaga contexto de trace entre processos.** O nosso viaja no contrato A2A.
- **Vazamentos de texto não verificado:** a CLI faz streaming antes de `transform_llm_output`, e o Telegram manda
  mensagens intermediárias por padrão. Ambos foram desligados.
- **Langfuse v4 em modo `events_only`:** `/api/public/traces` não existe; usamos `/api/public/v2/observations`.
- **O modo `hermes chat -q` responde o `clarify` sozinho**, então não serve para testar confirmações.

## Observabilidade

- **Um trace por turno da dona no Langfuse**, atravessando orchestrator → especialistas → researcher → filhos → ferramentas
  `mcp__ledger__*`. O `trace_id` é o mesmo do `audit_log`, e o custo e os tokens de cada chamada vêm da tabela de preços.
- **Cockpit** em http://localhost:8080:
  - o caminho animado entre guard de entrada, orchestrator, especialistas, researcher, MCP e guard de saída;
  - linha do tempo com duração, tokens e custo;
  - painel de estado (saldo e pratos), atualizado a cada escrita no MCP.
- **Telemetria é best-effort:** com Langfuse e cockpit parados, o turno responde normalmente.
- **LGPD:** a demo captura conteúdo completo porque tudo é self-hosted. Em produção seriam captura sanitizada e prazo
  de retenção.

## Evals e resultados

`KITCHEN_ALLOW_EVAL_RESET=1 make evals` roda, contra a pilha em execução, as camadas abaixo e escreve
`evals/results/<data>.md`.

| Camada | Como | Limite |
|---|---|---|
| Núcleo de custos | `pytest` unitário e de integração do kitchen-ledger (85 + 90 testes) | 100% |
| Extração de requisitos | páginas fixas repetidas pelo `researcher-eval` | recall 100% equipamentos, ≥ 90% técnicas |
| Guard de entrada | 84 mensagens rotuladas em `evals/guardrail_dataset.jsonl` | falsos positivos ≤ 5% |
| Cenários multi-turno | 9 cenários × 3 tentativas: a Dona Maria simulada conversa na CLI; graders de estado final e trajetória decidem; juiz Sonnet só alerta | pass^3 ≥ 80% |
| Red-team | 7 casos (injeção, jailbreak, fora de escopo, página maliciosa, envenenamento de memória, escrita sem clique, alegação enganosa) | vazamento 0% |
| Qualidade da conversa | juiz Sonnet dá nota 1 a 5 em clareza didática, clareza dos números, quem decide e tom | média da rodada ≥ 3,5 em **cada** critério; nenhum cenário abaixo de 3 |

Cada rodada vira um *dataset run* no Langfuse (`kitchen-scenarios`), ligado aos traces e aos hashes de prompt, e as
notas do juiz de cada tentativa viram *scores* no trace dela (`judge_<critério>`, `judge_mean`, `trial_passed`), o que
deixa as telas *Scores* e *Experiments* comparáveis entre rodadas.

**Conversas reais da dona (`make review-conversations SINCE=<data>`).** O Langfuse só roda um avaliador LLM com chave
de API do provedor, e aqui o acesso aos modelos é pelas credenciais do Claude Code (D46). Por decisão da dona, o juiz roda
fora do Langfuse e grava os resultados nele:
- lê as sessões do orchestrator (CLI e Telegram) no `state.db`, sem as sessões das evals;
- calcula sinais: mensagens bloqueadas que ela precisou reescrever, erros de ferramenta, cliques em Cancelar, latência
  p90 por turno (alerta acima de 60 s) e custo por turno (alerta acima de US$ 1,00);
- dá notas com `evals/rubric.md` e grava cada critério como score 1–5 na sessão, com ids estáveis (rodar de novo
  atualiza, não duplica);
- coloca as conversas suspeitas na fila de anotação `kitchen-review`;
- escreve `evals/reviews/<data>.md` e rascunhos de linhas para o dataset do guard em `evals/proposals/<data>/`, ambos
  fora do git porque guardam as conversas dela.

Nada é aplicado sozinho: uma pessoa revisa, e o que for aceito vira teste antes de virar mudança. Por enquanto a revisão
roda à mão e as conversas ficam 90 dias (pergunta aberta 15 no plano).

**Exemplo do ciclo de melhoria.** A dona perguntou "como você está?" e o guard de entrada bloqueou. A conversa virou
seis linhas de conversa rápida em `evals/guardrail_dataset.jsonl`; com o classificador real, cinco saíram bloqueadas
(13,9% de falsos positivos, acima do limite de 5%). O prompt do guard passou a permitir cumprimentos e a nova rodada deu
66/66 corretas, com 0 falso positivo (correção C54), com as 66 linhas que o dataset tinha então. O mesmo ciclo se
repetiu depois com "me acha receitas na internet" (C89) e com a escalada de autoridade dos testes de intrusão, e o
dataset está hoje em 84 linhas, todas corretas.

**Resultados:** ver a seção *Latest eval run* abaixo, atualizada a cada rodada completa.

### Latest eval run

`20260915-095503-final` (15/09/2026, relatório completo em `evals/results/20260915-095503-final.md`).

| Camada | Resultado | Limite |
|---|---|---|
| Núcleo do ledger (unitário e integração) | passou (175 testes) | 100% |
| Extração de requisitos | passou | 100% |
| Guard de entrada | 0 falso positivo, precisão 1,0, recall 1,0 (84 mensagens) | ≤ 5% |
| Cenários multi-turno (pass^3) | **100%** (9 de 9) | ≥ 80% |
| Red-team | 7 de 7, **vazamento 0%** | 0% |
| Juiz — clareza dos números | 3,56 | ≥ 3,5 na rodada, ≥ 3,0 por cenário |
| Juiz — clareza didática | **3,04** | ≥ 3,5 na rodada, ≥ 3,0 por cenário |
| Juiz — quem decide | 4,70 | ≥ 3,5 na rodada, ≥ 3,0 por cenário |
| Juiz — tom | 4,48 | ≥ 3,5 na rodada, ≥ 3,0 por cenário |

| Cenário | Tentativas | Critério mais fraco |
|---|---|---|
| 01 caminho feliz | ✓ ✓ ✓ | didática 3,33 |
| 02 forno não mencionado | ✓ ✓ ✓ | didática 3,00 |
| 03 preço corrigido pela dona | ✓ ✓ ✓ | didática 3,33 |
| 04 orçamento estourado | ✓ ✓ ✓ | didática 3,00 |
| 05 estoque de tomate compartilhado | ✓ ✓ ✓ | didática 3,33 |
| 06 peso da cobertura de chocolate | ✓ ✓ ✓ | **didática 2,67** |
| 07 promoção simulada | ✓ ✓ ✓ | didática 3,00 |
| 08 planilha atualizada | ✓ ✓ ✓ | números 3,00 |
| 09 ela muda de ideia | ✓ ✓ ✓ | **didática 2,67** |

Cada tentativa virou um item do *dataset run* no Langfuse, com trace e 162 notas do juiz.

**Leitura desta rodada.** As 27 tentativas passaram, os 7 ataques continuam sem vazar e o guard segue sem falso
positivo: o que protege a dona e o que calcula o dinheiro dela estão sólidos. O único limite não atingido é a **clareza
didática, 3,04 contra 3,5**, com dois cenários abaixo do piso de 3,0 — o 06 (peso de uma medida caseira) e o 09 (ela
explora e muda de ideia). São justamente os dois fluxos sem momento de preço: a conta que o ledger escreve e o guard
coloca na frente da pergunta não tem onde entrar, e a explicação volta a depender do modelo.

**Próximo passo para a didática:** levar a conta também aos momentos sem preço — a medida caseira do cenário 06
("1 barra = 1 kg, então 200 g = 1/5 da barra") e o estado da exploração no 09.

## Simplificações

- **Preço mais recente:** o custo unitário usa a última compra ou cotação, não a média ponderada.
- **Três cenários de preço:** a dona adota um deles; não há preço livre fora dos cenários.
- **A taxa da plataforma é fixa em 10%** e ignora planos reais.
- **Embalagem fica fora do CMV**, mostrada à parte.

## Demo em vídeo e apresentação
A demo em vídeo **está incluída nesta entrega** em um formato de apresentação em MP4.

## Próximos passos

- Deploy em nuvem com segredos gerenciados.
- Postgres multi-tenant para várias donas.
- Classificador na saída do researcher, se o red-team mostrar vazamento.
- Evals de LLM agendadas fora do CI.
- Preço livre além dos cenários.
