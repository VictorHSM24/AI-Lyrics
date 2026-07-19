# Relatório — Fase 12: Streaming Speech Pipeline

**Data:** 18 de julho de 2026
**Fase:** 12 — Streaming Speech Pipeline
**Status:** Concluído
**Testes:** 2238 passaram (2087 existentes + 151 novos), zero regressão

---

## 1. Objetivo

Criar uma infraestrutura determinística, orientada a eventos,
completamente rastreável, desacoplada e auditável que conecta todos
os módulos das fases anteriores (Searcher, Ranking, Context, Feedback,
Evaluation, Sermon Intelligence, Evidence Layer, Parser, STT, LLM,
Holyrics) **sem modificar o comportamento de nenhum deles**.

**Filosofia:** O Pipeline NUNCA implementa regra de negócio. NUNCA
decide, calcula ranking, interpreta contexto, aprende, executa
heurísticas, cria Evidence, altera Signals ou modifica Intelligence.
**Apenas coordena via eventos tipados.**

---

## 2. Arquitetura Criada

### 2.1 Novo módulo: `pipeline/`

```
pipeline/
├── __init__.py          # Exporta todos os componentes públicos
├── metadata.py          # EventMetadata (DTO de rastreabilidade)
├── events.py            # 15 eventos tipados (frozen dataclass)
├── bus.py               # PipelineEventBus (subscribe/publish/dispatch)
├── policy.py            # PipelinePolicy (timeouts, buffers, limites)
├── state.py             # PipelineState (estado imutável)
├── session.py           # PipelineSession (sermão completo)
├── metrics.py           # PipelineMetrics (contadores, latência, throughput)
├── handlers_base.py     # Base + 4 handlers de fluxo principal
├── handlers_aux.py      # 4 handlers auxiliares
├── handlers.py          # Reexporta todos os handlers
├── coordinator.py       # PipelineCoordinator (registra handlers)
└── engine.py            # StreamingPipelineEngine (start/stop/process)
```

### 2.2 Componentes

| Componente               | Responsabilidade                                    |
|--------------------------|-----------------------------------------------------|
| `EventMetadata`          | DTO imutável de rastreabilidade (7 campos)          |
| `PipelineEvent` (base)   | Base comum com `meta: EventMetadata`                |
| 15 eventos tipados       | `SpeechSegmentReceived` → `EvaluationRecorded` + ciclo de vida |
| `PipelineEventBus`       | Barramento síncrono genérico (subscribe/publish)    |
| `PipelinePolicy`         | Timeouts, buffers, limites, retries (imutável)      |
| `PipelineState`          | Estado imutável (running, paused, last_query, etc.) |
| `PipelineSession`        | Sessão imutável (sermão completo, estatísticas)     |
| `PipelineMetrics`        | Métricas em tempo real (latência, throughput, erros)|
| 8 Handlers               | Cada um: recebe evento → executa → publica novo     |
| `PipelineCoordinator`    | Registra Handlers no EventBus                       |
| `StreamingPipelineEngine`| start/stop/pause/resume/process                     |

---

## 3. EventMetadata

DTO imutável, hashable, serializável. Campos:

| Campo            | Tipo           | Descrição                              |
|------------------|----------------|----------------------------------------|
| `event_id`       | str            | ID único do evento (nunca reutilizado) |
| `correlation_id` | str            | ID do fluxo (compartilhado)            |
| `causation_id`   | str \| None    | event_id do evento anterior            |
| `session_id`     | str            | ID da PipelineSession                  |
| `timestamp`      | float          | Momento de criação                     |
| `origin`         | str            | Componente criador                     |
| `metadata`       | tuple          | Pares (chave, valor) extras            |

**Fábricas estáticas:**
- `for_initial()`: novo correlation_id, causation_id=None
- `for_next(previous)`: preserva correlation_id, causation_id=previous.event_id
- `for_session_event()`: para eventos de ciclo de vida

---

## 4. EventBus

`PipelineEventBus` — barramento síncrono e genérico.

**Métodos:** `subscribe`, `unsubscribe`, `unsubscribe_all`, `publish`,
`dispatch`, `handlers`, `has_subscribers`, `subscribed_types`,
`event_count`, `history`, `history_types`, `clear_history`, `clear`,
`reset`.

**Características:**
- Síncrono (sem threads/asyncio)
- Genérico (não conhece tipos específicos)
- Múltiplos handlers por tipo
- Ordem de execução = ordem de inscrição
- Histórico de eventos para replay/diagnóstico

---

## 5. Eventos (15 tipados)

### Fluxo principal (9):
```
SpeechSegmentReceived → SpeechRecognized → SearchRequested →
SearchCompleted → RankingCompleted → IntelligenceCompleted →
PresentationRequested → PresentationCompleted →
FeedbackRecorded → EvaluationRecorded
```

### Ciclo de vida (4):
`PipelineStarted`, `PipelineStopped`, `PipelinePaused`, `PipelineResumed`

### Erro (1):
`PipelineError`

**Todos:** frozen dataclass, hashable, serializáveis, herdam de
`PipelineEvent` (que tem campo `meta: EventMetadata`).

---

## 6. Handlers (8)

| Handler               | Entrada                    | Saída (publica)                          |
|-----------------------|----------------------------|------------------------------------------|
| `RecognitionHandler`  | SpeechSegmentReceived      | SpeechRecognized                         |
| `SearchHandler`       | SpeechRecognized           | SearchRequested → SearchCompleted        |
| `RankingHandler`      | SearchCompleted            | RankingCompleted                         |
| `IntelligenceHandler` | RankingCompleted           | IntelligenceCompleted                    |
| `PresentationHandler` | IntelligenceCompleted      | PresentationRequested → PresentationCompleted |
| `FeedbackHandler`     | PresentationCompleted      | FeedbackRecorded                         |
| `EvaluationHandler`   | FeedbackRecorded           | EvaluationRecorded                       |
| `ContextHandler`      | SpeechRecognized           | (atualiza contexto, sem evento)          |

**Regras:**
- Nenhum Handler chama outro Handler diretamente
- Toda comunicação via EventBus
- Cada Handler preserva correlation_id via `EventMetadata.for_next()`
- Erros em Handlers publicam `PipelineError` (não quebram o pipeline)
- Dependências (STT, Searcher, etc.) injetadas via construtor (duck-typing)

---

## 7. Coordinator

`PipelineCoordinator` — registra Handlers no EventBus.

**Métodos:** `register`, `unregister`, `unregister_all`, `is_registered`,
`register_default_flow`, `registered_handlers`, `handler_count`.

`register_default_flow(handlers)` mapeia automaticamente cada Handler
para seu evento de entrada.

---

## 8. Pipeline Engine

`StreamingPipelineEngine` — orquestra o ciclo de vida.

**Métodos:** `start`, `stop`, `pause`, `resume`, `process`, `reset`.

**Properties:** `bus`, `policy`, `session`, `state`, `metrics`,
`session_id`, `is_running`, `is_paused`, `is_active`.

**Comportamento:**
- `start()`/`stop()` são idempotentes
- `process()` quando não ativo → descarta segmento + registra métrica
- `process()` valida duração do segmento via policy
- `process()` cria novo `correlation_id` (único por segmento)
- `process()` retorna o `correlation_id` para rastreabilidade

---

## 9. State, Session, Metrics

### PipelineState (imutável)
Campos: `running`, `paused`, `current_segment`, `last_query`,
`last_candidate_id`, `last_event_type`, `last_event_timestamp`,
`statistics`. Methods `with_*` produzem novo estado.

### PipelineSession (imutável)
Campos: `session_id`, `started_at`, `ended_at`, `processed_segments`,
`processed_queries`, `presentations`, `errors`, `statistics`,
`correlation_ids`. Properties: `is_active`, `duration_s`,
`error_rate`, `presentation_rate`, `segments_per_minute`,
`queries_per_minute`.

### PipelineMetrics (mutável, contadores em tempo real)
Contadores: segmentos (received/processed/dropped), queries,
presentations (executed/failed), errors (total/recoverable/fatal).
Latência por etapa (recognition, search, ranking, intelligence,
presentation, feedback, evaluation). Properties: `avg_latency_ms`,
`throughput_segments_per_min`, `error_rate`, `drop_rate`,
`presentation_success_rate`.

---

## 10. Política

`PipelinePolicy` (imutável) centraliza:
- **Timeouts** (ms): recognition, search, ranking, intelligence,
  presentation, feedback, evaluation
- **Buffers/limites**: max_segment_duration, max_query_length,
  max_results_per_search, max_candidates_per_ranking, max_history_events
- **Retries**: recognition, search, presentation
- **Intervalos**: min_interval_between_segments, debounce
- **Backpressure** (preparado, não implementado): enabled, threshold,
  strategy ("drop_oldest" | "drop_newest" | "block")
- **Comportamento**: continue_on_error, auto_present,
  auto_record_feedback, auto_record_evaluation

---

## 11. Fluxo Completo

```
┌─────────────────────────────────────────────────────────────┐
│                StreamingPipelineEngine                       │
│                                                             │
│  start() ──► PipelineStarted                                │
│  process() ──► SpeechSegmentReceived (novo correlation_id)  │
│                    │                                        │
│                    ▼                                        │
│  ┌─ RecognitionHandler ── SpeechRecognized                  │
│  │                    │                                     │
│  │                    ▼                                     │
│  │  SearchHandler ── SearchRequested ── SearchCompleted     │
│  │                    │                                     │
│  │                    ▼                                     │
│  │  RankingHandler ── RankingCompleted                      │
│  │                    │                                     │
│  │                    ▼                                     │
│  │  IntelligenceHandler ── IntelligenceCompleted             │
│  │                    │ (preserva Evidences)                │
│  │                    ▼                                     │
│  │  PresentationHandler ── PresentationRequested            │
│  │                    │   ── PresentationCompleted          │
│  │                    ▼                                     │
│  │  FeedbackHandler ── FeedbackRecorded                     │
│  │                    │                                     │
│  │                    ▼                                     │
│  └─ EvaluationHandler ── EvaluationRecorded                 │
│                                                             │
│  stop() ──► PipelineStopped                                 │
└─────────────────────────────────────────────────────────────┘
```

**Todos os eventos compartilham o mesmo `correlation_id`.**
**Cada evento aponta para seu `causation_id` (event_id do anterior).**

---

## 12. Estratégias

### 12.1 Observabilidade
- Cada evento carrega `EventMetadata` completo
- `PipelineEventBus.history()` armazena todos os eventos publicados
- `PipelineMetrics` registra latência por etapa, throughput, erros
- `PipelineState` rastreia último evento, último query, último candidato
- `PipelineSession` agrega estatísticas do sermão completo

### 12.2 Rastreabilidade
- `event_id`: único por evento (uuid4)
- `correlation_id`: único por fluxo (compartilhado entre todos os eventos)
- `causation_id`: event_id do evento anterior (cadeia causal)
- `session_id`: identificador da sessão
- `timestamp`: momento de criação
- `origin`: componente criador

### 12.3 Correlação
- Somente `SpeechSegmentReceived` inicia novo `correlation_id`
- `EventMetadata.for_next(previous)` preserva `correlation_id` e
  encadeia `causation_id`
- Múltiplos segmentos geram `correlation_ids` diferentes
- `PipelineSession.correlation_ids` rastreia todos os fluxos

### 12.4 Replay (preparado, não implementado)
- `PipelineEventBus.history()` contém todos os eventos
- Cadeia causal (`causation_id`) permite reconstruir o fluxo
- `correlation_id` permite filtrar eventos de um fluxo específico
- Arquitetura pronta para `ReplayEngine` futuro

### 12.5 Backpressure (preparado, não implementado)
- `PipelinePolicy.backpressure_enabled` (default False)
- `PipelinePolicy.backpressure_threshold` (limite)
- `PipelinePolicy.backpressure_strategy` ("drop_oldest" | "drop_newest" | "block")
- `PipelineMetrics.record_segment_dropped()` já registra descartes
- Engine já descarta segmentos quando não ativo ou duração inválida

---

## 13. Integrações

### 13.1 Context Engine
- `ContextHandler` recebe `SpeechRecognized` e atualiza contexto via
  `SermonContextEngine.process()` (duck-typing)
- Contexto atualizado é usado pelo `IntelligenceHandler`
- Não publica evento próprio (contexto é estado, não evento)

### 13.2 Feedback Learning
- `FeedbackHandler` recebe `PresentationCompleted` e delega para
  `FeedbackEngine.process()` (duck-typing)
- Registra aceitação/rejeição automática baseada em `presented`
- Controlado por `policy.auto_record_feedback`

### 13.3 Continuous Evaluation
- `EvaluationHandler` recebe `FeedbackRecorded` e delega para
  `EvaluationEngine.record()` (duck-typing)
- Controlado por `policy.auto_record_evaluation`
- `PipelineSession` integra-se naturalmente (estatísticas agregadas)

### 13.4 Sermon Intelligence
- `IntelligenceHandler` constrói `IntelligenceRequest` com candidatos,
  contexto, feedback_summaries e evaluation_metrics
- Delega para `SermonIntelligenceEngine.recommend()`
- Publica `IntelligenceCompleted` com a recomendação

### 13.5 Preservação de Evidences
- O Pipeline **NUNCA** cria, modifica ou interpreta Evidences
- `IntelligenceCompleted` carrega `recommendation` que contém
  `IntelligenceScore` com `signals` que contêm `evidences`
- As Evidences produzidas pelo Sermon Intelligence são preservadas
  integralmente no evento, sem modificação

---

## 14. Testes

### 14.1 Novos arquivos

| Arquivo                          | Testes | Cobertura                                         |
|----------------------------------|--------|---------------------------------------------------|
| `tests/test_pipeline_core.py`    | 80     | EventMetadata, Eventos, Policy, State, Session, Metrics |
| `tests/test_pipeline_flow.py`    | 71     | EventBus, Coordinator, Handlers, Engine, Fluxo, Compatibilidade |
| **Total**                        | **151**|                                                   |

### 14.2 Cobertura detalhada

**`test_pipeline_core.py` (80 testes):**
- `EventMetadata`: imutabilidade, hashability, `is_initial`,
  `has_metadata`, `to_dict`, `for_initial`, `for_next` (preserva
  correlation, encadeia causation), `for_session_event`, geradores
  customizados
- `Eventos`: 15 tipos, imutabilidade, hashability, properties
  (`event_type`, `event_id`, `correlation_id`, `causation_id`),
  `to_dict`, campos específicos de cada evento, herança de
  `PipelineEvent`
- `PipelinePolicy`: imutabilidade, defaults, `total_timeout_ms`,
  `is_segment_valid`, `is_query_valid`, `should_continue_on_error`,
  `retry_count_for`, backpressure preparado
- `PipelineState`: defaults, imutabilidade, `with_running`, `with_paused`,
  `with_current_segment`, `with_last_query`, `with_last_candidate`,
  `with_last_event`, `with_statistics`, `with_incremented_stat`,
  `reset`, `to_dict`, properties (`is_active`, `is_idle`,
  `is_processing`)
- `PipelineSession`: `create`, imutabilidade, `with_segment_processed`
  (com dedup de correlation), `with_query_processed`, `with_presentation`,
  `with_error`, `with_ended`, `has_correlation`, `unique_correlations`,
  `error_rate`, `presentation_rate`, `to_dict`
- `PipelineMetrics`: defaults, todos os `record_*`, `avg_latency`,
  `throughput`, `error_rate`, `drop_rate`, `presentation_success_rate`,
  `processing_success_rate`, `reset`, `to_dict`, latências por etapa

**`test_pipeline_flow.py` (71 testes):**
- `PipelineEventBus`: subscribe/publish, dispatch, múltiplos handlers,
  unsubscribe, unsubscribe_all, no subscribers, handlers tuple,
  event_count, history, history_types, clear_history, clear,
  subscribed_types, duplicate handler, non-callable raises, non-type
  raises
- `PipelineCoordinator`: register, non-handler raises, unregister,
  unregister_all, register_default_flow (8 handlers), partial flow
- `Handlers`: RecognitionHandler (com texto, com STT, preserva
  correlation), SearchHandler (empty query, com searcher), RankingHandler,
  IntelligenceHandler (sem engine, com engine), PresentationHandler
  (sem candidato, com Holyrics), FeedbackHandler (accepted/rejected),
  EvaluationHandler, ContextHandler, erro publica PipelineError
- `StreamingPipelineEngine`: start, start idempotent, stop, stop
  idempotent, pause/resume, process when not running (drop), process
  when paused (drop), process returns correlation, process publishes
  event, invalid duration (drop), reset
- **Fluxo completo**: sem dependências, correlation preservado, cadeia
  causal, com searcher (chega a PresentationRequested), múltiplos
  segmentos (correlations diferentes), métricas atualizadas, sessão
  atualizada, Evidences preservadas, pipeline vazio, pausado descarta,
  parado descarta, erro não crasha
- **Compatibilidade**: Intelligence sem pipeline, Context sem pipeline,
  Evidence Layer sem pipeline

### 14.3 Resultado final

```
2238 passed in 209.04s
```

- 2087 testes existentes: **todos passam** (zero regressão)
- 151 testes novos: **todos passam**

---

## 15. Exemplo Completo

```python
from pipeline import (
    PipelineEventBus, PipelinePolicy, PipelineSession,
    PipelineCoordinator, StreamingPipelineEngine,
    RecognitionHandler, SearchHandler, RankingHandler,
    IntelligenceHandler, PresentationHandler,
    FeedbackHandler, EvaluationHandler, ContextHandler,
)

# 1. Criar infraestrutura
bus = PipelineEventBus()
policy = PipelinePolicy()
session = PipelineSession.create(session_id="sermon-001")
engine = StreamingPipelineEngine(
    bus=bus, policy=policy, session=session, session_id="sermon-001")

# 2. Registrar handlers (com dependências opcionais)
coord = PipelineCoordinator(bus)
coord.register_default_flow({
    "recognition": RecognitionHandler(bus, policy, "sermon-001"),
    "search": SearchHandler(bus, policy, "sermon-001", searcher=my_searcher),
    "ranking": RankingHandler(bus, policy, "sermon-001"),
    "intelligence": IntelligenceHandler(
        bus, policy, "sermon-001",
        intelligence_engine=my_intelligence_engine,
        context=my_context,
    ),
    "presentation": PresentationHandler(
        bus, policy, "sermon-001", holyrics=my_holyrics),
    "feedback": FeedbackHandler(bus, policy, "sermon-001"),
    "evaluation": EvaluationHandler(bus, policy, "sermon-001"),
    "context": ContextHandler(bus, policy, "sermon-001"),
})

# 3. Iniciar pipeline
engine.start()

# 4. Processar segmentos
corr1 = engine.process(text="joão 3 16", confidence=0.9)
corr2 = engine.process(text="fé e esperança", confidence=0.85)

# 5. Verificar rastreabilidade
for ev in bus.history():
    print(f"{ev.event_type}: corr={ev.correlation_id[:8]}... "
          f"cause={ev.causation_id[:8] if ev.causation_id else None}...")

# 6. Verificar métricas
print(f"Segmentos: {engine.metrics.segments_received}")
print(f"Latência média: {engine.metrics.avg_latency_ms:.1f}ms")
print(f"Throughput: {engine.metrics.throughput_segments_per_min:.1f}/min")

# 7. Parar pipeline
engine.stop("end of sermon")
```

---

## 16. Confirmações

### 16.1 Compatibilidade
- ✅ Nenhuma API pública existente foi alterada
- ✅ Se o Pipeline não existir, todo o restante funciona normalmente
- ✅ Intelligence, Context, Feedback, Evaluation, Evidence Layer
  funcionam independentemente (testado em `TestCompatibility`)

### 16.2 Comportamento não alterado
- ✅ Searcher: não modificado
- ✅ Ranking: não modificado
- ✅ Knowledge Graph: não modificado
- ✅ Feedback Learning: não modificado
- ✅ Context Engine: não modificado
- ✅ Continuous Evaluation: não modificado
- ✅ Sermon Intelligence: não modificado
- ✅ Evidence Layer: não modificado
- ✅ Holyrics Client: não modificado
- ✅ Speech Recognition: não modificado
- ✅ Parser: não modificado
- ✅ LLM: não modificado
- ✅ Embeddings: não modificado

### 16.3 Testes
- ✅ Todos os 2087 testes existentes continuam passando
- ✅ 151 novos testes do Pipeline passam
- ✅ Total: 2238 testes, zero falhas, zero regressão

### 16.4 Restrições respeitadas
- ✅ Não implementou threads, asyncio, multiprocessing
- ✅ Não implementou filas externas (RabbitMQ, Kafka, Redis)
- ✅ Não implementou WebSocket, persistência, Replay, Dashboard
- ✅ Tudo síncrono
- ✅ Sem estado global
- ✅ Sem números mágicos (tudo em PipelinePolicy)
- ✅ DTOs imutáveis (frozen dataclass)
- ✅ Responsabilidade única
- ✅ Baixo acoplamento (duck-typing)
- ✅ Alta coesão
- ✅ Handlers independentes
- ✅ EventBus totalmente genérico
- ✅ Preparado para evolução futura (Replay, Backpressure)

---

## 17. Conclusão

A Fase 12 — Streaming Speech Pipeline foi implementada com sucesso
como uma infraestrutura determinística, orientada a eventos,
completamente rastreável, desacoplada e auditável. Principais
conquistas:

1. **Event-driven:** 8 Handlers não se chamam diretamente; toda
   comunicação via EventBus com 15 eventos tipados.
2. **Rastreabilidade completa:** `EventMetadata` com `event_id`,
   `correlation_id`, `causation_id`, `session_id` em todos os eventos.
3. **Zero regressão:** 2087 testes existentes passam sem modificação.
4. **Preservação de Evidences:** Pipeline nunca cria/modifica
   Evidences; apenas preserva as produzidas pelo Intelligence.
5. **Preparado para o futuro:** Replay (via history + cadeia causal)
   e Backpressure (via policy + métricas de descarte) prontos.
6. **Sem regra de negócio:** Pipeline apenas coordena; todas as
   decisões continuam nos módulos especializados.
7. **151 novos testes** cobrindo DTOs, eventos, bus, handlers,
   coordinator, engine, state, session, metrics, policy, fluxo
   completo e compatibilidade.
