# Relatório Técnico — Fase 9: Feedback Learning

**Data:** 2026-07-18
**Status:** Concluído
**Fase:** 9 — Feedback Learning
**Testes:** 1679 totais (187 novos) — todos passando

---

## 1. Arquitetura Criada

A Fase 9 introduz o **Feedback Learning** — uma camada independente que aprende preferências operacionais do operador e as utiliza para influenciar o Ranking de forma controlada, explicável e determinística.

### Princípios fundamentais

| Princípio | Implementação |
|-----------|---------------|
| **NÃO é ML** | Sem redes neurais, sem treinamento, sem IA — apenas contadores e pesos determinísticos |
| **Não altera conhecimento bíblico** | Banco bíblico, embeddings, Knowledge Graph, Parser, LLM — todos intactos |
| **Desacoplamento total** | Engine e Adapter não conhecem Searcher, Ranking, Holyrics, Parser, LLM, Embeddings, KnowledgeBase, Context Engine |
| **Único ponto de integração** | `RankingFeedbackAdapter` — o Ranking pergunta, o Adapter responde apenas um ajuste de score |
| **Feedback complementa, não substitui** | Teto absoluto de 0.15 no bônus; score mínimo de 0.10 para aplicar feedback |
| **Explicabilidade total** | `ScoreBreakdown` decompose o score em similaridade + feedback + contexto |
| **Contexto do sermão** | Preferências são aprendidas por (query + contexto), não apenas por query |
| **Decaimento determinístico** | Preferências perdem influência se não são reutilizadas |
| **Imutabilidade** | Todos os DTOs são `frozen dataclass`; atualizações criam novas instâncias |

### Diagrama de fluxo

```
┌──────────────┐  FeedbackEvent   ┌──────────────┐    consulta    ┌─────────────────────────┐
│  Pipeline    │ ───────────────> │ FeedbackEngine│ <──────────── │ RankingFeedbackAdapter  │
│  (futuro)    │                  │  .process()   │   estatísticas│   .adjust() → bonus     │
└──────────────┘                  └──────────────┘                └─────────────────────────┘
                                         │                                  ▲
                                         ▼                                  │
                                 ┌─────────────────┐               ┌──────────────┐
                                 │ FeedbackRepository│              │   Ranking    │
                                 │  (JSON / SQLite)  │              │  (existente) │
                                 └─────────────────┘               └──────────────┘
```

### Estrutura de arquivos

```
feedback/
├── __init__.py      (94 linhas)  — API pública
├── dtos.py          (361 linhas) — 6 DTOs imutáveis + FeedbackScope
├── events.py        (167 linhas) — FeedbackEvent + 5 eventos tipados
├── policy.py        (301 linhas) — LearningPolicy (pesos, decaimento, limites)
├── store.py         (172 linhas) — FeedbackStore (armazenamento puro)
├── repository.py    (195 linhas) — FeedbackRepository (JSON, interface SQLite)
├── engine.py        (264 linhas) — FeedbackEngine (processa eventos)
└── adapter.py       (293 linhas) — RankingFeedbackAdapter + helper contexto

tests/
├── test_feedback_dtos.py             (416 linhas, 56 testes)
├── test_feedback_policy_store.py     (465 linhas, 64 testes)
├── test_feedback_engine_adapter.py   (482 linhas, 38 testes)
└── test_feedback_scenarios.py        (392 linhas, 29 testes)
```

---

## 2. Novos Módulos

### `feedback/` (pacote Python)

Módulo novo, totalmente isolado. Única dependência externa: `context.SermonContext` (apenas leitura de `book` e `chapter` via `getattr` no helper `context_signature_from_sermon_context`).

**API pública** (exportada via `feedback/__init__.py`):

- **DTOs:** `FeedbackScope`, `FeedbackKey`, `FeedbackRecord`, `FeedbackStatistics`, `FeedbackSummary`, `ScoreBreakdown`
- **Eventos:** `FeedbackEvent`, `CandidateAccepted`, `CandidateRejected`, `ManualReferenceSelected`, `ManualSearch`, `SuggestionIgnored`
- **Policy:** `LearningPolicy`
- **Store/Repository:** `FeedbackStore`, `FeedbackRepository`, `FeedbackRepositoryProtocol`
- **Engine:** `FeedbackEngine`
- **Adapter:** `RankingFeedbackAdapter`, `context_signature_from_sermon_context`

---

## 3. Novos DTOs

Todos os DTOs são `@dataclass(frozen=True)` — imutáveis, hashable, fortemente tipados.

### `FeedbackScope` (Enum)
Escopo da preferência. Valores: `GLOBAL`, `SESSION`, `SERMON`, `USER`. Apenas `GLOBAL` é utilizado nesta fase; os demais estão preparados para uso futuro.

### `FeedbackKey`
Chave única de uma preferência: `(scope, query, context_signature, candidate_id)`. A combinação identifica uma preferência única — mesma query com contextos diferentes são chaves diferentes. Hashable, serializável.

### `FeedbackRecord`
Registro individual de um evento: `(key, event_type, weight, timestamp, decay_count)`. Serializável.

### `FeedbackStatistics`
Estatísticas acumuladas por chave: `acceptances`, `rejections`, `manual_selections`, `ignored`, `total_weight`, `last_used`, `first_used`, `decay_count`. Properties: `total_events`, `frequency`. Imutável, serializável.

### `FeedbackSummary`
Resumo para explicabilidade: snapshot de `FeedbackStatistics` + `has_feedback`. Serializável.

### `ScoreBreakdown`
Decomposição do score final: `base_score`, `feedback_bonus`, `context_bonus`, `final_score`, `feedback_summary`, `has_feedback`, `feedback_capped`. Método `explain()` gera texto legível: `"Lucas 15: +0.83 Similaridade, +0.09 Feedback, +0.05 Contexto"`.

---

## 4. Novos Eventos

Todos os eventos são `@dataclass(frozen=True)` herdados de `FeedbackEvent` (que tem campo opcional `timestamp: float = 0.0`).

| Evento | Peso | Quando emitir |
|--------|------|---------------|
| `CandidateAccepted` | +3 | Operador aceitou candidato sugerido |
| `CandidateRejected` | -1 | Operador rejeitou candidato sugerido |
| `ManualReferenceSelected` | +5 | Operador selecionou referência manualmente (preferência forte) |
| `ManualSearch` | 0 | Operador fez busca manual (neutro, apenas registra) |
| `SuggestionIgnored` | -2 | Operador ignorou sugestão (não agiu) |

**Type alias:** `FeedbackEventUnion = Union[...]` para type hints.

---

## 5. FeedbackEngine

Engine que processa eventos de feedback e atualiza estatísticas.

### API

```python
engine = FeedbackEngine(repository, policy=None, clock=time.time)
stats = engine.process(CandidateAccepted(key=..., timestamp=...))
stats = engine.get_statistics(key)
summary = engine.get_summary(key)
engine.increment_decay(key)
engine.apply_all_decay()
engine.reset()
engine.flush()
```

### Características

- **`process(event) → FeedbackStatistics`**: atualiza contadores, peso acumulado, timestamps. Persiste via repository.
- **`get_statistics(key)`**: recupera estatísticas (ou None).
- **`get_summary(key) → FeedbackSummary`**: resumo para explicabilidade (sempre retorna, com `has_feedback=False` se não existe).
- **`increment_decay(key)`**: incrementa contador de decaimento.
- **`apply_all_decay()`**: recalcula `total_weight` com decaimento para todas as chaves.
- **`reset()`**: limpa todas as estatísticas.
- **`flush()`**: persiste em disco.
- **Clock injetável**: para testes determinísticos.
- **Desacoplado**: não conhece Searcher, Ranking, Holyrics, Parser, LLM, Embeddings, KnowledgeBase, Context Engine.

---

## 6. FeedbackRepository

Camada de abstração sobre `FeedbackStore` com interface clara para futura troca por SQLite.

### API

```python
repo = FeedbackRepository(path=None, auto_save=False)
repo.save(stats)
stats = repo.get(key)
repo.delete(key)
repo.list_all()
repo.list_by_query(query, scope)
repo.list_by_scope(scope)
repo.clear()
repo.flush()
```

### Características

- **Persistência JSON**: `path` configura arquivo. Se `None`, em memória (testes).
- **`auto_save=True`**: persiste a cada `save()`. Default `False` (flush explícito).
- **`load` automático**: carrega do arquivo na inicialização se o arquivo existe.
- **`FeedbackRepositoryProtocol`**: interface (Protocol) para futura implementação SQLite sem alterar Engine.
- **Consultas**: `list_by_query`, `list_by_scope` para filtrar preferências.

---

## 7. FeedbackStore

Armazenamento puro — sem regra de negócio.

### API

```python
store = FeedbackStore()
store.put(key, stats)
stats = store.get(key)
store.delete(key)
store.has(key)
store.list_keys()
store.list_all()
store.clear()
store.save(path)
store.load(path)
store.to_json()
store.from_json(json_str)
```

### Características

- **CRUD puro**: put, get, delete, has, list, clear.
- **Persistência JSON**: save/load para arquivo, to_json/from_json para string.
- **Sem regra de negócio**: não calcula pesos, não aplica decaimento, não decide bônus.
- **Dict interno**: `{FeedbackKey: FeedbackStatistics}`.
- **Suporta `in`, `len()`, `iter()`**.

---

## 8. LearningPolicy

Política centralizada de pesos, limites e decaimento. Stateless.

### Política de pesos

| Evento | Peso | Constante |
|--------|------|-----------|
| `CandidateAccepted` | +3.0 | `_WEIGHT_CANDIDATE_ACCEPTED` |
| `CandidateRejected` | -1.0 | `_WEIGHT_CANDIDATE_REJECTED` |
| `ManualReferenceSelected` | +5.0 | `_WEIGHT_MANUAL_REFERENCE_SELECTED` |
| `SuggestionIgnored` | -2.0 | `_WEIGHT_SUGGESTION_IGNORED` |
| `ManualSearch` | 0.0 | `_WEIGHT_MANUAL_SEARCH` |

### Conversão peso → bônus

Fórmula: `bonus = tanh(accumulated_weight / BONUS_SCALE)` onde `BONUS_SCALE = 10.0`.

A sigmoide `tanh` mapeia peso acumulado (que cresce indefinidamente) para o intervalo `[-1, 1]`. Exemplos:
- Peso 3 (1 aceitação): `tanh(0.3) ≈ 0.29` → capado em 0.15
- Peso 9 (3 aceitações): `tanh(0.9) ≈ 0.72` → capado em 0.15
- Peso -3 (3 rejeições): `tanh(-0.3) ≈ -0.29` → capado em -0.10

### Limites de influência

| Parâmetro | Valor | Significado |
|-----------|-------|-------------|
| `max_feedback_bonus` | 0.15 | Teto absoluto do bônus (feedback nunca vence sozinho) |
| `min_feedback_bonus` | -0.10 | Floor absoluto (penalização máxima) |
| `min_base_score_for_feedback` | 0.10 | Score mínimo do candidato para aplicar feedback |

### Política de decaimento

| Parâmetro | Valor | Significado |
|-----------|-------|-------------|
| `decay_factor` | 0.95 | Fator multiplicativo a cada intervalo |
| `decay_interval` | 10 | A cada 10 contagens sem reutilização, aplica o fator |
| `min_decayed_weight` | 0.01 | Peso mínimo após decaimento (não decai a zero) |

**Fórmula:** `decayed = total_weight * (0.95 ^ (decay_count // 10))`, limitado a `min_decayed_weight`.

**Decaimento é determinístico e configurável.** Quanto mais uso sem reutilização, menor a influência.

---

## 9. RankingFeedbackAdapter

Único ponto de integração entre Feedback Learning e Ranking.

### API

```python
adapter = RankingFeedbackAdapter(engine, policy=None, scope=FeedbackScope.GLOBAL)
breakdown = adapter.adjust(query, candidate_id, base_score, context_signature="")
breakdowns = adapter.adjust_batch(query, candidates, context_signature="")
summary = adapter.get_feedback_summary(query, candidate_id, context_signature="")
```

### Características

- **`adjust() → ScoreBreakdown`**: consulta engine, aplica decaimento, converte peso em bônus, aplica cap, retorna decomposição.
- **`adjust_batch()`**: processa múltiplos candidatos de uma vez.
- **`get_feedback_summary()`**: consulta sem ajustar (para explicabilidade).
- **Sem feedback → score inalterado**: se não há estatísticas, `feedback_bonus = 0.0`, `final_score = base_score`.
- **Score baixo → sem feedback**: se `base_score < min_base_score_for_feedback`, `feedback_bonus = 0.0`.
- **Cap garantido**: bônus nunca excede `max_feedback_bonus` nem fica abaixo de `min_feedback_bonus`.
- **Desacoplado**: não conhece Searcher, Ranking, Holyrics, Parser, LLM, Embeddings, KnowledgeBase.

### Helper de contexto

`context_signature_from_sermon_context(ctx)` extrai assinatura do `SermonContext`:
- Sem contexto: `""`
- Livro ativo: `"João"`
- Livro + capítulo: `"João:3"`

---

## 10. Política de Pesos

Centralizada em `LearningPolicy` (ver seção 8). Nenhum número mágico espalhado pelo código. Todos os pesos e limites são constantes nomeadas, acessíveis via properties, ajustáveis sem quebrar compatibilidade.

---

## 11. Política de Decaimento

Determinística e configurável (ver seção 8). O decaimento é baseado em contadores (não tempo real): a cada `decay_interval` (10) incrementos de `decay_count` sem reutilização, o peso acumulado é multiplicado por `decay_factor` (0.95). Não decai abaixo de `min_decayed_weight` (0.01).

O `decay_count` é incrementado explicitamente via `engine.increment_decay(key)` — chamado quando uma busca é feita sem que o candidato seja reutilizado.

---

## 12. Formato de Persistência

JSON, com versão para compatibilidade futura:

```json
{
  "version": 1,
  "entries": [
    {
      "key": {
        "scope": "GLOBAL",
        "query": "pedro",
        "context_signature": "João",
        "candidate_id": "43:21:15"
      },
      "acceptances": 3,
      "rejections": 0,
      "manual_selections": 0,
      "ignored": 0,
      "total_weight": 9.0,
      "last_used": 1003.0,
      "first_used": 1001.0,
      "decay_count": 0
    }
  ]
}
```

**Futura troca por SQLite:** basta criar `FeedbackSQLiteRepository` implementando `FeedbackRepositoryProtocol`. O Engine não muda — apenas a instância do repository.

---

## 13. Estratégia de Explicabilidade

Toda decisão de feedback é explicável via `ScoreBreakdown`:

```python
breakdown = adapter.adjust(query="pedro", candidate_id="43:21:15",
                           base_score=0.83, context_signature="João")
print(breakdown.explain())
# "Lucas 15: +0.83 Similaridade, +0.15 Feedback (limitado)"
```

**Decomposição:**
- `base_score`: score original do Ranking (similaridade)
- `feedback_bonus`: bônus aplicado pelo feedback (com `(limitado)` se capado)
- `context_bonus`: bônus de contexto (reservado, 0 hoje)
- `final_score`: score final após ajustes
- `feedback_summary`: estatísticas completas usadas (acceptances, rejections, etc.)
- `has_feedback`: True se feedback foi aplicado
- `feedback_capped`: True se o bônus foi limitado pelo teto

**Auditoria:** `breakdown.to_dict()` serializa tudo para JSON, permitindo log e análise posterior.

---

## 14. Estratégia de Contexto

O Feedback aprende preferências **contextuais**, não apenas por query:

```
Consulta: "Pedro" + Contexto: "João" → João 21
Consulta: "Pedro" + Contexto: "Atos" → Atos 2
```

A assinatura do contexto (`context_signature`) é parte da `FeedbackKey`. Duas preferências para a mesma query mas contextos diferentes são chaves diferentes — não interferem entre si.

O helper `context_signature_from_sermon_context(ctx)` extrai a assinatura do `SermonContext` existente (Fase 8), usando `book` e `chapter` ativos. O Adapter recebe a assinatura como parâmetro string — não importa `SermonContext` diretamente, mantendo desacoplamento.

---

## 15. Preparação para Múltiplos Escopos

`FeedbackScope` (Enum) define 4 escopos:

| Escopo | Status | Descrição |
|--------|--------|-----------|
| `GLOBAL` | ✅ Implementado | Preferência global do operador |
| `SESSION` | 🔒 Preparado | Preferência da sessão (futuro) |
| `SERMON` | 🔒 Preparado | Preferência do sermão (futuro) |
| `USER` | 🔒 Preparado | Preferência por usuário (futuro, multi-usuário) |

Nesta fase, apenas `GLOBAL` é utilizado (default do `RankingFeedbackAdapter`). Os demais valores existem no enum e são totalmente funcionais (chaves com escopos diferentes são separadas), mas nenhuma lógica adicional foi implementada. A arquitetura suporta adicionar escopos futuros sem quebrar compatibilidade.

---

## 16. Quantidade de Novos Testes

**187 novos testes** distribuídos em 4 arquivos (cada um < 500 linhas):

| Arquivo | Linhas | Testes | Cobertura |
|---------|--------|--------|-----------|
| `tests/test_feedback_dtos.py` | 416 | 56 | DTOs, FeedbackScope, FeedbackKey, FeedbackRecord, FeedbackStatistics, FeedbackSummary, ScoreBreakdown, eventos (imutabilidade, herança) |
| `tests/test_feedback_policy_store.py` | 465 | 64 | LearningPolicy (pesos, weight_for, event_type_name, weight_to_bonus, cap_bonus, should_apply_feedback, apply_decay), FeedbackStore (CRUD, persistência JSON), FeedbackRepository (CRUD, list_by_query/scope, auto_save, flush) |
| `tests/test_feedback_engine_adapter.py` | 482 | 38 | FeedbackEngine (process para cada evento, consultas, decaimento, reset, flush), RankingFeedbackAdapter (adjust, adjust_batch, get_feedback_summary, no-feedback, with-feedback, capped, low-score, contexto) |
| `tests/test_feedback_scenarios.py` | 392 | 29 | Desacoplamento (engine + adapter), cenários de aprendizado (Pedro/João vs Pedro/Atos, complementa-não-substitui, decaimento, eventos mistos, manual reference), persistência roundtrip, escopos, imutabilidade após updates, context_signature |
| **Total** | **1755** | **187** | |

---

## 17. Exemplos de Aprendizado

### Exemplo 1: Preferência contextual

```python
engine = FeedbackEngine(FeedbackRepository())
adapter = RankingFeedbackAdapter(engine)

# Operador aceita João 21 quando pregando em João
key_joao = FeedbackKey(FeedbackScope.GLOBAL, "pedro", "João", "43:21:15")
engine.process(CandidateAccepted(key=key_joao, timestamp=1001.0))

# Operador aceita Atos 2 quando pregando em Atos
key_atos = FeedbackKey(FeedbackScope.GLOBAL, "pedro", "Atos", "44:2:38")
engine.process(CandidateAccepted(key=key_atos, timestamp=1002.0))

# Contexto "João" favorece João 21
b = adapter.adjust(query="pedro", candidate_id="43:21:15",
                   base_score=0.83, context_signature="João")
# → has_feedback=True, feedback_bonus=+0.15 (capado)

# Contexto "Atos" NÃO favorece João 21
b = adapter.adjust(query="pedro", candidate_id="43:21:15",
                   base_score=0.83, context_signature="Atos")
# → has_feedback=False, feedback_bonus=0.0
```

### Exemplo 2: Feedback complementa, não substitui

```python
# Candidato A: alta similaridade (0.90), sem feedback
# Candidato B: baixa similaridade (0.15), muito feedback (20 aceitações)
for _ in range(20):
    engine.process(CandidateAccepted(key=key_b, timestamp=1001.0))

b_a = adapter.adjust(query="amor", candidate_id="42:15:11",
                     base_score=0.90, context_signature="")
b_b = adapter.adjust(query="amor", candidate_id="43:3:16",
                     base_score=0.15, context_signature="")
# A vence: 0.90 > 0.30 (0.15 + 0.15 max bonus)
```

### Exemplo 3: Decaimento

```python
engine.process(CandidateAccepted(key=key, timestamp=1001.0))
# Peso acumulado: 3.0

# 100 buscas sem reutilizar o candidato
for _ in range(100):
    engine.increment_decay(key)
# decay_count = 100, decay_factor^10 = 0.95^10 ≈ 0.599
# Peso decaído: 3.0 * 0.599 ≈ 1.80
```

### Exemplo 4: Explicabilidade

```python
b = adapter.adjust(query="pedro", candidate_id="43:21:15",
                   base_score=0.83, context_signature="João")
print(b.explain())
# "+0.83 Similaridade, +0.15 Feedback (limitado)"
print(b.to_dict())
# {"candidate_id": "43:21:15", "base_score": 0.83, "feedback_bonus": 0.15, ...}
```

---

## 18. Confirmação: Nenhum Comportamento Existente foi Alterado

A Fase 9 é **puramente aditiva**. Nenhum arquivo existente foi modificado em seu comportamento.

**Evidências:**

1. **Novo pacote isolado**: `feedback/` é um módulo novo, não importado por nenhum componente existente.
2. **Nenhum import reverso**: nenhum arquivo existente importa `feedback.*`.
3. **Sem alteração de APIs existentes**: Searcher, Ranking, Holyrics, Parser, LLM, Embeddings, KnowledgeBase, Context Engine — todos intactos.
4. **Sem integração automática**: o Ranking não foi modificado para usar o Adapter. A integração é opcional e futura.
5. **Caso não exista feedback**: o comportamento é exatamente igual ao atual (`feedback_bonus = 0.0`, `final_score = base_score`).
6. **Testes existentes**: 1492 testes pré-existentes continuam passando sem modificação.

---

## 19. Confirmação: Compatibilidade com Futuras Fases

A arquitetura foi projetada para suportar futuras evoluções:

1. **Streaming Speech Pipeline (Fase futura)**: O pipeline poderá emitir `CandidateAccepted`/`CandidateRejected` automaticamente quando o operador agir sobre sugestões. O Engine já está pronto para processá-los.

2. **Integração com Ranking (Fase futura)**: O Ranking poderá opcionalmente consultar o `RankingFeedbackAdapter` via `adjust()`. A assinatura é simples: recebe `(query, candidate_id, base_score, context_signature)`, retorna `ScoreBreakdown`. Sem feedback, comportamento idêntico ao atual.

3. **Múltiplos escopos (Fase futura)**: `SESSION`, `SERMON`, `USER` já existem no enum. A lógica de chaves já separa por escopo. Basta o Adapter usar o escopo apropriado.

4. **SQLite (Fase futura)**: `FeedbackRepositoryProtocol` define a interface. Basta criar `FeedbackSQLiteRepository` implementando-a. O Engine não muda.

5. **Context Engine (Fase 8)**: O helper `context_signature_from_sermon_context` já integra com `SermonContext`. Quando o pipeline conectar Context Engine + Feedback, a assinatura será extraída automaticamente.

6. **Novos eventos (Fase futura)**: Eventos desconhecidos são tratados graciosamente (`weight_for` retorna 0.0). Adicionar `CandidateEdited` ou `ResultReordered` não quebra o engine.

7. **Decaimento baseado em tempo (Fase futura)**: A política atual é baseada em contadores. Pode ser estendida para tempo real sem quebrar a interface.

---

## 20. Confirmação: Todos os Testes Antigos Continuam Passando

**Execução completa da suíte de testes:**

```
$ python -m pytest tests/ -q

1679 passed in 205.97s (0:03:25)
```

| Categoria | Quantidade | Status |
|-----------|-----------|--------|
| Testes pré-existentes (Fases 1-8) | 1492 | ✅ Passando |
| Testes novos (Fase 9) | 187 | ✅ Passando |
| **Total** | **1679** | **✅ Todos passando** |

### Arquivos de teste novos (cada um < 500 linhas)

| Arquivo | Linhas | Testes |
|---------|--------|--------|
| `tests/test_feedback_dtos.py` | 416 | 56 |
| `tests/test_feedback_policy_store.py` | 465 | 64 |
| `tests/test_feedback_engine_adapter.py` | 482 | 38 |
| `tests/test_feedback_scenarios.py` | 392 | 29 |

---

## 21. Resumo Executivo

| Aspecto | Valor |
|---------|-------|
| **Fase** | 9 — Feedback Learning |
| **Módulos novos** | 1 pacote (`feedback/`) com 8 arquivos (1847 linhas) |
| **DTOs novos** | 6 (`FeedbackScope`, `FeedbackKey`, `FeedbackRecord`, `FeedbackStatistics`, `FeedbackSummary`, `ScoreBreakdown`) |
| **Eventos novos** | 5 (`CandidateAccepted`, `CandidateRejected`, `ManualReferenceSelected`, `ManualSearch`, `SuggestionIgnored`) |
| **Engine** | `FeedbackEngine` (processa eventos, atualiza estatísticas) |
| **Repository** | `FeedbackRepository` (JSON, interface para SQLite) |
| **Store** | `FeedbackStore` (armazenamento puro, sem regra de negócio) |
| **Policy** | `LearningPolicy` (pesos, limites, decaimento — centralizado) |
| **Adapter** | `RankingFeedbackAdapter` (único ponto de integração com Ranking) |
| **Política de pesos** | +3 aceito, -1 rejeitado, +5 manual, -2 ignorado, 0 busca manual |
| **Política de decaimento** | Fator 0.95 a cada 10 usos sem reutilização, mínimo 0.01 |
| **Teto de influência** | ±0.15 (feedback nunca vence sozinho) |
| **Score mínimo** | 0.10 (feedback não ajuda candidato com similaridade muito baixa) |
| **Formato de persistência** | JSON (versionado, pronto para SQLite) |
| **Explicabilidade** | `ScoreBreakdown.explain()` + `to_dict()` |
| **Contexto** | Assinatura `book` ou `book:chapter` do SermonContext |
| **Escopos** | GLOBAL (ativo), SESSION/SERMON/USER (preparados) |
| **Testes novos** | 187 (em 4 arquivos, 1755 linhas) |
| **Testes totais** | 1679 (todos passando) |
| **Comportamento alterado** | Nenhum (puramente aditivo) |
| **ML/IA** | Nenhum (totalmente determinístico) |

---

*Relatório gerado automaticamente pela implementação da Fase 9.*
