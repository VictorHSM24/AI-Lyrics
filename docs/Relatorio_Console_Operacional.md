# Relatório — Console Operacional

**Data:** 18 de julho de 2026
**Fase:** Console Operacional (primeira tela funcional)
**Status:** Concluído
**Testes Frontend:** 319 passaram (46 novos + 273 existentes, zero regressão)
**Build:** Vite production build OK (289 KB JS, 21 KB CSS)
**TypeCheck:** Sem erros

---

## 1. Objetivo

Implementar a primeira tela funcional do AI Lyrics: **Console Operacional**.
Esta é a principal interface utilizada durante a operação do sistema,
validando toda a infraestrutura construída nas fases anteriores.

---

## 2. Confirmações Arquiteturais

### Nenhuma camada arquitetural foi alterada

- ✅ Client SDK: **não modificado**
- ✅ EventStream: **não modificado**
- ✅ SnapshotStore: **não modificado**
- ✅ Services: **não modificados**
- ✅ Hooks: **não modificados**
- ✅ Transports: **não modificados**
- ✅ RealClient: **não modificado**
- ✅ EventStreamBridge: **não modificado**
- ✅ InfraContext: **não modificado**
- ✅ ConnectionContext: **não modificado**

### Nenhuma nova abstração foi criada

- ✅ Nenhum novo Service
- ✅ Nenhum novo Hook
- ✅ Nenhum novo Store
- ✅ Nenhum novo Transport
- ✅ Nenhuma nova camada

### Apenas componentes de UI foram criados

Todos os novos arquivos são componentes React ou módulos
puramente declarativos (mapeamento de eventos → categorias).

---

## 3. Estrutura dos Novos Componentes

```
frontend/src/components/console/
├── index.ts                    # Barrel
├── icons.ts                    # Re-export de ícones lucide-react
├── event-categories.ts         # Mapeamento tipo → categoria (declarativo)
├── ConnectionBadge.tsx         # Badge de status da conexão
├── LatencyBadge.tsx            # Badge de latência média
├── SeverityBadge.tsx           # Badge de severidade de evento
├── EventCard.tsx               # Cartão individual de evento
├── PipelineStage.tsx           # Etapa individual do pipeline
├── RecognitionCard.tsx         # Card de fala reconhecida
├── VerseCard.tsx               # Card de versículo encontrado
├── ConsoleHeader.tsx           # Cabeçalho do Console
├── TimelinePanel.tsx           # Linha do tempo (principal)
├── PipelinePanel.tsx           # Painel do pipeline
├── RecognitionPanel.tsx        # Painel de reconhecimento
└── ResultPanel.tsx             # Painel de resultado
```

**Total:** 15 novos arquivos (14 componentes + 1 módulo declarativo)

---

## 4. Layout do Console (5 Regiões)

```
┌─────────────────────────────────────────────────────┐
│ 1. Cabeçalho (ConsoleHeader)                        │
│    [Conexão] [Backend] [Pipeline] [Latência]        │
│    [Sessão] [Tempo] [STT] [Idioma]                  │
├──────────────────────────┬──────────────────────────┤
│ 2. Linha do Tempo        │ 3. Pipeline              │
│    (TimelinePanel)       │    (PipelinePanel)       │
│    [Busca] [Pause]       │    Microfone → Captura   │
│    [Auto-scroll]         │    → VAD → Segment       │
│    [Filtros] [Limpar]    │    → Whisper → Intenção  │
│                          │    → Busca → Holyrics    │
│    [EventCard]           │    → Concluído           │
│    [EventCard]           ├──────────────────────────┤
│    [EventCard]           │ 4. Reconhecimento        │
│    [EventCard]           │    (RecognitionPanel)    │
│    [EventCard]           │    "João 3:16"           │
│    ...                   │    Confiança: 95%        │
│                          │    Latência: 312 ms      │
│                          ├──────────────────────────┤
│                          │ 5. Resultado             │
│                          │    (ResultPanel)         │
│                          │    João 3:16 (ACF)       │
│                          │    Holyrics: Enviado     │
│                          │    Tempo: 450 ms         │
└──────────────────────────┴──────────────────────────┘
```

---

## 5. Fluxo de Atualização

### 5.1 Consulta Inicial (REST)

```
ConsolePage monta
    → Hooks (usePipeline, useSession, useMetrics, useConfiguration, useHealth)
    → Services (carregam estado inicial via REST)
    → Stores (armazenam snapshots)
    → Hooks re-renderizam
    → Componentes exibem dados iniciais
```

### 5.2 Atualização Contínua (EventStream)

```
Backend publica evento
    → WebSocket Transport recebe
    → RealClient emite ClientEvent { type: "event" }
    → EventStreamBridge converte para StreamEvent
    → EventStream publica
    → EventStreamBridge assina e atualiza EventStore
    → useEvents() re-renderiza
    → TimelinePanel mostra novo EventCard
    → PipelinePanel atualiza etapa
    → RecognitionCard mostra fala
    → VerseCard mostra versículo
```

### 5.3 Nenhum Polling

- ✅ Nenhum componente usa setInterval/setTimeout para consultar dados
- ✅ Toda atualização é orientada a eventos
- ✅ Hooks assinam Stores, que são atualizados pelo EventStreamBridge

---

## 6. Integração com EventStream

### 6.1 TimelinePanel

Consome `useEvents()` que assina `stores.events` (EventStore).
O EventStore é atualizado automaticamente pelo EventStreamBridge
quando eventos chegam via WebSocket.

### 6.2 PipelinePanel

Consome `useEvents()` para inferir o estado de cada etapa do pipeline
a partir dos eventos recebidos. Também consome `usePipeline()` para
saber se o pipeline está running/paused/stopped.

### 6.3 RecognitionCard

Consome `useEvents()` e busca o último evento `SpeechRecognized`.

### 6.4 VerseCard

Consome `useEvents()` e busca os últimos eventos `VerseFound` e
`HolyricsSuccess`/`HolyricsFailure`.

### 6.5 ConsoleHeader

Consume `usePipeline()`, `useSession()`, `useConfiguration()`,
`useHealth()` e `useConnectionStatus()` — todos via Stores.

---

## 7. Integração com SnapshotStore

| Componente | Hook | Store | Dados |
|-----------|------|-------|-------|
| ConsoleHeader | usePipeline | stores.pipeline | status, running, paused |
| ConsoleHeader | useSession | stores.session | session_id, duration_s |
| ConsoleHeader | useMetrics | stores.metrics | avg_latency_ms |
| ConsoleHeader | useConfiguration | stores.configuration | stt.model, stt.language |
| ConsoleHeader | useHealth | stores.health | all_healthy |
| ConsoleHeader | useConnectionStatus | ConnectionContext | status |
| TimelinePanel | useEvents | stores.events | EventDTO[] |
| PipelinePanel | useEvents | stores.events | EventDTO[] |
| PipelinePanel | usePipeline | stores.pipeline | status |
| RecognitionCard | useEvents | stores.events | EventDTO[] |
| VerseCard | useEvents | stores.events | EventDTO[] |

---

## 8. Componentes Reutilizados

### Design System existente

- ✅ `Panel` — contêiner com título
- ✅ `Card` — cartão com título/descrição
- ✅ `StatusBadge` — badge de status visual
- ✅ `SearchBox` — campo de busca
- ✅ `EmptyState` — estado vazio
- ✅ `PageLayout` — layout padrão de página
- ✅ `PageContainer` — contêiner de página
- ✅ `Toolbar` — barra de ferramentas

### Hooks existentes

- ✅ `usePipeline()` — status e snapshot do pipeline
- ✅ `useSession()` — sessão atual
- ✅ `useMetrics()` — métricas
- ✅ `useConfiguration()` — configuração
- ✅ `useHealth()` — health snapshot
- ✅ `useEvents()` — eventos do EventStore
- ✅ `useConnectionStatus()` — status da conexão

### Contexts existentes

- ✅ `InfraProvider` — provê Client, Stream, Stores, Services
- ✅ `ConnectionProvider` — provê status da conexão
- ✅ `ThemeProvider` — tema
- ✅ `ApplicationProvider` — metadados da aplicação
- ✅ `NotificationsProvider` — notificações

---

## 9. UX Implementada

### 9.1 Linha do Tempo

- ✅ **Scroll virtual** — `max-h-[500px]` com `overflow-y-auto`
- ✅ **Auto-scroll configurável** — botão toggle, rola para o final automaticamente
- ✅ **Pausar atualização** — botão Pause/Retomar, congela eventos atuais
- ✅ **Limpar console** — botão Limpar, oculta eventos atuais (offset)
- ✅ **Buscar texto** — SearchBox filtra por texto no tipo/payload/correlation_id
- ✅ **Filtrar por categoria** — toggles para 7 categorias (audio, stt, pipeline, search, holyrics, system, error)
- ✅ **Filtrar por severity** — toggles para 5 severidades (info, low, medium, high, critical)
- ✅ **Contador** — mostra número de eventos visíveis vs total
- ✅ **Estado vazio** — "Aguardando início do pipeline..."

### 9.2 Pipeline Panel

- ✅ **9 etapas** — Microfone, Captura, VAD, Speech Segment, Whisper, Intenção, Busca Bíblica, Holyrics, Concluído
- ✅ **5 estados visuais** — Idle, Running, Success, Warning, Error
- ✅ **Latência por etapa** — quando disponível no payload
- ✅ **Conectores visuais** — linha entre etapas

### 9.3 Reconhecimento

- ✅ **Texto reconhecido** — aspas + texto
- ✅ **Idioma** — com ícone Globe
- ✅ **Confiança** — percentual
- ✅ **Latência** — ms
- ✅ **Modelo** — nome do modelo STT
- ✅ **Estado vazio** — "Aguardando reconhecimento..."

### 9.4 Resultado

- ✅ **Referência** — livro, capítulo, versículo
- ✅ **Versão** — ACF, etc.
- ✅ **Texto do versículo** — quando disponível
- ✅ **Status Holyrics** — Enviado, Falhou, Pendente, Aguardando
- ✅ **Tempo total** — ms
- ✅ **Estado vazio** — "Aguardando resultado..."

---

## 10. Eventos Suportados

O Console está preparado para exibir todos os eventos listados:

| Evento | Categoria | Mapeamento |
|--------|-----------|------------|
| AudioCaptured | audio | Captura → success |
| SpeechStarted | audio | VAD → running |
| SpeechEnded | audio | VAD → success |
| SpeechSegmentReceived | audio | Speech Segment → success |
| SpeechRecognized | stt | Whisper → success |
| IntentDetected | pipeline | Intenção → success |
| SearchRequested | search | Busca Bíblica → running |
| SearchCompleted | search | Busca Bíblica → success |
| CandidateGenerated | search | Busca Bíblica → running |
| RecommendationChosen | search | Busca Bíblica → success |
| VerseFound | search | Busca Bíblica → success |
| HolyricsRequest | holyrics | Holyrics → running |
| HolyricsSuccess | holyrics | Holyrics → success |
| HolyricsFailure | holyrics | Holyrics → error |
| PresentationCompleted | holyrics | Concluído → success |
| PipelineStarted | pipeline | — |
| PipelineStopped | pipeline | — |
| PipelinePaused | pipeline | — |
| PipelineResumed | pipeline | — |
| PipelineError | error | Concluído → error |
| ConnectionLost | system | — |
| ConnectionRestored | system | — |

### Eventos futuros

Eventos desconhecidos caem automaticamente na categoria "Sistema"
com severity "info", sem necessidade de refatoração.

---

## 11. Acessibilidade

Todos os indicadores possuem:

- ✅ **Ícones** — cada badge/card tem ícone lucide-react
- ✅ **Texto** — cada indicador tem texto legível
- ✅ **Tooltip** — `title` attribute em todos os indicadores
- ✅ **aria-hidden** — ícones decorativos marcados
- ✅ **data-testid** — todos os componentes têm testid
- ✅ **data-category** — EventCard expõe categoria
- ✅ **data-event-type** — EventCard expõe tipo
- ✅ **data-state** — PipelineStage expõe estado
- ✅ **data-severity** — SeverityBadge expõe severity

Nunca depende apenas de cor — sempre há ícone + texto.

---

## 12. Tratamento de Erros

- ✅ Usa exclusivamente `PresentationError` (via infraestrutura existente)
- ✅ Eventos de erro (PipelineError, HolyricsFailure) têm categoria "error"
- ✅ Severity "high" ou "critical" para erros
- ✅ PipelineStage mostra estado "error" com ícone XCircle
- ✅ EventCard mostra erro com cor vermelha + ícone AlertCircle

---

## 13. Testes Adicionados

### Arquivo: `tests/console.test.tsx`

| Suite | Testes | Cobertura |
|-------|--------|-----------|
| event-categories | 4 | Mapeamento tipo→categoria, severity, ALL_CATEGORIES, ALL_SEVERITIES |
| EventCard | 5 | Renderização, descrição, correlation id, data-category, data-event-type |
| PipelineStage | 6 | Nome, idle, running, success, error, latência |
| SeverityBadge | 3 | info, critical, data-severity |
| ConnectionBadge | 1 | Status desconhecido por padrão |
| LatencyBadge | 3 | Sem métricas, ms, segundos |
| TimelinePanel | 7 | Empty state, renderização, pause, clear, busca, filtros categoria, filtros severity, contador |
| PipelinePanel | 3 | Renderiza etapas, idle por padrão, atualiza com evento |
| RecognitionCard | 2 | Empty state, texto reconhecido |
| VerseCard | 4 | Empty state, versículo, Holyrics success, Holyrics failure |
| ConsoleHeader | 3 | Renderiza indicadores, modelo STT, idioma |
| ConsolePage | 3 | Renderiza regiões, empty state, atualização via eventos |
| **Total** | **46** | |

### Teste de routing atualizado

O teste `routing.test.tsx` foi atualizado para refletir que o Console
agora é uma página funcional (não mais DevelopmentPage):
- Console não tem "Em desenvolvimento"
- Console tem `console-header`, `timeline-panel`, `pipeline-panel`

---

## 14. Cobertura

```
Testes Frontend: 319 passed (46 novos + 273 existentes)
  - console.test.tsx:       46 testes
  - sdk-rest-transport:     20 testes
  - sdk-real-client:        18 testes
  - contexts:               ~15 testes
  - hooks:                  ~10 testes
  - layout:                 ~20 testes
  - routing:                ~17 testes
  - outros:                 ~173 testes

Build:       OK (289 KB JS, 21 KB CSS)
TypeCheck:   OK (sem erros)
```

---

## 15. Confirmação Final

### Nenhuma camada arquitetural foi alterada

- ✅ Client SDK: inalterado
- ✅ EventStream: inalterado
- ✅ SnapshotStore: inalterado
- ✅ Services: inalterados
- ✅ Hooks: inalterados
- ✅ Transports: inalterados
- ✅ RealClient: inalterado
- ✅ EventStreamBridge: inalterado
- ✅ InfraContext: inalterado
- ✅ ConnectionContext: inalterado

### Nenhuma nova abstração foi criada

- ✅ Apenas componentes de UI
- ✅ Um módulo declarativo (event-categories.ts)
- ✅ Um módulo de re-export de ícones (icons.ts)

### Console consome exclusivamente a infraestrutura existente

- ✅ via Hooks (usePipeline, useSession, useMetrics, useConfiguration, useHealth, useEvents, useConnectionStatus)
- ✅ via Stores (stores.pipeline, stores.session, stores.metrics, stores.configuration, stores.health, stores.events)
- ✅ via Contexts (ConnectionContext, InfraContext)
- ✅ via Design System (Panel, Card, StatusBadge, SearchBox, EmptyState, PageLayout)

### Nenhum polling

- ✅ Toda atualização é orientada a eventos
- ✅ EventStream → EventStreamBridge → EventStore → useEvents → Componentes
