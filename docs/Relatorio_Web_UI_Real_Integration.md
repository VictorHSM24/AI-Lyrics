# Relatório — Web UI Real Integration

**Data:** 18 de julho de 2026
**Fase:** Real Integration (substituição de stubs por comunicação real)
**Status:** Concluído
**Testes Frontend:** 273 passaram (Vitest) — 38 novos + 235 existentes
**Testes Backend:** 2517 passaram (pytest) — 32 novos + 2485 existentes, zero regressão
**Build:** Vite production build OK (258 KB JS, 19 KB CSS)

---

## 1. Objetivo

Implementar a primeira integração real entre frontend e backend
do AI Lyrics, validando toda a arquitetura consolidada durante
o Architecture Freeze.

**Nenhuma camada arquitetural foi alterada.** Apenas as
implementações stub foram substituídas por implementações reais.

---

## 2. Estrutura FastAPI Criada

### 2.1 Diretórios

```
api/
├── __init__.py
├── app.py                    # create_app() + singleton app
├── routers/
│   ├── __init__.py           # ALL_ROUTERS
│   ├── health.py             # /health, /health/live, /health/ready
│   ├── info.py               # /info
│   ├── pipeline.py           # /pipeline/status, /session, /metrics, /snapshot
│   ├── session.py            # /session/current
│   ├── metrics.py            # /metrics
│   ├── configuration.py      # /configuration
│   ├── diagnostics.py        # /diagnostics
│   └── events.py             # /events, /by-correlation, /by-session, /snapshot
├── schemas/
│   ├── __init__.py
│   └── models.py             # 15+ modelos Pydantic + versioned()
├── dependencies/
│   ├── __init__.py
│   └── services.py           # 7 dependencies (Presentation Services)
├── websocket/
│   ├── __init__.py
│   └── events.py             # /ws/events + ConnectionManager + EventPublisher
├── startup/
│   ├── __init__.py
│   └── composition.py        # CompositionRoot + create_composition_root()
├── health/
│   ├── __init__.py
│   └── checks.py             # check_api_health()
├── middlewares/
│   ├── __init__.py
│   └── setup.py              # CORS + RequestLoggingMiddleware
└── exceptions/
    ├── __init__.py
    └── handlers.py           # 404, 500, Exception → PresentationErrorModel
```

### 2.2 Composition Root

O `api/startup/composition.py` é o ÚNICO lugar que conhece tanto
o Core quanto a Presentation Layer:

```python
CompositionRoot(
    bus=PipelineEventBus,
    store=MemoryEventStore,
    state=PipelineState,
    session=PipelineSession,
    metrics=PipelineMetrics,
    policy=PipelinePolicy,
    pipeline_service=PipelinePresentationService,
    session_service=SessionPresentationService,
    metrics_service=MetricsPresentationService,
    configuration_service=ConfigurationPresentationService,
    health_service=HealthPresentationService,
    diagnostic_service=DiagnosticPresentationService,
    event_service=EventPresentationService,
)
```

A API consome apenas `CompositionRoot` — nunca o Core diretamente.

---

## 3. Estrutura do Transport REST

### 3.1 Arquivo

`frontend/src/sdk/transports/rest.ts`

### 3.2 Características

- Usa Fetch API nativa do browser (sem dependências externas)
- Mapeamento método SDK → endpoint REST (15 mapeamentos)
- Timeout via `AbortController`
- Cancelamento via `CancelToken` (integrado com `AbortController`)
- Tratamento de erros HTTP → `PresentationError`
- Headers configuráveis
- Listeners de status e erro

### 3.3 Mapeamento de Métodos

| Método SDK | Endpoint REST |
|-----------|---------------|
| `pipeline.getStatus` | `/pipeline/status` |
| `pipeline.getSession` | `/pipeline/session` |
| `pipeline.getMetrics` | `/pipeline/metrics` |
| `pipeline.getSnapshot` | `/pipeline/snapshot` |
| `session.getCurrent` | `/session/current` |
| `metrics.get` | `/metrics` |
| `configuration.get` | `/configuration` |
| `health.get` | `/health` |
| `diagnostics.get` | `/diagnostics` |
| `events.getAll` | `/events` |
| `events.getByCorrelation` | `/events/by-correlation` |
| `events.getBySession` | `/events/by-session` |
| `events.getSnapshot` | `/events/snapshot` |

---

## 4. Estrutura do Transport WebSocket

### 4.1 Arquivo

`frontend/src/sdk/transports/websocket.ts`

### 4.2 Características

- Usa WebSocket API nativa do browser
- Conexão persistente para eventos (server push)
- Heartbeat periódico (30s padrão, configurável)
- Reconexão automática com backoff exponencial + jitter
- Timeout de conexão (10s padrão)
- Tratamento de erros → `PresentationError`
- Backpressure simples (fila por conexão, 1000 eventos)
- Cancelamento via `CancelToken`

### 4.3 Protocolo

```
Server → Client: hello (com versão da API)
Server → Client: event (para cada evento publicado)
Client → Server: heartbeat → Server: heartbeat_ack
Client → Server: ping → Server: heartbeat_ack
Server → Client: heartbeat_ack (periódico, 30s)
```

---

## 5. Integração Client SDK

### 5.1 RealClient

`frontend/src/sdk/real-client.ts`

O `RealClient` orquestra REST + WebSocket:

```typescript
class RealClient {
  // REST para consultas (request/response)
  // WebSocket para eventos (server push)
  
  async connect(): Promise<void>    // abre ambos os transportes
  async disconnect(): Promise<void> // fecha ambos
  async call<T>(method, params, options): Promise<Versioned<T>> // via REST
  subscribe(listener): () => void   // eventos do WebSocket
}
```

### 5.2 Compatibilidade

`asClient(real)` adapta `RealClient` para a interface `Client`,
permitindo uso em qualquer lugar que espera `Client` (InfraProvider,
createServices, etc.).

### 5.3 Nenhuma Mudança na API Pública

- `Client` interface: inalterada
- `CallOptions`: inalterado
- `ClientEvent`: inalterado
- `createServices(client)`: inalterado
- Hooks: inalterados
- Stores: inalterados
- EventStream: inalterado

---

## 6. Integração EventStream

### 6.1 EventStreamBridge

`frontend/src/stream/bridge.ts`

Conecta Client SDK → EventStream → SnapshotStores:

```
Client SDK (WebSocket event)
    ↓ ClientEvent { type: "event", payload: EventDTO }
EventStreamBridge
    ↓ eventDtoToStreamEvent(dto)
EventStream
    ↓ StreamEvent
EventStreamBridge (subscriber)
    ↓ stores.events.set([...current, dto])
SnapshotStore (EventStore)
    ↓ Snapshot<EventDTO[]>
Hooks (useStoreSnapshot)
    ↓ re-render
Components
```

### 6.2 Responsabilidades

- Assina eventos do Client SDK
- Converte EventDTO → StreamEvent
- Publica no EventStream
- Assina o EventStream
- Atualiza o EventStore (SnapshotStore) com novos eventos

### 6.3 NÃO Responsabilidades

- ❌ Não executa lógica de negócio
- ❌ Não interpreta eventos
- ❌ Não conhece React
- ❌ Não conhece transporte

---

## 7. Integração SnapshotStore

### 7.1 Atualização Automática

Quando eventos chegam via WebSocket:
1. `EventStreamBridge` recebe o evento do Client SDK
2. Publica no `EventStream`
3. Assina o `EventStream` e atualiza `stores.events`
4. Hooks que assinam `stores.events` re-renderizam

### 7.2 Nenhuma Atualização Manual

- Componentes NUNCA atualizam estado manualmente
- Componentes consomem snapshots via Hooks
- Stores são atualizados exclusivamente pelo `EventStreamBridge`

---

## 8. Endpoints Implementados

### 8.1 REST (11 endpoints)

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/info` | GET | Metadados da API (nome, versão) |
| `/health` | GET | Snapshot de saúde de todos os componentes |
| `/health/live` | GET | Liveness probe |
| `/health/ready` | GET | Readiness probe |
| `/pipeline/status` | GET | Status atual do pipeline |
| `/pipeline/session` | GET | Sessão atual do pipeline |
| `/pipeline/metrics` | GET | Métricas atuais do pipeline |
| `/pipeline/snapshot` | GET | Snapshot completo do pipeline |
| `/session/current` | GET | Sessão atual |
| `/metrics` | GET | Métricas do sistema |
| `/configuration` | GET | Configuração do sistema |
| `/diagnostics` | GET | Diagnósticos de todos os componentes |
| `/events` | GET | Todos os eventos |
| `/events/by-correlation` | GET | Eventos por correlation_id |
| `/events/by-session` | GET | Eventos por session_id |
| `/events/snapshot` | GET | Snapshot de eventos |

Todos retornam `Versioned<T>` (envelope com versão da API).

### 8.2 WebSocket (1 endpoint)

| Endpoint | Descrição |
|----------|-----------|
| `/ws/events` | Streaming de eventos em tempo real |

---

## 9. WebSocket Implementado

### 9.1 Endpoint

`/ws/events` — streaming de eventos da Presentation Layer.

### 9.2 ConnectionManager

Gerencia conexões WebSocket ativas:
- `connect(ws)` — aceita conexão, cria fila dedicada
- `disconnect(ws)` — remove conexão
- `broadcast_event(dto)` — enfileira evento para todas as conexões
- Backpressure: fila de 1000 eventos por conexão

### 9.3 EventPublisher

Bridge entre EventBus (Core) e ConnectionManager (WebSocket):
- Inscreve no EventBus para todos os eventos
- Converte eventos core em EventDTO
- Broadcasta via ConnectionManager
- Drenagem assíncrona (50ms interval)

---

## 10. Estratégia de Reconexão

### 10.1 WebSocket Transport

- **Backoff exponencial:** base * 2^(attempt-1) + jitter
- **Base:** 1000ms (configurável)
- **Jitter:** 0-500ms (evita thundering herd)
- **Máximo de tentativas:** 5 (configurável)
- **Após esgotar:** emite `TRANSPORT_UNAVAILABLE` (severity: critical)

### 10.2 Estados

```
idle → connecting → connected
                   ↓ (erro)
                reconnecting → connecting → connected
                              ↓ (max tentativas)
                           error
```

---

## 11. Estratégia de Heartbeat

### 11.1 Backend

- Envia `heartbeat_ack` periódico (30s) para cada conexão
- Responde `heartbeat` e `ping` do cliente com `heartbeat_ack`

### 11.2 Frontend (WebSocketTransport)

- Envia `heartbeat` para o server a cada 30s (configurável)
- Se o WebSocket cair, o heartbeat falha → onclose → reconexão

---

## 12. Estratégia de Versionamento

### 12.1 Backend

Toda resposta REST retorna `Versioned<T>`:
```json
{
  "api": { "major": 0, "minor": 1, "patch": 0, "pre": "foundation" },
  "payload": { ... }
}
```

### 12.2 Frontend (Client SDK)

O `RealClient` valida compatibilidade major automaticamente:
```typescript
if (!isCompatible(result.result, this.expectedApi)) {
  throw new PresentationError({
    code: "SDK_VERSION_MISMATCH",
    message: `Versão incompatível: esperada ${expected}, recebida ${received}.`,
  });
}
```

### 12.3 WebSocket

O server envia `hello` com a versão da API ao conectar.

---

## 13. Estratégia de Cancelamento

### 13.1 REST Transport

- `CancelToken` integrado com `AbortController`
- Se cancelado, `fetch()` aborta → `DOMException(AbortError)`
- Converte para `PresentationError(SDK_CANCELED)`

### 13.2 Timeout

- `AbortController` com `setTimeout`
- Se timeout expira, `fetch()` aborta → `PresentationError(TRANSPORT_TIMEOUT)`

### 13.3 Uso

```typescript
const source = createCancelSource();
client.call("pipeline.getStatus", {}, { cancel: source.token, timeoutMs: 5000 });
// ... depois
source.cancel("usuário navegou");
```

---

## 14. Fluxo Completo Ponta a Ponta

### 14.1 Consulta (REST)

```
Hooks → Services → RealClient.call()
    → RestTransport.request()
    → fetch("http://localhost:8000/pipeline/status")
    → FastAPI router
    → PresentationService.get_status()
    → PipelineMapper.to_status_dto(state)
    → PipelineStatusDTO
    → PipelineStatusModel.from_dto()
    → versioned(model)
    → JSON response
    → fetch() resolve
    → RestTransport retorna TransportResult
    → RealClient valida versão
    → Services retornam DTO
    → Hooks atualizam Store
    → Components re-render
```

### 14.2 Eventos (WebSocket)

```
Backend EventBus.publish(event)
    → EventPublisher._on_event()
    → EventMapper.to_dto(event)
    → ConnectionManager.broadcast_event(dto)
    → WebSocket.send_text(WsEventModel)
    → WebSocketTransport.onmessage
    → TransportEvent { type: "message", payload }
    → RealClient handleTransportEvent
    → ClientEvent { type: "event", payload }
    → EventStreamBridge.handleClientEvent()
    → eventDtoToStreamEvent(dto)
    → EventStream.publish(streamEvent)
    → EventStreamBridge.handleStreamEvent()
    → stores.events.set([...current, dto])
    → Hooks (useEvents) re-render
    → Components
```

---

## 15. Logging Estruturado

### 15.1 Backend

```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
```

Loggers:
- `api` — geral
- `api.middleware` — requisições HTTP
- `api.websocket` — conexões WebSocket
- `api.exceptions` — erros

### 15.2 Eventos Logados

- Conexão estabelecida
- Desconexão
- Reconexão (com attempt e delay)
- Timeout
- Erros (com exception type)
- Handshake (hello recebido)
- Version mismatch
- Queue cheia (backpressure)

### 15.3 Sem Logs de Negócio

Apenas infraestrutura é logada. Nenhum log de regra de negócio.

---

## 16. Quantidade de Novos Testes

### 16.1 Backend (Python)

| Arquivo | Testes | Cobertura |
|---------|--------|-----------|
| `tests/test_api.py` | 32 (+ 11 subtests) | CompositionRoot, endpoints REST, WebSocket, schemas, versioning, error handling, CORS |

**Total backend:** 32 novos testes (2517 total, zero regressão)

### 16.2 Frontend (TypeScript)

| Arquivo | Testes | Cobertura |
|---------|--------|-----------|
| `tests/sdk-rest-transport.test.ts` | 20 | RestTransport: fetch mock, timeout, cancelamento, erros HTTP, listeners |
| `tests/sdk-real-client.test.ts` | 18 | RealClient + EventStreamBridge: call, versioning, cancel, bridge, stores |

**Total frontend:** 38 novos testes (273 total, zero regressão)

### 16.3 Resultado Final

```
Backend:  2517 passed (32 new + 2485 existing)
Frontend: 273 passed (38 new + 235 existing)
```

---

## 17. Compatibilidade Preservada

### 17.1 Arquitetura

- ✅ Client SDK: interface `Client` inalterada
- ✅ EventStream: interface inalterada
- ✅ SnapshotStore: interface inalterada
- ✅ Services: interface `PresentationServices` inalterada
- ✅ Hooks: API pública inalterada
- ✅ Stores: interface inalterada
- ✅ Components: inalterados
- ✅ Pages: inalteradas (apenas adicionado ConnectionIndicator)

### 17.2 Testes

- ✅ 235 testes frontend existentes: todos passam
- ✅ 2485 testes Python existentes: todos passam
- ✅ 70 novos testes: todos passam

### 17.3 Build

- ✅ `tsc --noEmit`: sem erros
- ✅ `vite build`: OK (258 KB JS, 19 KB CSS)

---

## 18. Confirmações

### 18.1 Nenhuma regra de negócio foi adicionada

- ✅ Nenhum Dashboard implementado
- ✅ Nenhum Console implementado
- ✅ Nenhum Replay implementado
- ✅ Nenhuma configuração implementada
- ✅ Nenhum diagnóstico implementado
- ✅ Backend apenas expõe Presentation Layer
- ✅ Frontend apenas mostra indicadores de conexão

### 18.2 Nenhuma camada arquitetural foi alterada

- ✅ Client SDK: inalterado (apenas adicionado RealClient + transports)
- ✅ EventStream: inalterado (apenas adicionado Bridge)
- ✅ SnapshotStore: inalterado
- ✅ Services: inalterado (apenas usa RealClient em vez de stub)
- ✅ Hooks: inalterados (apenas recebem dados reais)
- ✅ Stores: inalterados
- ✅ Components: inalterados (apenas adicionado ConnectionIndicator)
- ✅ Pages: inalteradas (apenas incluem ConnectionIndicator)

### 18.3 Arquitetura funcionando com comunicação real

- ✅ REST Transport faz `fetch()` real para FastAPI
- ✅ WebSocket Transport conecta a `/ws/events` real
- ✅ FastAPI expõe Presentation Layer via endpoints REST
- ✅ FastAPI transmite eventos via WebSocket
- ✅ EventStreamBridge conecta Client SDK → EventStream → Stores
- ✅ Hooks recebem dados reais via Stores
- ✅ ConnectionIndicator mostra status real da conexão
- ✅ Versionamento validado automaticamente
- ✅ Cancelamento funcional
- ✅ Timeout funcional
- ✅ Reconexão com backoff exponencial
- ✅ Heartbeat periódico

---

## 19. Conclusão

A **primeira integração real** entre frontend e backend foi
concluída com sucesso. Principais conquistas:

1. **FastAPI backend** com 16 endpoints REST + 1 WebSocket
2. **RestTransport** real usando Fetch API
3. **WebSocketTransport** real com reconexão e heartbeat
4. **RealClient** orquestrando REST + WebSocket
5. **EventStreamBridge** conectando Client SDK → EventStream → Stores
6. **CompositionRoot** isolando Core da API
7. **Versionamento** automático em todas as respostas
8. **Cancelamento** e **timeout** funcionais
9. **Logging estruturado** de infraestrutura
10. **70 novos testes** (32 backend + 38 frontend)
11. **Zero regressão** — 2517 + 273 testes passam
12. **Nenhuma camada arquitetural alterada**

A arquitetura definida durante o Architecture Freeze funcionou
integralmente com comunicação real, sem necessidade de qualquer
refatoração estrutural.

As próximas fases podem concentrar-se exclusivamente na
implementação das funcionalidades da aplicação (Dashboard,
Console, Replay, Diagnóstico, Configurações, etc.), reutilizando
toda a infraestrutura construída aqui.
