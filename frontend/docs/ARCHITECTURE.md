# AI Lyrics — Web UI Architecture

> **Architecture Freeze** — 18 de julho de 2026
>
> Após esta fase, nenhuma reorganização arquitetural significativa
> deverá ser necessária. Todas as próximas fases apenas adicionam
> funcionalidades sobre esta estrutura.

---

## 1. Filosofia

O frontend do AI Lyrics é **completamente orientado a eventos**.

- O frontend **nunca** conhece o Core.
- O frontend **nunca** conhece EventBus, EventStore, ou Pipeline.
- O frontend **nunca** conhece transporte (REST, WebSocket, SSE).
- Toda comunicação ocorre exclusivamente através da **Presentation Layer**.
- Toda atualização visual é consequência de **eventos**, nunca de polling.

### 1.1 Proibições

- ❌ Polling
- ❌ `setInterval` para atualização
- ❌ Refresh periódico
- ❌ Timers de atualização
- ❌ Acesso direto ao Core

### 1.2 Princípios

- ✅ SOLID
- ✅ Clean Architecture
- ✅ Clean Code
- ✅ Baixo acoplamento
- ✅ Alta coesão
- ✅ Responsabilidade única
- ✅ Arquitetura orientada a eventos
- ✅ Arquitetura reativa

---

## 2. Camadas Arquiteturais

```
┌─────────────────────────────────────────────────┐
│                  PAGES                          │
│  (Apenas orquestram componentes)                │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│               COMPONENTS                        │
│  (Design System — não conhecem SDK nem Stores)  │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│                  HOOKS                          │
│  (Consomem Stores + Services + EventStream)     │
└──────┬───────────────────────┬──────────────────┘
       │                       │
┌──────▼──────┐         ┌──────▼──────────────────┐
│   STORES    │         │       SERVICES          │
│ (Snapshots) │         │ (Consultas somente)     │
└──────┬──────┘         └──────┬──────────────────┘
       │                       │
┌──────▼──────────┐    ┌───────▼──────────────────┐
│  EVENT STREAM   │    │      CLIENT SDK          │
│ (Barramento)    │    │ (Serialização, erros)    │
└─────────────────┘    └───────┬──────────────────┘
                               │
                       ┌───────▼──────────────────┐
                       │       TRANSPORT          │
                       │ (REST / WS / SSE)        │
                       └───────┬──────────────────┘
                               │
                       ┌───────▼──────────────────┐
                       │   PRESENTATION LAYER     │
                       │      (Backend)           │
                       └──────────────────────────┘
```

### 2.1 Responsabilidades

| Camada | Responsabilidade | Conhece |
|--------|-----------------|---------|
| **Pages** | Orquestrar componentes | Components, Hooks |
| **Components** | Renderizar UI | Apenas si mesmos |
| **Hooks** | Ponte React ↔ infra | Stores, Services, EventStream |
| **Stores** | Estado (snapshots) | Nada (puro TS) |
| **Services** | Consultas | Client SDK |
| **EventStream** | Barramento de eventos | Nada (puro TS) |
| **Client SDK** | Serialização, erros, timeout | Transport |
| **Transport** | Comunicação real | Backend |

### 2.2 Regras Oficiais

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

---

## 3. Fluxo de Dados

```
Backend (Presentation Layer)
    │
    │ DTOs (imutáveis, serializáveis)
    ▼
Transport (REST/WS/SSE)
    │
    │ Versioned<T>
    ▼
Client SDK
    │
    │ Desserialização + validação de versão
    ▼
Services
    │
    │ Promise<T>
    ▼
Hooks
    │
    │ Store.set(data)
    ▼
SnapshotStore
    │
    │ Snapshot<T> (imutável)
    ▼
Hooks (useStoreSnapshot)
    │
    │ Re-render
    ▼
Components
    │
    ▼
Usuário
```

---

## 4. Fluxo de Eventos

```
Backend (EventBus)
    │
    │ EventDTO
    ▼
Transport (WebSocket)
    │
    │ message
    ▼
Client SDK
    │
    │ ClientEvent
    ▼
EventStream
    │
    │ StreamEvent
    ├──→ SnapshotStore (atualiza estado)
    │
    └──→ Hooks (subscribe)
              │
              ▼
         Components (re-render)
```

### 4.1 EventStream

- Recebe eventos do Client SDK
- Distribui para subscribers
- Mantém histórico recente (configurável, padrão 1000)
- Fornece snapshot do stream
- **Não interpreta eventos**
- **Não executa lógica de negócio**
- **Não conhece React**

### 4.2 SnapshotStore

- Transforma fluxo de eventos em estado consumível
- Mantém último snapshot
- Emite notificações de mudança
- **Componentes nunca reconstruem estado manualmente**
- **Componentes consomem snapshots**

---

## 5. Client SDK

### 5.1 Estrutura

```
src/sdk/
├── index.ts          # Barrel público
├── client.ts         # Client (orquestra Transport)
├── transport.ts      # Contrato de transporte
├── errors.ts         # PresentationError + Result<T>
├── cancel.ts         # CancelToken + CancelSource
└── versioning.ts     # ApiVersion + Versioned<T>
```

### 5.2 Responsabilidades Futuras

- Serialização / desserialização
- Timeout
- Tratamento de erros
- Heartbeat
- Reconexão
- Cache
- Versionamento
- Autenticação futura
- Multiplexação de conexões

### 5.3 Contratos

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

### 5.4 Substituição de Transporte

Para trocar REST por WebSocket (ou vice-versa):
1. Implementar `Transport` para a nova tecnologia.
2. Passar a nova implementação para `ClientImpl`.
3. **Nenhum Hook, Service ou Componente precisa ser modificado.**

---

## 6. Error Model

### 6.1 PresentationError

```typescript
class PresentationError extends Error {
  readonly code: ErrorCode;
  readonly message: string;
  readonly details: Record<string, unknown>;
  readonly recoverable: boolean;
  readonly severity: ErrorSeverity;
  readonly correlationId: string | null;
  readonly timestamp: number;
  readonly cause: PresentationError | null;
}
```

### 6.2 Severity

| Severity | Significado |
|----------|-------------|
| `info` | Apenas log, sem impacto visual |
| `low` | Impacto mínimo |
| `medium` | Funcionalidade degradada |
| `high` | Funcionalidade indisponível |
| `critical` | Toda a interface deve parar |

### 6.3 Result<T>

Alternativa a `throw` para fluxos controlados:

```typescript
type Result<T, E = PresentationError> =
  | { ok: true; value: T }
  | { ok: false; error: E };
```

---

## 7. Cancelamento

```typescript
interface CancelToken {
  readonly canceled: boolean;
  readonly reason: string | null;
  onCancel(callback: (reason: string | null) => void): () => void;
  throwIfCanceled(): void;
}
```

Toda chamada futura do Client SDK aceita `CallOptions.cancel`:
```typescript
client.call<T>("method", params, { cancel: token, timeoutMs: 5000 });
```

---

## 8. Versionamento

```typescript
interface Versioned<T> {
  readonly api: ApiVersion;
  readonly payload: T;
}

interface ApiVersion {
  readonly major: number;
  readonly minor: number;
  readonly patch: number;
  readonly pre: string | null;
}
```

O Client SDK valida compatibilidade major automaticamente.
Futuras versões do backend podem coexistir sem quebrar clientes antigos.

---

## 9. Organização de Diretórios

```
src/
├── app/              # Root, layout, error boundary
│   └── layout/
├── pages/            # Páginas (orquestram componentes)
├── components/       # Design System
│   ├── common/       # Genéricos
│   ├── layout/       # Layout
│   ├── feedback/     # Feedback visual
│   ├── navigation/   # Navegação
│   ├── status/       # Status
│   ├── metrics/      # Métricas
│   ├── tables/       # Tabelas
│   ├── timeline/     # Timeline
│   └── forms/        # Formulários (preparado)
├── shared/           # Constantes e enums
├── hooks/            # Hooks (consomem Stores + Services + Stream)
├── contexts/         # Contexts React
├── services/         # Services (consultas via Client SDK)
├── stores/           # SnapshotStore + Domain Stores
├── stream/           # EventStream
├── sdk/              # Client SDK
│   ├── client.ts
│   ├── transport.ts
│   ├── errors.ts
│   ├── cancel.ts
│   └── versioning.ts
├── types/            # Tipos (DTOs da Presentation Layer)
├── utils/            # Utilitários
├── styles/           # CSS global
├── assets/           # Assets
└── router/           # Roteamento
```

---

## 10. Feature Modules — Estratégia de Crescimento

Quando a aplicação crescer, a evolução ocorrerá por **módulos de funcionalidade**.

### 10.1 Estrutura Futura

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

### 10.2 Regras

- Cada feature é **autocontida**.
- Cada feature possui seus próprios componentes, hooks, services, types.
- Features podem importar de `components/` (Design System).
- Features **não** importam de outras features diretamente.
- Comunicação entre features ocorre via **Stores** ou **EventStream**.

### 10.3 Quando Migrar

A migração para `features/` ocorre quando:
- Uma página passa a ter componentes específicos.
- Uma página passa a ter hooks específicos.
- Uma página passa a ter services específicos.

**Não reorganizar agora.** A estrutura atual em `pages/` é suficiente
para a fase atual. A migração é incremental.

---

## 11. Páginas — Regra Arquitetural

> **Pages apenas orquestram componentes.**
>
> - Pages **nunca** implementam lógica.
> - Pages **nunca** fazem chamadas.
> - Pages **nunca** manipulam estado.

### Exemplo

```tsx
// ✅ Correto — Page apenas orquestra
function DashboardPage() {
  return (
    <PageLayout title="Dashboard" description="...">
      <DashboardMetrics />  {/* componente específico */}
      <DashboardHealth />   {/* componente específico */}
    </PageLayout>
  );
}

// ❌ Incorreto — Page com lógica
function DashboardPage() {
  const [data, setData] = useState(null);
  useEffect(() => {
    fetch("/api/dashboard").then(r => r.json()).then(setData);
  }, []);
  return <div>{data}</div>;
}
```

---

## 12. Atualização Reativa

### 12.1 Proibido

```typescript
// ❌ Polling
useEffect(() => {
  const id = setInterval(() => fetchStatus(), 5000);
  return () => clearInterval(id);
}, []);

// ❌ Refresh periódico
useEffect(() => {
  const id = setTimeout(() => window.location.reload(), 30000);
  return () => clearTimeout(id);
}, []);
```

### 12.2 Correto

```typescript
// ✅ Orientado a eventos
const { status } = usePipeline(); // assina Store
// Store é atualizada por EventStream → Client SDK → WebSocket

// ✅ Consulta única (sob demanda)
const { services } = useInfrastructure();
useEffect(() => {
  services.pipeline.getStatus().then(...);
}, []); // uma vez
```

---

## 13. Boas Práticas Obrigatórias

1. **Nunca** importar de `sdk/` em componentes ou pages.
2. **Nunca** importar de `stores/` em componentes diretamente.
3. **Sempre** usar hooks para acessar estado.
4. **Sempre** usar services para consultas.
5. **Sempre** usar `PresentationError` para erros.
6. **Sempre** aceitar `CancelToken` em operações assíncronas.
7. **Sempre** validar versão da API ao receber dados.
8. **Nunca** usar `setInterval` ou `setTimeout` para atualização.
9. **Nunca** acessar `window` ou `document` em hooks (use utils).
10. **Sempre** preferir composição sobre herança.

---

## 14. Diagrama de Dependências

```
pages → components, hooks
hooks → contexts, stores, services, stream
contexts → sdk, stores, stream, services
services → sdk
stores → (puro TS, sem deps)
stream → (puro TS, sem deps)
sdk → (puro TS, sem deps)
components → shared, utils, types
shared → (puro TS)
utils → (puro TS)
types → (puro TS)
```

**Nenhuma dependência circular.**
**Toda comunicação é descendente.**
