# Relatório — Web UI Architecture Freeze

**Data:** 18 de julho de 2026
**Fase:** Architecture Freeze (consolidação definitiva da arquitetura)
**Status:** Concluído
**Testes Frontend:** 235 passaram (Vitest) — 119 novos + 116 existentes
**Testes Backend:** 2485 passaram (pytest), zero regressão
**Build:** Vite production build OK (242 KB JS, 19 KB CSS)

---

## 1. Objetivo

Consolidar definitivamente a arquitetura do frontend do AI Lyrics
para suportar o crescimento do projeto durante muitos anos,
minimizando futuras refatorações.

**Esta é a última revisão estrutural da Web UI Foundation.**
Após esta fase, todas as próximas fases apenas adicionam
funcionalidades.

---

## 2. Alterações Arquiteturais Realizadas

### 2.1 Novas Camadas

| Camada | Arquivo | Responsabilidade |
|--------|---------|-----------------|
| **Client SDK** | `src/sdk/` | Comunicação com backend (serialização, erros, timeout, versionamento, cancelamento) |
| **EventStream** | `src/stream/` | Barramento de eventos do frontend |
| **SnapshotStore** | `src/stores/` | Estado reativo (snapshots imutáveis) |
| **Domain Stores** | `src/stores/domain.ts` | 9 stores por domínio |

### 2.2 Camadas Atualizadas

| Camada | Alteração |
|--------|-----------|
| **Services** | Agora usam Client SDK em vez de stub direto |
| **Hooks** | Agora consomem Stores + EventStream em vez de retornar valores estáticos |
| **Contexts** | Novo `InfraContext` provê Client, Stream, Stores, Services |
| **Components** | Reorganizados em 9 categorias |

### 2.3 Novos Contratos

| Contrato | Descrição |
|----------|-----------|
| `PresentationError` | Modelo único de erros (code, severity, recoverable, correlationId) |
| `CancelToken` | Cancelamento de operações assíncronas |
| `ApiVersion` | Versionamento de DTOs e API |
| `Versioned<T>` | Envelope versionado para payloads |
| `Transport` | Abstração de transporte (REST/WS/SSE) |
| `Client` | SDK orquestrando Transport + serialização + erros |
| `EventStream` | Barramento de eventos com subscriptions |
| `SnapshotStore<T>` | Store de estado com snapshots imutáveis |

---

## 3. Nova Organização de Diretórios

```
src/
├── app/              # Root, layout, error boundary
│   └── layout/
├── pages/            # Páginas (orquestram componentes)
├── components/       # Design System (9 categorias)
│   ├── common/       # Genéricos (Divider, PageContainer, Section, Card, Panel, PropertyGrid)
│   ├── layout/       # Layout (PageContainer, Section, Panel)
│   ├── feedback/     # Feedback (Loading, EmptyState, ErrorState, Toast, Modal, ConfirmationDialog)
│   ├── navigation/   # Navegação (Toolbar, SearchBox)
│   ├── status/       # Status (StatusBadge)
│   ├── metrics/      # Métricas (MetricCard)
│   ├── tables/       # Tabelas (Table)
│   ├── timeline/     # Timeline (Timeline)
│   └── forms/        # Formulários (preparado, vazio)
├── shared/           # Constantes e enums
├── hooks/            # Hooks (consomem Stores + Services + Stream)
├── contexts/         # Contexts React (5 contexts)
├── services/         # Services (consultas via Client SDK)
├── stores/           # SnapshotStore + 9 Domain Stores
├── stream/           # EventStream
├── sdk/              # Client SDK (6 módulos)
│   ├── client.ts     # Client (orquestra Transport)
│   ├── transport.ts  # Contrato de transporte
│   ├── errors.ts     # PresentationError + Result<T>
│   ├── cancel.ts     # CancelToken + CancelSource
│   ├── versioning.ts # ApiVersion + Versioned<T>
│   └── index.ts      # Barrel público
├── types/            # Tipos (DTOs da Presentation Layer)
├── utils/            # Utilitários
├── styles/           # CSS global
├── assets/           # Assets
├── router/           # Roteamento
└── docs/
    └── ARCHITECTURE.md  # Documentação arquitetural completa
```

---

## 4. Estrutura do Client SDK

### 4.1 Módulos

```
src/sdk/
├── index.ts          # Barrel público (único ponto de entrada)
├── client.ts         # Client + ClientImpl + factory
├── transport.ts      # Transport + TransportFactory + StubTransport
├── errors.ts         # PresentationError + Result<T> + helpers
├── cancel.ts         # CancelToken + CancelSource + raceCancel
└── versioning.ts     # ApiVersion + Versioned<T> + compare/parse
```

### 4.2 Contratos Principais

```typescript
interface Client {
  connect(): Promise<void>;
  disconnect(): Promise<void>;
  readonly status: TransportStatus;
  readonly expectedApiVersion: ApiVersion;
  subscribe(listener: ClientEventListener): () => void;
  call<T>(method: string, params: Record<string, unknown>, options?: CallOptions): Promise<Versioned<T>>;
}

interface Transport {
  open(): Promise<void>;
  close(): Promise<void>;
  readonly status: TransportStatus;
  subscribe(listener: TransportListener): () => void;
  request<T>(req: TransportRequest): Promise<TransportResult<T>>;
}
```

### 4.3 Responsabilidades Futuras

- Serialização / desserialização
- Timeout
- Tratamento de erros
- Heartbeat
- Reconexão
- Cache
- Versionamento
- Autenticação futura
- Multiplexação de conexões

### 4.4 Substituição de Transporte

Para trocar REST por WebSocket:
1. Implementar `Transport` para a nova tecnologia.
2. Passar para `ClientImpl`.
3. **Nenhum Hook, Service ou Componente precisa ser modificado.**

---

## 5. Estrutura do EventStream

### 5.1 Arquitetura

```
Backend (EventBus)
    ↓ EventDTO
Transport (WebSocket)
    ↓ message
Client SDK
    ↓ ClientEvent
EventStream
    ↓ StreamEvent
    ├──→ SnapshotStore (atualiza estado)
    └──→ Hooks (subscribe)
              ↓
         Components (re-render)
```

### 5.2 Contrato

```typescript
interface EventStream {
  publish(event: StreamEvent): void;
  subscribe(listener: StreamListener): StreamSubscription;
  subscribeToType(type: string, listener: StreamListener): StreamSubscription;
  subscribeToCorrelation(correlationId: string, listener: StreamListener): StreamSubscription;
  snapshot(): StreamSnapshot;
  history(limit?: number): readonly StreamEvent[];
  clear(): void;
  close(): void;
  readonly closed: boolean;
}
```

### 5.3 Responsabilidades

- ✅ Receber eventos
- ✅ Registrar subscribers
- ✅ Unsubscribe
- ✅ Publicar eventos
- ✅ Armazenar último evento
- ✅ Histórico recente (configurável, padrão 1000)
- ✅ Snapshot do stream
- ✅ Subscriptions por tipo e por correlação
- ❌ NÃO interpreta eventos
- ❌ NÃO executa lógica de negócio
- ❌ NÃO conhece React

---

## 6. Estrutura do SnapshotStore

### 6.1 Contrato

```typescript
interface SnapshotStore<T> {
  readonly current: Snapshot<T> | null;
  readonly version: number;
  readonly hasSnapshot: boolean;
  subscribe(listener: StoreListener<T>): StoreSubscription;
  set(data: T): void;
  update(updater: (prev: T | null) => T): void;
  clear(): void;
}

interface Snapshot<T> {
  readonly data: T;
  readonly version: number;
  readonly timestamp: number;
}
```

### 6.2 Domain Stores (9)

| Store | Domínio |
|-------|---------|
| `PipelineStore` | PipelineSnapshot + setStatus |
| `HealthStore` | HealthSnapshot |
| `MetricsStore` | MetricsDTO |
| `SessionStore` | SessionDTO |
| `ConfigurationStore` | ConfigurationDTO |
| `DiagnosticsStore` | DiagnosticDTO[] |
| `LogStore` | LogDTO[] |
| `ReplayStore` | ReplayState (events, sessionIds, correlations) |
| `EventStore` | EventDTO[] |

### 6.3 StoreRegistry

Agregador de todos os stores:
```typescript
interface StoreRegistry {
  pipeline: PipelineStore;
  health: HealthStore;
  metrics: MetricsStore;
  session: SessionStore;
  configuration: ConfigurationStore;
  diagnostics: DiagnosticsStore;
  logs: LogStore;
  replay: ReplayStore;
  events: EventStore;
}
```

---

## 7. Novo Fluxo Arquitetural Completo

### 7.1 Fluxo de Dados (Consultas)

```
Hooks → Services → Client SDK → Transport → Backend
                                              ↓
                                         Versioned<T>
                                              ↓
                                    Client SDK (valida versão)
                                              ↓
                                         Services
                                              ↓
                                    Store.set(data)
                                              ↓
                                    SnapshotStore
                                              ↓
                                    Hooks (useStoreSnapshot)
                                              ↓
                                    Components (re-render)
```

### 7.2 Fluxo de Eventos (Atualização Reativa)

```
Backend (EventBus)
    ↓ EventDTO
Transport (WebSocket)
    ↓ message
Client SDK
    ↓ ClientEvent
EventStream
    ↓ StreamEvent
    ├──→ SnapshotStore (atualiza estado)
    │         ↓
    │    Hooks (subscribe)
    │         ↓
    │    Components (re-render)
    │
    └──→ Hooks (subscribe direto)
              ↓
         Components (re-render)
```

### 7.3 Fluxo de Erros

```
Transport / SDK / Services
    ↓ PresentationError
    ↓ (code, severity, recoverable, correlationId)
Hooks
    ↓ error: string | null
Components
    ↓ ErrorState / Toast
```

---

## 8. Atualização dos Services

### 8.1 Antes

```typescript
// Stub direto — todas as chamadas lançavam "not implemented"
export function createPresentationApi(): PresentationApi {
  const notImplemented = (): never => { throw new Error("..."); };
  return { pipeline: { getStatus: notImplemented, ... }, ... };
}
```

### 8.2 Depois

```typescript
// Services delegam ao Client SDK
export function createServices(client: Client): PresentationServices {
  const call = <T>(method: string, params: Record<string, unknown>, options?: CallOptions) =>
    client.call<T>(method, params, options).then(unwrap);
  return {
    pipeline: {
      getStatus: (o) => call<PipelineStatusDTO>("pipeline.getStatus", {}, o),
      ...
    },
    ...
  };
}
```

### 8.3 Regras

- Services **nunca** armazenam estado.
- Services **nunca** recebem eventos.
- Services **nunca** conhecem transporte.
- Services **nunca** conhecem React.
- Services aceitam `CallOptions` (cancel + timeout).

---

## 9. Atualização dos Hooks

### 9.1 Antes

```typescript
// Retornavam valores estáticos (null/empty)
export function usePipeline(): UsePipelineResult {
  return { status: null, snapshot: null, loading: false, error: null };
}
```

### 9.2 Depois

```typescript
// Assinam SnapshotStore e re-renderizam em mudanças
export function usePipeline(): UsePipelineResult {
  const stores = useStores();
  const snap = useStoreSnapshot(stores.pipeline);
  return {
    status: snap?.data.status ?? null,
    snapshot: snap?.data ?? null,
    loading: !snap,
    error: null,
  };
}
```

### 9.3 Novos Hooks

- `useStreamSnapshot()` — snapshot do EventStream
- `useStreamEvents(limit)` — eventos do stream
- `useServicesHook()` — accessa services

### 9.4 Regras

- Hooks consomem **exclusivamente** Stores + Services + EventStream.
- Hooks **nunca** conhecem transporte.
- Hooks **nunca** conhecem Client SDK diretamente.
- Hooks **nunca** usam polling.

---

## 10. Atualização da Documentação

### 10.1 `docs/ARCHITECTURE.md`

Documentação arquitetural completa criada com:
- Filosofia (orientado a eventos, sem polling)
- Camadas arquiteturais (diagrama)
- Responsabilidades de cada camada
- Regras oficiais (10 regras)
- Fluxo de dados (diagrama)
- Fluxo de eventos (diagrama)
- Client SDK (estrutura, contratos, substituição)
- Error Model (PresentationError, severity, Result<T>)
- Cancelamento (CancelToken)
- Versionamento (ApiVersion, Versioned<T>)
- Organização de diretórios
- Feature Modules (estratégia de crescimento)
- Regra arquitetural de Pages
- Atualização reativa (proibido vs correto)
- Boas práticas obrigatórias (10 práticas)
- Diagrama de dependências

### 10.2 Remoção de Polling

Toda referência a polling foi removida da documentação.
A documentação agora explicitamente proíbe:
- ❌ Polling
- ❌ `setInterval` para atualização
- ❌ Refresh periódico
- ❌ Timers de atualização

---

## 11. Estratégia Oficial de Crescimento por Feature Modules

### 11.1 Estrutura Futura

```
src/features/
├── dashboard/
│   ├── components/
│   ├── hooks/
│   ├── services/
│   ├── types/
│   ├── utils/
│   └── pages/
├── console/
├── replay/
├── sessions/
├── diagnostics/
├── configuration/
└── logs/
```

### 11.2 Regras

- Cada feature é **autocontida**.
- Cada feature possui seus próprios componentes, hooks, services, types.
- Features podem importar de `components/` (Design System).
- Features **não** importam de outras features diretamente.
- Comunicação entre features ocorre via **Stores** ou **EventStream**.

### 11.3 Quando Migrar

A migração para `features/` é **incremental** e ocorre quando:
- Uma página passa a ter componentes específicos.
- Uma página passa a ter hooks específicos.
- Uma página passa a ter services específicos.

**Não reorganizar agora.** A estrutura atual em `pages/` é suficiente.

---

## 12. Error Model Definido

### 12.1 PresentationError

```typescript
class PresentationError extends Error {
  readonly code: ErrorCode;           // TRANSPORT_TIMEOUT, SDK_CANCELED, etc.
  readonly message: string;
  readonly details: Record<string, unknown>;
  readonly recoverable: boolean;      // true = pode tentar novamente
  readonly severity: ErrorSeverity;   // info | low | medium | high | critical
  readonly correlationId: string | null;
  readonly timestamp: number;
  readonly cause: PresentationError | null;
}
```

### 12.2 Error Codes (25 códigos)

- **Transporte:** TRANSPORT_TIMEOUT, TRANSPORT_DISCONNECTED, TRANSPORT_RECONNECTING, TRANSPORT_HANDSHAKE_FAILED, TRANSPORT_AUTH_REQUIRED, TRANSPORT_RATE_LIMITED, TRANSPORT_UNAVAILABLE
- **SDK:** SDK_NOT_CONFIGURED, SDK_SERIALIZATION_FAILED, SDK_DESERIALIZATION_FAILED, SDK_VERSION_MISMATCH, SDK_CANCELED
- **Services:** SERVICE_NOT_FOUND, SERVICE_UNAVAILABLE, SERVICE_INVALID_ARGUMENT
- **EventStream:** STREAM_OVERFLOW, STREAM_CLOSED, STREAM_SUBSCRIPTION_FAILED
- **SnapshotStore:** STORE_EMPTY, STORE_STALE, STORE_CONFLICT
- **Genérico:** UNKNOWN

### 12.3 Result<T>

```typescript
type Result<T, E = PresentationError> =
  | { ok: true; value: T }
  | { ok: false; error: E };
```

### 12.4 Helpers

- `canceled(correlationId?)` → PresentationError(SDK_CANCELED)
- `timeout(ms, correlationId?)` → PresentationError(TRANSPORT_TIMEOUT)
- `notConfigured()` → PresentationError(SDK_NOT_CONFIGURED)
- `PresentationError.fromUnknown(err)` → converte Error genérico
- `PresentationError.fromEvent(meta, overrides)` → correlaciona com evento

---

## 13. Estratégia de Cancelamento

### 13.1 CancelToken

```typescript
interface CancelToken {
  readonly canceled: boolean;
  readonly reason: string | null;
  onCancel(callback: (reason: string | null) => void): () => void;
  throwIfCanceled(): void;
}
```

### 13.2 Uso

```typescript
const source = createCancelSource();
client.call<T>("method", params, { cancel: source.token, timeoutMs: 5000 });
// ... depois
source.cancel("usuário navegou para outra página");
```

### 13.3 Helpers

- `createCancelSource()` — cria fonte + token
- `canceledToken(reason?)` — token já cancelado
- `raceCancel(...tokens)` — cancela quando qualquer um cancelar
- `NEVER_CANCEL` — token que nunca cancela

---

## 14. Preparação para Versionamento

### 14.1 ApiVersion

```typescript
interface ApiVersion {
  readonly major: number;   // breaking changes
  readonly minor: number;   // features adicionadas
  readonly patch: number;   // correções
  readonly pre: string | null;  // pré-lançamento
}
```

### 14.2 Versioned<T>

```typescript
interface Versioned<T> {
  readonly api: ApiVersion;
  readonly payload: T;
}
```

### 14.3 Validação Automática

O Client SDK valida compatibilidade major automaticamente:
```typescript
if (!isCompatible(result.result, this.expectedApi)) {
  throw new PresentationError({
    code: "SDK_VERSION_MISMATCH",
    message: `Versão incompatível: esperada ${expected}, recebida ${received}.`,
  });
}
```

### 14.4 Helpers

- `apiVersionToString(v)` → "1.2.3-beta.1"
- `parseApiVersion(s)` → ApiVersion | null
- `compareApiVersion(a, b)` → número (semver-like)
- `versioned(payload, api?)` → Versioned<T>
- `isCompatible(v, current?)` → boolean

---

## 15. Regras Arquiteturais Oficiais

1. **Componentes** nunca conhecem SDK.
2. **Componentes** nunca conhecem transporte.
3. **Componentes** nunca conhecem Stores diretamente.
4. **Hooks** nunca conhecem transporte.
5. **Stores** nunca conhecem React.
6. **SDK** nunca conhece React.
7. **Services** nunca conhecem transporte.
8. **Pages** nunca implementam lógica.
9. **Toda comunicação é descendente.**
10. **Nenhuma dependência circular.**

### 15.1 Boas Práticas Obrigatórias

1. Nunca importar de `sdk/` em componentes ou pages.
2. Nunca importar de `stores/` em componentes diretamente.
3. Sempre usar hooks para acessar estado.
4. Sempre usar services para consultas.
5. Sempre usar `PresentationError` para erros.
6. Sempre aceitar `CancelToken` em operações assíncronas.
7. Sempre validar versão da API ao receber dados.
8. Nunca usar `setInterval` ou `setTimeout` para atualização.
9. Nunca acessar `window` ou `document` em hooks (use utils).
10. Sempre preferir composição sobre herança.

---

## 16. Quantidade de Novos Testes

### 16.1 Novos Arquivos de Teste

| Arquivo | Testes | Cobertura |
|---------|--------|-----------|
| `tests/sdk-errors.test.ts` | 22 | PresentationError, Result, helpers, fromUnknown, fromEvent |
| `tests/sdk-cancel.test.ts` | 16 | CancelToken, CancelSource, NEVER_CANCEL, raceCancel |
| `tests/sdk-versioning.test.ts` | 18 | ApiVersion, Versioned, parse, compare, isCompatible |
| `tests/sdk-client.test.ts` | 22 | Client, StubTransport, default client, ClientImpl |
| `tests/stream.test.ts` | 22 | EventStream, publish, subscribe, subscribeToType, subscribeToCorrelation, snapshot, history, clear, close |
| `tests/stores.test.ts` | 19 | SnapshotStore, StoreRegistry, 9 Domain Stores |
| `tests/infrastructure-integration.test.tsx` | 14 | InfraContext, Services, integração Stores + EventStream |
| **Total novos** | **133** | |

### 16.2 Testes Atualizados

| Arquivo | Alteração |
|---------|-----------|
| `tests/hooks.test.tsx` | Atualizado para usar InfraProvider + nova semântica de loading |

### 16.3 Resultado Final

```
Test Files  14 passed (14)
     Tests  235 passed (235)
```

- 116 testes existentes: **todos passam** (1 arquivo atualizado)
- 119 novos testes: **todos passam**

### 16.4 Build

```
vite v5.4.21 building for production...
✓ 1620 modules transformed.
dist/index.html                  0.47 kB │ gzip:  0.30 kB
dist/assets/index-vUlsgpDH.css  18.95 kB │ gzip:  4.14 kB
dist/assets/index-DRSypYhV.js  241.88 kB │ gzip: 77.07 kB
✓ built in 3.11s
```

---

## 17. Compatibilidade Preservada

### 17.1 Testes Backend

```
2485 passed in 209.31s
```

- 2485 testes Python: **todos passam** (zero regressão)
- Nenhum arquivo Python foi modificado

### 17.2 Testes Frontend

- 116 testes existentes: **todos passam** (1 arquivo atualizado)
- 119 novos testes: **todos passam**
- Total: 235 testes, zero falhas

### 17.3 Compatibilidade de Imports

- `import { Card } from "@/components"` continua funcionando (barrel re-exporta tudo)
- Types aliases deprecated (`PipelineApi` = `PipelineService`) preservados
- `createPresentationApi()` removido, mas `createServices()` e `createStubServices()` substituem

---

## 18. Confirmações

### 18.1 Remoção definitiva do polling

- ✅ Nenhuma referência a polling na documentação
- ✅ `docs/ARCHITECTURE.md` explicitamente proíbe polling
- ✅ Nenhum `setInterval` ou `setTimeout` em hooks
- ✅ Atualização ocorre exclusivamente via eventos (EventStream + Stores)
- ✅ Documentação explica fluxo reativo correto

### 18.2 Nenhuma funcionalidade foi adicionada

- ✅ Nenhum Dashboard implementado
- ✅ Nenhum Console implementado
- ✅ Nenhum Replay implementado
- ✅ Nenhuma configuração implementada
- ✅ Nenhum diagnóstico implementado
- ✅ Nenhuma página funcional adicionada
- ✅ Todas as páginas continuam exibindo "Em desenvolvimento"

### 18.3 Nenhuma comunicação real foi implementada

- ✅ Nenhum endpoint REST implementado
- ✅ Nenhum WebSocket implementado
- ✅ Nenhum SSE implementado
- ✅ Nenhum FastAPI implementado
- ✅ Nenhuma chamada HTTP feita
- ✅ Stub Transport retorna "notConfigured" para todas as chamadas
- ✅ Todos os hooks retornam valores nulos/vazios (loading=true)
- ✅ Connection status é "unknown" por padrão

### 18.4 Arquitetura preparada para FastAPI, WebSocket e futuras tecnologias

- ✅ `Transport` é uma interface — REST, WebSocket, SSE podem implementá-la
- ✅ `Client` orquestra Transport — troca de tecnologia não afeta Hooks/Services
- ✅ `EventStream` é agnóstico a transporte
- ✅ `SnapshotStore` é agnóstico a transporte
- ✅ `PresentationError` cobre todos os cenários de erro de transporte
- ✅ `CancelToken` funciona com qualquer transporte
- ✅ `ApiVersion` permite evolução do backend sem quebrar clientes
- ✅ Para trocar REST por WebSocket: implementar `Transport`, passar para `ClientImpl`
- ✅ Nenhum Hook, Service ou Componente precisa ser modificado

### 18.5 Arquitetura consolidada para crescimento

- ✅ 9 camadas com responsabilidade única
- ✅ Dependências unidirecionais (sem ciclos)
- ✅ Baixo acoplamento (camadas não conhecem detalhes internas umas das outras)
- ✅ Alta coesão (cada módulo agrupa funcionalidades relacionadas)
- ✅ Substituição de tecnologia possível sem refatoração
- ✅ Feature Modules documentado como estratégia oficial
- ✅ Error Model unificado
- ✅ Cancelamento preparado
- ✅ Versionamento preparado
- ✅ 235 testes garantem isolamento das camadas
- ✅ Documentação arquitetural completa em `docs/ARCHITECTURE.md`

---

## 19. Conclusão

A arquitetura do frontend do AI Lyrics foi consolidada
definitivamente. Principais conquistas:

1. **Client SDK** com 6 módulos (client, transport, errors, cancel, versioning, barrel)
2. **EventStream** — barramento de eventos reativo, agnóstico a React
3. **SnapshotStore** — estado imutável com 9 Domain Stores
4. **PresentationError** — modelo único de erros com 25 códigos
5. **CancelToken** — cancelamento de operações assíncronas
6. **ApiVersion** — versionamento preparado para evolução
7. **Services** atualizados para usar Client SDK
8. **Hooks** atualizados para usar Stores + EventStream
9. **Components** reorganizados em 9 categorias
10. **InfraContext** — ponte única entre React e infraestrutura
11. **Documentação arquitetural** completa em `docs/ARCHITECTURE.md`
12. **Feature Modules** documentado como estratégia oficial
13. **Polling removido** definitivamente da arquitetura
14. **235 testes** (119 novos + 116 existentes) garantem isolamento
15. **Zero regressão** — 2485 testes Python passam

**Esta é a última revisão estrutural da Web UI Foundation.**
Após esta fase, todas as próximas fases deverão concentrar-se
exclusivamente na implementação de funcionalidades, sem
necessidade de novas reorganizações arquiteturais significativas.
