# Relatório Técnico — Fase 11: Sermon Intelligence

**Data:** 2026-07-18
**Status:** Concluído
**Fase:** 11 — Sermon Intelligence
**Testes:** 1995 totais (145 novos) — todos passando

---

## 1. Arquitetura Criada

A Fase 11 introduz o **Sermon Intelligence** — uma camada de orquestração determinística que reúne todos os sinais produzidos pelas fases anteriores (Context Engine, Feedback Learning, Continuous Evaluation) e produz uma recomendação única, totalmente explicável, auditável e desacoplada.

### Princípios fundamentais

| Princípio | Implementação |
|-----------|---------------|
| **Apenas coordena** | Nunca executa busca, nunca calcula embeddings, nunca interpreta áudio, nunca consulta Holyrics |
| **Não modifica nada** | Nunca altera Ranking, Feedback, Context, Evaluation, Searcher, Parser, LLM, Embeddings, Knowledge Graph |
| **Desacoplamento total** | Engine, Coordinator, Strategies não conhecem implementação interna de nenhum módulo — apenas interfaces públicas (duck-typing) |
| **Sinais independentes** | Cada sinal retorna apenas (value, weight, explanation) — nenhum sinal altera outro |
| **Explicabilidade total** | Toda recomendação responde: por que X venceu? Quais sinais influenciaram? Quanto cada um contribuiu? |
| **Confiança não-binária** | LOW, MEDIUM, HIGH — calculada a partir de número de sinais ativos e score final |
| **Imutabilidade** | Todos os DTOs são `frozen dataclass` |
| **Política centralizada** | `IntelligencePolicy` centraliza pesos, limites, thresholds — sem números mágicos |
| **Preparação futura** | 6 sinais futuros preparados (Semantic, Operator, ChurchProfile, Language, Temporal, Emotion) |

### Diagrama de fluxo

```
┌─────────────────────────────────────────────────────────────┐
│                    IntelligenceRequest                       │
│  (query, context, candidates, feedback_summaries, metrics)  │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  SermonIntelligenceEngine                    │
│                       .recommend()                           │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                IntelligenceCoordinator                       │
│                    .coordinate()                             │
└───────────────────────────┬─────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
     ┌────────────┐  ┌────────────┐  ┌────────────┐
     │ Context    │  │ Feedback   │  │ Continuity │  ... (8 estratégias)
     │ Strategy   │  │ Strategy   │  │ Strategy   │
     └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
           │               │               │
           ▼               ▼               ▼
     ContextSignal   FeedbackSignal  ContinuitySignal  ... (8 sinais)
           │               │               │
           └───────────────┼───────────────┘
                           ▼
                ┌────────────────────┐
                │  SignalCombiner    │
                │    .combine()      │
                └─────────┬──────────┘
                          ▼
                ┌────────────────────┐
                │ IntelligenceScore  │
                │  (por candidato)   │
                └─────────┬──────────┘
                          ▼
                ┌─────────────────────────┐
                │ IntelligenceRecommendation│
                │  (scores ordenados)     │
                └─────────────────────────┘
```

### Estrutura de arquivos

```
intelligence/
├── __init__.py      (131 linhas) — API pública
├── dtos.py          (352 linhas) — 6 DTOs imutáveis + 1 enum
├── signals.py       (240 linhas) — 8 sinais ativos + 6 futuros + registry
├── policy.py        (301 linhas) — IntelligencePolicy (pesos, limites)
├── strategies.py    (495 linhas) — 8 estratégias independentes
├── combiner.py      (168 linhas) — SignalCombiner (combina sinais)
├── coordinator.py   (117 linhas) — IntelligenceCoordinator (orquestra)
└── engine.py        (134 linhas) — SermonIntelligenceEngine (ponto de entrada)

tests/
├── test_intelligence_dtos.py        (434 linhas, 62 testes)
├── test_intelligence_strategies.py  (461 linhas, 42 testes)
└── test_intelligence_engine.py      (553 linhas, 41 testes)
```

---

## 2. Novos Módulos

### `intelligence/` (pacote Python)

Módulo novo, totalmente isolado. Não importa `searcher`, `ranking`, `holyrics`, `parser`, `llm`, `embeddings`, `knowledge`, `feedback`, `context`, `evaluation`. Apenas usa duck-typing via `getattr` para acessar atributos públicos dos objetos recebidos.

**API pública** (exportada via `intelligence/__init__.py`):

- **DTOs:** `ConfidenceLevel`, `CandidateInfo`, `IntelligenceRequest`, `IntelligenceSignal`, `IntelligenceScore`, `IntelligenceRecommendation`
- **Sinais ativos (8):** `ContextSignal`, `FeedbackSignal`, `ContinuitySignal`, `ReferenceSignal`, `ThemeSignal`, `BookSignal`, `ConfidenceSignal`, `EvaluationSignal`
- **Sinais futuros (6):** `SemanticSignal`, `OperatorSignal`, `ChurchProfileSignal`, `LanguageSignal`, `TemporalSignal`, `EmotionSignal`
- **Registry:** `ACTIVE_SIGNAL_TYPES`, `FUTURE_SIGNAL_TYPES`, `ALL_SIGNAL_TYPES`
- **Policy:** `IntelligencePolicy`
- **Estratégias (8):** `ContextStrategy`, `FeedbackStrategy`, `ContinuityStrategy`, `ReferenceStrategy`, `ThemeStrategy`, `BookStrategy`, `ConfidenceStrategy`, `EvaluationStrategy`
- **Combiner/Coordinator/Engine:** `SignalCombiner`, `IntelligenceCoordinator`, `SermonIntelligenceEngine`

---

## 3. Novos DTOs

Todos os DTOs são `@dataclass(frozen=True)` — imutáveis, hashable, serializáveis.

### `ConfidenceLevel` (Enum)
Nível de confiança: `LOW`, `MEDIUM`, `HIGH`. Nunca binária — calculada a partir de número de sinais ativos e score final.

### `CandidateInfo`
Informação de um candidato: `candidate_id`, `base_score`, `book`, `chapter`, `verse`, `display`.

### `IntelligenceRequest`
Requisição completa: `query`, `context` (SermonContext | None), `candidates` (tuple), `feedback_summaries` (dict), `evaluation_metrics` (duck-typed).

### `IntelligenceSignal`
Sinal individual: `signal_type`, `value` [-1.0, 1.0], `weight` [0.0, 1.0], `explanation`. Property `contribution = value * weight`.

### `IntelligenceScore`
Score final de um candidato: `candidate_id`, `base_score`, `final_score`, 8 contribuições individuais (context, feedback, continuity, reference, theme, book, confidence, evaluation), `confidence_level`, `signals` (tuple), `explanation`. Methods `to_dict()`, `explain()`.

### `IntelligenceRecommendation`
Recomendação de ordenação: `query`, `scores` (tuple ordenada por final_score desc), `best_candidate_id`, `confidence_level`, `explanation`, `has_candidates`. Properties `best_score`, `ranking`. Methods `to_dict()`, `explain()`.

---

## 4. Novos Sinais

### Sinais ativos (8, todos frozen dataclass)

| Sinal | Tipo | Descrição |
|-------|------|-----------|
| `ContextSignal` | `context` | Contexto do sermão favorece o candidato? |
| `FeedbackSignal` | `feedback` | Há feedback aprendido para o candidato? |
| `ContinuitySignal` | `continuity` | O candidato continua a sequência de referências? |
| `ReferenceSignal` | `reference` | O candidato é a última referência resolvida? |
| `ThemeSignal` | `theme` | O candidato corresponde a temas recentes? |
| `BookSignal` | `book` | O candidato é do livro ativo/recente? |
| `ConfidenceSignal` | `confidence` | Sinal agregado de confiança (consistência) |
| `EvaluationSignal` | `evaluation` | Estatísticas de avaliação favorecem? |

### Sinais futuros (6, preparados mas não implementados)

| Sinal | Tipo | Reservado para |
|-------|------|----------------|
| `SemanticSignal` | `semantic` | Análise semântica da consulta |
| `OperatorSignal` | `operator` | Perfil do operador |
| `ChurchProfileSignal` | `church_profile` | Perfil da congregação |
| `LanguageSignal` | `language` | Idioma/dialeto |
| `TemporalSignal` | `temporal` | Padrões temporais |
| `EmotionSignal` | `emotion` | Tom emocional do sermão |

---

## 5. SermonIntelligenceEngine

Engine principal — ponto de entrada público do módulo.

### API

```python
engine = SermonIntelligenceEngine(policy=None, coordinator=None)
recommendation = engine.recommend(request)
print(recommendation.explain())
print(recommendation.ranking)
```

### Características

- **`recommend(request) → IntelligenceRecommendation`**: coordena sinais, ordena scores, produz recomendação.
- **Sem candidatos**: retorna recomendação vazia com `has_candidates=False`.
- **Ordenação**: scores ordenados por `final_score` decrescente.
- **Confiança**: herda do melhor candidato.
- **Explicação**: texto legível com decomposição completa.
- **Desacoplado**: não conhece nenhum outro componente.

---

## 6. IntelligenceCoordinator

Coordenador que orquestra estratégias e produz scores.

### API

```python
coordinator = IntelligenceCoordinator(policy=None, combiner=None)
scores = coordinator.coordinate(request)
```

### Características

- **`coordinate(request) → tuple[IntelligenceScore, ...]`**: para cada candidato, coleta sinais de todas as estratégias, adiciona sinal de confiança, combina via SignalCombiner.
- **ConfidenceStrategy é especial**: recebe os outros sinais como entrada para calcular consistência.
- **Ordem preservada**: scores na mesma ordem dos candidatos de entrada.
- **Sem lógica de negócio**: apenas orquestra.

---

## 7. SignalCombiner

Combinador de sinais em IntelligenceScore.

### API

```python
combiner = SignalCombiner(policy=None)
score = combiner.combine(candidate, signals)
```

### Características

- **`combine(candidate, signals) → IntelligenceScore`**: mapeia sinais por tipo, calcula contribuições individuais (value * weight), soma, aplica cap, calcula score final e confiança.
- **Cap**: ajuste total limitado a `[min_intelligence_adjustment, max_intelligence_adjustment]` = `[-0.10, +0.20]`.
- **Score final**: `base_score + capped_adjustment`, clamped `[0.0, 1.0]`.
- **Confiança**: calculada a partir de sinais ativos e score final.
- **Decomposição**: cada contribuição individual é preservada para explicabilidade.

---

## 8. IntelligencePolicy

Política centralizada — pesos, limites, thresholds. Stateless.

### Pesos dos sinais

| Sinal | Peso |
|-------|------|
| Context | 0.20 |
| Feedback | 0.25 |
| Continuity | 0.15 |
| Reference | 0.10 |
| Theme | 0.10 |
| Book | 0.10 |
| Confidence | 0.05 |
| Evaluation | 0.05 |

### Limites de ajuste

| Parâmetro | Valor |
|-----------|-------|
| `max_intelligence_adjustment` | +0.20 |
| `min_intelligence_adjustment` | -0.10 |

### Bônus por correspondência

| Bônus | Valor |
|-------|-------|
| Context book match | 0.10 |
| Context chapter match | 0.15 |
| Book recent match | 0.08 |
| Continuity match | 0.12 |
| Reference repeat | 0.05 |
| Theme match | 0.08 |
| Feedback strong | 0.12 |
| Feedback weak | 0.06 |

### Thresholds de confiança

| Nível | Sinais mínimos | Score mínimo |
|-------|----------------|--------------|
| HIGH | 5 | 0.85 |
| MEDIUM | 3 | 0.60 |
| LOW | — | — |

---

## 9. Estratégias Implementadas

### ContextStrategy
Analisa se o contexto atual (livro/capítulo ativo) favorece o candidato. Bônus: 0.10 (livro), 0.15 (livro+capítulo).

### FeedbackStrategy
Analisa feedback aprendido. Bônus: +0.12 (forte, peso ≥ 5), +0.06 (fraco), -0.06 (negativo). Usa duck-typing para acessar `FeedbackSummary`.

### ContinuityStrategy
Analisa continuidade com referências recentes. Bônus: 0.12 (mesmo livro+capítulo), 0.06 (mesmo livro). Exemplo: João 3 → João 3:17.

### ReferenceStrategy
Analisa se o candidato é a última referência resolvida (repetição). Bônus: 0.05.

### ThemeStrategy
Analisa correspondência com temas recentes. Heurística: verifica se o display do candidato contém tema recente. Bônus: 0.08.

### BookStrategy
Analisa se o candidato é do livro ativo ou recentemente mencionado. Bônus: 0.08.

### ConfidenceStrategy
Calcula sinal de confiança agregado a partir da consistência dos outros sinais. Bônus proporcional à consistência (±0.05).

### EvaluationStrategy
Analisa estatísticas de Continuous Evaluation. Bônus: +0.05 (precisão ≥ 70%), -0.03 (precisão < 50%). Usa duck-typing para acessar `EvaluationMetrics`.

---

## 10. Cálculo de Confiança

A confiança nunca é binária. É calculada combinando:

1. **Número de sinais ativos** (contribuição != 0)
2. **Score final** do candidato

| Condição | Nível |
|----------|-------|
| Sinais ≥ 5 AND score ≥ 0.85 | HIGH |
| Sinais ≥ 3 AND score ≥ 0.60 | MEDIUM |
| Caso contrário | LOW |

Adicionalmente, `ConfidenceStrategy` produz um sinal de consistência que contribui para o score: se todos os sinais são positivos, bônus de confiança; se todos negativos, penalização.

---

## 11. Cálculo de Score

```
Para cada candidato:
  1. Coletar 8 sinais (7 estratégias + confidence)
  2. Calcular contribuição de cada sinal: value * weight
  3. Somar todas as contribuições → total_adjustment
  4. Aplicar cap: [-0.10, +0.20]
  5. final_score = base_score + capped_adjustment
  6. Clamp: [0.0, 1.0]
  7. Calcular confiança a partir de sinais ativos e final_score
```

---

## 12. Estratégia Temática

A `ThemeStrategy` reconhece continuidade temática verificando se o `display` do candidato contém algum tema recentemente mencionado no `SermonContext.recent_themes`.

Exemplo:
```
Tema recente: "graça"
Candidato display: "graça de Deus em João 3:16"
→ ThemeSignal(value=0.08, explanation="Tema recente 'graça' corresponde")
```

Não utiliza IA, embeddings novos, ou Knowledge Graph diretamente — apenas informações existentes do Context Engine (`recent_themes`).

---

## 13. Estratégia de Continuidade

A `ContinuityStrategy` verifica se o candidato continua a sequência lógica de referências recentes.

Exemplo:
```
Referência recente: João 3 (book=João, chapter=3)
Candidato: João 3:17 (book=João, chapter=3)
→ ContinuitySignal(value=0.12, "Continuidade: mesmo livro e capítulo")

Candidato: João 4 (book=João, chapter=4)
→ ContinuitySignal(value=0.06, "Continuidade parcial: mesmo livro")
```

Não implementa resolução de pronomes complexa — apenas prepara infraestrutura.

---

## 14. Estratégia de Contexto

A `ContextStrategy` analisa se o contexto atual (livro/capítulo ativo do `SermonContext`) favorece o candidato.

Exemplo:
```
Contexto: book=João, chapter=21
Candidato: João 21:15 (book=João, chapter=21)
→ ContextSignal(value=0.15, "Contexto João 21 corresponde ao candidato")

Candidato: Lucas 15:11 (book=Lucas)
→ ContextSignal(value=0.0, "Contexto João não corresponde")
```

---

## 15. Explicabilidade

Toda recomendação é totalmente explicável:

```python
recommendation = engine.recommend(request)
print(recommendation.explain())
```

Saída:
```
Consulta 'pedro': recomendação (MEDIUM)
  +0.83 Base, +0.03 Contexto, +0.03 Feedback, +0.02 Continuidade, +0.01 Referência, +0.02 Livro, +0.01 Tema, +0.00 Confiança, +0.00 Estatística → 0.95, (HIGH)
  +0.80 Base, +0.00 Confiança, +0.00 Estatística → 0.80, (LOW)
  +0.75 Base, +0.00 Confiança, +0.00 Estatística → 0.75, (LOW)
```

Cada `IntelligenceScore` tem:
- Decomposição completa (8 contribuições individuais)
- Lista de sinais com explanations
- Nível de confiança
- Método `explain()` legível
- Método `to_dict()` para auditoria

---

## 16. Preparação para Novos Sinais

6 sinais futuros já estão preparados no módulo:

| Sinal | Tipo | Status |
|-------|------|--------|
| `SemanticSignal` | `semantic` | Preparado (frozen dataclass) |
| `OperatorSignal` | `operator` | Preparado |
| `ChurchProfileSignal` | `church_profile` | Preparado |
| `LanguageSignal` | `language` | Preparado |
| `TemporalSignal` | `temporal` | Preparado |
| `EmotionSignal` | `emotion` | Preparado |

Para adicionar um novo sinal ativo no futuro:
1. Criar `XxxStrategy` em `strategies.py`
2. Adicionar à tuple retornada por `all_strategies()`
3. Adicionar peso em `IntelligencePolicy`
4. Adicionar contribuição em `SignalCombiner`
5. Mover tipo de `FUTURE_SIGNAL_TYPES` para `ACTIVE_SIGNAL_TYPES`

Nenhum componente existente precisa ser modificado — apenas estendido.

---

## 17. Quantidade de Novos Testes

**145 novos testes** distribuídos em 3 arquivos:

| Arquivo | Linhas | Testes | Cobertura |
|---------|--------|--------|-----------|
| `tests/test_intelligence_dtos.py` | 434 | 62 | DTOs, sinais (8 ativos + 6 futuros), registry, policy (pesos, limites, cap, confiança) |
| `tests/test_intelligence_strategies.py` | 461 | 42 | 8 estratégias (context, feedback, continuity, reference, theme, book, confidence, evaluation) com cenários positivos, negativos e neutros |
| `tests/test_intelligence_engine.py` | 553 | 41 | Combiner, Coordinator, Engine, cenários (sem contexto, sem feedback, conflito, Pedro/João vs Pedro/Atos), desacoplamento, explicabilidade, imutabilidade |
| **Total** | **1448** | **145** | |

---

## 18. Exemplos Completos

### Exemplo 1: Recomendação com contexto

```python
from intelligence import SermonIntelligenceEngine, IntelligenceRequest, CandidateInfo
from context import SermonContext

ctx = SermonContext(book="João", book_id=43, chapter=21)
candidates = (
    CandidateInfo("43:21:15", 0.83, "João", 21, 15, "João 21:15"),
    CandidateInfo("42:15:11", 0.80, "Lucas", 15, 11, "Lucas 15:11"),
)

request = IntelligenceRequest(query="pedro", context=ctx, candidates=candidates)
engine = SermonIntelligenceEngine()
rec = engine.recommend(request)

print(rec.explain())
# Consulta 'pedro': recomendação (MEDIUM)
#   +0.83 Base, +0.03 Contexto, ... → 0.88, (MEDIUM)
#   +0.80 Base, ... → 0.80, (LOW)

print(rec.ranking)  # ('43:21:15', '42:15:11')
print(rec.best_candidate_id)  # '43:21:15'
```

### Exemplo 2: Pedro/João vs Pedro/Atos

```python
candidates = (
    CandidateInfo("43:21:15", 0.75, "João", 21, 15, "João 21:15"),
    CandidateInfo("44:2:38", 0.75, "Atos", 2, 38, "Atos 2:38"),
)

# Contexto João → João 21 vence
ctx_joao = SermonContext(book="João", book_id=43, chapter=21)
rec_joao = engine.recommend(IntelligenceRequest(
    query="pedro", context=ctx_joao, candidates=candidates))
# rec_joao.best_candidate_id == "43:21:15"

# Contexto Atos → Atos 2 vence
ctx_atos = SermonContext(book="Atos", book_id=44, chapter=2)
rec_atos = engine.recommend(IntelligenceRequest(
    query="pedro", context=ctx_atos, candidates=candidates))
# rec_atos.best_candidate_id == "44:2:38"
```

### Exemplo 3: Sem contexto nem feedback

```python
candidates = (CandidateInfo("43:21:15", 0.80),)
rec = engine.recommend(IntelligenceRequest(query="x", candidates=candidates))
# rec.scores[0].final_score == 0.80 (sem ajuste)
# rec.scores[0].confidence_level == LOW
```

### Exemplo 4: Conflito de sinais

```python
ctx = SermonContext(book="João", book_id=43, chapter=21)
# Contexto favorece, mas feedback é negativo
rec = engine.recommend(IntelligenceRequest(
    query="x", context=ctx,
    candidates=(CandidateInfo("43:21:15", 0.80, "João", 21),),
    feedback_summaries={"43:21:15": FakeSummary(total_weight=-5, rejections=5)},
))
# score.context_contribution > 0
# score.feedback_contribution < 0
```

---

## 19. Confirmação: Nenhum Comportamento Existente foi Alterado

A Fase 11 é **puramente aditiva**.

**Evidências:**

1. **Novo pacote isolado**: `intelligence/` é um módulo novo, não importado por nenhum componente existente.
2. **Nenhum import reverso**: nenhum arquivo existente importa `intelligence.*`.
3. **Sem alteração de APIs existentes**: Searcher, Ranking, Holyrics, Parser, LLM, Embeddings, KnowledgeBase, Context Engine, Feedback Learning, Continuous Evaluation — todos intactos.
4. **Duck-typing**: o Intelligence acessa apenas atributos públicos via `getattr` — não importa tipos concretos.
5. **Caso não exista Intelligence**: o sistema continua funcionando normalmente.
6. **Testes existentes**: 1850 testes pré-existentes continuam passando sem modificação.

---

## 20. Confirmação: Compatibilidade com Futuras Fases

1. **Streaming Speech Pipeline**: O pipeline poderá construir `IntelligenceRequest` com contexto, candidatos e feedback, e chamar `engine.recommend()` para obter ordenação recomendada.

2. **Integração com Ranking**: O Ranking poderá opcionalmente consultar `SermonIntelligenceEngine.recommend()` para reordenar candidatos. A recomendação é apenas uma sugestão — o Ranking decide se aplica.

3. **Novos sinais**: 6 sinais futuros já preparados. Adicionar novos sinais não quebra existentes.

4. **Novas estratégias**: Basta criar nova estratégia, adicionar a `all_strategies()`, e adicionar peso em `IntelligencePolicy`.

5. **Política ajustável**: Todos os pesos, limites e thresholds são centralizados em `IntelligencePolicy` e podem ser ajustados sem quebrar compatibilidade.

6. **Múltiplos coordenadores**: `IntelligenceCoordinator` aceita estratégias customizadas via construtor — permite configurações diferentes para diferentes cenários.

7. **Explicabilidade para auditoria**: `to_dict()` em todos os DTOs permite log completo e análise posterior.

---

## 21. Confirmação: Todos os Testes Antigos Continuam Passando

**Execução completa da suíte de testes:**

```
$ python -m pytest tests/ -q

1995 passed in 208.20s (0:03:28)
```

| Categoria | Quantidade | Status |
|-----------|-----------|--------|
| Testes pré-existentes (Fases 1-10) | 1850 | Passando |
| Testes novos (Fase 11) | 145 | Passando |
| **Total** | **1995** | **Todos passando** |

---

## 22. Resumo Executivo

| Aspecto | Valor |
|---------|-------|
| **Fase** | 11 — Sermon Intelligence |
| **Módulos novos** | 1 pacote (`intelligence/`) com 8 arquivos (1938 linhas) |
| **DTOs novos** | 6 (`ConfidenceLevel`, `CandidateInfo`, `IntelligenceRequest`, `IntelligenceSignal`, `IntelligenceScore`, `IntelligenceRecommendation`) |
| **Sinais ativos** | 8 (Context, Feedback, Continuity, Reference, Theme, Book, Confidence, Evaluation) |
| **Sinais futuros** | 6 (Semantic, Operator, ChurchProfile, Language, Temporal, Emotion) |
| **Estratégias** | 8 (uma por sinal ativo) |
| **Engine** | `SermonIntelligenceEngine` (ponto de entrada) |
| **Coordinator** | `IntelligenceCoordinator` (orquestra estratégias) |
| **Combiner** | `SignalCombiner` (combina sinais → IntelligenceScore) |
| **Policy** | `IntelligencePolicy` (pesos, limites, thresholds — centralizado) |
| **Limite de ajuste** | [-0.10, +0.20] (Intelligence nunca vence sozinho) |
| **Confiança** | LOW / MEDIUM / HIGH (não-binária) |
| **Explicabilidade** | `explain()` + `to_dict()` em todos os DTOs |
| **Desacoplamento** | Duck-typing via getattr — nenhum import de módulos existentes |
| **Testes novos** | 145 (em 3 arquivos, 1448 linhas) |
| **Testes totais** | 1995 (todos passando) |
| **Comportamento alterado** | Nenhum (puramente aditivo) |
| **ML/IA** | Nenhum (totalmente determinístico) |

---

*Relatório gerado automaticamente pela implementação da Fase 11.*
