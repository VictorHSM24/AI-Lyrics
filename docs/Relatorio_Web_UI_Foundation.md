# Relatório — Web UI Foundation

**Data:** 18 de julho de 2026
**Fase:** Web UI Foundation (infraestrutura base da interface web)
**Status:** Concluído
**Testes Frontend:** 116 passaram (Vitest)
**Testes Backend:** 2485 passaram (pytest), zero regressão
**Build:** Vite production build OK (233 KB JS, 19 KB CSS)

---

## 1. Objetivo

Criar a estrutura definitiva da aplicação web do AI Lyrics.
Esta fase NÃO implementa funcionalidades — apenas cria a fundação
arquitetural para que todas as próximas funcionalidades possam ser
adicionadas sem reorganização.

**Filosofia:**
- A interface nunca acessa o Core.
- A interface nunca conhece EventBus, EventStore, ou Pipeline.
- Toda comunicação futura ocorre exclusivamente através da
  Presentation Layer.
- A Web UI é completamente desacoplada da implementação interna.

---

## 2. Tecnologias

| Camada | Tecnologia | Versão |
|--------|-----------|--------|
| Framework | React | 18.3.1 |
| Linguagem | TypeScript | 5.5.4 |
| Bundler | Vite | 5.4.1 |
| Roteamento | React Router DOM | 6.26.0 |
| Estilos | Tailwind CSS | 3.4.10 |
| Ícones | Lucide React | 0.427.0 |
| Testes | Vitest + Testing Library | 2.0.5 + 16.0.0 |

**Backend (preparado, não implementado):**
- FastAPI (não implementado)
- WebSocket (não implementado)

---

## 3. Estrutura Criada

```
frontend/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tsconfig.node.json
├── tailwind.config.js
├── postcss.config.js
├── index.html
├── src/
│   ├── main.tsx                    # Entry point
│   ├── app/
│   │   ├── App.tsx                 # App root (providers + router)
│   │   ├── ErrorBoundary.tsx       # Boundary de erro
│   │   ├── index.ts
│   │   └── layout/
│   │       ├── AppLayout.tsx       # Layout principal
│   │       ├── Header.tsx          # Cabeçalho
│   │       ├── Sidebar.tsx         # Menu lateral
│   │       ├── Footer.tsx          # Rodapé
│   │       ├── PageLayout.tsx      # Layout padrão das páginas
│   │       └── index.ts
│   ├── pages/
│   │   ├── DashboardPage.tsx
│   │   ├── ConsolePage.tsx
│   │   ├── SessionsPage.tsx
│   │   ├── ReplayPage.tsx
│   │   ├── LogsPage.tsx
│   │   ├── ConfigurationPage.tsx
│   │   ├── DiagnosticPage.tsx
│   │   ├── AboutPage.tsx
│   │   ├── NotFoundPage.tsx        # Página 404
│   │   ├── ErrorPage.tsx           # Página de erro genérica
│   │   ├── DevelopmentPage.tsx     # Base para páginas em dev
│   │   └── index.ts
│   ├── components/                 # Design system (18 componentes)
│   │   ├── PageContainer.tsx
│   │   ├── Section.tsx
│   │   ├── Card.tsx
│   │   ├── Panel.tsx
│   │   ├── StatusBadge.tsx
│   │   ├── MetricCard.tsx
│   │   ├── Loading.tsx
│   │   ├── EmptyState.tsx
│   │   ├── ErrorState.tsx
│   │   ├── Divider.tsx
│   │   ├── Toolbar.tsx
│   │   ├── SearchBox.tsx
│   │   ├── Table.tsx
│   │   ├── Timeline.tsx
│   │   ├── PropertyGrid.tsx
│   │   ├── Modal.tsx
│   │   ├── ConfirmationDialog.tsx
│   │   ├── Toast.tsx
│   │   └── index.ts
│   ├── shared/
│   │   └── status.ts               # Enumeração de status visuais
│   ├── hooks/
│   │   └── index.ts                # 9 hooks vazios
│   ├── contexts/
│   │   ├── ThemeContext.tsx        # Light/Dark/System
│   │   ├── ApplicationContext.tsx  # Info da aplicação
│   │   ├── ConnectionContext.tsx   # Status da conexão
│   │   ├── NotificationsContext.tsx# Toast/notifications
│   │   └── index.ts
│   ├── services/
│   │   └── index.ts                # 8 interfaces de services
│   ├── api/
│   │   └── client.ts               # Stub de PresentationApi
│   ├── types/
│   │   └── index.ts                # Tipos refletindo DTOs
│   ├── utils/
│   │   └── index.ts                # Utilitários (format, cn, etc.)
│   ├── styles/
│   │   └── globals.css             # CSS global + variáveis de tema
│   ├── assets/                     # (vazio, preparado)
│   └── router/
│       └── index.tsx               # Roteamento completo
└── tests/
    ├── setup.ts                    # Setup do Vitest
    ├── components.test.tsx         # 40 testes de componentes
    ├── contexts.test.tsx           # 16 testes de contexts
    ├── layout.test.tsx             # 15 testes de layout
    ├── routing.test.tsx            # 17 testes de roteamento
    ├── hooks.test.tsx              |  12 testes de hooks
    ├── infrastructure.test.tsx     |  10 testes de infra (API, Toast, ErrorBoundary)
    └── utils.test.ts               |   6 testes de utils
```

---

## 4. Organização do Frontend

### 4.1 Diretórios e Responsabilidades

| Diretório | Responsabilidade |
|-----------|-----------------|
| `app/` | Root, layout, error boundary |
| `app/layout/` | Header, Sidebar, Footer, PageLayout |
| `pages/` | Páginas da aplicação (8 + 2 de erro) |
| `components/` | Design system reutilizável (18 componentes) |
| `shared/` | Constantes e enums compartilhados |
| `hooks/` | Hooks customizados (9 hooks) |
| `contexts/` | Contexts globais (4 contexts) |
| `services/` | Interfaces de services (8 interfaces) |
| `api/` | Cliente API (stub) |
| `types/` | Tipos TypeScript refletindo DTOs |
| `utils/` | Funções utilitárias |
| `styles/` | CSS global e variáveis de tema |
| `assets/` | Assets estáticos (preparado, vazio) |
| `router/` | Configuração de roteamento |

### 4.2 Fluxo de Dependências

```
pages → components, hooks, contexts
hooks → contexts, services, types
services → types
api → services
components → shared, utils, types
contexts → (independentes)
```

**Regra:** Nenhum módulo importa diretamente do Core. Toda
comunicação futura será via services → api → Presentation Layer.

---

## 5. Layout

### 5.1 Estrutura

```
AppLayout
├── Header (h-14)
│   ├── Logo + Nome + Versão
│   ├── Pipeline indicator
│   ├── Connection status
│   └── Theme toggle (Light/Dark/System)
├── Sidebar (w-60)
│   └── 8 itens de navegação
├── Main content (flex-1, scrollable)
│   └── Page content
└── Footer (h-8)
```

### 5.2 Header

Prepara espaço para:
- Logo AI Lyrics (ícone Mic)
- Nome da aplicação + versão
- Indicador do Pipeline (placeholder)
- Status da conexão (4 estados: connected, disconnected, connecting, unknown)
- Toggle de tema (Light/Dark/System)
- Menu do usuário (preparado)

### 5.3 Sidebar

Menu definitivo com 8 itens:
1. Dashboard → `/`
2. Console → `/console`
3. Sessões → `/sessoes`
4. Replay → `/replay`
5. Logs → `/logs`
6. Configurações → `/configuracoes`
7. Diagnóstico → `/diagnostico`
8. Sobre → `/sobre`

Todos usam `NavLink` com estado ativo. Responsivo: colapsa em mobile.

### 5.4 Responsividade

- **Desktop (lg+):** Sidebar fixa, layout horizontal
- **Tablet/Mobile:** Sidebar colapsável com overlay, botão de menu

---

## 6. Componentes Reutilizáveis (Design System)

18 componentes criados, todos sem lógica de negócio:

| Componente | Responsabilidade |
|-----------|-----------------|
| `PageContainer` | Container de página com padding |
| `Section` | Seção com título, descrição e actions |
| `Card` | Card com título, descrição e actions |
| `Panel` | Painel com header opcional |
| `StatusBadge` | Badge de status visual (10 estados) |
| `MetricCard` | Card de métrica com label, value, unit, status |
| `Loading` | Spinner com label |
| `EmptyState` | Estado vazio com ícone e descrição |
| `ErrorState` | Estado de erro com ícone e action |
| `Divider` | Separador horizontal (com label opcional) |
| `Toolbar` | Barra de ferramentas |
| `SearchBox` | Campo de busca com ícone |
| `Table` | Tabela genérica com columns e data |
| `Timeline` | Timeline de eventos |
| `PropertyGrid` | Grid de propriedades (label/value) |
| `Modal` | Modal acessível (ESC, overlay click) |
| `ConfirmationDialog` | Dialog de confirmação |
| `Toast` | Container de notificações toast |

---

## 7. Sistema de Páginas

### 7.1 Padrão Visual

Toda página segue exatamente o mesmo padrão:
```
PageLayout
├── PageHeader
│   ├── Título (h1)
│   ├── Descrição
│   └── Toolbar (opcional)
└── PageContent
    └── ... conteúdo ...
```

### 7.2 Páginas Criadas (10)

| Página | Rota | Conteúdo |
|--------|------|----------|
| Dashboard | `/` | Em desenvolvimento |
| Console | `/console` | Em desenvolvimento |
| Sessões | `/sessoes` | Em desenvolvimento |
| Replay | `/replay` | Em desenvolvimento |
| Logs | `/logs` | Em desenvolvimento |
| Configurações | `/configuracoes` | Em desenvolvimento |
| Diagnóstico | `/diagnostico` | Em desenvolvimento |
| Sobre | `/sobre` | Info da aplicação + arquitetura |
| NotFound (404) | `*` | Página 404 com link para Dashboard |
| ErrorPage | — | Página de erro genérica |

---

## 8. Sistema de Roteamento

### 8.1 Configuração

Roteamento completo com `createBrowserRouter`. Todas as 8 rotas
principais + rota catch-all para 404.

### 8.2 Error Boundary

Cada rota é envolvida por `ErrorBoundary` que captura erros e
exibe `ErrorPage` com botão "Tentar novamente".

### 8.3 Estrutura

```tsx
<ErrorBoundary>
  <AppLayout>
    <XxxPage />
  </AppLayout>
</ErrorBoundary>
```

---

## 9. Contexts (Estado Global)

4 contexts preparados, nenhum com dados reais:

| Context | Estado | Propósito |
|---------|--------|-----------|
| `ThemeContext` | mode, resolved, toggle | Light/Dark/System com persistência |
| `ApplicationContext` | info (name, version, description) | Metadados da aplicação |
| `ConnectionContext` | status, backendUrl, lastConnectedAt | Status da conexão com backend |
| `NotificationsContext` | notifications[], notify, dismiss, clear | Sistema de toast/notificações |

### 9.1 ThemeContext

- 3 modos: `light`, `dark`, `system`
- Persiste em `localStorage`
- Responde a `prefers-color-scheme` do SO
- Aplica classe `dark` no `<html>`
- Toggle rápido entre light/dark

### 9.2 NotificationsContext

- 4 tipos: `info`, `success`, `warning`, `error`
- API: `notify(type, title, message)`, `dismiss(id)`, `clear()`
- Auto-dismiss após 5 segundos (no Toast component)

---

## 10. Hooks (9)

Todos retornam valores padrão (null/empty). Sem chamadas HTTP.

| Hook | Retorna | Preparado para |
|------|---------|----------------|
| `useConnectionStatus()` | status, lastConnectedAt | Status da conexão |
| `usePipeline()` | status, snapshot, loading, error | Status do pipeline |
| `useMetrics()` | metrics, loading, error | Métricas |
| `useHealth()` | health, loading, error | Health check |
| `useSession()` | session, loading, error | Sessão atual |
| `useReplay()` | events, sessionIds, loading, error | Replay de eventos |
| `useConfiguration()` | configuration, loading, error | Configuração |
| `useDiagnostics()` | diagnostics, loading, error | Diagnósticos |
| `useEvents()` | events, loading, error | Eventos |

---

## 11. Services Preparados (8 interfaces)

Nenhum implementa comunicação real. Todos são apenas contratos.

| Service | Métodos |
|---------|---------|
| `PipelineApi` | getStatus, getSession, getMetrics, getSnapshot |
| `SessionApi` | getCurrentSession |
| `MetricsApi` | getMetrics |
| `ConfigurationApi` | getConfiguration |
| `HealthApi` | getHealth |
| `DiagnosticsApi` | getDiagnostics |
| `EventApi` | getAllEvents, getEventsByCorrelation, getEventsBySession, getEventSnapshot |
| `ReplayApi` | getReplayEvents, getReplaySessions, getReplayCorrelations |
| `PresentationApi` | Aggregador de todos os services acima |

### 11.1 API Stub

`createPresentationApi()` retorna um stub onde todos os métodos
lançam `"não implementada"`. Quando o backend FastAPI existir,
substituir por implementação real com `fetch()`.

---

## 12. Tipos Preparados

`src/types/index.ts` reflete EXCLUSIVAMENTE os DTOs da Presentation
Layer do backend. NUNCA objetos internos do Core.

### 12.1 DTOs de Apresentação (9)

- `EventMetadataDTO`
- `EventDTO`
- `PipelineStatusDTO`
- `SessionDTO`
- `MetricsDTO`
- `ConfigurationDTO`
- `HealthDTO` + `HealthStatus` + `HealthSnapshot`
- `DiagnosticDTO`
- `LogDTO`

### 12.2 DTOs de Domínio (6)

- `CandidateDTO`
- `EvidenceDTO`
- `SignalDTO`
- `ScoreDTO`
- `RecommendationDTO`
- `PresentationDTO`

### 12.3 Snapshots (5)

- `PipelineSnapshot`
- `SessionSnapshot`
- `MetricsSnapshot`
- `ConfigurationSnapshot`
- `EventSnapshot`

---

## 13. Sistema de Tema

### 13.1 Modos

- **Light:** tema claro (padrão)
- **Dark:** tema escuro
- **System:** segue o SO

### 13.2 Implementação

- CSS variables em `:root` (light) e `.dark` (dark)
- Tailwind config mapeia variables para classes semânticas
- `ThemeContext` aplica classe `dark` no `<html>`
- Persistência em `localStorage`
- Responde a `prefers-color-scheme` em tempo real

### 13.3 Tokens Semânticos

| Token | Light | Dark |
|-------|-------|------|
| `surface` | branco | slate-900 |
| `surface-hover` | slate-50 | slate-800 |
| `surface-raised` | slate-100 | slate-700 |
| `border` | slate-200 | slate-700 |
| `text` | slate-900 | slate-100 |
| `text-muted` | slate-600 | slate-400 |
| `accent` | blue-500 | blue-400 |
| `status-*` | cores padrão | cores mais claras |

---

## 14. Sistema de Status

### 14.1 Status Visuais (10)

| Status | Label | Cor |
|--------|-------|-----|
| `healthy` | Saudável | verde |
| `warning` | Atenção | amarelo |
| `error` | Erro | vermelho |
| `offline` | Offline | cinza |
| `unknown` | Desconhecido | cinza claro |
| `processing` | Processando | roxo |
| `paused` | Pausado | laranja |
| `running` | Executando | verde |
| `success` | Sucesso | verde |
| `info` | Informação | azul |

### 14.2 Conversão

`healthToVisualStatus()` converte `HealthStatus` do backend para
`VisualStatus` do frontend:
- `healthy` → `healthy`
- `degraded` → `warning`
- `unhealthy` → `error`
- `unknown` → `unknown`

---

## 15. Estratégia de Evolução

### 15.1 Dashboard

**Atual:** Página vazia com "Em desenvolvimento".

**Evolução:**
1. Implementar `HealthApi.getHealth()` no backend FastAPI
2. Implementar `useHealth()` hook com chamada real
3. Adicionar `MetricCard` components para cada métrica
4. Adicionar `StatusBadge` para cada componente de health
5. Adicionar gráficos (futuro: recharts ou visx)
6. Polling ou WebSocket para atualização em tempo real

### 15.2 Console

**Atual:** Página vazia com "Em desenvolvimento".

**Evolução:**
1. Implementar `PipelineApi.getStatus()` no backend
2. Implementar `usePipeline()` hook com polling
3. Adicionar `Timeline` para eventos em tempo real
4. WebSocket para streaming de eventos
5. `EventDTO` → `Timeline` items
6. Filtros por tipo de evento

### 15.3 Replay

**Atual:** Página vazia com "Em desenvolvimento".

**Evolução:**
1. Implementar `ReplayApi` no backend
2. Implementar `useReplay()` hook
3. Lista de sessões disponíveis
4. Seleção de correlation_id
5. `Timeline` com eventos do correlation
6. Player controls (play, pause, step)

### 15.4 Configurações

**Atual:** Página vazia com "Em desenvolvimento".

**Evolução:**
1. Implementar `ConfigurationApi.getConfiguration()` no backend
2. Implementar `useConfiguration()` hook
3. `PropertyGrid` para exibir configuração
4. `Card` por seção (holyrics, stt, llm, search, etc.)
5. Futuro: formulário de edição (write-back via API)

---

## 16. Acessibilidade

Preparado desde o início:

- **ARIA:** `role`, `aria-label`, `aria-modal`, `aria-pressed`, `aria-live`
- **Navegação por teclado:** ESC fecha Modal, focus visible
- **Contraste:** tokens semânticos garantem contraste adequado
- **Foco visível:** `:focus-visible` com ring accent
- **Semântica:** `<header>`, `<aside>`, `<main>`, `<footer>`, `<nav>`
- **Labels:** todos os botões têm `aria-label`

---

## 17. Notificações

### 17.1 Toast

- `ToastContainer` renderiza no canto inferior direito
- 4 tipos: info, success, warning, error
- Auto-dismiss após 5 segundos
- Botão de fechar manual
- Acessível: `role="alert"`, `aria-live`

### 17.2 Confirmation

- `ConfirmationDialog` baseado em `Modal`
- Botões Confirmar/Cancelar
- Ícone de alerta

### 17.3 Alert / Info

Preparado via `NotificationsContext.notify(type, title, message)`.

---

## 18. Erros

### 18.1 Página 404

`NotFoundPage` exibe "404" + mensagem + link para Dashboard.

### 18.2 Página de Erro

`ErrorPage` exibe ícone + mensagem + botão "Tentar novamente".

### 18.3 Error Boundary

`ErrorBoundary` captura erros de render e exibe `ErrorPage`.

### 18.4 Estados Vazios

- `EmptyState`: estado vazio genérico
- `Loading`: estado de carregamento
- `ErrorState`: estado de erro inline

---

## 19. Testes

### 19.1 Testes Frontend (Vitest)

| Arquivo | Testes | Cobertura |
|---------|--------|-----------|
| `components.test.tsx` | 40 | Todos os 18 componentes |
| `contexts.test.tsx` | 16 | 4 contexts (valores padrão, toggle, notify, dismiss, clear, erro fora do provider) |
| `layout.test.tsx` | 15 | Header, Sidebar, Footer, AppLayout, PageLayout |
| `routing.test.tsx` | 17 | 8 páginas + 404 + padrão visual |
| `hooks.test.tsx` | 12 | 9 hooks (valores padrão) + 4 contexts (erro fora do provider) |
| `infrastructure.test.tsx` | 10 | API stub, Toast, ErrorBoundary, ErrorPage |
| `utils.test.ts` | 6 | status.ts + utils.ts |
| **Total** | **116** | |

### 19.2 Resultado

```
Test Files  7 passed (7)
     Tests  116 passed (116)
```

### 19.3 Build

```
vite v5.4.21 building for production...
✓ 1607 modules transformed.
dist/index.html                  0.47 kB │ gzip:  0.30 kB
dist/assets/index-vUlsgpDH.css  18.95 kB │ gzip:  4.14 kB
dist/assets/index-DnHTLWl_.js  233.51 kB │ gzip: 74.46 kB
✓ built in 3.38s
```

### 19.4 Testes Backend (Python)

```
2485 passed in 209.24s
```

- 2485 testes Python existentes: **todos passam** (zero regressão)
- Nenhum arquivo Python foi modificado

---

## 20. Confirmações

### 20.1 Nenhuma funcionalidade do Core foi alterada

- ✅ Nenhum arquivo Python foi modificado
- ✅ Nenhum componente do Core foi alterado
- ✅ Nenhum teste Python foi modificado
- ✅ 2485 testes Python passam sem alteração

### 20.2 Toda comunicação permanece inexistente

- ✅ Nenhum endpoint REST implementado
- ✅ Nenhum WebSocket implementado
- ✅ Nenhum SSE implementado
- ✅ Nenhum FastAPI implementado
- ✅ Nenhuma chamada HTTP feita
- ✅ Nenhum dado real é exibido
- ✅ API stub lança "não implementada" para todos os métodos
- ✅ Todos os hooks retornam valores nulos/vazios
- ✅ Connection status é "unknown" por padrão

### 20.3 Restrições respeitadas

- ✅ Não implementou Dashboard, Console, Replay, Logs, Configurações, Diagnóstico
- ✅ Não implementou REST, FastAPI, WebSocket, SSE
- ✅ Não implementou autenticação, banco, polling, eventos
- ✅ Não implementou gráficos, chamadas HTTP, dados reais
- ✅ Responsabilidade única (cada diretório tem função clara)
- ✅ Baixo acoplamento (interface não conhece Core)
- ✅ Alta coesão (componentes agrupados por função)
- ✅ Sem estado global indevido (apenas 4 contexts necessários)
- ✅ Sem números mágicos (cores via CSS variables, labels via STATUS_CONFIG)
- ✅ Sem duplicação (componentes reutilizáveis, PageLayout padrão)
- ✅ Acessibilidade desde o início (ARIA, teclado, contraste, foco)
- ✅ Responsividade desde o início (mobile, tablet, desktop)
- ✅ Uma única biblioteca de ícones (Lucide)

---

## 21. Conclusão

A fundação arquitetural da interface web do AI Lyrics foi criada
com sucesso. Principais conquistas:

1. **Estrutura definitiva** em `frontend/` com 14 diretórios, cada
   um com responsabilidade única.
2. **18 componentes reutilizáveis** formando o design system.
3. **8 páginas** + 2 páginas de erro, todas seguindo o mesmo padrão
   visual.
4. **Roteamento completo** com ErrorBoundary em cada rota.
5. **4 contexts** para estado global (Theme, Application,
   Connection, Notifications).
6. **9 hooks** preparados para futura integração.
7. **8 interfaces de services** definindo contratos para comunicação
   com o backend.
8. **Tipos TypeScript** refletindo exclusivamente os DTOs da
   Presentation Layer.
9. **Sistema de tema** Light/Dark/System com persistência.
10. **Sistema de status** com 10 estados visuais reutilizáveis.
11. **Acessibilidade** preparada desde o início.
12. **Responsividade** preparada para desktop, tablet e mobile.
13. **116 testes frontend** cobrindo componentes, contexts, layout,
    roteamento, hooks, infraestrutura e utils.
14. **Build de produção** funcionando (233 KB JS, 19 KB CSS).
15. **Zero regressão** — 2485 testes Python passam sem alteração.

Após esta fase, todas as próximas funcionalidades poderão ser
adicionadas sobre esta estrutura, sem necessidade de reorganização
arquitetural.
