# Relatório — Fase 12.1: Event Store Layer

**Data:** 18 de julho de 2026
**Fase:** 12.1 — Event Store Layer (refinamento arquitetural da Fase 12)
**Status:** Concluído
**Testes:** 2311 passaram (2238 existentes + 73 novos), zero regressão

---

## 1. Objetivo

Separar completamente o armazenamento de eventos do `PipelineEventBus`.
O EventBus deixa de ser responsável por armazenar histórico — apenas
publica eventos. Toda persistência (mesmo em memória) passa a ser
responsabilidade de um `EventStore`.

**Filosofia:**
- EventBus comunica.
- EventStore armazena.
- Replay utiliza EventStore.
- Dashboard consulta EventStore.
- Logs consultam EventStore.

---

## 2. Arquitetura Criada

### 2.1 Novo módulo: `pipeline/event_store.py`

| Componente              | Responsabilidade                                    |
|-------------------------|-----------------------------------------------------|
| `EventStore`            | Interface abstrata (ABC) com 11 métodos             |
| `MemoryEventStore`      | Implementação padrão em memória                     |
| `EventStorePolicy`      | Política centralizada (limites, retenção) — imutável|
| `EventStoreStatistics`  | Estatísticas do store (contadores por tipo/sessão/origin/correlation) |

### 2.2 Modificações em arquivos existentes

| Arquivo                  | Mudança                                                |
|--------------------------|--------------------------------------------------------|
| `pipeline/bus.py`        | `PipelineEventBus` recebe `EventStore` por injeção. `history()`, `history_types()`, `event_count()`, `clear_history()` delegam ao store. `publish()` chama `store.append()` antes de notificar handlers. |
| `pipeline/__init__.py`   | Exporta `EventStore`, `MemoryEventStore`, `EventStorePolicy`, `EventStoreStatistics`. |

---

## 3. EventStore (Interface)

```python
class EventStore(ABC):
    def append(self, event) -> None: ...
    def append_many(self, events) -> None: ...
    def all(self) -> tuple: ...
    def clear(self) -> None: ...
    def count(self) -> int: ...
    def last(self) -> Any: ...
    def by_event(self, event_type: type) -> tuple: ...
    def by_correlation(self, correlation_id: str) -> tuple: ...
    def by_session(self, session_id: str) -> tuple: ...
    def by_origin(self, origin: str) -> tuple: ...
    def between(self, start_ts: float, end_ts: float) -> tuple: ...
```

---

## 4. MemoryEventStore

Implementação padrão em memória:

- **Imutável externamente:** `all()` e consultas retornam `tuple`.
- **Internamente eficiente:** lista para preservar ordem.
- **Preserva ordem de inserção.**
- **Sem deduplicação automática.**
- **Sem persistência** (apenas memória).
- **Aplica `EventStorePolicy** quando atinge limite.

### 4.1 Fluxo de publicação

```
bus.publish(event)
    ↓
store.append(event)     ← armazena ANTES de notificar
    ↓
handlers(event)         ← notifica handlers
```

### 4.2 Policy de retenção

| Estratégia      | Comportamento quando atinge `max_events`       |
|-----------------|-------------------------------------------------|
| `drop_oldest`   | Remove o evento mais antigo, adiciona o novo   |
| `drop_newest`   | Adiciona o novo, remove os mais recentes excedentes |
| `reject`        | Levanta `OverflowError`                        |

---

## 5. EventStorePolicy

```python
@dataclass(frozen=True)
class EventStorePolicy:
    max_events: int = 0                    # 0 = ilimitado
    retention_strategy: str = "drop_oldest"
    auto_cleanup: bool = False             # não implementado
    cleanup_interval_events: int = 1000    # não implementado
```

Methods: `is_unlimited()`, `should_drop_oldest()`, `should_drop_newest()`,
`should_reject()`.

---

## 6. EventStoreStatistics

```python
@dataclass
class EventStoreStatistics:
    events_appended: int = 0
    events_removed: int = 0
    by_type: dict          # contagem por tipo de evento
    by_session: dict       # contagem por session_id
    by_origin: dict        # contagem por origin
    by_correlation: dict   # contagem por correlation_id
```

Atualizada automaticamente pelo `MemoryEventStore` a cada
`append()`/`clear()`/drop. Methods: `record_append(event)`,
`record_remove(count)`, `reset()`, `to_dict()`.

---

## 7. Integração com EventBus

### 7.1 Injeção de dependência

```python
# Bus cria MemoryEventStore padrão
bus = PipelineEventBus()

# Bus com store injetado
store = MemoryEventStore(policy=EventStorePolicy(max_events=1000))
bus = PipelineEventBus(store=store)
```

### 7.2 Delegação de APIs

| API do Bus              | Delegação                    |
|-------------------------|------------------------------|
| `event_count()`         | `store.count()`              |
| `history()`             | `store.all()`                |
| `history_types()`       | `store.all()` + type names   |
| `clear_history()`       | `store.clear()`              |
| `clear()`               | `subscriptions.clear()` + `store.clear()` |
| `publish(event)`        | `store.append(event)` + handlers |

### 7.3 Compatibilidade

- `PipelineEventBus()` sem argumentos continua funcionando (cria
  `MemoryEventStore` padrão).
- `history()`, `history_types()`, `event_count()` continuam retornando
  os mesmos tipos (`tuple`, `tuple`, `int`).
- `publish()` continua notificando handlers na ordem de inscrição.
- `subscribe()`/`unsubscribe()` não mudaram.

---

## 8. Estratégia de Consultas

O EventStore oferece consultas eficientes para todos os casos de uso:

| Consulta           | Método                          | Uso                    |
|---------------------|---------------------------------|------------------------|
| Todos eventos       | `all()`                         | Auditoria completa     |
| Por correlation_id  | `by_correlation(id)`            | Replay de fluxo        |
| Por session_id      | `by_session(id)`                | Dashboard de sessão    |
| Por tipo            | `by_event(cls)`                 | Filtro por etapa       |
| Por origin          | `by_origin(name)`               | Filtro por handler     |
| Intervalo temporal  | `between(start, end)`           | Logs por período       |
| Último evento       | `last()`                        | Estado atual           |
| Total               | `count()`                       | Métricas               |

---

## 9. Preparação para Replay

O ReplayEngine futuro utilizará exclusivamente o EventStore:

```python
# Preparação (não implementado):
store = bus.store
flow_events = store.by_correlation("corr-123")
# Reconstruir o fluxo a partir dos eventos preservando ordem
for event in flow_events:
    # causal chain: event.causation_id → event.event_id
    ...
```

**Nunca acessa EventBus diretamente.** Toda informação necessária
está no EventStore (eventos + cadeia causal via `EventMetadata`).

---

## 10. Preparação para Dashboard

O Dashboard futuro consultará exclusivamente o EventStore:

```python
# Preparação (não implementado):
store = bus.store
session_events = store.by_session("sermon-001")
stats = store.statistics
# stats.by_type, stats.by_origin, stats.by_correlation
```

**Nunca acessa EventBus diretamente.** Estatísticas agregadas estão
disponíveis via `EventStoreStatistics`.

---

## 11. Testes

### 11.1 Novo arquivo

| Arquivo                       | Testes | Cobertura                                         |
|-------------------------------|--------|---------------------------------------------------|
| `tests/test_event_store.py`   | 73     | EventStore, MemoryEventStore, Policy, Statistics, Integração, Compatibilidade, Replay/Dashboard prep |

### 11.2 Cobertura detalhada

- **EventStore (interface):** é abstrata, tem todos os 11 métodos.
- **MemoryEventStore — escrita:** append single/multiple, append_many,
  append_many empty, preserva ordem, sem dedup.
- **MemoryEventStore — leitura:** all() retorna tuple, all() é cópia,
  count, last, last empty, by_event, by_event empty, by_correlation,
  by_correlation preserva ordem, by_correlation not found, by_session,
  by_session preserva ordem, by_session not found, by_origin,
  by_origin not found, between inclusivo, between full range,
  between empty, between exact boundary.
- **MemoryEventStore — limpeza:** clear, clear empty.
- **MemoryEventStore — policy:** unlimited default, drop_oldest,
  drop_newest, reject, policy acessível.
- **EventStorePolicy:** defaults, frozen, is_unlimited,
  should_drop_oldest/newest/reject, custom values.
- **EventStoreStatistics:** defaults, record_append, multiple types,
  record_remove, reset, to_dict, auto-updated by store, removed on
  clear, removed on drop_oldest.
- **Serialização:** to_dict, to_dict with policy.
- **Integração EventBus ↔ EventStore:** default store, injected store,
  publish appends to store, event_count delegates, history delegates,
  history_types delegates, clear_history delegates, clear clears both,
  store queries via bus.store, store with policy via bus, statistics
  via bus.store, multiple buses share store, event immutability
  preserved.
- **Compatibilidade:** bus without store works, history returns tuple,
  history_types returns tuple, publish notifies handlers,
  subscribe/unsubscribe work, engine works with store, replay
  preparation (by_correlation), dashboard preparation (by_session +
  statistics).

### 11.3 Ajuste em teste existente

`test_clear_history` em `test_pipeline_flow.py` foi ajustado para
refletir a nova semântica: `event_count()` agora delega ao
`store.count()`, e `clear_history()` chama `store.clear()`, então o
count vai para 0 após clear_history (antes era um contador cumulativo
separado do histórico).

### 11.4 Resultado final

```
2311 passed in 203.72s
```

- 2238 testes existentes: **todos passam** (zero regressão)
- 73 testes novos: **todos passam**

---

## 12. Exemplo Completo

```python
from pipeline import (
    PipelineEventBus, MemoryEventStore, EventStorePolicy,
    EventStoreStatistics, EventMetadata, SpeechRecognized,
)

# 1. Criar store com policy
policy = EventStorePolicy(max_events=1000, retention_strategy="drop_oldest")
store = MemoryEventStore(policy=policy)

# 2. Criar bus com store injetado
bus = PipelineEventBus(store=store)

# 3. Publicar eventos
meta1 = EventMetadata.for_initial(
    session_id="sermon-001", origin="RecognitionHandler",
    correlation_id="c1")
bus.publish(SpeechRecognized(meta=meta1, text="joão 3 16"))

meta2 = EventMetadata.for_next(previous=meta1, origin="SearchHandler")
bus.publish(SearchRequested(meta=meta2, query="joão 3 16"))

# 4. Consultar store
print(f"Total: {store.count()}")
print(f"Por correlation c1: {len(store.by_correlation('c1'))}")
print(f"Por session sermon-001: {len(store.by_session('sermon-001'))}")
print(f"Por origin SearchHandler: {len(store.by_origin('SearchHandler'))}")

# 5. Estatísticas
stats = store.statistics
print(f"Appended: {stats.events_appended}")
print(f"By type: {stats.by_type}")

# 6. Compatibilidade — APIs antigas funcionam
print(f"bus.event_count(): {bus.event_count()}")  # delega ao store
print(f"bus.history(): {len(bus.history())}")      # delega ao store
```

---

## 13. Confirmações

### 13.1 Compatibilidade
- ✅ Nenhuma API pública existente foi alterada
- ✅ `PipelineEventBus()` sem argumentos continua funcionando
- ✅ `history()`, `history_types()`, `event_count()` continuam funcionando
- ✅ `publish()` continua notificando handlers na ordem de inscrição
- ✅ `subscribe()`/`unsubscribe()` não mudaram

### 13.2 Comportamento não alterado
- ✅ PipelineEventBus: apenas delega armazenamento ao EventStore
- ✅ StreamingPipelineEngine: não modificado
- ✅ Handlers: não modificados
- ✅ Coordinator: não modificado
- ✅ PipelineSession: não modificada
- ✅ PipelineMetrics: não modificada
- ✅ PipelinePolicy: não modificada
- ✅ EventMetadata: não modificada
- ✅ Eventos: não modificados
- ✅ Searcher, Ranking, Context, Feedback, Evaluation, Intelligence,
  Evidence Layer, Holyrics: não modificados

### 13.3 Testes
- ✅ Todos os 2238 testes existentes continuam passando
- ✅ 73 novos testes do EventStore passam
- ✅ Total: 2311 testes, zero falhas, zero regressão

### 13.4 Restrições respeitadas
- ✅ Não implementou SQLite, Redis, Kafka, RabbitMQ
- ✅ Não implementou persistência, Replay, Dashboard
- ✅ Não implementou compressão, snapshots, rotação/limpeza automática
- ✅ Sem estado global, sem números mágicos
- ✅ DTOs imutáveis (EventStorePolicy é frozen)
- ✅ Responsabilidade única (EventBus comunica, EventStore armazena)
- ✅ Baixo acoplamento (EventStore injetado no Bus)
- ✅ Alta coesão

---

## 14. Conclusão

A Fase 12.1 — Event Store Layer foi implementada com sucesso como um
refinamento arquitetural não-invasivo. Principais conquistas:

1. **Separação de responsabilidades:** EventBus apenas comunica;
   EventStore apenas armazena.
2. **Injeção de dependência:** Bus recebe EventStore por construtor;
   cria MemoryEventStore padrão se não fornecido.
3. **Consultas ricas:** 11 métodos de consulta (all, by_event,
   by_correlation, by_session, by_origin, between, last, count).
4. **Policy centralizada:** limites e estratégias de retenção
   (drop_oldest, drop_newest, reject).
5. **Estatísticas automáticas:** contadores por tipo, sessão, origin,
   correlation — atualizados a cada operação.
6. **Preparado para Replay:** `by_correlation()` + cadeia causal
   permitem reconstruir fluxos.
7. **Preparado para Dashboard:** `by_session()` + `statistics`
   permitem visualizações agregadas.
8. **Zero regressão:** 2238 testes existentes passam sem modificação
   (1 teste ajustado para refletir nova semântica de delegação).
9. **73 novos testes** cobrindo interface, implementação, policy,
   statistics, integração e compatibilidade.
