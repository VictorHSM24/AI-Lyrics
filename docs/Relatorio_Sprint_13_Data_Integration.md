# Sprint 13 — Data Integration Foundation

**Data:** 2026-07-19
**Objetivo:** Transformar o frontend em um consumidor consistente do backend, estabelecendo uma única fonte de verdade para todos os dados operacionais.

---

## Critérios de Aceite

| Critério | Status |
|----------|--------|
| Todo dado compartilhado vem de um Store | ✅ |
| Nenhum Service retorna dados descartados | ✅ |
| Todo hook consome Stores | ✅ |
| O Bootstrap popula completamente a aplicação | ✅ |
| O Bridge mantém os Stores sincronizados em tempo real | ✅ |
| Startup reflete exclusivamente estados reais do backend | ✅ |
| Nenhum componente React depende de mocks para funcionalidades já existentes no backend | ✅ |

**Testes:** 434 passando (401 anteriores + 33 novos)
**TypeCheck:** sem erros
**Build:** 1662 módulos, 342KB JS (101KB gzip)

---

## 1. Fluxo de Dados Final

```
Backend (FastAPI)
      ↓
REST / WebSocket
      ↓
SDK (RealClient: RestTransport + WebSocketTransport)
      ↓
┌─────────────────────────────────────────────┐
│ Bridge (EventStreamBridge)                  │
│   Client SDK → EventStream → Stores         │
│   dispatchDomainHandlers() → handlers.ts    │
└─────────────────────────────────────────────┘
      ↓                           ↑
┌──────────────────┐    ┌──────────────────────┐
│ Bootstrap         │    │ Bridge handlers       │
│ (bootstrapStores) │    │ (handlers.ts)         │
│ 6 services em     │    │ pipeline lifecycle    │
│ paralelo → Stores │    │ session events        │
└──────────────────┘    │ metrics incremental    │
      ↓                  │ diagnostics errors    │
┌─────────────────────────────────────────────┐
│ Stores (única fonte de verdade)              │
│   pipeline · health · metrics · session      │
│   configuration · diagnostics · events       │
│   logs · replay                              │
└─────────────────────────────────────────────┘
      ↓
┌─────────────────────────────────────────────┐
│ Hooks (useStoreSnapshot)                     │
│   usePipeline · useHealth · useMetrics       │
│   useSession · useConfiguration              │
│   useDiagnostics · useEvents · useReplay     │
│   useBootstrap (dispara bootstrap)           │
└─────────────────────────────────────────────┘
      ↓
React Components (re-render automático)
```

### Fluxo de Bootstrap

1. App monta → `InfraProvider` cria `RealClient`, `EventStream`, `StoreRegistry`, `Services`, `Bridge`
2. `InfraProvider` chama `client.connect()` → WebSocket + REST conectam
3. `ConnectionContext` detecta status "connected"
4. `useBootstrap()` (em `BootstrapOrchestrator`) detecta transição para "connected"
5. `bootstrapStores(services, stores)` executa 6 requisições em paralelo
6. Cada resultado → `store.set()` ou `store.update()`
7. Hooks re-renderizam com dados reais

### Fluxo de Eventos (tempo real)

1. Backend emite evento → WebSocket → `Client.subscribe()`
2. `Bridge.handleClientEvent()` → `EventStream.publish()`
3. `Bridge.handleStreamEvent()` → `stores.events.set()` + `dispatchDomainHandlers()`
4. `dispatchDomainHandlers()` despacha para:
   - `handlePipelineLifecycle()` → `stores.pipeline`
   - `handleSessionEvent()` → `stores.session`
   - `handleMetricsEvent()` → `stores.metrics`
   - `handleDiagnosticEvent()` → `stores.diagnostics`
5. Hooks re-renderizam

---

## 2. Stores

| Store | Origem dos dados | Quem atualiza | Quem consome |
|-------|-----------------|---------------|--------------|
| **pipeline** | Backend (REST + WS) | Bootstrap (`pipeline.getStatus`), Bridge (`PipelineStarted/Stopped/Paused/Resumed`) | `usePipeline()` → ConsoleHeader, PipelinePanel, OperationContext |
| **health** | Backend (REST) | Bootstrap (`health.getHealth`) | `useHealth()` → HealthPanel, ConsoleHeader, OperationContext |
| **metrics** | Backend (REST + WS) | Bootstrap (`pipeline.getMetrics`), Bridge (`SpeechSegmentReceived/Recognized/SearchCompleted/PresentationCompleted/PipelineError`) | `useMetrics()` → LatencyBadge |
| **session** | Backend (REST + WS) | Bootstrap (`pipeline.getSession`), Bridge (`PipelineStarted/Stopped`) | `useSession()` → ConsoleHeader |
| **configuration** | Backend (REST) | Bootstrap (`configuration.getConfiguration`) | `useConfiguration()` → AITab, AdvancedTab, ConsoleHeader, OperationContext |
| **diagnostics** | Backend (REST + WS) | Bootstrap (`diagnostics.getDiagnostics`), Bridge (`PipelineError`) | `useDiagnostics()` |
| **events** | Backend (WS) | Bridge (todos os eventos) | `useEvents()` → TimelinePanel, PipelinePanel, VerseCard, RecognitionCard |
| **logs** | (vazio) | Nenhum (sem endpoint de logs ainda) | Nenhum |
| **replay** | (vazio) | Nenhum (sem endpoint de replay ainda) | `useReplay()` |

### Stores adicionais (OperationContext)

| Store | Origem | Quem atualiza | Quem consome |
|-------|--------|---------------|--------------|
| **operationStore** | Local (derivado de connection + pipeline + health) | OperationContext (derivação automática) | `useOperationState()` → StartupScreen, ConfigurationPage, AboutPage, Header |
| **settingsStore** | localStorage | `updateSettings()`, `resetSettings()` | `useOperationState()` → GeneralTab, AudioTab, AITab, HolyricsTab, SystemTab |

---

## 3. Hooks

### Hooks modificados

| Hook | Modificação |
|------|-------------|
| `useBootstrap()` | **Novo** — dispara `bootstrapStores()` quando conexão é estabelecida |

### Hooks existentes (sem modificação — já consumiam Stores)

| Hook | Store consumido | Status |
|------|-----------------|--------|
| `usePipeline()` | `stores.pipeline` | ✅ Já consumia Store (Store agora é populado) |
| `useMetrics()` | `stores.metrics` | ✅ Já consumia Store (Store agora é populado) |
| `useHealth()` | `stores.health` | ✅ Já consumia Store (Store agora é populado) |
| `useSession()` | `stores.session` | ✅ Já consumia Store (Store agora é populado) |
| `useConfiguration()` | `stores.configuration` | ✅ Já consumia Store (Store agora é populado) |
| `useDiagnostics()` | `stores.diagnostics` | ✅ Já consumia Store (Store agora é populado) |
| `useEvents()` | `stores.events` | ✅ Já funcionava (Bridge já populava) |
| `useReplay()` | `stores.replay` | ✅ Já consumia Store (Store permanece vazio — sem endpoint) |

> **Nota:** Os hooks já estavam corretos — eles consumiam Stores via `useStoreSnapshot()`. O problema era que **ninguém populava os Stores**. Esta sprint resolveu isso com Bootstrap + Bridge handlers.

---

## 4. Componentes que passaram a consumir dados reais

| Componente | Antes | Depois |
|------------|-------|--------|
| **ConsoleHeader** | `usePipeline()`, `useHealth()`, `useSession()`, `useConfiguration()` retornavam `null` | Agora retornam dados reais do backend via Bootstrap |
| **PipelinePanel** | `usePipeline()` retornava `null` | Status real do pipeline |
| **LatencyBadge** | `useMetrics()` retornava `null` | Métricas reais |
| **HealthPanel** | STT/Bible/Holyrics do backend; resto derivado localmente | Agora também pipeline tem dados reais |
| **AdvancedTab** | `useConfiguration()` retornava `null` | Configuração real do backend |
| **AITab** | `useConfiguration()` retornava `null` | Configuração real do backend |
| **OperationContext** | Derivava estado de `null` (sempre "stopped") | Agora deriva de dados reais |
| **StartupScreen** | 8 etapas simuladas com `setTimeout` | 8 etapas com verificações reais do backend |

---

## 5. Código Removido

### Mocks eliminados

| Arquivo | Linha | Mock | Substituído por |
|---------|-------|------|-----------------|
| `contexts/OperationContext.tsx` | 318-363 | `setTimeout` simulation (8 etapas) | `checkStartupStep()` com verificações reais |
| `contexts/OperationContext.tsx` | 319 | Comentário "Simulate startup sequence with delays" | Código real de verificação |

### Estados duplicados eliminados

Nenhum. A auditoria confirmou que nenhum componente mantinha `useState(response)` duplicando dados de backend. Os hooks já consumiam Stores corretamente — o problema era que os Stores estavam vazios.

### Chamadas diretas eliminadas

| Arquivo | Chamada | Substituída por |
|---------|---------|-----------------|
| `contexts/OperationContext.tsx` | `setTimeout(runNext, delay)` | `await checkStartupStep(stepId, services, stores, client, stream)` |

### Código stub eliminado

| Arquivo | Linha | Stub | Substituído por |
|---------|-------|------|-----------------|
| `stream/bridge.ts` | 109-140 | `updateDomainStores()` com switch vazio | `dispatchDomainHandlers()` → `handlers.ts` |

---

## 6. Dívidas Restantes (para Sprint 14)

Estas dívidas dependem de **novas capacidades do backend** e não puderam ser resolvidas apenas com integração:

| Dívida | Motivo | Sprint 14 |
|--------|--------|-----------|
| **logs store vazio** | Não existe endpoint `GET /logs` no backend | Criar endpoint de logs |
| **replay store vazio** | Não existem endpoints `/replay/*` no backend | Criar endpoints de replay |
| **MOCK_DEVICES no AudioTab** | Não existe endpoint `GET /audio/devices` no backend | Criar endpoint de dispositivos |
| **Teste de conexão Holyrics simulado** | `holyrics_health()` é placeholder no backend | Implementar health check real |
| **systemInfo mock no SystemTab** | Não existe endpoint `GET /system/info` no backend | Criar endpoint de system info |
| **AboutPage Build/Commit hardcoded** | Endpoint `/info` existe mas não retorna build/commit | Estender resposta do `/info` |
| **Configuration não sincroniza com backend** | Não existe `PUT /configuration` no backend | Criar endpoint de gravação |
| **Pipeline actions (start/stop/pause/resume)** | Não existem endpoints POST no backend | Criar endpoints de actions |
| **Páginas placeholder (Dashboard, Logs, Replay, Sessions, Diagnostic)** | Dependem de stores/endpoint inexistentes | Implementar após stores disponíveis |
| **WsErrorModel nunca emitido** | Schema existe mas não é usado | Implementar emissão no WebSocket |

---

## Arquivos Criados

| Arquivo | Descrição |
|---------|-----------|
| `src/stream/handlers.ts` | Handlers de domínio organizados (pipeline, session, metrics, diagnostics) + despachante |
| `src/stream/bootstrap.ts` | Função `bootstrapStores()` — 6 requisições em paralelo populando Stores |
| `src/utils/dev-log.ts` | Telemetria de desenvolvimento (no-op em produção) |
| `tests/integration.test.tsx` | 33 testes para handlers, bootstrap e dev-log |

## Arquivos Modificados

| Arquivo | Modificação |
|---------|-------------|
| `src/stream/bridge.ts` | `updateDomainStores()` stub substituído por `dispatchDomainHandlers()` |
| `src/stream/index.ts` | Exporta handlers e bootstrap |
| `src/hooks/index.ts` | Adicionado `useBootstrap()` hook |
| `src/contexts/OperationContext.tsx` | Startup real (sem setTimeout), imports de useConfiguration + useInfrastructure |
| `src/app/App.tsx` | Adicionado `BootstrapOrchestrator` que dispara `useBootstrap()` |
| `src/utils/index.ts` | Adicionado export de `devLog` |

## Arquitetura Preservada

- ✅ EventStream — não modificado
- ✅ SnapshotStore — não modificado
- ✅ SDK (Client, RealClient, RestTransport, WebSocketTransport) — não modificado
- ✅ API pública — não modificada
- ✅ Organização das pastas — mantida
- ✅ Separação por domínios — mantida
- ✅ Services — não modificados (apenas consumidos pelo Bootstrap)
- ✅ Stores (domain.ts) — não modificados (apenas populados)

## Design do Bridge (não God Object)

O Bridge permanece pequeno e focado em roteamento. A lógica de mapeamento está em `handlers.ts`, organizada por domínio:

```
bridge.ts (roteamento)
  └→ dispatchDomainHandlers() (despachante)
       ├→ handlePipelineLifecycle()  — pipeline store
       ├→ handleSessionEvent()       — session store
       ├→ handleMetricsEvent()       — metrics store
       └→ handleDiagnosticEvent()    — diagnostics store
```

Cada handler é uma função pura que recebe `EventDTO` + `StoreRegistry` e atualiza apenas os Stores correspondentes. O Bridge não contém lógica de mapeamento — apenas despacha.
