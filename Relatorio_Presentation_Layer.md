# Relatório — Presentation Layer

**Data:** 18 de julho de 2026
**Fase:** Presentation Layer
**Status:** Concluído
**Testes:** 2485 passaram (2311 existentes + 174 novos), zero regressão

---

## 1. Objetivo

Criar uma camada de apresentação completamente desacoplada entre o
Core do AI Lyrics e qualquer tecnologia de interface futura (REST,
WebSocket, CLI, Dashboard, Replay, ferramentas de diagnóstico).

**Filosofia:**
- O Core conhece apenas domínio.
- A Presentation Layer conhece apenas apresentação.
- Ela nunca implementa regra de negócio.
- Nunca altera estado interno.
- Nunca decide, executa Search, Ranking, interpreta Evidence, modifica
  Sessions ou altera Pipeline.
- Ela apenas adapta informações.

---

## 2. Arquitetura Criada

### 2.1 Novo módulo: `presentation/`

```
presentation/
├── __init__.py          # Exporta todos os componentes públicos
├── dtos.py              # 9 DTOs de apresentação (frozen dataclass)
├── dtos_domain.py       # 6 DTOs de domínio (frozen dataclass)
├── mappers.py           # 14 Mappers (Core → DTO, one-way)
├── snapshots.py         # 6 Snapshots + SnapshotFactory
├── observers.py         # 5 Observers (Base + 4 concretos)
├── services.py          # 7 Services (somente leitura)
└── adapters.py          # 6 Adapters (contratos ABC)
```

### 2.2 Componentes

| Componente       | Quantidade | Responsabilidade                         |
|------------------|------------|------------------------------------------|
| DTOs             | 15         | Imutáveis, serializáveis, independentes  |
| Mappers          | 14         | Core → DTO (one-way, nunca inverso)      |
| Snapshots        | 6 + Factory| Estado do sistema em um momento          |
| Observers        | 5          | Observam EventBus, atualizam snapshots   |
| Services         | 7          | Somente leitura, consultam Core          |
| Adapters         | 6          | Contratos ABC para futuras interfaces    |

---

## 3. DTOs (15)

### 3.1 DTOs de Apresentação (9)

| DTO                    | Campos principais                                     |
|------------------------|-------------------------------------------------------|
| `EventMetadataDTO`     | event_id, correlation_id, causation_id, session_id, timestamp, origin, metadata |
| `EventDTO`             | event_type, meta (EventMetadataDTO), payload (dict)   |
| `PipelineStatusDTO`    | running, paused, is_active, is_idle, is_processing, last_query, last_candidate_id, last_event_type, statistics |
| `SessionDTO`           | session_id, started_at, ended_at, is_active, duration_s, processed_segments, processed_queries, presentations, errors, error_rate, correlation_ids |
| `MetricsDTO`           | segments_received/processed/dropped, queries_processed, presentations_executed/failed, errors_total/recoverable/fatal, avg_latency_ms, throughput, error_rate, drop_rate |
| `ConfigurationDTO`     | mode, holyrics, stt, llm, search, state, cache, confidence, log, audio, pipeline_policy |
| `HealthDTO`            | component, status, message, details                   |
| `DiagnosticDTO`        | component, category, available, info, warnings, errors |
| `LogDTO`               | timestamp, level, component, message, correlation_id, session_id |

### 3.2 DTOs de Domínio (6)

| DTO                    | Campos principais                                     |
|------------------------|-------------------------------------------------------|
| `CandidateDTO`         | candidate_id, base_score, book, chapter, verse, display |
| `EvidenceDTO`          | id, type, description, value, weight, confidence, contribution, metadata |
| `SignalDTO`            | signal_type, value, weight, contribution, explanation, evidences |
| `ScoreDTO`             | candidate_id, base_score, final_score, *_contribution, confidence_level, signals, explanation |
| `RecommendationDTO`    | query, best_candidate_id, confidence_level, explanation, has_candidates, scores, ranking |
| `PresentationDTO`      | candidate_id, book_id, chapter, verse, version, status, verse_id, presented |

**Todos:** frozen dataclass, serializáveis via `to_dict()`, independentes
do Core (nenhum expõe objetos internos do domínio).

---

## 4. Mappers (14)

| Mapper                  | Conversão                                    |
|-------------------------|----------------------------------------------|
| `PipelineMapper`        | PipelineState → PipelineStatusDTO            |
| `SessionMapper`         | PipelineSession → SessionDTO                 |
| `MetricsMapper`         | PipelineMetrics → MetricsDTO                 |
| `EventMapper`           | PipelineEvent → EventDTO, EventMetadata → DTO |
| `EvidenceMapper`        | Evidence → EvidenceDTO                       |
| `SignalMapper`          | IntelligenceSignal → SignalDTO               |
| `ScoreMapper`           | IntelligenceScore → ScoreDTO                 |
| `RecommendationMapper`  | IntelligenceRecommendation → RecommendationDTO |
| `CandidateMapper`       | CandidateInfo → CandidateDTO                 |
| `PresentationMapper`    | PresentationRequested/Completed → PresentationDTO |
| `ConfigurationMapper`   | Config → ConfigurationDTO                    |
| `HealthMapper`          | Constrói HealthDTO (healthy/degraded/unhealthy/unknown) |
| `DiagnosticMapper`      | Constrói DiagnosticDTO                       |
| `LogMapper`             | Constrói LogDTO, from_event                  |

**Regra fundamental:** NUNCA converter no sentido inverso (DTO → Core).
Mappers são one-way: Core → Presentation DTO.

---

## 5. Snapshots (6 + Factory)

| Snapshot                | Conteúdo                                     |
|-------------------------|----------------------------------------------|
| `PipelineSnapshot`      | status + session + metrics + last_event      |
| `SessionSnapshot`       | session DTO                                  |
| `MetricsSnapshot`       | metrics DTO                                  |
| `HealthSnapshot`        | tuple de HealthDTO + all_healthy             |
| `ConfigurationSnapshot` | configuration DTO                            |
| `EventSnapshot`         | tuple de EventDTO + event_count + event_types |

`SnapshotFactory` cria snapshots a partir de objetos do Core usando
Mappers internamente.

**Todos:** frozen dataclass, imutáveis, serializáveis via `to_dict()`.

---

## 6. Observers (5)

| Observer           | Observa                              | Mantém                  |
|--------------------|--------------------------------------|-------------------------|
| `BaseObserver`     | Base (subscribe_to all types)        | last_snapshot           |
| `EventObserver`    | Todos os eventos                     | Histórico de EventDTOs  |
| `PipelineObserver` | Started/Stopped/Paused/Resumed/Error | running, paused, errors |
| `MetricsObserver`  | Todos os eventos                     | counts_by_type, total   |
| `SessionObserver`  | Todos os eventos                     | events por session_id   |

**Regras:**
- Observers NUNCA publicam eventos.
- Observers NUNCA alteram estado do Core.
- Observers apenas leem eventos e atualizam snapshots internos.
- `subscribe_to(bus)` inscreve em todos os tipos de evento.

---

## 7. Services (7)

| Service                              | Consulta                     |
|--------------------------------------|------------------------------|
| `PipelinePresentationService`        | status, session, metrics, snapshot |
| `SessionPresentationService`         | session DTO, properties      |
| `MetricsPresentationService`         | metrics DTO, properties      |
| `ConfigurationPresentationService`   | configuration DTO            |
| `HealthPresentationService`          | health de 8 componentes      |
| `DiagnosticPresentationService`      | diagnóstico de 7 componentes |
| `EventPresentationService`           | eventos (all, by_correlation, by_session, by_type, between, logs) |

**Regras:**
- Services NUNCA modificam estado do Core.
- Services NUNCA executam regra de negócio.
- Services NUNCA publicam eventos.
- Services apenas consultam e adaptam via Mappers.

---

## 8. Adapters (6)

| Adapter             | Contrato para          | Métodos principais                          |
|---------------------|------------------------|---------------------------------------------|
| `BaseAdapter`       | Base (recebe Services) | properties para todos os services           |
| `RestAdapter`       | API REST               | get_pipeline_status, get_session, get_metrics, get_configuration, get_health, get_events, get_diagnostics |
| `WebSocketAdapter`  | WebSocket              | serialize_snapshot, serialize_event, serialize_metrics, serialize_health |
| `CliAdapter`        | CLI                    | format_status, format_metrics, format_session, format_events, format_health, format_configuration |
| `DashboardAdapter`  | Dashboard              | get_dashboard_data, get_session_history, get_correlation_flow |
| `ReplayAdapter`     | Replay                 | get_replay_events, get_replay_sessions, get_replay_correlations |

**Todos ABC (abstract).** Nenhum implementa comunicação real — apenas
contratos. Futuras implementações (FastAPI, WebSocket server, CLI
tool, Dashboard web) herdam destes adapters.

---

## 9. Estratégia de Adaptação

```
Core (Pipeline, Intelligence, Config, etc.)
    ↓
Mappers (one-way: Core → DTO)
    ↓
DTOs (imutáveis, serializáveis)
    ↓
Services (somente leitura)
    ↓
Adapters (contratos para REST, WS, CLI, Dashboard, Replay)
    ↓
Futuras Interfaces (não implementadas)
```

**Fluxo:**
1. Core produz objetos (PipelineState, PipelineSession, etc.).
2. Mappers convertem para DTOs imutáveis.
3. Services expõem DTOs e Snapshots.
4. Adapters usam Services para servir interfaces futuras.
5. Interfaces (REST, WS, CLI, Dashboard, Replay) implementam Adapters.

---

## 10. Estratégia de Observação

```
EventBus
    ↓ publish(event)
Observers (inscritos via subscribe_to)
    ↓ on_event(event)
EventMapper.to_dto(event)
    ↓
Snapshots internos (atualizados)
    ↓
Services consultam snapshots
```

**Observers são consumidores do EventBus. Nunca produtores.**
- `EventObserver`: mantém histórico de EventDTOs.
- `PipelineObserver`: rastreia running/paused/errors.
- `MetricsObserver`: conta eventos por tipo.
- `SessionObserver`: rastreia eventos por session_id.

---

## 11. Preparação para REST

`RestAdapter` define 7 endpoints:
- `GET /api/pipeline/status` → PipelineStatusDTO
- `GET /api/session` → SessionDTO
- `GET /api/metrics` → MetricsDTO
- `GET /api/configuration` → ConfigurationDTO
- `GET /api/health` → HealthSnapshot
- `GET /api/events?correlation_id=...` → EventSnapshot
- `GET /api/diagnostics` → tuple de DiagnosticDTO

Futura implementação FastAPI herda de `RestAdapter` e implementa
os métodos abstract.

---

## 12. Preparação para WebSocket

`WebSocketAdapter` define 4 métodos de serialização:
- `serialize_snapshot(PipelineSnapshot) → str` (JSON)
- `serialize_event(EventDTO) → str`
- `serialize_metrics(MetricsDTO) → str`
- `serialize_health(HealthSnapshot) → str`

Futuro servidor WebSocket usa `EventObserver` para receber eventos
em tempo real e `serialize_event()` para enviá-los aos clientes.

---

## 13. Preparação para Dashboard

`DashboardAdapter` define 3 métodos:
- `get_dashboard_data() → dict` (todos os dados em um request)
- `get_session_history(session_id) → EventSnapshot`
- `get_correlation_flow(correlation_id) → EventSnapshot`

Futuro Dashboard web usa `HealthPresentationService` para cards de
saúde, `MetricsPresentationService` para gráficos, e
`EventPresentationService` para timeline de eventos.

---

## 14. Preparação para Replay

`ReplayAdapter` define 3 métodos:
- `get_replay_events(correlation_id) → EventSnapshot`
- `get_replay_sessions() → tuple` (session_ids disponíveis)
- `get_replay_correlations(session_id) → tuple`

Futuro ReplayEngine usa `EventPresentationService.get_events_by_correlation()`
para obter eventos de um fluxo e reconstruir a cadeia causal.

---

## 15. Preparação para CLI

`CliAdapter` define 6 métodos de formatação:
- `format_status(PipelineStatusDTO) → str`
- `format_metrics(MetricsDTO) → str`
- `format_session(SessionDTO) → str`
- `format_events(tuple) → str`
- `format_health(HealthSnapshot) → str`
- `format_configuration(ConfigurationDTO) → str`

Futura CLI (Click, Typer, argparse) usa estes métodos para exibir
informações no terminal.

---

## 16. Testes

### 16.1 Novos arquivos

| Arquivo                                    | Testes | Cobertura                                         |
|--------------------------------------------|--------|---------------------------------------------------|
| `tests/test_presentation_dtos.py`          | 56     | Todos os 15 DTOs (imutabilidade, to_dict, properties, defaults) |
| `tests/test_presentation_mappers.py`       | 55     | Todos os 14 Mappers (conversão Core → DTO, properties, edge cases) |
| `tests/test_presentation_services.py`      | 63     | Snapshots, Observers, Services, Adapters, Integração, Compatibilidade |
| **Total**                                  | **174**|                                                   |

### 16.2 Cobertura detalhada

**`test_presentation_dtos.py` (56 testes):**
- EventMetadataDTO: frozen, is_initial, to_dict, defaults
- EventDTO: frozen, properties, to_dict, defaults
- PipelineStatusDTO: frozen, to_dict
- SessionDTO: frozen, to_dict
- MetricsDTO: frozen, to_dict
- ConfigurationDTO: frozen, to_dict, optional fields
- HealthDTO: frozen, is_healthy/degraded/unhealthy, to_dict
- DiagnosticDTO: frozen, has_warnings/errors, to_dict
- LogDTO: frozen, to_dict
- CandidateDTO: frozen, to_dict
- EvidenceDTO: frozen, to_dict
- SignalDTO: frozen, has_evidences, evidence_count, to_dict
- ScoreDTO: frozen, total_contribution, signal_count, to_dict
- RecommendationDTO: frozen, best_score, candidate_count, to_dict
- PresentationDTO: frozen, to_dict

**`test_presentation_mappers.py` (55 testes):**
- PipelineMapper: to_status_dto (running, paused, idle, with_segment)
- SessionMapper: to_dto (active, ended)
- MetricsMapper: to_dto (with data, empty)
- EventMapper: to_metadata_dto, to_dto, preserves correlation, to_dto_many
- EvidenceMapper: to_dto, to_dto_many
- SignalMapper: to_dto, with evidences
- ScoreMapper: to_dto, to_dto_many
- RecommendationMapper: to_dto (with candidates, empty)
- CandidateMapper: to_dto, to_dto_many
- PresentationMapper: from_requested, from_completed
- ConfigurationMapper: to_dto (with/without pipeline_policy)
- HealthMapper: healthy, degraded, unhealthy, unknown, from_state, with_details
- DiagnosticMapper: to_dto, defaults
- LogMapper: to_dto, from_event

**`test_presentation_services.py` (63 testes):**
- Snapshots: frozen, to_dict, HealthSnapshot (all_healthy, component),
  EventSnapshot, SnapshotFactory (pipeline, session, metrics, health, event)
- EventObserver: observe, last_event, by_correlation, by_type, snapshot,
  clear, max_events_limit
- PipelineObserver: started, stopped, paused/resumed, error, health, reset
- MetricsObserver: counts, event_types, reset
- SessionObserver: tracking, events_for_session, current_session
- PipelinePresentationService: status, session, metrics, snapshot,
  is_running, is_paused
- SessionPresentationService: session, snapshot, properties, has_correlation
- MetricsPresentationService: metrics, snapshot, properties
- ConfigurationPresentationService: configuration, snapshot
- HealthPresentationService: pipeline (active/paused/stopped/no_state),
  event_bus, event_store, all_components, snapshot, component by name
- DiagnosticPresentationService: microphone, gpu, pipeline (with/without
  state), event_store, event_bus, all_diagnostics, component by name
- EventPresentationService: all_events, count, last_event, by_correlation,
  by_session, by_type, between, snapshot, snapshot with correlation, logs
- Adapters: all 5 are abstract (cannot instantiate), have all methods,
  BaseAdapter properties
- Full Integration: Pipeline + Observers + Services
- Compatibility: Core works without Presentation, Intelligence works
  without Presentation, Presentation does not modify Core

### 16.3 Resultado final

```
2485 passed in 211.64s
```

- 2311 testes existentes: **todos passam** (zero regressão)
- 174 testes novos: **todos passam**

---

## 17. Exemplo Completo

```python
from pipeline import (
    PipelineEventBus, PipelinePolicy, PipelineSession, PipelineState,
    PipelineMetrics, EventMetadata, SpeechRecognized, SpeechSegmentReceived,
)
from presentation import (
    # Observers
    EventObserver, PipelineObserver, MetricsObserver, SessionObserver,
    # Services
    PipelinePresentationService, EventPresentationService,
    HealthPresentationService, DiagnosticPresentationService,
    # Snapshots
    SnapshotFactory,
)

# 1. Setup pipeline
bus = PipelineEventBus()
state = PipelineState(running=True)
session = PipelineSession.create(session_id="sermon-001")
metrics = PipelineMetrics()

# 2. Register observers (observam EventBus, nunca publicam)
event_obs = EventObserver()
pipe_obs = PipelineObserver()
metrics_obs = MetricsObserver()
session_obs = SessionObserver()
for obs in [event_obs, pipe_obs, metrics_obs, session_obs]:
    obs.subscribe_to(bus)

# 3. Publish events
meta1 = EventMetadata.for_initial(
    session_id="sermon-001", origin="Engine",
    correlation_id="c1")
bus.publish(SpeechSegmentReceived(meta=meta1, duration_ms=1000))
meta2 = EventMetadata.for_next(previous=meta1, origin="RecognitionHandler")
bus.publish(SpeechRecognized(meta=meta2, text="joão 3 16", confidence=0.9))

# 4. Consultar via Services
pipe_svc = PipelinePresentationService(state, session, metrics, bus)
event_svc = EventPresentationService(bus)
health_svc = HealthPresentationService(state, bus, bus.store)
diag_svc = DiagnosticPresentationService(state, bus, bus.store)

# 5. Obter DTOs
status = pipe_svc.get_status()       # PipelineStatusDTO
session_dto = pipe_svc.get_session() # SessionDTO
metrics_dto = pipe_svc.get_metrics() # MetricsDTO

# 6. Obter Snapshot completo
snapshot = pipe_svc.get_snapshot()   # PipelineSnapshot
print(f"Running: {snapshot.status.running}")
print(f"Last event: {snapshot.last_event.event_type}")

# 7. Consultar eventos (para Replay)
c1_events = event_svc.get_events_by_correlation("c1")
print(f"Events in c1: {len(c1_events)}")

# 8. Consultar health (para Dashboard)
health = health_svc.get_snapshot()
print(f"Components: {health.component_count}")
print(f"All healthy: {health.all_healthy}")

# 9. Consultar diagnostics
for d in diag_svc.all_diagnostics():
    print(f"  {d.component}: available={d.available}")
```

---

## 18. Confirmações

### 18.1 Compatibilidade
- ✅ Nenhum componente existente depende da Presentation Layer
- ✅ Ela depende do Core. Nunca o contrário.
- ✅ Se a Presentation Layer não existir, todo o restante funciona
  (testado em `TestCompatibility`)
- ✅ Intelligence, Pipeline, EventBus, EventStore funcionam
  independentemente

### 18.2 Comportamento não alterado
- ✅ Speech Recognition: não modificado
- ✅ Pipeline: não modificado
- ✅ EventBus: não modificado
- ✅ EventStore: não modificado
- ✅ PipelineEngine: não modificado
- ✅ Handlers: não modificados
- ✅ Searcher: não modificado
- ✅ Ranking: não modificado
- ✅ Knowledge Graph: não modificado
- ✅ Feedback Learning: não modificado
- ✅ Continuous Evaluation: não modificado
- ✅ Context Engine: não modificado
- ✅ Sermon Intelligence: não modificado
- ✅ Evidence Layer: não modificado
- ✅ Holyrics: não modificado

### 18.3 Testes
- ✅ Todos os 2311 testes existentes continuam passando
- ✅ 174 novos testes da Presentation Layer passam
- ✅ Total: 2485 testes, zero falhas, zero regressão

### 18.4 Restrições respeitadas
- ✅ Não implementou FastAPI, REST, WebSocket, SSE, React, Tailwind
- ✅ Não implementou autenticação, persistência, Replay, Dashboard, Logs
- ✅ Sem estado global, sem números mágicos, sem lógica de negócio
- ✅ DTOs imutáveis (frozen dataclass)
- ✅ Responsabilidade única
- ✅ Baixo acoplamento (Presentation depende do Core, nunca o contrário)
- ✅ Alta coesão
- ✅ Mappers one-way (Core → DTO, nunca inverso)
- ✅ Services somente leitura
- ✅ Observers nunca publicam eventos
- ✅ Adapters são contratos (ABC), sem implementação

---

## 19. Conclusão

A Presentation Layer foi implementada com sucesso como uma camada
completamente desacoplada entre o Core do AI Lyrics e qualquer
tecnologia de interface futura. Principais conquistas:

1. **15 DTOs imutáveis** cobrindo todos os aspectos do sistema
   (pipeline, sessão, métricas, eventos, configuração, health,
   diagnóstico, logs, candidatos, evidências, sinais, scores,
   recomendações, apresentações).
2. **14 Mappers one-way** convertendo Core → DTO sem nunca inverter.
3. **6 Snapshots + Factory** representando estado do sistema em
   determinados momentos.
4. **5 Observers** observando EventBus e atualizando snapshots
   internos (nunca publicando eventos).
5. **7 Services somente leitura** consultando Core via Mappers.
6. **6 Adapters ABC** definindo contratos para REST, WebSocket,
   CLI, Dashboard, Replay.
7. **Zero regressão:** 2311 testes existentes passam sem modificação.
8. **174 novos testes** cobrindo DTOs, Mappers, Snapshots, Observers,
   Services, Adapters, integração completa e compatibilidade.
9. **Preparado para evolução:** futuras interfaces (FastAPI, WebSocket
   server, CLI tool, Dashboard web, ReplayEngine) herdam dos Adapters
   e usam os Services — sem qualquer modificação no Core.
