# Runtime Execution Spec — AI Lyrics

Especificação oficial da execução do AI Lyrics em tempo real.

Este documento descreve exclusivamente como o sistema executa: ordem de execução, ciclo de vida, concorrência, sincronização, fluxo operacional, recuperação, degradação, inicialização e desligamento. Não descreve componentes, eventos ou contratos; esses assuntos estão em `event_contracts.md`, `rfc_capabilities.md` e `adr_architecture_decisions.md`.

---

## Índice

1. [Runtime Overview](#1-runtime-overview)
2. [Application Lifecycle](#2-application-lifecycle)
3. [Startup Sequence](#3-startup-sequence)
4. [Component Registration](#4-component-registration)
5. [Runtime Pipeline](#5-runtime-pipeline)
6. [Execution Order](#6-execution-order)
7. [Concurrency Model](#7-concurrency-model)
8. [Threading Policy](#8-threading-policy)
9. [Scheduling Policy](#9-scheduling-policy)
10. [Failure Handling](#10-failure-handling)
11. [Degraded Modes](#11-degraded-modes)
12. [Cancellation Policy](#12-cancellation-policy)
13. [Timeout Policy](#13-timeout-policy)
14. [Retry Policy](#14-retry-policy)
15. [Backpressure Policy](#15-backpressure-policy)
16. [Memory Lifecycle](#16-memory-lifecycle)
17. [Graceful Shutdown](#17-graceful-shutdown)
18. [Runtime Invariants](#18-runtime-invariants)
19. [Runtime Sequence Diagrams](#19-runtime-sequence-diagrams)
20. [Performance Budget](#20-performance-budget)
21. [Observabilidade em Runtime](#21-observabilidade-em-runtime)
22. [Assumptions](#22-assumptions)
23. [Non-Goals](#23-non-goals)

---

## 1. Runtime Overview

O AI Lyrics opera continuamente como um servidor FastAPI que orquestra captura de áudio, transcrição streaming, parsing incremental, inferência semântica, resolução de referências, orquestração de estado e apresentação de versículos no Holyrics.

### Fluxo de alto nível

```
Inicialização (Composition Root)
    ↓
Captura de áudio (PortAudio thread)
    ↓
    ├─→ VAD Thread → SpeechQueue → SpeechWorker Thread → SpeechTranscribed
    │                                                    ↓
    │                                              [Sprint 28: confirmação/finalização]
    │                                              StateOrchestrator (confirma/corrige/limpa)
    │                                              ReadingFollowService (fallback)
    │                                              [BiblicalNLUService desativado por padrão]
    │
    └─→ RingBuffer → SlidingWindow Thread → StreamingSTTService
                                              ↓
                                        SpeechPartial / SpeechPartialUpdated
                                              ↓
                                        SpeechCommittedWords (LocalAgreement-2 — fluxo primário)
                                              ↓
                                    ├─→ IncrementalBiblicalParser
                                    │       ↓
                                    │   ReferenceCandidate / ReferenceAntecipada / ReferenceDetected
                                    │
                                    ├─→ SemanticEngine (debounce em committed words)
                                    │       ↓
                                    │   IntentCandidate
                                    │       ↓
                                    │   ReferenceResolver
                                    │       ↓
                                    │   ReferenceDetected (se validado)
                                    │
                                    ├─→ ReadingFollowService (leitura contínua)
                                    │       ↓
                                    │   ReadingFollowAdvanced (fuzzy_match)
                                    │
                                    └─→ VersionCommandDetector
                                            ↓
                                        NavigationCommandDetected (comandos de voz)
                                            ↓
                                        ReadingFollowAdvanced (voice_command_*)
                                    ↓
                                StateOrchestrator (CAP-01 — implementado Sprint 28)
                                    ↓
                                StateChanged
                                    ↓
                                VersePresentationService
                                    ↓
                                VerseResolving → VerseResolved → VersePresented
                                    ↓
                                Telemetry (hooks)
                                    ↓
                                Replay / Benchmark (sob demanda)
```

O sistema possui dois caminhos paralelos de processamento de áudio: o fluxo segmentado (VAD → SpeechWorker → BiblicalNLUService) e o fluxo streaming (SlidingWindow → StreamingSTTService → IncrementalBiblicalParser + SemanticEngine). Ambos coexistem e compartilham o mesmo modelo Whisper via `STTExecutor`, que serializa o acesso.

---

## 2. Application Lifecycle

O pipeline possui os seguintes estados de ciclo de vida. As transições são controladas pelo `StreamingPipelineEngine` e pela API FastAPI.

### BOOT

| Aspecto | Descrição |
|---|---|
| **Objetivo** | Processo iniciado. Composition Root ainda não executou. |
| **Quem entra** | Sistema operacional / gerenciador de processo. |
| **Quem sai** | Composition Root (`build_composition_root()`). |
| **Eventos emitidos** | Nenhum. |
| **Garantias** | Nenhum componente está ativo. EventBus não existe ainda. |

### INITIALIZATION

| Aspecto | Descrição |
|---|---|
| **Objetivo** | Construir todas as dependências, inscrever handlers no EventBus, carregar modelos em RAM/VRAM. |
| **Quem entra** | Composition Root. |
| **Quem sai** | Composition Root retorna `CompositionRoot` pronto para uso. |
| **Eventos emitidos** | `SemanticProviderUnavailable` (se Ollama offline). Nenhum evento do pipeline. |
| **Garantias** | Ao final, todos os componentes estão instanciados e inscritos no EventBus. O pipeline NÃO está rodando (`PipelineState.running=False`). |

### READY

| Aspecto | Descrição |
|---|---|
| **Objetivo** | Sistema pronto para receber `POST /pipeline/start`. Componentes instanciados mas inativos. |
| **Quem entra** | Fim de INITIALIZATION. |
| **Quem sai** | `POST /pipeline/start` (API FastAPI). |
| **Eventos emitidos** | Nenhum. |
| **Garantias** | EventBus tem todas as inscrições. Modelos carregados. Threads não estão rodando. |

### RUNNING

| Aspecto | Descrição |
|---|---|
| **Objetivo** | Captura, transcrição, parsing, semântica, apresentação ativos. |
| **Quem entra** | `POST /pipeline/start` chama `engine.start()`, `audio_capture.start()`, `speech_pipeline.start()`, `speech_worker.start()`, `sliding_window.start()`, `streaming_stt.start()`. |
| **Quem sai** | `POST /pipeline/stop` ou `POST /pipeline/pause`. |
| **Eventos emitidos** | `PipelineStarted`. A partir daqui, todos os eventos do fluxo operacional. |
| **Garantias** | `PipelineState.running=True`, `PipelineState.paused=False`. Áudio sendo capturado. Threads VAD, SpeechWorker, SlidingWindow ativas. |

### PAUSED

| Aspecto | Descrição |
|---|---|
| **Objetivo** | Pausar processamento sem desligar componentes. |
| **Quem entra** | `POST /pipeline/pause` chama `engine.pause()`. |
| **Quem sai** | `POST /pipeline/resume` chama `engine.resume()`. |
| **Eventos emitidos** | `PipelinePaused` na entrada. `PipelineResumed` na saída. |
| **Garantias** | `PipelineState.running=True`, `PipelineState.paused=True`. `engine.process()` descarta segmentos (não publica `SpeechSegmentReceived`). Threads de captura continuam rodando mas eventos são descartados pelo engine. |

### STOPPING

| Aspecto | Descrição |
|---|---|
| **Objetivo** | Desligar componentes na ordem inversa de inicialização. |
| **Quem entra** | `POST /pipeline/stop`. |
| **Quem sai** | Todas as threads paradas. |
| **Eventos emitidos** | `PipelineStopped`. |
| **Garantias** | Flush final do VAD (`segmenter.force_flush`). Threads joined com timeout. |

### STOPPED

| Aspecto | Descrição |
|---|---|
| **Objetivo** | Sistema parado. Pode reiniciar via `POST /pipeline/start`. |
| **Quem entra** | Fim de STOPPING. |
| **Quem sai** | `POST /pipeline/start` (volta para RUNNING). |
| **Eventos emitidos** | Nenhum. |
| **Garantias** | `PipelineState.running=False`. Threads mortas. EventBus ainda tem inscrições (componentes não foram destruídos). |

### ERROR

| Aspecto | Descrição |
|---|---|
| **Objetivo** | Estado de erro não fatal. Pipeline continua se `recoverable=True`. |
| **Quem entra** | Qualquer handler que captura exceção e publica `PipelineError`. |
| **Quem sai** | Handler recupera ou erro é fatal (`recoverable=False` → STOPPING). |
| **Eventos emitidos** | `PipelineError`. |
| **Garantias** | Se `recoverable=True`, pipeline continua. Se `recoverable=False`, transita para STOPPING. |

### Diagrama de transições

```
BOOT → INITIALIZATION → READY → RUNNING ⇄ PAUSED
                                ↓
                           STOPPING → STOPPED
                                ↑
                              ERROR (recoverable=False)
```

---

## 3. Startup Sequence

A inicialização ocorre em `build_composition_root()` no módulo `api/startup/composition.py`. A ordem é estrita e determinística.

### Ordem de inicialização

```
1.  Config (config.yaml + overrides)
2.  PipelineSession
3.  PipelineEventBus (com MemoryEventStore)
4.  PipelineState, PipelineMetrics, PipelinePolicy
5.  Presentation Services (Pipeline, Session, Metrics, Config, Health, Diagnostic, Event, Audio)
6.  HealthService
7.  AudioCaptureService (instanciado, NÃO iniciado)
8.  STT (faster-whisper carregado em RAM/VRAM)           ← bloqueante, ~5-30s
9.  SpeechQueue (maxsize=10)
10. SpeechPipelineService (VAD, instanciado, NÃO iniciado)
11. SpeechWorker (instanciado, NÃO iniciado)
12. BiblicalNLUService (instanciado + start()             ← inscreve no EventBus)
13. Searcher (carrega books.json)
14. HolyricsClient (instanciado)
15. VersePresentationService (instanciado + start()       ← inscreve no EventBus)
16. BibleRetriever (opcional, se knowledge.enabled)
17. STTExecutor (wraps STT, serializa acesso)
18. RingBuffer (20s de áudio, thread-safe)
19. StreamingSTTService (instanciado + start()            ← marca como ativo)
20. SlidingWindow (instanciado, NÃO iniciado)
21. IncrementalBiblicalParser (instanciado + start()      ← inscreve no EventBus)
22. StreamingPipelineMetrics (coletor de métricas)
23. SemanticProvider (Ollama/OpenAI/Stub)
24. Semantic health check (se Ollama)
25. Semantic warmup (se Ollama disponível)                ← bloqueante, ~15s cold start
26. SermonMemoryEngine (instanciado + start()             ← inscreve no EventBus)
27. ContextEngine (instanciado)
28. SemanticCache (instanciado)
29. SemanticEngine (instanciado + start()                 ← inscreve no EventBus)
30. ReferenceResolver (instanciado + start()              ← inscreve no EventBus)
31. CompositionRoot retornado                             ← READY
```

### Diagrama de dependências (ASCII)

```
                    Config
                      |
                 PipelineSession
                      |
                 PipelineEventBus
                      |
         +------------+------------+
         |            |            |
    PipelineState  Metrics    Policy
         |
    Presentation Services
         |
    HealthService
         |
    AudioCaptureService
         |
    +----+----+----+----+
    |    |    |    |
   STT  NLU  VP  Semantic
    |         |
    +--STTExecutor
    |         |
    |    RingBuffer
    |         |
    |    SlidingWindow
    |         |
    |    StreamingSTT
    |         |
    +-- IncrementalParser
    |
    SpeechQueue
    |         |
    VAD   SpeechWorker
```

### Paralelismo na inicialização

Não há paralelismo. A inicialização é estritamente sequencial. Cada componente depende do anterior:

- **STT** deve carregar antes de `SpeechWorker`, `STTExecutor` e `StreamingSTTService`.
- **Searcher** deve carregar antes de `VersePresentationService` e `ReferenceResolver`.
- **SermonMemoryEngine** deve iniciar antes de `SemanticEngine` (fornece `sermon_context_fn`).
- **BiblicalNLUService** deve inscrever antes de `SpeechWorker` publicar `SpeechTranscribed`.

### Componentes que podem falhar sem abortar

Os seguintes componentes são opcionais: se falharem na inicialização, o sistema continua em modo degradado:

- STT (desabilita fluxo de fala)
- BiblicalNLUService (desabilita parser determinístico)
- VersePresentationService (desabilita apresentação)
- StreamingSTTService (desabilita streaming)
- IncrementalBiblicalParser (desabilita parsing incremental)
- SemanticEngine (desabilita camada semântica)
- SermonMemoryEngine (desabilita contexto do sermão)
- ReferenceResolver (desabilita resolução semântica)
- BibleRetriever (desabilita RAG)

Cada falha é logada como warning e o componente é setado para `None`. O sistema nunca aborta por falha de componente individual.

---

## 4. Component Registration

### Ordem de inscrição no EventBus

A inscrição ocorre durante `start()` de cada componente, na ordem do Startup Sequence:

| # | Componente | Eventos inscritos | Quando |
|---|---|---|---|
| 1 | `BiblicalNLUService` | `SpeechTranscribed` | `nlu_service.start()` |
| 2 | `VersePresentationService` | `ReferenceDetected`, `ReferenceAntecipada` | `verse_presentation_service.start()` |
| 3 | `IncrementalBiblicalParser` | `SpeechPartial`, `SpeechPartialUpdated` | `incremental_parser.start()` |
| 4 | `SermonMemoryEngine` | `SpeechTranscribed`, `ReferenceDetected`, `SpeechPartial`, `SpeechPartialUpdated` | `sermon_memory_engine.start()` |
| 5 | `SemanticEngine` | `SpeechPartial`, `SpeechPartialUpdated` | `semantic_engine.start()` |
| 6 | `ReferenceResolver` | `IntentCandidate` | `reference_resolver.start()` |
| 7 | `PipelineCoordinator` (legacy) | `SpeechSegmentReceived`, `SpeechRecognized`, `SearchCompleted`, `RankingCompleted`, `IntelligenceCompleted`, `PresentationCompleted`, `FeedbackRecorded`, `SpeechRecognized` (Context) | `coordinator.register_default_flow()` |

### Quem registra handlers

Cada componente chama `bus.subscribe(EventType, self._handler_method)` em seu próprio `start()`. O `PipelineCoordinator` registra handlers do fluxo legacy via `register_default_flow()`.

### Quando inscrições são removidas

- `stop()` de cada componente chama `bus.unsubscribe()`.
- `PipelineCoordinator.unregister_all()` remove todos os handlers do fluxo legacy.
- O EventBus não remove inscrições automaticamente em caso de erro.

### Garantias

- A ordem de inscrição determina a ordem de execução dos handlers no EventBus síncrono.
- Handlers do mesmo evento executam na ordem em que foram inscritos.
- Nenhum handler é inscrito duas vezes para o mesmo evento (o EventBus previne duplicação).

---

## 5. Runtime Pipeline

### 5.1 Fluxo Streaming

| Aspecto | Descrição |
|---|---|
| **Objetivo** | Detectar referências bíblicas durante a fala, antes do silêncio fechar o segmento. |
| **Entrada** | Áudio contínuo do microfone. |
| **Saída** | `VersePresented` (apresentação no Holyrics). |
| **Componentes** | `AudioCaptureService` → `RingBuffer` → `SlidingWindow` → `StreamingSTTService` → `IncrementalBiblicalParser` → `VersePresentationService` |
| **Eventos** | `SpeechPartial` → `ReferenceCandidate` → `ReferenceDetected` → `VerseResolving` → `VerseResolved` → `VersePresented` |
| **Estado esperado** | `RUNNING` |

### 5.2 Fluxo Segmentado

| Aspecto | Descrição |
|---|---|
| **Objetivo** | Processar segmentos completos de fala após VAD detectar silêncio. |
| **Entrada** | Áudio contínuo → VAD detecta segmento. |
| **Saída** | `SpeechTranscribed` → `ReferenceDetected` ou `IntentUnknown`. |
| **Componentes** | `AudioCaptureService` → `SpeechPipelineService` (VAD) → `SpeechQueue` → `SpeechWorker` → `BiblicalNLUService` |
| **Eventos** | `SpeechStarted` → `SpeechEnded` → `SpeechSegmentCreated` → `SpeechTranscribing` → `SpeechTranscribed` → `ReferenceDetected` / `ReferenceInvalid` / `IntentUnknown` |
| **Estado esperado** | `RUNNING` |

### 5.3 Fluxo Incremental

| Aspecto | Descrição |
|---|---|
| **Objetivo** | Parser incremental que consome parciais e detecta referências progressivamente. |
| **Entrada** | `SpeechPartial` / `SpeechPartialUpdated`. |
| **Saída** | `ReferenceCandidate` (incompleto) → `ReferenceDetected` (completo) ou `ReferenceAntecipada` (antecipação). |
| **Componentes** | `IncrementalBiblicalParser` |
| **Eventos** | `ReferenceCandidate` → `ReferenceDetected` → `ReferenceAntecipada` |
| **Estado esperado** | `RUNNING` |

### 5.4 Fluxo Semântico

| Aspecto | Descrição |
|---|---|
| **Objetivo** | Inferir referências implícitas via LLM quando o parser determinístico não resolve. |
| **Entrada** | `SpeechPartial` / `SpeechPartialUpdated`. |
| **Saída** | `IntentCandidate` → `ReferenceDetected` (se validado) ou `IntentRejected` (se rejeitado). |
| **Componentes** | `SemanticEngine` → `ReferenceResolver` |
| **Eventos** | `IntentCandidate` → `SemanticResolutionCompleted` → `ReferenceDetected` ou `IntentRejected` |
| **Estado esperado** | `RUNNING` |

### 5.5 Fluxo de Replay

| Aspecto | Descrição |
|---|---|
| **Objetivo** | Reproduzir eventos gravados para teste de regressão (ADR-009). |
| **Entrada** | Eventos persistidos no `EventStore` ou benchmark YAML. |
| **Saída** | `BenchmarkPassed` ou `BenchmarkFailed`. |
| **Componentes** | Replay engine (sob demanda) |
| **Eventos** | `ReplayStarted` → eventos reproduzidos → `ReplayFinished` → `BenchmarkPassed` / `BenchmarkFailed` |
| **Estado esperado** | Qualquer estado. Replay NÃO altera estado do pipeline. |

### 5.6 Fluxo Benchmark

| Aspecto | Descrição |
|---|---|
| **Objetivo** | Validar que eventos produzidos correspondem ao `benchmark.yaml`. |
| **Entrada** | Eventos de `StateChanged` e `ReferenceDetected` produzidos durante Replay. |
| **Saída** | `BenchmarkPassed` ou `BenchmarkFailed`. |
| **Componentes** | Benchmark validator |
| **Eventos** | `BenchmarkPassed` (todos eventos correspondem) ou `BenchmarkFailed` (divergência encontrada) |
| **Estado esperado** | Replay em andamento. Benchmark nunca altera comportamento do pipeline. |

### 5.7 Fluxo Legacy

| Aspecto | Descrição |
|---|---|
| **Objetivo** | Pipeline linear original (Sprint 12). Processa segmentos via Search → Ranking → Intelligence → Presentation. |
| **Entrada** | `SpeechSegmentReceived` (via `engine.process()`). |
| **Saída** | `EvaluationRecorded`. |
| **Componentes** | `RecognitionHandler` → `SearchHandler` → `RankingHandler` → `IntelligenceHandler` → `PresentationHandler` → `FeedbackHandler` → `EvaluationHandler` |
| **Eventos** | `SpeechSegmentReceived` → `SpeechRecognized` → `SearchRequested` → `SearchCompleted` → `RankingCompleted` → `IntelligenceCompleted` → `PresentationRequested` → `PresentationCompleted` → `FeedbackRecorded` → `EvaluationRecorded` |
| **Estado esperado** | `RUNNING`. `PipelineCoordinator.register_default_flow()` foi chamado. |

---

## 6. Execution Order

### Quando um `SpeechPartial` chega ao EventBus

O EventBus é síncrono: handlers executam na thread do publisher, na ordem de inscrição.

```
SpeechPartial publicado por StreamingSTTService (thread SlidingWindow-Extractor)
    ↓
1. IncrementalBiblicalParser._on_partial  (inscrito primeiro)
    → publica ReferenceCandidate ou ReferenceDetected (síncrono, mesma thread)
    → se ReferenceDetected: VersePresentationService.handle (inscrito)
        → publica VerseResolving (síncrono)
        → chama Searcher.search_by_reference (síncrono, pode bloquear)
        → publica VerseResolved ou VersePresentationFailed (síncrono)
        → se VerseResolved: chama HolyricsClient.show_verse (síncrono, rede)
        → publica VersePresented ou VersePresentationFailed (síncrono)

2. SemanticEngine._on_partial  (inscrito depois)
    → avalia política de crescimento
    → se growth trigger: _fire_inference() (síncrono, mesma thread)
        → chama LLM (rede, pode bloquear ~4s)
        → publica IntentCandidate (síncrono)
        → ReferenceResolver._on_intent_candidate (inscrito)
            → valida via Searcher (síncrono)
            → publica ReferenceDetected ou IntentRejected (síncrono)
    → se debounce: agenda threading.Timer (thread separada)
        → Timer expira → _fire_inference() na thread do Timer

3. SermonMemoryEngine._on_partial  (inscrito depois)
    → atualiza SermonContext
    → publica SermonContextUpdated (síncrono, se mudou)
```

### Quem executa primeiro

`IncrementalBiblicalParser` executa primeiro (inscrito antes de `SemanticEngine` e `SermonMemoryEngine`).

### Quem executa depois

`SemanticEngine` e `SermonMemoryEngine` executam após o parser, na mesma thread, sequencialmente.

### Quem executa em paralelo

- `SpeechWorker` (thread `SpeechWorker-Whisper`) processa segmentos finais em paralelo ao fluxo streaming.
- `SemanticEngine` debounce Timer executa em thread separada quando o timer expira.
- `SlidingWindow-Extractor` e `SpeechPipeline-VAD` são threads independentes.

### Quem aguarda

- `STTExecutor` serializa acesso ao Whisper: se `SpeechWorker` está transcrevendo, `StreamingSTTService` aguarda o lock.
- `VersePresentationService` aguarda resposta do Holyrics (rede síncrona).
- `SemanticEngine` aguarda resposta do LLM (rede síncrona, com timeout).

### Quem nunca bloqueia

- `AudioCaptureService` (thread PortAudio): apenas coloca áudio na fila, nunca processa.
- `SpeechPipelineService._on_audio_data`: apenas coloca chunk na fila, nunca processa.
- `EventBus.publish`: apenas itera handlers, não tem lock próprio.

---

## 7. Concurrency Model

### Há múltiplas threads?

Sim. O sistema opera com múltiplas threads daemon:

| Thread | Nome | Tipo |
|---|---|---|
| Main | `MainThread` | FastAPI / uvicorn |
| PortAudio | `PortAudio` | daemon, callback de áudio |
| VAD | `SpeechPipeline-VAD` | daemon |
| SpeechWorker | `SpeechWorker-Whisper` | daemon |
| SlidingWindow | `SlidingWindow-Extractor` | daemon |
| SemanticEngine Timer | `Thread-N` (threading.Timer) | daemon, efêmera |

### Há filas?

| Fila | Tipo | Tamanho | Produtor | Consumidor |
|---|---|---|---|---|
| `_chunk_queue` (VAD) | `queue.Queue` | 200 | PortAudio callback | VAD thread |
| `SpeechQueue` | `queue.Queue` | 10 | VAD thread | SpeechWorker thread |
| `RingBuffer` | numpy array circular | 20s de áudio | PortAudio callback | SlidingWindow thread |

### Há locks?

| Lock | Tipo | Protege |
|---|---|---|
| `STTExecutor._lock` | `threading.Lock` | Acesso serial ao modelo Whisper |
| `SemanticEngine._lock` | `threading.Lock` | Estado de debounce e política de crescimento |
| `SpeechQueue._lock` | `threading.Lock` | Métricas da fila |
| `RingBuffer` | lock interno | Escrita/leitura do buffer circular |

### Há sincronização?

O EventBus NÃO tem lock. A sincronização é garantida pelo fato de que `publish()` é chamado de múltiplas threads mas as inscrições são estáveis após inicialização (não há subscribe/unsubscribe durante RUNNING). Handlers síncronos executam na thread do publisher.

### Quem pode executar simultaneamente?

- `SpeechWorker-Whisper` e `SlidingWindow-Extractor` executam simultaneamente, mas o `STTExecutor._lock` serializa o acesso ao Whisper.
- `SemanticEngine` debounce Timer pode disparar enquanto `SlidingWindow-Extractor` publica o próximo `SpeechPartialUpdated`.
- `SpeechPipeline-VAD` e `SlidingWindow-Extractor` executam simultaneamente (consomem áudio de fontes independentes).

### Quem nunca pode executar simultaneamente?

- Duas transcrições Whisper nunca executam simultaneamente (`STTExecutor._lock`).
- Dois handlers do mesmo evento nunca executam simultaneamente (EventBus síncrono, ordem de inscrição).
- `SemanticEngine._fire_inference` nunca executa simultaneamente com `_schedule_inference` (`_lock` interno).

---

## 8. Threading Policy

### Main Thread

| Aspecto | Descrição |
|---|---|
| **Responsabilidades** | FastAPI / uvicorn. Atende requisições HTTP. Orquestra start/stop do pipeline. |
| **Eventos produzidos** | `PipelineStarted`, `PipelineStopped`, `PipelinePaused`, `PipelineResumed` (via `engine.start/stop/pause/resume`). |
| **Eventos consumidos** | Nenhum diretamente. Acesso via Presentation Services. |
| **Restrições** | Nunca chama Whisper, Searcher ou Holyrics diretamente. Apenas orquestra lifecycle. |

### PortAudio Thread

| Aspecto | Descrição |
|---|---|
| **Responsabilidades** | Capturar áudio do microfone. Chamar callback `_on_audio_data`. |
| **Eventos produzidos** | Nenhum diretamente. Coloca chunks na `_chunk_queue` (VAD) e escreve no `RingBuffer` (streaming). |
| **Eventos consumidos** | Nenhum. |
| **Restrições** | Nunca pode bloquear. Callback deve retornar em < 10ms. Apenas enfileira. |

### VAD Thread (`SpeechPipeline-VAD`)

| Aspecto | Descrição |
|---|---|
| **Responsabilidades** | Consumir chunks da `_chunk_queue`. Processar VAD. Detectar início/fim de fala. Criar segmentos. Publicar `SpeechStarted`, `SpeechEnded`, `SpeechSegmentCreated`. Enfileirar segmentos na `SpeechQueue`. |
| **Eventos produzidos** | `SpeechStarted`, `SpeechEnded`, `SpeechSegmentCreated`. |
| **Eventos consumidos** | Nenhum (consome da fila, não do EventBus). |
| **Restrições** | Não chama Whisper. Não chama Holyrics. Não chama LLM. |

### SpeechWorker Thread (`SpeechWorker-Whisper`)

| Aspecto | Descrição |
|---|---|
| **Responsabilidades** | Consumir segmentos da `SpeechQueue`. Transcrever via `STT.transcribe()`. Publicar `SpeechTranscribing`, `SpeechTranscribed`. |
| **Eventos produzidos** | `SpeechTranscribing`, `SpeechTranscribed`. |
| **Eventos consumidos** | Nenhum (consome da fila). |
| **Restrições** | Acessa Whisper via `STT.transcribe()` diretamente (não via `STTExecutor`). Pode bloquear por segundos durante transcrição. |

### SlidingWindow Thread (`SlidingWindow-Extractor`)

| Aspecto | Descrição |
|---|---|
| **Responsabilidades** | Extrair janela de 6s do `RingBuffer` a cada 400ms. Chamar `StreamingSTTService.on_window()`. |
| **Eventos produzidos** | Nenhum diretamente. |
| **Eventos consumidos** | Nenhum. |
| **Restrições** | Intervalo de 400ms entre extrações. Se `on_window` demora mais que 400ms, o próximo ciclo espera menos (não há overlap). |

### Streaming Inference Thread (efêmera, SemanticEngine Timer)

| Aspecto | Descrição |
|---|---|
| **Responsabilidades** | Executar `_fire_inference()` quando o debounce timer expira. Chamar LLM. Publicar `IntentCandidate`. |
| **Eventos produzidos** | `IntentCandidate`, `SemanticInferenceCompleted`. |
| **Eventos consumidos** | Nenhum diretamente (recebe via Timer, não via EventBus). |
| **Restrições** | Thread efêmera (morre ao terminar `_fire_inference`). Não mantém estado entre invocações. |

### Replay Thread (sob demanda)

| Aspecto | Descrição |
|---|---|
| **Responsabilidades** | Reproduzir eventos do EventStore ou benchmark. Comparar com esperado. Publicar `ReplayStarted`, `ReplayFinished`, `BenchmarkPassed`, `BenchmarkFailed`. |
| **Eventos produzidos** | `ReplayStarted`, `ReplayFinished`, `BenchmarkPassed`, `BenchmarkFailed`. |
| **Eventos consumidos** | Nenhum (lê do EventStore, não do EventBus). |
| **Restrições** | Nunca altera estado do pipeline. Nunca publica eventos operacionais (apenas eventos de replay/benchmark). |

### Telemetry Thread

| Aspecto | Descrição |
|---|---|
| **Responsabilidades** | Coletar métricas de sistema (CPU, GPU, latência). Publicar eventos de telemetria. |
| **Eventos produzidos** | `TelemetryEvent` subclasses (não persistidas). |
| **Eventos consumidos** | Nenhum. |
| **Restrições** | Nunca bloqueia o pipeline. Telemetria é best-effort. |

---

## 9. Scheduling Policy

### Ordem de execução

O EventBus executa handlers na ordem de inscrição. Não há prioridade nem preempção. Dentro de um `publish()`, todos handlers executam antes de retornar ao caller.

### Prioridades

Não há prioridade explícita. A ordem de inscrição determina a prioridade implícita:

1. `IncrementalBiblicalParser` (parser determinístico, rápido, prioritário)
2. `SemanticEngine` (LLM, lento, secundário)
3. `SermonMemoryEngine` (atualização de contexto, terciário)

### Fairness

Não há fairness garantida. Se o parser publica `ReferenceDetected` dentro de seu handler, `VersePresentationService` executa (rede Holyrics) antes de `SemanticEngine` receber o `SpeechPartial`. O LLM pode ser atrasado pela apresentação.

### Starvation

`SemanticEngine` pode sofrer starvation se o parser publica `ReferenceDetected` frequentemente e `VersePresentationService` bloqueia por segundos no Holyrics, e o debounce timer do SemanticEngine é cancelado repetidamente por novos `SpeechPartialUpdated`.

Mitigação: o gatilho de crescimento (Sprint 21.5) dispara imediatamente quando `growth_chars >= 22` e `append_words >= 3` e `elapsed_ms >= 1000`, sem esperar debounce.

### Latência

A latência de cada handler é determinística para o parser (microssegundos) e não-determinística para LLM e Holyrics (rede). Ver seção 20 (Performance Budget).

### Tempo máximo por etapa

| Etapa | Tempo máximo | Comportamento após exceder |
|---|---|---|
| VAD process_chunk | < 5ms | Log warning |
| Parser incremental | < 10ms | Log warning |
| STT (Whisper) | < 3000ms (CPU) / < 500ms (GPU) | STTExecutor aguarda lock |
| SemanticEngine inferência | < 5000ms (timeout) | Ver seção 13 |
| Searcher.search_by_reference | < 500ms | Ver seção 13 |
| HolyricsClient.show_verse | < 2000ms (timeout) | Ver seção 13 |

---

## 10. Failure Handling

### Erro no STT

| Aspecto | Descrição |
|---|---|
| **Como detectar** | `STT.transcribe()` levanta exceção. `SpeechWorker._transcribe_segment` captura. |
| **Como recuperar** | Publica `SpeechTranscribed` com `text=""`, `confidence=0.0`. Pipeline continua. |
| **Quais eventos publicar** | `SpeechTranscribed` (com campos vazios). `PipelineError` se o handler decidir. |
| **Quem continua** | `SpeechWorker` continua consumindo a fila. `BiblicalNLUService` recebe `SpeechTranscribed` vazio e publica `IntentUnknown` com `reason="empty_text"`. |

### Erro no Parser

| Aspecto | Descrição |
|---|---|
| **Como detectar** | `IncrementalBiblicalParser._on_partial` captura exceção. |
| **Como recuperar** | Log do erro. Parser continua processando próximos parciais. |
| **Quais eventos publicar** | `PipelineError` com `handler_name="IncrementalBiblicalParser"`, `recoverable=True`. |
| **Quem continua** | Parser continua. SemanticEngine e SermonMemoryEngine continuam (são handlers independentes no mesmo publish). |

### Erro no Semantic

| Aspecto | Descrição |
|---|---|
| **Como detectar** | `SemanticEngine._fire_inference` captura exceção do provider. |
| **Como recuperar** | Log do erro. Publica `SemanticInferenceCompleted` com `error` preenchido. Continua operando. |
| **Quais eventos publicar** | `SemanticInferenceCompleted` (com `error`). Se provider offline: `SemanticProviderUnavailable`. |
| **Quem continua** | SemanticEngine continua. Parser e VersePresentationService não são afetados. |

### Erro no Searcher

| Aspecto | Descrição |
|---|---|
| **Como detectar** | `Searcher.search_by_reference()` levanta exceção ou retorna vazio. |
| **Como recuperar** | `VersePresentationService` publica `VersePresentationFailed` com `failure_stage="search"`. |
| **Quais eventos publicar** | `VersePresentationFailed`. |
| **Quem continua** | Pipeline continua. Versículo não é apresentado. Operador pode intervir manualmente. |

### Erro no Holyrics

| Aspecto | Descrição |
|---|---|
| **Como detectar** | `HolyricsClient.show_verse()` levanta exceção (connection, timeout, auth, api). |
| **Como recuperar** | `VersePresentationService` publica `VersePresentationFailed` com `failure_stage="holyrics"`. NÃO altera Health do Holyrics. |
| **Quais eventos publicar** | `VersePresentationFailed`. |
| **Quem continua** | Pipeline continua. HealthService verifica Holyrics periodicamente via health_check. |

### Erro no Replay

| Aspecto | Descrição |
|---|---|
| **Como detectar** | Replay engine encontra divergência ou exceção. |
| **Como recuperar** | Publica `BenchmarkFailed` com `failure_reason`. |
| **Quais eventos publicar** | `ReplayFinished` (com `success=False`), `BenchmarkFailed`. |
| **Quem continua** | Pipeline NÃO é afetado. Replay nunca altera estado do pipeline. |

### Erro no Benchmark

| Aspecto | Descrição |
|---|---|
| **Como detectar** | Benchmark validator encontra evento que não corresponde ao `benchmark.yaml`. |
| **Como recuperar** | Publica `BenchmarkFailed`. Log detalhado da divergência. |
| **Quais eventos publicar** | `BenchmarkFailed`. |
| **Quem continua** | Pipeline NÃO é afetado. Benchmark nunca altera comportamento. |

---

## 11. Degraded Modes

### Semantic indisponível

| Aspecto | Descrição |
|---|---|
| **Causa** | Ollama offline, modelo não instalado, timeout de inferência. |
| **Detecção** | `SemanticProviderUnavailable` publicado. |
| **Comportamento** | `IncrementalBiblicalParser` continua operando normalmente. `SemanticEngine` não publica `IntentCandidate`. `ReferenceResolver` não recebe candidatos. |
| **Impacto** | Referências implícitas não são detectadas. Referências explícitas (parser) continuam funcionando. |
| **Recuperação** | `SemanticEngine` tenta novamente a cada novo `SpeechPartial`. Se Ollama volta a ficar online, inferência é retomada. |

### Holyrics indisponível

| Aspecto | Descrição |
|---|---|
| **Causa** | Holyrics offline, token inválido, rede indisponível. |
| **Detecção** | `VersePresentationFailed` com `failure_stage="holyrics"`. HealthService marca Holyrics como unhealthy. |
| **Comportamento** | `VersePresentationService` continua tentando apresentar a cada novo `ReferenceDetected`. Cada tentativa falha e publica `VersePresentationFailed`. |
| **Impacto** | Versículos não são apresentados na tela. Detecção e parsing continuam normais. |
| **Recuperação** | HealthService verifica periodicamente. Quando Holyrics volta, apresentação é retomada. |

### Replay indisponível

| Aspecto | Descrição |
|---|---|
| **Causa** | EventStore vazio, benchmark.yaml ausente, erro de desserialização. |
| **Detecção** | Replay engine loga erro. |
| **Comportamento** | Replay não executa. Pipeline não é afetado. |
| **Impacto** | Teste de regressão não pode ser executado. |
| **Recuperação** | Reiniciar com EventStore populado. |

### Benchmark indisponível

| Aspecto | Descrição |
|---|---|
| **Causa** | `benchmark.yaml` ausente ou malformado. |
| **Detecção** | Benchmark validator loga erro. |
| **Comportamento** | Benchmark não executa. |
| **Impacto** | Validação de regressão não ocorre. |
| **Recuperação** | Corrigir `benchmark.yaml` e re-executar. |

### Searcher indisponível

| Aspecto | Descrição |
|---|---|
| **Causa** | `books.json` ausente, índice bíblico corrompido, config de busca ausente. |
| **Detecção** | `VersePresentationService` falha ao buscar. `ReferenceResolver` não valida candidatos. |
| **Comportamento** | `VersePresentationFailed` com `failure_stage="search"`. `SemanticResolutionCompleted` com `reason="all_invalid"`. |
| **Impacto** | Versículos não são apresentados nem resolvidos semanticamente. Parser continua detectando referências. |
| **Recuperação** | Corrigir `books.json` ou config de busca e reiniciar. |

---

## 12. Cancellation Policy

### Quando uma operação é cancelada

| Cenário | Quem cancela | O que é cancelado |
|---|---|---|
| `SemanticEngine` recebe novo `SpeechPartialUpdated` antes do debounce expirar | `SemanticEngine._schedule_inference` | Debounce timer anterior é cancelado |
| Pipeline é pausado | `engine.pause()` | `engine.process()` descarta segmentos |
| Pipeline é parado | `engine.stop()` | Threads param via `_stop_event.set()` |
| `SemanticEngine.stop()` | Chamado no shutdown | Debounce timer cancelado, inscrições removidas |

### Quem cancela

- `SemanticEngine` cancela seu próprio debounce timer.
- `StreamingPipelineEngine` cancela processamento de segmentos (descarta).
- Cada componente cancela suas próprias threads via `_stop_event`.

### Quem recebe cancelamento

- `threading.Timer` cancelado via `timer.cancel()`.
- Threads daemon via `_stop_event.set()` + `thread.join(timeout)`.
- EventBus: inscrições removidas via `bus.unsubscribe()`.

### Quais eventos são descartados

- `SpeechSegmentReceived` é descartado se pipeline não está ativo (`engine.process()` retorna `""`).
- `SpeechPartial` e `SpeechPartialUpdated` são ignorados se `StreamingSTTService._active=False`.
- Nenhum evento já publicado é descartado do EventStore.

### Quais continuam válidos

- Eventos já persistidos no EventStore permanecem válidos.
- `correlation_id` de fluxos anteriores permanece válido para rastreabilidade.
- Estado do `StateOrchestrator` (CAP-01, futuro) persiste entre segmentos.

---

## 13. Timeout Policy

### Timeouts oficiais

| Componente | Timeout | Config | Comportamento após timeout |
|---|---|---|---|
| **Streaming (SlidingWindow)** | 400ms por extração | hardcoded | Se `on_window` demora > 400ms, próximo ciclo não espera. Não há timeout fatal. |
| **Parser** | N/A (determinístico, < 10ms) | N/A | N/A |
| **Semantic (LLM)** | 5000ms (default) | `semantic.timeout_ms` | `SemanticInferenceCompleted` com `error="timeout"`. Inferência abortada. |
| **Searcher** | 500ms (implícito) | N/A | Se Searcher demora, `VersePresentationService` aguarda. Não há timeout explícito. |
| **Holyrics** | 2000ms (default) | `holyrics.timeout_ms` | `VersePresentationFailed` com `failure_stage="holyrics"`, `error_type="timeout"`. |
| **Presentation** | Mesmo do Holyrics | `holyrics.timeout_ms` | Igual ao Holyrics. |
| **Replay** | N/A (síncrono) | N/A | Replay executa até terminar. |
| **Benchmark** | N/A (síncrono) | N/A | Benchmark executa até terminar. |
| **STT (Whisper)** | Sem timeout explícito | N/A | Transcrição termina quando Whisper termina. Em CPU, ~3s para 6s de áudio. |
| **Semantic warmup** | 60s | hardcoded no warmup | Se warmup demora > 60s, log warning. SemanticEngine continua. |
| **Thread join (VAD)** | 2.0s | hardcoded | Se thread não termina em 2s, continua sem ela (daemon). |
| **Thread join (SpeechWorker)** | 5.0s | hardcoded | Se thread não termina em 5s, continua sem ela (daemon). |
| **Thread join (SlidingWindow)** | 2.0s | hardcoded | Se thread não termina em 2s, continua sem ela (daemon). |

---

## 14. Retry Policy

### Operações que podem repetir

| Operação | Repete? | Backoff | Limite |
|---|---|---|---|
| `SemanticEngine` inferência | Sim, a cada novo `SpeechPartial` | Sem backoff explícito. Rate limiting via `min_interval_ms=1000`. | Sem limite. |
| `VersePresentationService` apresentação | Sim, a cada novo `ReferenceDetected` | Sem backoff. Cada referência é uma nova tentativa. | Sem limite. |
| `HealthService` health_check | Sim, periódico | Intervalo configurável. | Sem limite. |

### Operações que nunca repetem

| Operação | Razão |
|---|---|
| `SpeechWorker` transcrição de segmento | Cada segmento é único. Se falha, publica vazio e segue. |
| `IncrementalBiblicalParser` parsing de parcial | Cada parcial é único. Se falha, log e segue. |
| `EventBus.publish` | Sem retry. Se handler falha, exceção propagada (ou capturada pelo handler). |
| Replay de evento | Cada evento é reproduzido uma vez. |

### Backoff

Não há backoff exponencial. O `SemanticEngine` usa rate limiting via `min_interval_ms` para evitar chamadas consecutivas ao LLM. O `VersePresentationService` tenta a cada novo `ReferenceDetected` sem backoff.

---

## 15. Backpressure Policy

### Fila cheia

| Fila | Tamanho máximo | Comportamento quando cheia |
|---|---|---|
| `_chunk_queue` (VAD) | 200 chunks | Descarta chunk mais antigo (`get_nowait` + `put_nowait`). PortAudio nunca bloqueia. |
| `SpeechQueue` | 10 segmentos | Descarta segmento (`put_nowait` falha, log warning). VAD continua. |
| `RingBuffer` | 20s de áudio | Sobrescreve áudio mais antigo (buffer circular). Sempre aceita escrita. |

### Entrada mais rápida que processamento

Se o pregador fala continuamente e o Whisper não acompanha:

1. `SlidingWindow` extrai janela a cada 400ms.
2. `StreamingSTTService` chama `STTExecutor.transcribe_audio()` que aguarda lock.
3. Se `SpeechWorker` está usando o Whisper, `StreamingSTTService` aguarda.
4. Enquanto aguarda, `SlidingWindow` não extrai próxima janela (execução síncrona no callback).
5. Quando Whisper libera, `StreamingSTTService` transcreve e `SlidingWindow` continua.

Se o VAD produz segmentos mais rápido que o SpeechWorker transcreve:

1. `SpeechQueue` enche (10 segmentos).
2. VAD tenta `put_nowait`, falha, descarta segmento.
3. Log warning: "SpeechQueue full — dropping segment".
4. Segmentos antigos são perdidos. O pipeline não para.

### Como evitar acúmulo

- `SpeechQueue` é bounded (10). Segmentos excedentes são descartados.
- `_chunk_queue` é bounded (200). Chunks excedentes substituem antigos.
- `RingBuffer` é circular (20s). Áudio antigo é sobrescrito.
- `SemanticEngine` tem rate limiting (`min_interval_ms=1000`) para não chamar LLM em cada parcial.

### Quando descartar

- Chunks de áudio: descartados quando `_chunk_queue` está cheia.
- Segmentos de fala: descartados quando `SpeechQueue` está cheia.
- Parciais de streaming: não são descartados (processados imediatamente ou ignorados se texto não mudou).

### Quando pausar captura

O sistema NÃO pausa captura automaticamente. A captura sempre continua. O backpressure é resolvido por descarte, não por pausa. O operador pode pausar manualmente via `POST /pipeline/pause`.

---

## 16. Memory Lifecycle

### Contexto (SermonContext)

| Fase | Descrição |
|---|---|
| **Criação** | `SermonMemoryEngine` cria `SermonContext` vazio no `start()`. |
| **Uso** | Atualizado incrementalmente a cada `SpeechTranscribed`, `ReferenceDetected`, `SpeechPartial`. |
| **Expiração** | Contexto expira após N segmentos sem menção ao livro atual (CAP-05, ADR-008). `active_book`, `active_chapter`, `pending_reference` são limpos. |
| **Limpeza** | `SermonMemoryEngine.stop()` descarta o contexto. Novo contexto é criado no próximo `start()`. |

### Referências

| Fase | Descrição |
|---|---|
| **Criação** | `ReferenceCandidate` e `ReferenceDetected` criam entradas no `SermonContext`. |
| **Uso** | `StateOrchestrator` (CAP-01, futuro) usa referências para decidir transições de estado. |
| **Expiração** | Referências recentes expiram do contexto após N segmentos. |
| **Limpeza** | Contexto é limpo na expiração de PREPARE (CAP-05). |

### Cache (SemanticCache)

| Fase | Descrição |
|---|---|
| **Criação** | `SemanticCache` instanciado vazio no startup. |
| **Uso** | `SemanticEngine` consulta cache antes de chamar LLM. Se `context_hash` bate, usa resultado cacheado. |
| **Expiração** | Sem expiração automática. Cache cresce indefinidamente durante a sessão. |
| **Limpeza** | `SemanticEngine.stop()` descarta o cache. Novo cache é criado no próximo `start()`. |

### Buffers

| Buffer | Tamanho | Criação | Limpeza |
|---|---|---|---|
| `RingBuffer` | 20s x 16000 Hz x 2 bytes = ~640KB | Startup | Sobrescrito continuamente. `stop()` não limpa. |
| `_chunk_queue` | 200 chunks x ~320 bytes = ~64KB | `SpeechPipelineService.start()` | `stop()` esvazia implicitamente (thread para de consumir). |
| `SpeechQueue` | 10 segmentos x áudio variável | Startup | `SpeechQueue.clear()` esvazia. |

### Replay

| Fase | Descrição |
|---|---|
| **Criação** | Replay lê eventos do `EventStore` (em memória). |
| **Uso** | Eventos são reproduzidos em ordem. Comparados com benchmark. |
| **Expiração** | N/A (síncrono, termina quando acaba). |
| **Limpeza** | `EventStore` é limpo quando `MemoryEventStore` é destruído (fim do processo). |

---

## 17. Graceful Shutdown

### Ordem de desligamento

O desligamento é triggered por `POST /pipeline/stop` e executa na ordem inversa de inicialização:

```
1.  SpeechWorker.stop()           ← para de consumir SpeechQueue (join timeout=5s)
2.  SpeechPipelineService.stop()  ← para VAD, flush final (join timeout=2s)
3.  AudioCaptureService.stop()    ← para captura de microfone
4.  SlidingWindow.stop()          ← para extração de janelas (join timeout=2s)
5.  StreamingSTTService.stop()    ← marca como inativo
6.  IncrementalBiblicalParser.stop()  ← desinscreve do EventBus
7.  SemanticEngine.stop()         ← cancela debounce timer, desinscreve
8.  ReferenceResolver.stop()      ← desinscreve
9.  SermonMemoryEngine.stop()     ← desinscreve
10. VersePresentationService.stop()  ← desinscreve
11. BiblicalNLUService.stop()     ← desinscreve
12. StreamingPipelineEngine.stop()  ← publica PipelineStopped, state.running=False
```

### Quem para primeiro

`SpeechWorker` para primeiro. Isso garante que nenhum novo `SpeechTranscribed` seja publicado enquanto os demais componentes ainda estão ativos.

### Quem para por último

`StreamingPipelineEngine` para por último. Isso garanta que `PipelineStopped` seja publicado após todos os componentes terem parado, e que nenhum evento operacional seja perdido.

### Como garantir que nenhum evento seja perdido

1. `SpeechPipelineService.stop()` faz `segmenter.force_flush()` antes de parar a thread. Se há áudio acumulado no VAD, um segmento final é emitido e enfileirado.
2. `SpeechWorker.stop()` aguarda até 5s para terminar transcrição em andamento.
3. Todos os eventos publicados antes de `PipelineStopped` são persistidos no `EventStore`.
4. `PipelineStopped` é o último evento publicado.

### Como finalizar filas

- `SpeechQueue`: `SpeechWorker` consome até esvaziar ou timeout. Segmentos restantes são perdidos.
- `_chunk_queue`: VAD thread para de consumir. Chunks restantes são perdidos.
- `RingBuffer`: Não é explicitamente limpo. Memória é liberada pelo GC.

### Como finalizar Replay

Replay é síncrono: se está em andamento durante o shutdown, ele termina antes do desligamento (ou é abortado se o processo é morto). Não há finalização especial.

### Como finalizar Telemetry

Telemetry não tem thread própria (hooks são chamados síncronamente). Não há finalização especial.

---

## 18. Runtime Invariants

1. **Nenhum handler chama outro handler diretamente.** Toda comunicação ocorre via EventBus.
2. **Toda comunicação ocorre pelo EventBus.** Nenhum componente chama outro diretamente (exceção: Composition Root durante inicialização).
3. **Nenhum evento Operational é perdido.** Todo `OperationalEvent` é persistido no `EventStore` antes do dispatch.
4. **Toda exceção gera evento.** Handlers capturam exceções e publicam `PipelineError` ou evento específico de erro.
5. **Nenhum componente modifica eventos recebidos.** Eventos são `frozen dataclass` (imutáveis).
6. **`StateOrchestrator` é a única origem de `StateChanged`.** Nenhum outro componente publica `StateChanged` (CAP-01, ADR-001).
7. **`SemanticEngine` nunca publica `ReferenceDetected`.** Apenas `ReferenceResolver` pode fazer isso após validação (ADR-004).
8. **Replay nunca altera estado do pipeline.** Replay apenas lê e compara.
9. **Benchmark nunca altera comportamento.** Benchmark apenas valida.
10. **EventBus é síncrono.** Handlers executam na thread do publisher, na ordem de inscrição.
11. **`STTExecutor` serializa acesso ao Whisper.** Apenas uma transcrição por vez.
12. **PortAudio callback nunca bloqueia.** Apenas enfileira.
13. **Todas as threads são daemon.** O processo pode terminar mesmo se threads estão rodando.
14. **`PipelineState` é imutável.** Mudanças produzem novo estado via `with_*` methods.
15. **`correlation_id` é constante dentro de um fluxo.** Preservado de `SpeechPartial` até `VersePresented`.
16. **`causation_id` forma cadeia.** Cada evento aponta para seu predecessor.
17. **Componentes opcionais não abortam o startup.** Falha de componente individual loga warning e continua.
18. **Shutdown é ordem inversa de startup.** SpeechWorker para primeiro, Engine para por último.

---

## 19. Runtime Sequence Diagrams

### 1. Referência explícita

```
[SlidingWindow]  [StreamingSTT]  [EventBus]  [Parser]  [VersePresentation]  [Holyrics]
      |               |              |           |              |                |
      |--read_last--->|              |           |              |                |
      |               |--transcribe->|           |              |                |
      |               |  (STTExecutor.lock)      |              |                |
      |               |<--result----|           |              |                |
      |               |--publish--->|           |              |                |
      |               |  SpeechPartial|          |              |                |
      |               |              |-->handle->|              |                |
      |               |              |           |--parse------>|                |
      |               |              |           |  book+ch+vs  |                |
      |               |              |           |  conf=0.98   |                |
      |               |              |<--publish-|              |                |
      |               |              |  RefDetected              |                |
      |               |              |-->handle----------------->|                |
      |               |              |           |  |--search--->|                |
      |               |              |           |  |<--result---|                |
      |               |              |<--publish-|  | VerseResolved               |
      |               |              |           |  |--show_verse->|              |
      |               |              |           |  |<--ok---------|              |
      |               |              |<--publish-|  | VersePresented              |
```

### 2. Referência construída em múltiplos segmentos

```
[SlidingWindow]  [StreamingSTT]  [EventBus]  [Parser]  [StateOrchestrator(futuro)]
      |               |              |           |              |
      |               |              |           |              |
      |--window1----->|--transcribe->|           |              |
      |               |--publish---->|           |              |
      |               |  SpeechPartial|          |              |
      |               |              |-->handle->|              |
      |               |              |           |--parse("joão")|
      |               |              |<--publish-|              |
      |               |              |  RefCandidate            |
      |               |              |           |  (book only) |
      |               |              |           |  conf=0.60   |
      |               |              |           |              |
      |--window2----->|--transcribe->|           |              |
      |               |--publish---->|           |              |
      |               |  SpeechPartialUpdated    |              |
      |               |              |-->handle->|              |
      |               |              |           |--parse("joão cap 3")|
      |               |              |<--publish-|              |
      |               |              |  RefCandidate            |
      |               |              |           |  (book+ch)   |
      |               |              |           |  conf=0.85   |
      |               |              |           |              |
      |--window3----->|--transcribe->|           |              |
      |               |--publish---->|           |              |
      |               |  SpeechPartialUpdated    |              |
      |               |              |-->handle->|              |
      |               |              |           |--parse("joão 3:16")|
      |               |              |<--publish-|              |
      |               |              |  ReferenceDetected       |
      |               |              |           |  conf=0.95   |
      |               |              |           |  complete    |
```

### 3. Referência rejeitada

```
[StreamingSTT]  [EventBus]  [Parser]  [SemanticEngine]  [ReferenceResolver]
      |              |           |              |                |
      |--publish---->|           |              |                |
      |  SpeechPartial|          |              |                |
      |              |-->handle->|              |                |
      |              |           |--parse------>|                |
      |              |           |  no match    |                |
      |              |           |              |                |
      |              |-->handle----------------->|                |
      |              |           |  (debounce)  |                |
      |              |           |              |--LLM call----->|
      |              |           |              |  (timeout 5s) |
      |              |           |              |<--result------|
      |              |<--publish-|              |  IntentCandidate
      |              |  IntentCandidate        |                |
      |              |-->handle--------------------------------->|
      |              |           |              |  |--validate->|
      |              |           |              |  | (Searcher) |
      |              |           |              |  |<--invalid--|
      |              |<--publish-|              |  | IntentRejected
```

### 4. Menção narrativa

```
[StreamingSTT]  [EventBus]  [Parser]  [SemanticEngine]  [ReferenceResolver]
      |              |           |              |                |
      |--publish---->|           |              |                |
      |  SpeechPartial|          |              |                |
      |              |-->handle->|              |                |
      |              |           |--parse------>|                |
      |              |           |  "como disseram|              |
      |              |           |   os profetas" |              |
      |              |           |  no_match     |                |
      |              |           |              |                |
      |              |-->handle----------------->|                |
      |              |           |              |--LLM call----->|
      |              |           |              |  context:     |
      |              |           |              |  sermon_ctx   |
      |              |           |              |  active_book= |
      |              |           |              |  "Isaías"     |
      |              |           |              |<--result------|
      |              |           |              |  intent:      |
      |              |           |              |  "Isaías 53"  |
      |              |<--publish-|              |  IntentCandidate
      |              |-->handle--------------------------------->|
      |              |           |              |  |--validate->|
      |              |           |              |  | (Searcher) |
      |              |           |              |  |<--valid----|
      |              |<--publish-|              |  | ReferenceDetected
```

### 5. Repeat

```
[Parser]  [EventBus]  [StateOrchestrator(futuro)]  [VersePresentation]
   |           |                   |                      |
   |--parse-->|                   |                      |
   |  RefDetected                  |                      |
   |           |-->handle--------->|                      |
   |           |                   |--check repeat------->|
   |           |                   |  same as last?       |
   |           |                   |  YES                 |
   |           |<--publish---------|                      |
   |           |  StateChanged     |                      |
   |           |  new_state=IGNORE |                      |
   |           |                   |                      |
   |           | (no VerseResolving published)            |
   |           | (no presentation)                        |
```

### 6. Expiração de PREPARE

```
[StateOrchestrator(futuro)]  [EventBus]  [Timer]
         |                       |           |
         |--enter PREPARE------->|           |
         |  StateChanged         |           |
         |                       |           |
         |--start timer----------|---------->|
         |  (PREPARE_TIMEOUT)    |           |
         |                       |           |
         |    ... tempo passa ... |           |
         |                       |           |
         |<--timeout expire-------|-----------|
         |                       |           |
         |--enter WAIT----------->|           |
         |  StateChanged         |           |
         |  new_state=WAIT       |           |
         |  reason="prepare_timeout"        |
         |                       |           |
         | (clear pending_reference)        |
         | (clear active_chapter)           |
```

### 7. Falha do Holyrics

```
[Parser]  [EventBus]  [VersePresentation]  [Holyrics]
   |           |              |                  |
   |--parse-->|              |                  |
   |  RefDetected              |                  |
   |           |-->handle----->|                  |
   |           |              |--search----------->|
   |           |              |  (Searcher OK)    |
   |           |<--publish----|  VerseResolved    |
   |           |              |--show_verse------>|
   |           |              |                   |
   |           |              |  X (connection    |
   |           |              |    refused)       |
   |           |              |<--exception-------|
   |           |              |                   |
   |           |<--publish----|                   |
   |           |  VersePresentationFailed         |
   |           |  failure_stage="holyrics"       |
   |           |  error_type="connection_error"  |
   |           |              |                   |
   |           |              | (pipeline continua)|
   |           |              |  (não altera health)|
```

### 8. Semantic indisponível

```
[StreamingSTT]  [EventBus]  [SemanticEngine]  [Ollama]
      |              |              |              |
      |--publish---->|              |              |
      |  SpeechPartial|             |              |
      |              |-->handle----->|              |
      |              |              |--check cache-|
      |              |              |  (miss)      |
      |              |              |--call LLM--->|
      |              |              |              |
      |              |              |  X (server   |
      |              |              |    offline)  |
      |              |              |<--error------|
      |              |              |              |
      |              |<--publish----|              |
      |              |  SemanticProviderUnavailable|
      |              |  reason="server_offline"    |
      |              |              |              |
      |              | (Parser continua normal)    |
      |              | (SermonMemory continua)     |
```

### 9. Replay

```
[ReplayEngine]  [EventBus]  [EventStore]  [BenchmarkValidator]
      |              |              |              |
      |--start------->|             |              |
      |  ReplayStarted|             |              |
      |              |              |              |
      |--read events---------------|              |
      |<--events[]---|              |              |
      |              |              |              |
      |--replay event1 (StateChanged WAIT→PREPARE)|
      |              |              |              |
      |--replay event2 (ReferenceDetected "João 3:16")|
      |              |              |              |
      |--replay event3 (StateChanged PREPARE→PRESENT)|
      |              |              |              |
      |--replay eventN...           |              |
      |              |              |              |
      |--finish----->|             |              |
      |  ReplayFinished             |              |
      |  success=True              |              |
      |              |              |              |
      |--validate------------------|------------->|
      |              |              |  (compare   |
      |              |              |   with      |
      |              |              |   benchmark)|
      |<--result-----|--------------|-------------|
      |              |              |              |
      |--publish---->|              |              |
      |  BenchmarkPassed             |              |
```

### 10. Benchmark

```
[ReplayEngine]  [BenchmarkValidator]  [EventBus]
      |              |                    |
      |--replay----->|                    |
      |  events      |                    |
      |              |                    |
      |              |--compare with      |
      |              |  benchmark.yaml    |
      |              |                    |
      |              |  DIVERGENCE found: |
      |              |  expected: StateChanged|
      |              |   PREPARE→PRESENT    |
      |              |  got: StateChanged   |
      |              |   PREPARE→IGNORE     |
      |              |                    |
      |<--fail-------|                    |
      |              |                    |
      |--publish---->|                    |
      |  BenchmarkFailed                  |
      |  failure_reason="state_mismatch   |
      |   at segment 7: expected PRESENT, |
      |   got IGNORE"                     |
      |              |                    |
      | (pipeline NÃO é afetado)          |
      | (benchmark nunca altera           |
      |  comportamento)                   |
```

---

## 20. Performance Budget

### Orçamento de latência por componente

```
Captura (PortAudio callback)
    ↓ < 10ms
RingBuffer write
    ↓ < 1ms
SlidingWindow extract (6s window)
    ↓ < 5ms
STT (Whisper transcribe 6s)
    ↓ < 3000ms (CPU) / < 500ms (GPU)
StreamingSTT diff + publish
    ↓ < 5ms
Parser incremental
    ↓ < 10ms
[paralelo] SemanticEngine (LLM)
    ↓ < 5000ms (timeout)
[paralelo] ReferenceResolver (Searcher validate)
    ↓ < 500ms
StateOrchestrator (futuro)
    ↓ < 5ms
VersePresentationService (Searcher + Holyrics)
    ↓ < 2500ms (500ms search + 2000ms holyrics)
Telemetry hooks
    ↓ < 1ms
```

### Latência total alvo (fluxo streaming, parser path)

| Componente | Alvo |
|---|---|
| Captura → RingBuffer | < 10ms |
| SlidingWindow → STT | < 3000ms (CPU) / < 500ms (GPU) |
| STT → Parser → ReferenceDetected | < 20ms |
| ReferenceDetected → VersePresented | < 2500ms |
| **Total (fim a fim)** | **< 5500ms (CPU) / < 3000ms (GPU)** |

### Latência total alvo (fluxo semântico, LLM path)

| Componente | Alvo |
|---|---|
| Captura → RingBuffer | < 10ms |
| SlidingWindow → STT | < 3000ms (CPU) / < 500ms (GPU) |
| STT → SemanticEngine debounce | 400ms (debounce) ou imediato (growth trigger) |
| SemanticEngine → LLM | < 5000ms (timeout) |
| LLM → ReferenceResolver → ReferenceDetected | < 500ms |
| ReferenceDetected → VersePresented | < 2500ms |
| **Total (fim a fim)** | **< 11500ms (CPU, debounce) / < 9000ms (GPU, debounce)** |

### Latência máxima aceitável

| Cenário | Máximo aceitável | Consequência se exceder |
|---|---|---|
| Parser path (CPU) | 6000ms | Pregador já passou para outro tópico. Apresentação atrasada. |
| Parser path (GPU) | 3500ms | Aceitável. Pregador ainda no tópico. |
| Semantic path (CPU) | 12000ms | Pregador já avançou. Apresentação pode ser irrelevante. |
| Semantic path (GPU) | 10000ms | Limite superior. |
| Holyrics (show_verse) | 2000ms | Timeout. `VersePresentationFailed`. |

### Tempo máximo por componente

| Componente | Tempo máximo | Tipo |
|---|---|---|
| PortAudio callback | 10ms | Hard limit (real-time audio) |
| RingBuffer write | 1ms | Hard limit |
| SlidingWindow extract | 5ms | Soft limit |
| STT (Whisper, CPU) | 3000ms | Estimativa (6s de áudio) |
| STT (Whisper, GPU) | 500ms | Estimativa (6s de áudio) |
| Parser incremental | 10ms | Soft limit |
| SemanticEngine (LLM) | 5000ms | Hard limit (timeout) |
| Searcher | 500ms | Soft limit |
| Holyrics | 2000ms | Hard limit (timeout) |
| Telemetry hooks | 1ms | Soft limit |

---

## 21. Observabilidade em Runtime

### Logs

O sistema usa `logging` padrão Python com níveis:

| Nível | Quando | Exemplo |
|---|---|---|
| `INFO` | Eventos de lifecycle, startup, shutdown | "Sprint 19: Streaming Speech Pipeline started" |
| `WARNING` | Componente falhou mas sistema continua | "Sprint 18: search config not found" |
| `ERROR` | Erro em handler, transcrição falhou | "Whisper transcription failed: %s" |
| `DEBUG` | Métricas detalhadas, diffs de parciais | "StreamingSTT: skipping silence (rms=0.000312)" |

### Métricas

| Métrica | Fonte | Tipo |
|---|---|---|
| `total_windows` | StreamingSTTService | Contador |
| `total_partials_published` | StreamingSTTService | Contador |
| `total_updates_published` | StreamingSTTService | Contador |
| `total_skipped_silence` | StreamingSTTService | Contador |
| `total_skipped_low_confidence` | StreamingSTTService | Contador |
| `total_skipped_no_change` | StreamingSTTService | Contador |
| `avg_latency_ms` | StreamingSTTService | Média |
| `total_transcribed` | SpeechWorker | Contador |
| `total_errors` | SpeechWorker | Contador |
| `avg_latency_ms` | SpeechWorker | Média |
| `total_jobs` | STTExecutor | Contador |
| `avg_wait_ms` | STTExecutor | Média (fila do lock) |
| `avg_exec_ms` | STTExecutor | Média (execução Whisper) |
| `total_enqueued` | SpeechQueue | Contador |
| `total_dropped` | SpeechQueue | Contador |
| `max_size_reached` | SpeechQueue | Pico |
| `total_extractions` | SlidingWindow | Contador |
| `total_calls` | SemanticEngine | Contador |
| `total_cache_hits` | SemanticEngine | Contador |
| `total_errors` | SemanticEngine | Contador |
| `total_growth_triggers` | SemanticEngine | Contador |
| `total_debounce_triggers` | SemanticEngine | Contador |
| `record_segment_received` | PipelineMetrics | Contador |
| `record_segment_dropped` | PipelineMetrics | Contador |
| `record_correlation` | PipelineMetrics | Contador |

### Traces

A rastreabilidade é garantida por `EventMetadata` em cada evento:

| Campo | Função |
|---|---|
| `event_id` | UUID único por evento |
| `correlation_id` | Constante dentro de um fluxo (SpeechPartial → VersePresented) |
| `causation_id` | Aponta para o evento predecessor (cadeia causal) |
| `session_id` | Constante durante a sessão do pipeline |
| `timestamp` | Momento de criação do evento |
| `origin` | Componente que publicou o evento |

### Eventos persistidos

Apenas `OperationalEvent` subclasses são persistidos no `EventStore` (MemoryEventStore). `TelemetryEvent` subclasses são despachados aos handlers mas NÃO persistidos.

### Eventos descartáveis

`TelemetryEvent` subclasses não são persistidos. São usados apenas para observabilidade em tempo real (dashboards, alertas).

### KPIs

| KPI | Descrição | Meta |
|---|---|---|
| Latência fim a fim (parser) | SpeechPartial → VersePresented | < 5500ms (CPU) |
| Latência fim a fim (semântico) | SpeechPartial → VersePresented | < 11500ms (CPU) |
| Taxa de cache hit (SemanticEngine) | cache_hits / total_calls | > 30% |
| Taxa de descarte (SpeechQueue) | dropped / enqueued | < 5% |
| Taxa de alucinação (StreamingSTT) | skipped_silence / total_windows | Monitorar |
| Confiança média (STT) | avg confidence | > 0.50 |
| Tempo médio no lock (STTExecutor) | avg_wait_ms | < 500ms |

### Alertas

| Alerta | Condição | Severidade |
|---|---|---|
| SemanticProviderUnavailable | Ollama offline | Warning |
| SpeechQueue full | `total_dropped > 0` | Warning |
| STT latency alta | `avg_latency_ms > 5000` | Warning |
| Holyrics unhealthy | HealthService report | Critical |
| SemanticEngine timeout | `total_errors` incrementando | Warning |
| Cache hit rate baixo | `cache_hits / total_calls < 10%` | Info |

---

## 22. Assumptions

1. **Single-process.** O AI Lyrics roda como um único processo Python (uvicorn). Não há multiprocessamento. Comunicação entre componentes é in-process via EventBus.
2. **Single-machine.** Todos os componentes rodam na mesma máquina, exceto Holyrics (acessado via HTTP) e Ollama (acessado via HTTP).
3. **Whisper é single-instance.** Apenas uma instância do modelo Whisper em RAM/VRAM (~2GB). `STTExecutor` serializa o acesso.
4. **EventBus é síncrono.** Handlers executam na thread do publisher. Não há filas internas no EventBus.
5. **EventStore é em memória.** `MemoryEventStore` não persiste em disco. Eventos são perdidos quando o processo termina.
6. **AudioCaptureService suporta um único callback.** Apenas um `on_audio_data` pode ser registrado por vez. O RingBuffer é conectado via atributo `_ring_buffer` no `audio_capture`.
7. **Ollama pode não estar rodando.** O sistema foi projetado para operar sem Semantic Engine. A ausência do Ollama não impede o startup.
8. **Holyrics pode não estar rodando.** O sistema foi projetado para operar sem apresentação. A ausência do Holyrics não impede o startup.
9. **config.yaml é a fonte de verdade de configuração.** Todos os parâmetros (timeouts, modelos, endpoints) vêm do config.
10. **O pregador fala em português.** O Whisper é configurado para `language="pt"`. O parser é configurado para livros em português.
11. **O VAD detecta fala corretamente.** Silêncios curtos dentro de fala contínua podem não fechar segmentos. O fluxo streaming complementa o fluxo segmentado.
12. **O benchmark.yaml é a verdade para regressão.** Replay compara eventos produzidos com o benchmark. Divergências geram `BenchmarkFailed`.
13. **Threads daemon morrem com o processo.** Se o processo é morto (SIGKILL), threads daemon morrem imediatamente sem flush. Apenas `POST /pipeline/stop` garante graceful shutdown.
14. **StateOrchestrator (CAP-01) é futuro.** O estado WAIT/PREPARE/PRESENT/IGNORE não está implementado no código atual. Os eventos `StateChanged` existem nos contratos mas não são publicados em runtime.
15. **SemanticEngine nunca publica ReferenceDetected.** Apenas `ReferenceResolver` pode fazer isso após validação via Searcher (ADR-004).

---

## 23. Non-Goals

1. **Distribuído.** O runtime não suporta múltiplos processos ou máquinas coordenadas. Não há message broker externo (RabbitMQ, Kafka). O EventBus é in-process.
2. **Persistência em disco.** O EventStore é em memória. Não há persistência de eventos entre reinícios do processo.
3. **Multi-tenant.** O runtime suporta uma única sessão de pipeline por vez. Não há isolamento entre múltiplos usuários.
4. **Auto-scaling.** O runtime não escala horizontalmente. Uma instância do Whisper, uma instância do SemanticEngine.
5. **Hot reload.** Componentes não podem ser recarregados sem reiniciar o processo. Config changes requerem restart.
6. **Auth/Autorização no EventBus.** Qualquer componente pode publicar e inscrever em qualquer evento. Não há ACL.
7. **Backpressure com pausa automática.** O sistema resolve backpressure por descarte, não por pausa automática da captura.
8. **Retry com backoff exponencial.** Não há backoff. Rate limiting simples via `min_interval_ms`.
9. **Garantia de entrega (at-least-once, exactly-once).** O EventBus é fire-and-forget. Se um handler falha, o evento é perdido (não há re-entrega).
10. **Ordenação entre threads.** Eventos publicados de threads diferentes não têm ordenação garantida. Apenas dentro de um `publish()` a ordem é determinística (ordem de inscrição).
11. **Transações.** Não há transações no EventBus. Um handler pode publicar eventos antes de um handler posterior falhar.
12. **Schema evolution em runtime.** Eventos são frozen dataclasses. Mudanças de schema requerem reinício do processo.
13. **Monitoramento externo.** Não há integração com Prometheus, Grafana, ou OpenTelemetry. Métricas são acessíveis via API FastAPI.
14. **Cancelamento de operações em andamento.** Uma vez que um handler começa a executar (ex: LLM call, Holyrics call), não pode ser cancelado. Apenas o debounce timer pode ser cancelado antes de disparar.
15. **Múltiplas versões bíblicas simultâneas.** A versão bíblica é configurada uma vez no startup (`config.state.default_version`). Não há troca em runtime.
