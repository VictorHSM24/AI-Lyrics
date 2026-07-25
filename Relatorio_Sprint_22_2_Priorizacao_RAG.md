# Sprint 22.2 — Priorização do RAG e Desacoplamento do Contexto do Sermão

**Data:** 25 de julho de 2026
**Sprint:** 22.2
**Anterior:** Sprint 22.1 (Auditoria do Pipeline Semântico)
**Princípio arquitetural:** BibleRetriever > Texto Atual > Contexto do Sermão

---

## 1. Objetivo

Reorganizar a prioridade das decisões do pipeline sem alterar a arquitetura
geral. A Sprint 22.1 identificou que o contexto do sermão estava
dominando decisões mesmo quando o BibleRetriever recuperava candidatos
com altíssima confiança, contradizendo o objetivo da Sprint 22.0 (a
Bíblia local como fonte de verdade). A Sprint 22.2 corrige essa inversão
de prioridade através de uma política de contexto explícita, três
variantes de prompt, e infraestrutura mínima para confiança do livro
atual no SermonMemory.

A meta é que, ao final, o AI Lyrics opere segundo o princípio RAG
fundamental: a Bíblia local como fonte primária, o LLM como
desambiguador, e o contexto do sermão apenas como auxílio quando há
ambiguidade objetiva entre candidatos.

---

## 2. Escopo executado

Conforme decisão tomada com o usuário no início da Sprint, o escopo foi
focado na inversão de prioridade (RAG > contexto), com infraestrutura
mínima para `current_book_confidence` no SermonMemory. O BookConfidence
dinâmico completo (reforço por evidências, decaimento temporal, migração
entre livros) ficou para a Sprint 22.3, pois a ContextPolicy já resolve
a ancoragem na maioria dos casos ao omitir o contexto quando top1 é
dominante.

| Frente | Status |
|---|---|
| Config `semantic.rag` e `semantic.context` | Concluído |
| BibleRetriever: metadados top1/top2/gap | Concluído (sem alterar algoritmo) |
| ContextPolicy + ContextDecision | Concluído |
| SermonContext: campo `current_book_confidence` | Concluído |
| SermonMemory: infra mínima de `current_book_confidence` | Concluído |
| ContextEngine: propagar `sermon_book_confidence` | Concluído |
| Reformulação do `_SYSTEM_PROMPT_RAG` | Concluído |
| 3 variantes de user prompt | Concluído |
| Integração no `SemanticEngine._run_inference` | Concluído |
| Telemetria: `context_policy_decision` + `sermon_book_confidence_change` | Concluído |
| Testes unitários ContextPolicy (21 testes) | Concluído |
| Testes integração 4 casos de aceite (11 testes) | Concluído |
| Suíte completa (3072 testes) | Concluído, 0 falhas |

**Não implementado (Sprint 22.3):** BookConfidence dinâmico completo
com decaimento temporal, ajuste por candidatos RAG, e migração
automática entre livros.

---

## 3. Mudanças por componente

### 3.1 Configuração (`config/config.yaml`, `config/models.py`, `config/loader.py`)

Adicionadas duas sub-seções opcionais em `semantic`:

```yaml
semantic:
  rag:
    dominant_score: 0.98      # score mínimo do top1 para alta confiança
    dominant_gap: 0.08        # gap mínimo top1-top2 para alta confiança
    ambiguity_gap: 0.03       # gap abaixo do qual há alta ambiguidade
  context:
    min_confidence: 0.40              # confiança mínima do SermonMemory
    remove_when_confidence_below: 0.25  # limiar de remoção (Sprint 22.3)
```

Novos dataclasses imutáveis `RagPolicyConfig` e
`SermonContextPolicyConfig` em `config/models.py`. O loader valida os
intervalos [0,1] e a consistência (`ambiguity_gap <= dominant_gap`,
`remove_when_confidence_below <= min_confidence`).

### 3.2 BibleRetriever (`knowledge/types.py`)

Adicionados `RetrievalMeta` (dataclass imutável) e
`compute_retrieval_meta(candidates)` (helper funcional). O
`RetrievalMeta` expõe:

- `top1_score`, `top2_score`, `gap` (top1 - top2)
- `num_candidates`
- `top1_book`, `top1_reference`, `top1_num_versions`

**O algoritmo de recuperação não foi alterado.** O helper apenas computa
metadados a partir da lista ordenada retornada por `retrieve()`,
conforme a restrição do enunciado ("Não alterar BibleRetriever").

### 3.3 ContextPolicy (`semantic/context_policy.py` — novo arquivo)

Componente puramente funcional (sem IO, sem estado) que decide quanto
do contexto do sermão incluir no prompt. Recebe `RetrievalMeta` +
`sermon_book` + `sermon_book_confidence`, retorna `ContextDecision`.

Três níveis de confiança da recuperação:

| Nível | Critério | Inclusão de contexto |
|---|---|---|
| `alta_confianca` | top1 >= dominant_score AND gap >= dominant_gap | `omit` |
| `ambiguidade_moderada` | gap em [ambiguity_gap, dominant_gap) | `summary` (apenas livro) |
| `alta_ambiguidade` | gap < ambiguity_gap OU top1 < dominant_score | `full` |

Critério adicional: se `sermon_book` for vazio/None OU
`sermon_book_confidence < min_confidence`, o contexto é sempre `omit`
independentemente do nível. Isso evita ancoragem em contexto fraco ou
inexistente.

### 3.4 SermonContext e SermonMemory (`sermon/types.py`, `sermon/engine.py`)

Adicionado campo `current_book_confidence: float = 0.0` ao
`SermonContext` (imutável). O `SermonMemoryEngine._apply_reference`
calcula a confiança com heurística mínima:

- Livro mudou: confiança reseta para `_BOOK_CONFIDENCE_INITIAL` (0.50)
- Livro confirmado (mesmo livro): confiança reforça com
  `_BOOK_CONFIDENCE_REINFORCE` (0.15), teto `_BOOK_CONFIDENCE_MAX` (0.90)
- Sem livro: confiança = 0.0

Todos os 7 construtores de `SermonContext` no `engine.py` foram
atualizados para propagar o campo. O `EMPTY_SERMON_CONTEXT` já usa o
default 0.0 (reset correto).

### 3.5 ContextEngine (`semantic/context_engine.py`)

Propaga `current_book_confidence` do `SermonContext` para o
`SemanticContext` como `sermon_book_confidence`. Usa `getattr` com
fallback 0.0 para backward compatibility com `SermonContext` antigo.

### 3.6 SemanticContext (`semantic/types.py`)

Adicionados dois campos:

- `sermon_book_confidence: float = 0.0` — confiança específica do
  `sermon_book`, lida pela ContextPolicy.
- `context_decision: Any = None` — decisão da ContextPolicy
  (`ContextDecision` ou None). Incluído no `context_hash()` pois afeta
  qual variante do prompt é gerada.

### 3.7 LocalLLMProvider (`semantic/local_provider.py`)

**System prompt RAG reformulado** (`_SYSTEM_PROMPT_RAG`): agora declara
explicitamente que a lista de candidatos é a "FONTE OFICIAL de
conhecimento do sistema", que o modelo não deve usar memória
paramétrica para procurar outras referências, e que o contexto do
sermão é "APENAS auxiliar". A regra 7 anterior ("Considere o contexto
do sermão") foi substituída por: "Utilize prioritariamente os
candidatos recuperados da Bíblia local. O contexto do sermão, quando
fornecido, é APENAS auxiliar." A regra 8 adicionada: "NUNCA substitua
um candidato claramente superior apenas porque o contexto anterior
pertence a outro livro."

**Três variantes de user prompt** (novos métodos):

- `_build_user_prompt_rag_high_confidence`: sem contexto do sermão,
  apenas "Texto ouvido" + candidatos + "Escolha o melhor."
- `_build_user_prompt_rag_moderate`: contexto resumido (apenas
  `current_book`, sem tema/entidades), candidatos, "Utilize
  prioritariamente os candidatos da lista."
- `_build_user_prompt_rag_high_ambiguity`: contexto completo (livro +
  capítulo + tema + entidades), candidatos, "O contexto do sermão pode
  ajudar a desambiguar. NUNCA substitua um candidato claramente superior
  apenas pelo contexto do sermão."

O `_build_user_prompt` original foi refatorado para despachar para a
variante correta com base em `context.context_decision.include_context`.
O comportamento legado (Sprint 21 + 22.0) é preservado em
`_build_user_prompt_legacy` para modo não-RAG e fallback.

### 3.8 SemanticEngine (`semantic/engine.py`)

O `_run_inference` agora, após recuperar candidatos do BibleRetriever:

1. Computa `RetrievalMeta` via `compute_retrieval_meta(rag_candidates)`.
2. Chama `context_policy.decide(meta, sermon_book, sermon_book_confidence)`.
3. Emite telemetria `context_policy_decision`.
4. Injeta a `ContextDecision` no contexto via `dataclasses.replace`.

O `__init__` aceita novo parâmetro `context_policy: Any = None`
(opcional, backward compatible).

### 3.9 Composition Root (`api/startup/composition.py`)

Instancia `ContextPolicy` a partir de `semantic_config.rag` e
`semantic_config.context` quando `bible_retriever_instance` está
disponível, e passa ao `SemanticEngine`. Loga os limiares ativos.

### 3.10 Telemetria (`telemetry/hooks.py`)

Dois novos hooks:

- `context_policy_decision(correlation_id, decision)`: registra a
  decisão da ContextPolicy (level, include_context, reason, top1_score,
  top2_score, gap, sermon_confidence, sermon_book, num_candidates).
- `sermon_book_confidence_change(correlation_id, previous_book,
  new_book, previous_confidence, new_confidence, reason)`: registra
  mudanças na confiança do `current_book` (emitido no
  `_apply_reference`).

Ambos são no-op se a telemetria estiver desabilitada.

---

## 4. Casos de aceite validados

### Caso 1: "O Senhor te abençoe e te guarde" → Números 6:24

- Top1: Números 6:24 (score 1.00, gap 0.09 vs Salmos 67:1)
- Contexto do sermão: "pregando em Salmos", confiança 0.85
- **Resultado:** ContextPolicy classifica `alta_confianca`, contexto
  `omit`. StubProvider escolhe Números 6:24. O contexto Salmos não
  ancorou a decisão.

### Caso 2: "Portanto, vão e façam discípulos" → Mateus 28:19

- Top1: Mateus 28:19 (score 1.00, gap 0.09 vs Romanos 1:5)
- Contexto do sermão: "pregando em Romanos", confiança 0.85
- **Resultado:** ContextPolicy classifica `alta_confianca`, contexto
  `omit`. StubProvider escolhe Mateus 28:19. O contexto Romanos não
  ancorou a decisão.

### Caso 3: Candidatos empatados → contexto participa

- Top1: João 3:16 (0.91), Top2: Romanos 5:8 (0.90), gap 0.01
- Contexto do sermão: "pregando em João", confiança 0.75
- **Resultado:** ContextPolicy classifica `alta_ambiguidade` (gap <
  ambiguity_gap), contexto `full`. O contexto é incluído para auxiliar
  a desambiguação.

### Caso 4: Migração natural do SermonMemory

- Pregador começa em João 3 (confiança 0.50), reforça com João 4 e 5
  (confiança 0.80), migra para Romanos 8 (confiança reseta para 0.50).
- **Resultado:** `current_book_confidence` reseta corretamente ao
  trocar de livro. Após migração, se a confiança do novo livro ainda
  for baixa (< min_confidence=0.40), a ContextPolicy omite o contexto,
  evitando ancoragem prematura.
- **Limitação:** o decaimento temporal e a migração automática baseada
  em inferências contraditórias (sem nova `ReferenceDetected`) ficam
  para a Sprint 22.3.

---

## 5. Testes

### 5.1 Testes unitários ContextPolicy (21 testes)

Arquivo: `tests/test_sprint22_2_context_policy.py`

Cobre:
- Alta confiança (top1 dominante, limiares exatos, top1 abaixo do
  limiar não é dominante)
- Ambiguidade moderada (gap intermediário, top1 fraco com gap grande)
- Alta ambiguidade (gap pequeno, zero candidatos)
- Sem sermon_book (sempre omit)
- Confiança do SermonMemory abaixo do mínimo (omite mesmo em alta
  ambiguidade)
- Fronteira inclusiva no min_confidence
- Os 4 casos de aceite do enunciado
- Config customizada (dominant_score e min_confidence ajustados)
- `compute_retrieval_meta` (lista vazia, 1 candidato, 2 candidatos)
- `to_dict` para telemetria

### 5.2 Testes de integração (11 testes)

Arquivo: `tests/test_sprint22_2_rag_priorizacao.py`

Cobre:
- Caso 1: Números 6:24 prevalece sobre Salmos (2 testes: resultado +
  verificação de que ContextPolicy omitiu)
- Caso 2: Mateus 28:19 prevalece sobre Romanos (2 testes)
- Caso 3: Candidatos empatados → contexto full (2 testes)
- Caso 4: Migração do SermonMemory (2 testes: reset de confiança +
  omissão de contexto após confiança cair)
- 3 variantes do prompt no LocalLLMProvider (3 testes: omit sem
  contexto, summary só com livro, full com contexto completo)

Os testes usam `MockRetriever` para isolamento do BibleRetriever real
(não depende de bases SQLite locais), e `SpyProvider` para capturar o
`SemanticContext` enviado ao provider.

### 5.3 Suíte completa

```
3072 passed, 11 subtests passed in 191.44s
```

Nenhuma regressão. O único ajuste foi em
`test_knowledge_config_loaded_from_yaml` (expectativa `enabled is False`
→ `is True`) para refletir que o RAG agora está ativado no config
default, alinhado com o objetivo da Sprint 22.2.

---

## 6. Decisões de design

### 6.1 Por que ContextPolicy separada do SemanticEngine?

A ContextPolicy é puramente funcional (sem IO, sem estado), o que a
torna testável isoladamente e extensível. O SemanticEngine apenas a
invoca e injeta a decisão no contexto. Isso segue o princípio de
separação de política de mecanismo: a política de contexto é uma
decisão de negócio, o mecanismo de inferência é infraestrutura.

### 6.2 Por que três variantes em vez de um template com condicionais?

Templates com condicionais tendem a crescer e tornar-se difíceis de
auditar. Três métodos nomeados tornam explícito o que cada variante
contém, facilitam testes unitários por variante, e permitem ajustar
uma variante sem risco de afetar as outras. O `_build_user_prompt`
despacha com base em `include_context` (string estável para telemetria).

### 6.3 Por que `current_book_confidence` separado de `confidence`?

`confidence` mede o contexto geral do sermão (entidades, temas,
referências). `current_book_confidence` mede especificamente quão
fortemente o SermonMemory acredita que o pregador ainda está no
`current_book`. São evidências diferentes: o contexto geral pode ser
forte (muitas entidades) enquanto a confiança do livro pode ser fraca
(uma única referência antiga). A ContextPolicy precisa do segundo para
decidir se o livro deve influenciar a decisão RAG.

### 6.4 Por que infra mínima em vez de BookConfidence dinâmico completo?

A ContextPolicy já resolve a ancoragem na maioria dos casos ao omitir
o contexto quando top1 é dominante. O BookConfidence dinâmico completo
(decaimento temporal, ajuste por candidatos RAG, migração entre livros
sem nova ReferenceDetected) adicionaria complexidade prematura em um
componente cuja influência será significativamente menor após a
ContextPolicy. A infra mínima (campo no SermonContext + heurística
simples em `_apply_reference`) permite que a ContextPolicy leia a
confiança e tome decisões informadas, sem o custo de implementar
observadores ou canais de feedback do SemanticEngine para o
SermonMemory. A Sprint 22.3 pode evoluir isso quando houver evidência
de que a heurística simples é insuficiente.

---

## 7. O que não foi alterado (respeitando o enunciado)

- BibleRetriever: algoritmo FTS, ranking BM25, agregação multi-versão
  não foram tocados. Apenas adicionados `RetrievalMeta` e
  `compute_retrieval_meta` em `knowledge/types.py` (helper externo).
- ReferenceResolver: stateless, sem mudanças.
- Searcher, Holyrics, STT: sem mudanças.

---

## 8. Próximos passos (Sprint 22.3)

1. **BookConfidence dinâmico completo:** decaimento temporal (meia-vida
   configurável), ajuste por candidatos RAG (quando top1 do retriever
   aponta para outro livro, diminuir confiança do current_book),
   migração automática após N inferências contraditórias sem nova
   `ReferenceDetected`.

2. **Validação em ambiente real:** rodar com Ollama + qwen3:8b real
   (não StubProvider) para validar que o LLM respeita o novo system
   prompt e não substitui candidatos dominantes pelo contexto.

3. **Telemetria de pontos cegos restantes:** `semantic_skipped` (quando
   o SemanticEngine pula por min_text_length/growth), `rag_active` em
   `semantic_input` (para distinguir inferências RAG vs LLM direto),
   `bible_retriever_error` (quando retrieve falha).

4. **Ajuste fino dos limiares:** os defaults (dominant_score=0.98,
   dominant_gap=0.08, ambiguity_gap=0.03) foram escolhidos com base nos
   experimentos da Sprint 22.1, mas podem precisar de calibração após
   observação em produção.

---

## 9. Conclusão

A Sprint 22.2 cumpre o princípio RAG fundamental: a Bíblia local é a
fonte primária de conhecimento, o LLM atua como desambiguador sobre
candidatos recuperados, e o contexto do sermão é auxílio apenas quando
há ambiguidade objetiva. Os 4 casos de aceite do enunciado foram
validados por testes de integração. A suíte completa de 3072 testes
passa sem regressões. A infraestrutura está pronta para a Sprint 22.3
evoluir o BookConfidence dinâmico quando houver evidência de que a
heurística mínima é insuficiente.
