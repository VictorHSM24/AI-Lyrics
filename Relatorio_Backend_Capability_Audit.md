# Relatório de Auditoria — Backend Capability Audit

**Data:** 2026-07-19
**Fase:** Backend Capability Audit (INSPEÇÃO APENAS)
**Repositório:** AI Lyrics

---

## Sumário Executivo

O AI Lyrics possui um **backend robusto e funcional** com 6 módulos principais implementados e testados (~2000+ testes). A **API FastAPI** expõe 16 endpoints REST + 1 WebSocket, dos quais 11 são consumidos pelo frontend.

O **frontend** tem arquitetura bem estruturada (SDK, Stores, Contexts, Hooks), porém existe uma **desconexão crítica**: os Services chamam o backend mas **não populam os Stores** com os resultados. Apenas o `events` store é populado (via WebSocket → Bridge). Os outros 8 stores (pipeline, health, metrics, session, configuration, diagnostics, logs, replay) **permanecem vazios** durante a execução.

**Indicadores principais:**
- Backend: 6/6 módulos funcionais
- API: 16/16 endpoints implementados, 11/16 consumidos
- SDK: 16 métodos mapeados, 13 com backend correspondente, 3 órfãos (replay)
- Stores: 1/9 populados (events), 8/9 vazios
- Bridge: `updateDomainStores()` é stub vazio
- Startup: 8 etapas 100% simuladas (setTimeout)
- Configuration: persiste em localStorage, **não sincroniza** com backend
- Páginas: 3 integradas, 1 parcial, 5 placeholders

---

## 1. Matriz de Capacidades

Legenda: **E**=Existe | **F**=Funcional | **P**=Parcial | **A**=Apenas preparada | **N**=Não existe
Para API/SDK/Frontend: **✓**=Sim | **✗**=Não | **~**=Parcial

### Módulo: Áudio

| Capacidade | Backend | API | SDK | Frontend | Situação |
|------------|---------|-----|-----|----------|----------|
| enumeração de dispositivos | F | ✗ | ✗ | ~ (mock) | Backend funcional, não exposto na API |
| seleção de dispositivo | F | ✗ | ✗ | ~ (mock) | Backend funcional, não exposto |
| troca dinâmica | P | ✗ | ✗ | ✗ | Apenas reconexão após erro |
| VAD | F | ✗ | ✗ | ✗ | Backend funcional (Silero/webrtc/RMS) |
| RMS | F | ✗ | ✗ | ✗ | Backend funcional |
| Peak | N | ✗ | ✗ | ✗ | Não implementado |
| clipping | N | ✗ | ✗ | ✗ | Não implementado |
| latência | A | ✗ | ✗ | ✗ | Apenas documentada |
| teste de dispositivo | P | ✗ | ✗ | ~ (mock) | Apenas validação de existência |
| monitoramento contínuo | F | ✗ | ✗ | ✗ | CaptureMetrics funcional |

### Módulo: STT

| Capacidade | Backend | API | SDK | Frontend | Situação |
|------------|---------|-----|-----|----------|----------|
| inicialização | F | ✗ | ✗ | ✗ | STT class funcional |
| carregamento do modelo | F | ✗ | ✗ | ✗ | FasterWhisperBackend.load() |
| troca de modelo | N | ✗ | ✗ | ~ (UI existe) | UI permite trocar mas não envia ao backend |
| troca CPU/GPU | P | ✗ | ✗ | ~ (UI existe) | Apenas fallback GPU→CPU automático |
| métricas | F | ~ (em MetricsDTO) | ✓ | ~ (store vazio) | Backend expõe, store não populado |
| idioma | F | ~ (em ConfigurationDTO) | ✓ | ~ (UI existe) | Configurável mas não sincronizado |
| confiança | F | ~ (em MetricsDTO) | ✓ | ~ (store vazio) | Backend calcula, store vazio |
| fila | N | ✗ | ✗ | ✗ | Não implementado |
| cancelamento | N | ✗ | ✗ | ✗ | Não implementado |

### Módulo: Pipeline

| Capacidade | Backend | API | SDK | Frontend | Situação |
|------------|---------|-----|-----|----------|----------|
| eventos emitidos (15 tipos) | F | ✓ (WS) | ✓ | ✓ (events store) | Totalmente funcional via WS |
| estados | F | ✓ | ✓ | ~ (store vazio) | Backend expõe, store vazio |
| métricas | F | ✓ | ✓ | ~ (store vazio) | Backend expõe, store vazio |
| cancelamento | N | ✗ | ✗ | ✗ | Não implementado |
| restart | P | ✗ | ✗ | ✗ | Apenas reset interno |
| session lifecycle - start | F | ✗ | ✗ | ✗ | Sem endpoint para iniciar |
| session lifecycle - stop | F | ✗ | ✗ | ✗ | Sem endpoint para parar |
| session lifecycle - pause | F | ✗ | ✗ | ✗ | Sem endpoint para pausar |
| session lifecycle - resume | F | ✗ | ✗ | ✗ | Sem endpoint para resumir |

### Módulo: Busca

| Capacidade | Backend | API | SDK | Frontend | Situação |
|------------|---------|-----|-----|----------|----------|
| embeddings | F | ✗ | ✗ | ✗ | Backend funcional, não exposto |
| index | F | ✗ | ✗ | ✗ | Backend funcional, não exposto |
| reranker | F | ✗ | ✗ | ✗ | Backend funcional, não exposto |
| planner | F | ✗ | ✗ | ✗ | Backend funcional, não exposto |
| ranking | F | ✗ | ✗ | ✗ | Backend funcional, não exposto |
| cache | F | ✗ | ✗ | ✗ | Backend funcional, não exposto |

### Módulo: Intelligence

| Capacidade | Backend | API | SDK | Frontend | Situação |
|------------|---------|-----|-----|----------|----------|
| coordinator | F | ✗ | ✗ | ✗ | Backend funcional |
| evidence | F | ✗ | ✗ | ✗ | Backend funcional |
| strategies (8) | F | ✗ | ✗ | ✗ | Backend funcional |
| confidence | F | ✗ | ✗ | ✗ | Backend funcional |
| scoring | F | ✗ | ✗ | ✗ | Backend funcional |

### Módulo: Context

| Capacidade | Backend | API | SDK | Frontend | Situação |
|------------|---------|-----|-----|----------|----------|
| criação | F | ✗ | ✗ | ✗ | Backend funcional |
| atualização | F | ✗ | ✗ | ✗ | Backend funcional |
| expiração | F | ✗ | ✗ | ✗ | Backend funcional |
| limpeza | F | ✗ | ✗ | ✗ | Backend funcional |

### Módulo: Feedback

| Capacidade | Backend | API | SDK | Frontend | Situação |
|------------|---------|-----|-----|----------|----------|
| armazenamento | F | ✗ | ✗ | ✗ | FeedbackStore (JSON) |
| replay | A | ✗ | ✗ | ✗ | Apenas preparado |
| treinamento | A | ✗ | ✗ | ✗ | Não é ML por design |

### Módulo: Evaluation

| Capacidade | Backend | API | SDK | Frontend | Situação |
|------------|---------|-----|-----|----------|----------|
| métricas | F | ✗ | ✗ | ✗ | MetricsCalculator |
| persistência | F | ✗ | ✗ | ✗ | EvaluationStore (JSON) |
| relatórios | F | ✗ | ✗ | ✗ | ReportGenerator |

### Módulo: Presentation

| Capacidade | Backend | API | SDK | Frontend | Situação |
|------------|---------|-----|-----|----------|----------|
| snapshots | F | ✓ | ✓ | ~ (store vazio) | Backend expõe, store vazio |
| adapters | A | ✗ | ✗ | ✗ | Apenas contratos (ABCs) |
| observers | F | ✗ | ✗ | ✗ | Observers internos |
| mappers (12) | F | ✓ | ✓ | ~ (store vazio) | Backend mapeia, store vazio |

### Módulo: API REST

| Endpoint | Backend | SDK | Frontend | Situação |
|----------|---------|-----|----------|----------|
| GET /health | ✓ | ✓ | ✓ | Funcional |
| GET /health/live | ✓ | ✗ | ✗ | Órfão (útil para k8s) |
| GET /health/ready | ✓ | ✗ | ✗ | Órfão (útil para k8s) |
| GET /info | ✓ | ✗ | ✗ | Órfão |
| GET /pipeline/status | ✓ | ✓ | ~ (store vazio) | Backend ok, store vazio |
| GET /pipeline/session | ✓ | ✓ | ~ (store vazio) | Backend ok, store vazio |
| GET /pipeline/metrics | ✓ | ✓ | ~ (store vazio) | Backend ok, store vazio |
| GET /pipeline/snapshot | ✓ | ✓ | ~ (store vazio) | Backend ok, store vazio |
| GET /session/current | ✓ | ✓ | ~ (store vazio) | Backend ok, store vazio |
| GET /metrics | ✓ | ✓ | ~ (store vazio) | Backend ok, store vazio |
| GET /configuration | ✓ | ✓ | ~ (store vazio) | Backend ok, store vazio |
| GET /diagnostics | ✓ | ✓ | ~ (store vazio) | Backend ok, store vazio |
| GET /events | ✓ | ✓ | ✓ | Funcional |
| GET /events/by-correlation | ✓ | ✓ | ✗ | Órfão (sem uso direto) |
| GET /events/by-session | ✓ | ✓ | ✗ | Órfão (sem uso direto) |
| GET /events/snapshot | ✓ | ✓ | ✗ | Órfão (sem uso direto) |
| POST/PUT/DELETE (qualquer) | ✗ | ✗ | ✗ | API é apenas leitura |

### Módulo: WebSocket

| Evento | Publicado | Consumido | Situação |
|--------|-----------|-----------|----------|
| hello | ✓ | ✓ | Funcional |
| event (15 tipos pipeline) | ✓ | ✓ | Funcional (popula events store) |
| heartbeat_ack | ✓ | ✓ | Funcional |
| error (WsErrorModel) | ✗ | ✗ | **Morto** — schema existe, nunca emitido |

### Módulo: Frontend Pages

| Página | Status | Observação |
|--------|--------|------------|
| ConsolePage | TI | Totalmente integrada via EventStore |
| StartupPage | TI | Integrada com OperationContext (simulado) |
| ConfigurationPage | TI | Integrada com localStorage (não backend) |
| AboutPage | PI | Dados hardcoded (build, commit, backend version) |
| DashboardPage | PH | Placeholder via DevelopmentPage |
| LogsPage | PH | Placeholder |
| ReplayPage | PH | Placeholder |
| SessionsPage | PH | Placeholder |
| DiagnosticPage | PH | Placeholder |

### Módulo: Stores

| Store | Origem | Classificação |
|-------|--------|---------------|
| events | WebSocket via Bridge | **websocket** |
| pipeline | (vazio) | **vazio** |
| health | (vazio) | **vazio** |
| metrics | (vazio) | **vazio** |
| session | (vazio) | **vazio** |
| configuration | (vazio) | **vazio** |
| diagnostics | (vazio) | **vazio** |
| logs | (vazio) | **vazio** |
| replay | (vazio) | **vazio** |
| operation | local state | **local state** |
| settings | localStorage | **local state (persisted)** |

### Módulo: Contexts

| Context | Comunica Backend? | Classificação |
|---------|-------------------|---------------|
| ApplicationContext | ❌ | local state (static) |
| ConnectionContext | ✅ (via Client) | backend (indireto) |
| InfraContext | ✅ (cria Client) | backend (via SDK) |
| NotificationsContext | ❌ | local state |
| ThemeContext | ❌ | local state (persisted) |
| OperationContext | ❌ | local state (persisted) |

---

## 2. Lista Completa de Placeholders

| Arquivo | Linha | Descrição | Como substituir |
|---------|-------|-----------|-----------------|
| `presentation/services.py` | 308 | `speech_recognition_health()` placeholder | Implementar health check real do STT |
| `presentation/services.py` | 313 | `searcher_health()` placeholder | Implementar health check real do Searcher |
| `presentation/services.py` | 317 | `ranking_health()` placeholder | Implementar health check real do Ranking |
| `presentation/services.py` | 321 | `intelligence_health()` placeholder | Implementar health check real do Intelligence |
| `presentation/services.py` | 325 | `holyrics_health()` placeholder | Implementar health check real do Holyrics |
| `presentation/services.py` | 380 | `microphone_diagnostic()` placeholder | Implementar diagnóstico real de microfone |
| `presentation/services.py` | 388 | `gpu_diagnostic()` placeholder | Implementar diagnóstico real de GPU |
| `presentation/services.py` | 396 | `cpu_diagnostic()` placeholder | Implementar diagnóstico real de CPU |
| `presentation/services.py` | 404 | `holyrics_diagnostic()` placeholder | Implementar diagnóstico real do Holyrics |
| `frontend/src/stream/bridge.ts` | 109-140 | `updateDomainStores()` stub vazio | Mapear eventos WS → updates de stores |
| `frontend/src/pages/DashboardPage.tsx` | 1-10 | Placeholder via DevelopmentPage | Implementar DashboardPage real |
| `frontend/src/pages/LogsPage.tsx` | 1-10 | Placeholder via DevelopmentPage | Implementar LogsPage real |
| `frontend/src/pages/ReplayPage.tsx` | 1-10 | Placeholder via DevelopmentPage | Implementar ReplayPage real |
| `frontend/src/pages/SessionsPage.tsx` | 1-10 | Placeholder via DevelopmentPage | Implementar SessionsPage real |
| `frontend/src/pages/DiagnosticPage.tsx` | 1-10 | Placeholder via DevelopmentPage | Implementar DiagnosticPage real |
| `frontend/src/pages/AboutPage.tsx` | 60-62 | Build e Commit hardcoded como "—" | Ler do endpoint `/info` do backend |
| `frontend/src/pages/AboutPage.tsx` | 70-72 | Backend version hardcoded como "—" | Ler do endpoint `/info` do backend |
| `frontend/src/contexts/OperationContext.tsx` | 318-363 | Startup sequence 100% simulada | Verificar estado real de cada serviço |

---

## 3. Lista Completa de Mocks

| Arquivo | Linha | Motivo | Backend correspondente |
|---------|-------|--------|------------------------|
| `frontend/src/components/settings/AudioTab.tsx` | 25-29 | `MOCK_DEVICES` — lista de dispositivos | `microfone/capture.py:485` (list_input_devices) |
| `frontend/src/components/settings/AudioTab.tsx` | 50-66 | Teste de áudio simulado com rAF | Sem endpoint correspondente |
| `frontend/src/components/settings/HolyricsTab.tsx` | 30-65 | Teste de conexão Holyrics simulado | `presentation/services.py:325` (holyrics_health) |
| `frontend/src/components/settings/SystemTab.tsx` | 25-32 | `systemInfo` hardcoded (logDir, cacheDir, etc.) | Sem endpoint correspondente |
| `frontend/src/components/settings/SystemTab.tsx` | 41-49 | Limpar Cache simulado | Sem endpoint correspondente |
| `frontend/src/components/settings/SystemTab.tsx` | 52-55 | Abrir Pasta de Logs simulado | Sem endpoint correspondente |
| `frontend/src/components/settings/SystemTab.tsx` | 57-63 | Verificar Atualizações simulado | Sem endpoint correspondente |
| `frontend/src/contexts/OperationContext.tsx` | 318-363 | Startup steps com setTimeout | Cada etapa tem serviço correspondente |
| `frontend/src/contexts/ConnectionContext.tsx` | 55 | `backendUrl` hardcoded | Deveria vir de configuração |
| `frontend/src/contexts/ApplicationContext.tsx` | 17-21 | `info` hardcoded (nome, versão) | `api/routers/info.py:14` |

**Mocks em testes (uso apropriado, não substituir):**
- `tests/test_capture.py:68-86` — MockVAD
- `tests/test_stt.py:77-145` — MockBackend, MockSegment
- `tests/test_pipeline_flow.py:312-374` — Mocks para STT, Searcher, Holyrics
- `tests/test_reranker.py:21-43` — `_make_result()`
- `tests/test_embeddings.py:35-44` — MockEmbeddingProvider

---

## 4. Endpoints Órfãos

Endpoints existentes no backend mas **não consumidos** pelo frontend:

| Endpoint | Arquivo:Linha | Potencial uso |
|----------|---------------|---------------|
| `GET /health/live` | `api/routers/health.py:27` | Liveness probe — útil para orquestradores |
| `GET /health/ready` | `api/routers/health.py:33` | Readiness probe — útil para orquestradores |
| `GET /info` | `api/routers/info.py:14` | Metadados da API — usar em AboutPage |
| `GET /events/by-correlation` | `api/routers/events.py:25` | ReplayPage (não implementada) |
| `GET /events/by-session` | `api/routers/events.py:36` | SessionsPage (não implementada) |
| `GET /events/snapshot` | `api/routers/events.py:47` | Snapshot de eventos — útil para Console |

**Endpoints variantes com barra (`/health/`, `/metrics/`, etc.):** 6 endpoints duplicados com trailing slash. Redundantes mas inofensivos.

---

## 5. Métodos SDK Órfãos

Métodos do SDK sem consumidores ativos no frontend:

| Método | Arquivo SDK | Status Backend | Quem deveria consumir |
|--------|-------------|----------------|----------------------|
| `client.disconnect()` | `sdk/client.ts:130` | N/A | Ninguém (poderia ser usado em logout) |
| `client.expectedApiVersion` | `sdk/client.ts:120` | N/A | Versioning (não implementado) |
| `replay.getEvents` | `services/index.ts:165` | ❌ Não existe | ReplayPage (placeholder) |
| `replay.getSessions` | `services/index.ts:166` | ❌ Não existe | SessionsPage (placeholder) |
| `replay.getCorrelations` | `services/index.ts:167` | ❌ Não existe | ReplayPage (placeholder) |
| `events.getEventsByCorrelation` | `services/index.ts:88` | ✓ existe | ReplayPage |
| `events.getEventsBySession` | `services/index.ts:89` | ✓ existe | SessionsPage |
| `events.getEventSnapshot` | `services/index.ts:90` | ✓ existe | Console (não usado) |

**Métodos SDK implementados mas com store vazio (chamados via hooks mas resultado descartado):**
- `pipeline.getStatus`, `pipeline.getSession`, `pipeline.getMetrics`, `pipeline.getSnapshot`
- `session.getCurrentSession`
- `metrics.getMetrics`
- `configuration.getConfiguration`
- `health.getHealth`
- `diagnostics.getDiagnostics`

> **Nota:** Estes métodos são chamados pelos hooks mas os resultados **não são salvos nos stores**. O hook `usePipeline()` retorna `null` porque o store `pipeline` nunca recebe `.set()`.

---

## 6. Eventos Mortos

### Eventos publicados no WebSocket mas não consumidos de forma útil

| Evento WS | Publicado | Consumido | Problema |
|-----------|-----------|-----------|----------|
| `hello` | ✓ | ✓ | OK |
| `event` (15 tipos) | ✓ | ✓ (events store) | OK, mas **não atualiza outros stores** |
| `heartbeat_ack` | ✓ | ✓ | OK |
| `error` (WsErrorModel) | ✗ | ✗ | **Morto** — schema definido em `api/schemas/models.py:420` mas nunca emitido |

### Eventos do pipeline emitidos mas sem efeito em stores específicos

O `EventStreamBridge` recebe todos os 15 eventos do pipeline e os armazena no `events` store, mas `updateDomainStores()` (linha 109-140 de `bridge.ts`) é um **stub vazio**. Portanto:

| Evento Pipeline | Deveria atualizar | Atualmente atualiza |
|-----------------|-------------------|---------------------|
| `PipelineStarted` | `stores.pipeline` | Apenas `stores.events` |
| `PipelineStopped` | `stores.pipeline` | Apenas `stores.events` |
| `PipelinePaused` | `stores.pipeline` | Apenas `stores.events` |
| `PipelineResumed` | `stores.pipeline` | Apenas `stores.events` |
| `SpeechRecognized` | `stores.metrics` | Apenas `stores.events` |
| `SearchCompleted` | `stores.metrics` | Apenas `stores.events` |
| `PresentationCompleted` | `stores.metrics` | Apenas `stores.events` |
| `FeedbackRecorded` | `stores.metrics` | Apenas `stores.events` |
| `EvaluationRecorded` | `stores.metrics` | Apenas `stores.events` |
| `PipelineError` | `stores.pipeline`, `stores.diagnostics` | Apenas `stores.events` |

### Eventos consumidos e nunca emitidos

Nenhum caso identificado. Todos os eventos consumidos pelo frontend são emitidos pelo backend.

---

## 7. Próxima Sprint — Integração Vertical

**Objetivo:** Substituir mocks por integrações reais, sem criar funcionalidades novas.

**Critério de sucesso:** Para cada capacidade, o frontend deve usar dados reais do backend.

### Sprint Backlog (ordenado por dependência)

#### Task 1: Implementar `updateDomainStores()` no Bridge
**Arquivo:** `frontend/src/stream/bridge.ts:109-140`
**Esforço:** M
**Dependências:** Nenhuma
**Descrição:** Mapear eventos WebSocket para atualizações dos stores específicos:
- `PipelineStarted/Stopped/Paused/Resumed` → `stores.pipeline.setStatus()`
- `SpeechRecognized/SearchCompleted/PresentationCompleted` → `stores.metrics.update()`
- `PipelineError` → `stores.diagnostics.set()`
- Eventos de sessão → `stores.session.set()`

**Critério de aceite:** Ao receber evento WS, o store correspondente é atualizado e os hooks re-renderizam.

---

#### Task 2: Popular stores via Services na inicialização
**Arquivo:** `frontend/src/hooks/index.ts` (ou novo hook `useBootstrap`)
**Esforço:** M
**Dependências:** Task 1
**Descrição:** Criar hook que, ao conectar ao backend, chama os Services e popula os stores:
- `services.pipeline.getStatus()` → `stores.pipeline.set()`
- `services.pipeline.getSession()` → `stores.session.set()`
- `services.pipeline.getMetrics()` → `stores.metrics.set()`
- `services.configuration.getConfiguration()` → `stores.configuration.set()`
- `services.health.getHealth()` → `stores.health.set()`
- `services.diagnostics.getDiagnostics()` → `stores.diagnostics.set()`

**Critério de aceite:** Após conexão, todos os hooks (`usePipeline`, `useHealth`, etc.) retornam dados reais.

---

#### Task 3: Conectar Startup Sequence ao estado real do backend
**Arquivo:** `frontend/src/contexts/OperationContext.tsx:304-366`
**Esforço:** M
**Dependências:** Task 2
**Descrição:** Substituir simulações `setTimeout` por verificações reais:
- `backend`: verificar `client.status === "connected"`
- `eventstream`: verificar `stream.state()`
- `websocket`: verificar `client.status === "connected"`
- `presentation`: chamar `services.health.getHealth()`
- `stt`: verificar componente STT no HealthSnapshot
- `holyrics`: verificar componente Holyrics no HealthSnapshot
- `config`: chamar `services.configuration.getConfiguration()`
- `pipeline`: chamar `services.pipeline.getStatus()`

**Critério de aceite:** Cada etapa reflete o estado real do backend. Falhas reais aparecem como `error`.

---

#### Task 4: Sincronizar Configuration com backend
**Arquivo:** `frontend/src/contexts/OperationContext.tsx`, `frontend/src/components/settings/*.tsx`
**Esforço:** M
**Dependências:** Task 2
**Descrição:** Após editar settings, enviar ao backend:
- Adicionar endpoint `PUT /configuration` no backend
- Adicionar método `configuration.update` no SDK
- Após `updateSettings()`, chamar `services.configuration.update()`
- Em caso de erro, mostrar `PresentationError`

**Critério de aceite:** Alterações nas configurações são persistidas no backend e sobrevivem a reinicializações.

---

#### Task 5: Substituir MOCK_DEVICES por enumeração real
**Arquivo:** `frontend/src/components/settings/AudioTab.tsx:25-29`
**Esforço:** S
**Dependências:** Task 4
**Descrição:**
- Adicionar endpoint `GET /audio/devices` no backend (usando `MicrophoneCapture.list_input_devices()`)
- Adicionar método `audio.listDevices` no SDK
- Substituir `MOCK_DEVICES` por chamada real

**Critério de aceite:** Lista de dispositivos vem do backend.

---

#### Task 6: Substituir teste de conexão Holyrics por chamada real
**Arquivo:** `frontend/src/components/settings/HolyricsTab.tsx:30-65`
**Esforço:** S
**Dependências:** Task 2
**Descrição:**
- Implementar `holyrics_health()` em `presentation/services.py:325`
- Usar `services.health.getHealth()` e filtrar componente Holyrics
- Mostrar tempo de resposta real

**Critério de aceite:** Teste de conexão retorna status real do Holyrics.

---

#### Task 7: Substituir systemInfo mock por dados reais
**Arquivo:** `frontend/src/components/settings/SystemTab.tsx:25-32`
**Esforço:** S
**Dependências:** Task 2
**Descrição:**
- Adicionar endpoint `GET /system/info` no backend (logDir, cacheDir, diskUsage, versions)
- Adicionar método `system.getInfo` no SDK
- Substituir `systemInfo` hardcoded

**Critério de aceite:** SystemTab mostra dados reais do backend.

---

#### Task 8: Popular AboutPage com dados do backend
**Arquivo:** `frontend/src/pages/AboutPage.tsx:60-72`
**Esforço:** S
**Dependências:** Task 2
**Descrição:**
- Adicionar método `info.get` no SDK mapeando para `GET /info`
- Substituir Build, Commit, Backend version hardcoded
- Usar `info.server_time` para latência

**Critério de aceite:** AboutPage mostra versões reais do backend.

---

#### Task 9: Implementar endpoints de Replay no backend
**Arquivo:** `api/routers/replay.py` (novo)
**Esforço:** M
**Dependências:** Nenhuma (backend isolado)
**Descrição:**
- `GET /replay/sessions` — lista session IDs do EventStore
- `GET /replay/correlations?session_id=X` — lista correlation IDs
- `GET /replay/events?correlation_id=X` — lista eventos
- Usar `MemoryEventStore` existente

**Critério de aceite:** Os 3 métodos SDK `replay.*` têm endpoint correspondente.

---

#### Task 10: Implementar actions do pipeline (start/stop/pause/resume)
**Arquivo:** `api/routers/pipeline.py` (adicionar endpoints)
**Esforço:** M
**Dependências:** Nenhuma (backend isolado)
**Descrição:**
- `POST /pipeline/start` — chama `Pipeline.start()`
- `POST /pipeline/stop` — chama `Pipeline.stop()`
- `POST /pipeline/pause` — chama `StreamingPipelineEngine.pause()`
- `POST /pipeline/resume` — chama `StreamingPipelineEngine.resume()`
- Adicionar métodos correspondentes no SDK

**Critério de aceite:** Frontend pode iniciar/parar/pausar/resumir o pipeline via API.

---

#### Task 11: Implementar WsErrorModel no WebSocket
**Arquivo:** `api/websocket/events.py`
**Esforço:** S
**Dependências:** Nenhuma
**Descrição:**
- Emitir `WsErrorModel` quando ocorrerem erros no pipeline
- Tratar no frontend para mostrar notificações de erro

**Critério de aceite:** Erros do pipeline chegam ao frontend via WebSocket.

---

#### Task 12: Implementar páginas placeholder (opcional, fase seguinte)
**Arquivos:** `frontend/src/pages/{Dashboard,Logs,Replay,Sessions,Diagnostic}Page.tsx`
**Esforço:** L
**Dependências:** Tasks 1, 2, 9, 10
**Descrição:** Transformar cada placeholder em página funcional consumindo stores reais.

**Critério de aceite:** Nenhuma página mostra "Em desenvolvimento".

---

### Ordem Recomendada de Execução

```
Fase A (fundação):
  Task 1 (Bridge) → Task 2 (Bootstrap) → Task 3 (Startup real)

Fase B (configuração):
  Task 4 (Config sync) → Task 5 (Audio devices) → Task 6 (Holyrics test) → Task 7 (System info)

Fase C (completude):
  Task 8 (About) | Task 9 (Replay endpoints) | Task 10 (Pipeline actions) | Task 11 (WS error)

Fase D (UX):
  Task 12 (Páginas placeholder)
```

### Critério de Sucesso da Sprint

Ao final, para qualquer funcionalidade do sistema deve ser possível responder:

| Pergunta | Resposta esperada |
|----------|-------------------|
| Ela já existe? | Sim, em todos os módulos backend |
| Onde está implementada? | Mapa completo na matriz acima |
| Quem a consome? | Hooks → Services → Stores (após Tasks 1-2) |
| O frontend usa dados reais ou simulados? | Reais (após Tasks 1-8) |
| Menor alteração para torná-la funcional? | Lista em Sprint Backlog acima |

---

## Conclusão

O AI Lyrics tem uma **base sólida**: backend completo, API funcional, SDK bem estruturado. A **lacuna principal** está na **integração vertical**: os dados do backend não chegam aos stores do frontend (exceto eventos via WebSocket).

A Sprint de Integração Vertical (12 tasks) resolve esta lacuna **sem criar funcionalidades novas** — apenas conecta o que já existe. As 3 primeiras tasks (Bridge, Bootstrap, Startup) são as mais críticas e destravam todas as demais.
