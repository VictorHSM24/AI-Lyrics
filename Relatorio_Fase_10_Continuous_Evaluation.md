# Relatório Técnico — Fase 10: Continuous Evaluation

**Data:** 2026-07-18
**Status:** Concluído
**Fase:** 10 — Continuous Evaluation
**Testes:** 1850 totais (171 novos) — todos passando

---

## 1. Arquitetura Criada

A Fase 10 introduz o **Continuous Evaluation** — uma infraestrutura independente que mede continuamente a qualidade das decisões tomadas pelo sistema. Totalmente observacional: nunca influencia decisões, nunca altera nenhum componente.

### Princípios fundamentais

| Princípio | Implementação |
|-----------|---------------|
| **Apenas observa** | Evaluation nunca influencia decisões, nunca altera Ranking/Feedback/Contexto |
| **Desacoplamento total** | Engine, Metrics, Reports e Regressions não conhecem Searcher, Ranking, Feedback, Context Engine, Holyrics, Parser, LLM, Embeddings, KnowledgeBase |
| **Imutabilidade** | Todos os DTOs são `frozen dataclass`; registros são imutáveis |
| **Eventos tipados** | 8 eventos `frozen dataclass` herdam de `EvaluationEvent` |
| **Persistência JSON** | Com interface para futura troca por SQLite |
| **Política centralizada** | `EvaluationPolicy` centraliza thresholds, classificações, limites |
| **Métricas temporais** | 4 janelas: 24h, 7d, 30d, all |
| **Detecção de regressões** | Apenas registra alertas, não toma decisões automáticas |
| **Explicabilidade total** | Toda métrica é rastreável até o registro original |
| **Classificação extensível** | 7 tipos de consulta, arquitetura permite adicionar novos |

### Diagrama de fluxo

```
┌──────────────┐  EvaluationEvent  ┌──────────────────┐
│  Pipeline    │ ────────────────> │ EvaluationEngine │
│  (futuro)    │                   │   .record()      │
└──────────────┘                   └──────────────────┘
                                          │
                                          ▼
                                   ┌──────────────────┐
                                   │ EvaluationRepository│
                                   │  (JSON / SQLite)    │
                                   └──────────────────┘
                                          │
                            ┌─────────────┼─────────────┐
                            ▼             ▼             ▼
                   ┌────────────┐ ┌────────────┐ ┌──────────────┐
                   │ Metrics    │ │ Reports    │ │ Regressions  │
                   │ Calculator │ │ Generator  │ │ Detector     │
                   └────────────┘ └────────────┘ └──────────────┘
```

### Estrutura de arquivos

```
evaluation/
├── __init__.py      (107 linhas) — API pública
├── dtos.py          (459 linhas) — 8 DTOs imutáveis + 2 enums
├── events.py        (216 linhas) — EvaluationEvent + 8 eventos
├── policy.py        (233 linhas) — EvaluationPolicy (thresholds, classificações)
├── store.py         (203 linhas) — EvaluationStore (armazenamento puro)
├── repository.py    (180 linhas) — EvaluationRepository (JSON, interface SQLite)
├── metrics.py       (341 linhas) — MetricsCalculator (precisão, temporais)
├── engine.py        (244 linhas) — EvaluationEngine (registra eventos)
├── reports.py       (165 linhas) — ReportGenerator (gera EvaluationReport)
└── regressions.py   (189 linhas) — RegressionDetector (detecta regressões)

tests/
├── test_evaluation_dtos.py                  (467 linhas, 56 testes)
├── test_evaluation_policy_store.py          (340 linhas, 47 testes)
├── test_evaluation_engine_metrics.py        (405 linhas, 39 testes)
└── test_evaluation_reports_scenarios.py     (422 linhas, 29 testes)
```

---

## 2. Novos Módulos

### `evaluation/` (pacote Python)

Módulo novo, totalmente isolado. Nenhuma dependência externa além de Python padrão (`uuid`, `json`, `os`, `time`, `dataclasses`, `enum`, `collections`).

**API pública** (exportada via `evaluation/__init__.py`):

- **DTOs:** `QueryClassification`, `TemporalWindow`, `EvaluationRecord`, `EvaluationMetrics`, `TemporalSlice`, `EvaluationSummary`, `EvaluationReport`, `RegressionAlert`
- **Eventos:** `EvaluationEvent`, `SearchExecuted`, `CandidatePresented`, `CandidateAccepted`, `CandidateRejected`, `ManualCorrection`, `SearchFailed`, `NoResultFound`, `EvaluationReset`
- **Policy:** `EvaluationPolicy`
- **Store/Repository:** `EvaluationStore`, `EvaluationRepository`, `EvaluationRepositoryProtocol`
- **Engine:** `EvaluationEngine`
- **Metrics/Reports/Regressions:** `MetricsCalculator`, `ReportGenerator`, `RegressionDetector`

---

## 3. Novos DTOs

Todos os DTOs são `@dataclass(frozen=True)` — imutáveis, hashable, serializáveis.

### `QueryClassification` (Enum)
Classificação do tipo de consulta: `REFERENCE`, `BOOK`, `CHARACTER`, `CONCEPT`, `THEME`, `EVENT`, `UNKNOWN`. Arquitetura permite adicionar novos tipos.

### `TemporalWindow` (Enum)
Janela temporal: `LAST_24H`, `LAST_7D`, `LAST_30D`, `ALL`.

### `EvaluationRecord`
Registro individual de um evento: `record_id`, `timestamp`, `event_type`, `query`, `classification`, `candidate_id`, `context_signature`, `book`, `operator_id`, `duration_ms`, `metadata`. Serializável via `to_dict`/`from_dict`.

### `EvaluationMetrics`
Métricas acumuladas: totais (searches, presented, accepted, rejected, corrections, no_result, failed, duration), agrupamentos (by_classification, by_book, by_context). Properties: `acceptance_rate`, `rejection_rate`, `precision`, `avg_duration_ms`, `no_result_rate`.

### `TemporalSlice`
Fatia temporal das métricas: `window`, `start_timestamp`, `end_timestamp`, `metrics`, `record_count`.

### `EvaluationSummary`
Resumo agregado: `total_records`, `metrics`, `hardest_queries`, `top_candidates`, `worst_books`, `worst_themes`.

### `EvaluationReport`
Relatório completo: `generated_at`, `window`, `summary`, `temporal_slices`, `regressions`. Método `to_text()` gera relatório legível.

### `RegressionAlert`
Alerta de regressão: `metric_name`, `description`, `previous_value`, `current_value`, `threshold`, `detected_at`, `severity`.

---

## 4. Novos Eventos

Todos os eventos são `@dataclass(frozen=True)` herdados de `EvaluationEvent`.

| Evento | Quando emitir |
|--------|---------------|
| `SearchExecuted` | Uma busca foi executada (com duração e result_count) |
| `CandidatePresented` | Um candidato foi apresentado (com rank_position) |
| `CandidateAccepted` | Um candidato foi aceito pelo operador |
| `CandidateRejected` | Um candidato foi rejeitado pelo operador |
| `ManualCorrection` | O operador corrigiu manualmente (original → corrected) |
| `SearchFailed` | Uma busca falhou tecnicamente (com error_message) |
| `NoResultFound` | Uma busca não retornou resultados |
| `EvaluationReset` | As métricas foram resetadas |

**Type alias:** `EvaluationEventUnion = Union[...]` para type hints.

---

## 5. EvaluationEngine

Engine que registra eventos de avaliação.

### API

```python
engine = EvaluationEngine(repository, clock=time.time, id_generator=uuid4)
record = engine.record(SearchExecuted(query="pedro", duration_ms=250, ...))
records = engine.list_records()
records = engine.list_since(timestamp)
engine.reset()
engine.flush()
```

### Características

- **`record(event) → EvaluationRecord`**: cria registro, persiste via repository.
- **`EvaluationReset`**: tratado separadamente, limpa todos os registros.
- **Clock e ID generator injetáveis**: para testes determinísticos.
- **Desacoplado**: não conhece nenhum outro componente do sistema.

---

## 6. EvaluationRepository

Camada de abstração sobre `EvaluationStore` com interface para futura troca por SQLite.

### API

```python
repo = EvaluationRepository(path=None, auto_save=False)
repo.add(record)
record = repo.get(record_id)
repo.list_all()
repo.list_since(timestamp)
repo.list_between(start, end)
repo.list_by_event_type(event_type)
repo.list_by_query(query)
repo.clear()
repo.flush()
```

### Características

- **Persistência JSON**: `path` configura arquivo. Se `None`, em memória.
- **`auto_save=True`**: persiste a cada `add()`.
- **`load` automático**: carrega do arquivo na inicialização.
- **`EvaluationRepositoryProtocol`**: interface para futura implementação SQLite.

---

## 7. EvaluationStore

Armazenamento puro — sem regra de negócio.

### API

```python
store = EvaluationStore()
store.add(record)
store.get(record_id)
store.list_all()
store.list_since(timestamp)
store.list_between(start, end)
store.list_by_event_type(event_type)
store.list_by_query(query)
store.clear()
store.save(path)
store.load(path)
store.to_json()
store.from_json(json_str)
```

### Características

- **CRUD puro**: add, get, has, list, clear.
- **Filtros temporais**: list_since, list_between.
- **Filtros por tipo/query**: list_by_event_type, list_by_query.
- **Persistência JSON**: save/load para arquivo, to_json/from_json para string.

---

## 8. EvaluationPolicy

Política centralizada de thresholds, classificações e parâmetros. Stateless.

### Parâmetros de confiança estatística

| Parâmetro | Valor | Significado |
|-----------|-------|-------------|
| `min_records_for_confidence` | 10 | Mínimo de registros para confiança |
| `min_searches_per_book` | 5 | Mínimo de buscas por livro para precisão |

### Thresholds de regressão

| Parâmetro | Valor | Significado |
|-----------|-------|-------------|
| `regression_precision_drop` | 5.0 p.p. | Queda de precisão para alerta |
| `regression_duration_increase` | 50% | Aumento de tempo para alerta |
| `regression_corrections_increase` | 30% | Aumento de correções para alerta |
| `regression_no_result_increase` | 50% | Aumento de sem-resultado para alerta |

### Limites de relatórios

| Parâmetro | Valor |
|-----------|-------|
| `top_queries_limit` | 10 |
| `top_candidates_limit` | 10 |
| `worst_books_limit` | 10 |
| `worst_themes_limit` | 10 |

### Severidade

| Severidade | Queda de precisão |
|------------|-------------------|
| `low` | ≥ 5 p.p. |
| `medium` | ≥ 10 p.p. |
| `high` | ≥ 20 p.p. |

### Janelas temporais

| Janela | Duração (segundos) |
|--------|---------------------|
| `LAST_24H` | 86.400 |
| `LAST_7D` | 604.800 |
| `LAST_30D` | 2.592.000 |
| `ALL` | ∞ |

---

## 9. Métricas Implementadas

### Métricas globais

| Métrica | Descrição |
|---------|-----------|
| `total_searches` | Total de buscas executadas |
| `total_presented` | Total de candidatos apresentados |
| `total_accepted` | Total de candidatos aceitos |
| `total_rejected` | Total de candidatos rejeitados |
| `total_manual_corrections` | Total de correções manuais |
| `total_no_result` | Total de buscas sem resultado |
| `total_failed` | Total de buscas que falharam tecnicamente |
| `total_duration_ms` | Duração total das buscas |
| `acceptance_rate` | Taxa de aceitação [0.0, 1.0] |
| `rejection_rate` | Taxa de rejeição [0.0, 1.0] |
| `precision` | Precisão = aceitos / (aceitos + rejeitados + correções) |
| `avg_duration_ms` | Tempo médio das buscas |
| `no_result_rate` | Taxa de buscas sem resultado |

### Métricas por grupo

| Grupo | Método |
|-------|--------|
| Por classificação | `by_classification` em EvaluationMetrics + `precision_by_classification()` |
| Por livro | `by_book` em EvaluationMetrics + `precision_by_book()` |
| Por contexto | `by_context` em EvaluationMetrics |
| Por operador | Estrutura preparada (`operator_id` no EvaluationRecord) |

### Métricas de dificuldade

| Métrica | Método |
|---------|--------|
| Consultas mais difíceis | `hardest_queries()` — ranking por falhas |
| Candidatos que mais vencem | `top_candidates()` — ranking por aceites |
| Livros com menor precisão | `precision_by_book()` — ordenado por precisão crescente |

---

## 10. Estratégia Temporal

4 janelas temporais suportadas via `TemporalWindow`:

- **LAST_24H**: últimas 24 horas (86.400 segundos)
- **LAST_7D**: últimos 7 dias (604.800 segundos)
- **LAST_30D**: últimos 30 dias (2.592.000 segundos)
- **ALL**: desde o início (sem limite)

`MetricsCalculator.temporal_slice(records, window, now)` filtra registros pela janela e calcula métricas. `all_temporal_slices(records, now)` retorna todas as 4 fatias de uma vez.

`ReportGenerator.generate(records, window, now)` gera relatório com fatias temporais incluídas.

---

## 11. Estratégia de Regressão

`RegressionDetector.detect(previous, current, now)` compara métricas anteriores com atuais e retorna `RegressionAlert` para cada regressão detectada.

### Regressões monitoradas

| Regressão | Condição | Severidade |
|-----------|----------|------------|
| Queda de precisão | drop ≥ 5 p.p. | low/medium/high (por drop) |
| Aumento de tempo médio | increase ≥ 50% | medium |
| Aumento de correções | increase ≥ 30% | medium |
| Aumento de sem-resultado | increase ≥ 50% | low |

**Apenas registra — não toma decisões automáticas.** Não modifica comportamento do sistema, não alerta automaticamente, não notifica. Apenas retorna `RegressionAlert` para consumo futuro (dashboard, log, etc.).

---

## 12. Formato de Persistência

JSON, com versão para compatibilidade futura:

```json
{
  "version": 1,
  "records": [
    {
      "record_id": "rec_0001",
      "timestamp": 1001.0,
      "event_type": "search_executed",
      "query": "pedro",
      "classification": "CHARACTER",
      "candidate_id": "",
      "context_signature": "João",
      "book": "João",
      "operator_id": "",
      "duration_ms": 250.0,
      "metadata": [["result_count", "5"]]
    }
  ]
}
```

**Futura troca por SQLite:** basta criar `EvaluationSQLiteRepository` implementando `EvaluationRepositoryProtocol`. O Engine não muda.

---

## 13. Estratégia de Relatórios

`ReportGenerator` gera `EvaluationReport` completo com:

- **Summary**: métricas agregadas, consultas mais difíceis, candidatos top, livros com menor precisão.
- **Temporal slices**: 4 fatias temporais (24h, 7d, 30d, all).
- **Regressions**: alertas detectados (se métricas anteriores fornecidas).

`EvaluationReport.to_text()` gera relatório legível:

```
=== Relatório de Avaliação ===
Janela: ALL
Buscas: 1520
Acertos: 1480
Precisão: 97.4%
Correções: 31
Sem resultado: 9
Tempo médio: 310 ms
Consultas mais difíceis:
  - amor: 12 falhas
  - fé: 8 falhas
Livros com menor precisão:
  - Gênesis: 85.2%
Regressões detectadas:
  - precision: Precisão caiu 5.2 p.p. (97.4% → 92.2%)
```

---

## 14. Estratégia de Classificação

`QueryClassification` (Enum) define 7 tipos de consulta:

| Classificação | Exemplo |
|---------------|---------|
| `REFERENCE` | "João 3:16" |
| `BOOK` | "João" |
| `CHARACTER` | "Pedro" |
| `CONCEPT` | "filho pródigo" |
| `THEME` | "armadura de Deus" |
| `EVENT` | "Pentecostes" |
| `UNKNOWN` | Não determinada |

A arquitetura permite adicionar novos tipos sem quebrar compatibilidade — basta adicionar valores ao enum. `EvaluationPolicy.all_classifications()` retorna todos os tipos suportados.

Métricas são calculadas por classificação via `precision_by_classification()`, permitindo identificar quais tipos de consulta apresentam maior dificuldade.

---

## 15. Quantidade de Novos Testes

**171 novos testes** distribuídos em 4 arquivos:

| Arquivo | Linhas | Testes | Cobertura |
|---------|--------|--------|-----------|
| `tests/test_evaluation_dtos.py` | 467 | 56 | DTOs, enums, imutabilidade, serialização, eventos |
| `tests/test_evaluation_policy_store.py` | 340 | 47 | Policy (thresholds, janelas, severidade), Store (CRUD, persistência), Repository (CRUD, auto_save) |
| `tests/test_evaluation_engine_metrics.py` | 405 | 39 | Engine (record para cada evento, queries, reset, flush), Metrics (calculate, temporal_slice, precision_by_book, hardest_queries, top_candidates) |
| `tests/test_evaluation_reports_scenarios.py` | 422 | 29 | Reports (generate, to_text), Regressions (detect, checks, severidade), cenário completo, desacoplamento, explicabilidade, imutabilidade |
| **Total** | **1634** | **171** | |

---

## 16. Exemplos de Relatórios

### Exemplo 1: Relatório básico

```python
engine = EvaluationEngine(FeedbackRepository())
engine.record(SearchExecuted(query="pedro", duration_ms=250, book="João"))
engine.record(CandidateAccepted(query="pedro", candidate_id="43:21:15"))

gen = ReportGenerator()
report = gen.generate(engine.list_records(), window=TemporalWindow.ALL, now=1010.0)
print(report.to_text())
```

Saída:
```
=== Relatório de Avaliação ===
Janela: ALL
Buscas: 1
Acertos: 1
Precisão: 100.0%
Correções: 0
Sem resultado: 0
Tempo médio: 250 ms
```

### Exemplo 2: Relatório com regressão

```python
prev = EvaluationMetrics(total_accepted=90, total_rejected=10)  # 90%
curr = EvaluationMetrics(total_accepted=70, total_rejected=30)  # 70%

detector = RegressionDetector()
alerts = detector.detect(prev, curr, now=1000.0)
# → [RegressionAlert(metric_name="precision", severity="high",
#     description="Precisão caiu 20.0 p.p. (90.0% → 70.0%)")]
```

### Exemplo 3: Métricas temporais

```python
calc = MetricsCalculator()
records = engine.list_records()
slices = calc.all_temporal_slices(records, now=200000.0)
# 4 fatias: LAST_24H, LAST_7D, LAST_30D, ALL
for s in slices:
    print(f"{s.window.value}: {s.metrics.total_searches} buscas")
```

---

## 17. Confirmação: Nenhum Comportamento Existente foi Alterado

A Fase 10 é **puramente aditiva e observacional**.

**Evidências:**

1. **Novo pacote isolado**: `evaluation/` é um módulo novo, não importado por nenhum componente existente.
2. **Nenhum import reverso**: nenhum arquivo existente importa `evaluation.*`.
3. **Sem alteração de APIs existentes**: Searcher, Ranking, Holyrics, Parser, LLM, Embeddings, KnowledgeBase, Context Engine, Feedback Learning — todos intactos.
4. **Sem integração automática**: nenhum componente existente emite eventos de avaliação. A integração é futura.
5. **Se Evaluation não existir**: o sistema continua funcionando normalmente.
6. **Testes existentes**: 1679 testes pré-existentes continuam passando sem modificação.

---

## 18. Confirmação: Compatibilidade com Futuras Fases

1. **Streaming Speech Pipeline**: O pipeline poderá emitir `SearchExecuted`, `CandidateAccepted`, etc. automaticamente. O Engine já está pronto.

2. **Integração com Pipeline**: O pipeline poderá chamar `engine.record(event)` após cada operação. Sem alteração no comportamento do pipeline.

3. **Dashboard (futuro)**: `ReportGenerator.generate()` já produz dados estruturados (`to_dict()`) para futura interface web.

4. **SQLite (futuro)**: `EvaluationRepositoryProtocol` define a interface. Basta criar `EvaluationSQLiteRepository`.

5. **Múltiplos operadores (futuro)**: `operator_id` já existe em `EvaluationRecord` e `EvaluationEvent`. Métricas por operador podem ser calculadas filtrando registros.

6. **Novos tipos de consulta (futuro)**: Basta adicionar valores a `QueryClassification`. A arquitetura já suporta.

7. **Novos eventos (futuro)**: Eventos desconhecidos são registrados como `"unknown"`. Adicionar novos eventos não quebra o engine.

8. **Alertas automáticos (futuro)**: `RegressionDetector` já detecta regressões. Futuramente, pode-se adicionar notificações baseadas nos alertas.

---

## 19. Confirmação: Todos os Testes Antigos Continuam Passando

**Execução completa da suíte de testes:**

```
$ python -m pytest tests/ -q

1850 passed in 204.56s (0:03:24)
```

| Categoria | Quantidade | Status |
|-----------|-----------|--------|
| Testes pré-existentes (Fases 1-9) | 1679 | ✅ Passando |
| Testes novos (Fase 10) | 171 | ✅ Passando |
| **Total** | **1850** | **✅ Todos passando** |

---

## 20. Resumo Executivo

| Aspecto | Valor |
|---------|-------|
| **Fase** | 10 — Continuous Evaluation |
| **Módulos novos** | 1 pacote (`evaluation/`) com 10 arquivos (2337 linhas) |
| **DTOs novos** | 8 (`QueryClassification`, `TemporalWindow`, `EvaluationRecord`, `EvaluationMetrics`, `TemporalSlice`, `EvaluationSummary`, `EvaluationReport`, `RegressionAlert`) |
| **Eventos novos** | 8 (`SearchExecuted`, `CandidatePresented`, `CandidateAccepted`, `CandidateRejected`, `ManualCorrection`, `SearchFailed`, `NoResultFound`, `EvaluationReset`) |
| **Engine** | `EvaluationEngine` (registra eventos, clock/ID injetáveis) |
| **Repository** | `EvaluationRepository` (JSON, interface para SQLite) |
| **Store** | `EvaluationStore` (armazenamento puro, sem regra de negócio) |
| **Policy** | `EvaluationPolicy` (thresholds, classificações, limites — centralizado) |
| **Metrics** | `MetricsCalculator` (13+ métricas, agrupamentos, temporais) |
| **Reports** | `ReportGenerator` (EvaluationReport com to_text) |
| **Regressions** | `RegressionDetector` (4 tipos de regressão, 3 níveis de severidade) |
| **Janelas temporais** | 4 (24h, 7d, 30d, all) |
| **Classificações** | 7 (REFERENCE, BOOK, CHARACTER, CONCEPT, THEME, EVENT, UNKNOWN) |
| **Formato de persistência** | JSON (versionado, pronto para SQLite) |
| **Explicabilidade** | Rastreabilidade total via EvaluationRecord + to_dict |
| **Testes novos** | 171 (em 4 arquivos, 1634 linhas) |
| **Testes totais** | 1850 (todos passando) |
| **Comportamento alterado** | Nenhum (puramente observacional) |
| **ML/IA** | Nenhum |

---

*Relatório gerado automaticamente pela implementação da Fase 10.*
