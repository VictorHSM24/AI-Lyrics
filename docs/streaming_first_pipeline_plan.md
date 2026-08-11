# Streaming-First Pipeline Plan

Plano arquitetural para transformar o AI Lyrics em um pipeline streaming-first, onde `SpeechPartial`/`SpeechPartialUpdated` são o fluxo operacional primário e `SpeechTranscribed` torna-se o evento de confirmação/finalização, com migração incremental de parser, semântica, contexto, estado, apresentação e Reading Follow para consumir o stream contínuo.

> **Decisões confirmadas com o usuário**:
> 1. Entregável final em `AI-Lyrics/docs/streaming_first_pipeline_plan.md` (versionável).
> 2. StateOrchestrator (CAP-01): especificar **e** implementar as transições como parte da migração.
> 3. Fluxo segmentado VAD→SpeechWorker→BiblicalNLUService: reformular como caminho de **finalização/confirmação** — `SpeechTranscribed` deixa de disparar o parser determinístico (o incremental já tratou) e passa a confirmar o texto final.
> 4. ReadingFollowService: migrar para consumir `SpeechPartial`/`SpeechPartialUpdated` com janela de estabilidade + debounce.

---

## 1. Current Architecture Diagnosis

### 1.1 Visão geral

O AI Lyrics possui **dois caminhos paralelos** de processamento de áudio que coexistem e compartilham o mesmo modelo Whisper via `STTExecutor` (que serializa o acesso):

```
Caminho A — Segmentado (Sprint 16/17):
  AudioCapture → SpeechPipelineService (VAD) → SpeechQueue → SpeechWorker
    → SpeechTranscribed → BiblicalNLUService (parser determinístico stateless)
    → ReferenceDetected → VersePresentationService → Holyrics

Caminho B — Streaming (Sprint 19+):
  AudioCapture → RingBuffer → SlidingWindow (400ms) → StreamingSTTService
    → SpeechPartial / SpeechPartialUpdated
    → IncrementalBiblicalParser (parser incremental stateful)
      → ReferenceCandidate / ReferenceAntecipada / ReferenceDetected
    → SemanticEngine (debounce/growth) → IntentCandidate
      → ReferenceResolver → ReferenceDetected
    → SermonMemoryEngine → SermonContextUpdated
  [paralelo] SpeechWorker ainda emite SpeechTranscribed ao fechar segmento VAD
```

### 1.2 Diagnóstico dos problemas atuais

| Problema | Causa | Impacto |
|---|---|---|
| **Dependência excessiva de `SpeechTranscribed`** | `BiblicalNLUService`, `StateOrchestrator`, `VersionCommandDetector`, `ReadingFollowService` e o frontend consomem `SpeechTranscribed` | Durante fala contínua, o VAD pode não fechar o segmento por longos períodos; parser/state/reading-follow/version ficam inativos ou atrasados |
| **Parser duplicado** | `BiblicalNLUService` (stateless, em `SpeechTranscribed`) e `IncrementalBiblicalParser` (stateful, em `SpeechPartial`) fazem parsing do mesmo texto em momentos diferentes | Referências podem ser detectadas duas vezes (incremental antecipa, NLU confirma); sem dedup coordenado, `VersePresentationService` pode apresentar duas vezes |
| **StateOrchestrator é esqueleto** | Handlers `_handle_*` contêm apenas `pass`/TODO | Nenhum `StateChanged` é publicado; não há máquina WAIT/PREPARE/PRESENT/IGNORE; não há dedup autoritativo; `VersePresentationService` age diretamente sobre `ReferenceDetected` sem coordenação |
| **SemanticEngine sem cancelamento de inferência stale** | Debounce cancela timer, mas inferência em curso (Ollama) não é cancelável; resultado stale pode chegar após novo partial | Resultados regressivos; `IntentCandidate` com texto antigo pode gerar `ReferenceDetected` incorreto |
| **Ollama serial + GPU compartilhada** | Ollama roda um modelo por vez na GPU; Whisper também usa GPU | Concorrência entre Whisper (streaming + segmentos) e Ollama (semântica) causa timeouts (observado: 15s) |
| **Reading Follow em `SpeechTranscribed`** | Avança versículo apenas após pausa do VAD | Latência alta entre versículos consecutivos durante leitura contínua |
| **ContextEngine lê `bus.history()`** | Varre todo o EventStore a cada inferência | Custo O(n) crescente durante a sessão; não escala para sessões longas |
| **`SpeechPartial`/`Updated` não têm conceito de STABLE** | `is_stable` existe no dataclass mas é sempre `False` | Downstream não tem sinal confiável de "texto parou de mudar" sem esperar `SpeechTranscribed` |

### 1.3 O que para/demora sem `SpeechTranscribed`

Quando o VAD não fecha o segmento (fala contínua longa):
- **Para**: `BiblicalNLUService` (não recebe texto), `StateOrchestrator._handle_speech_transcribed` (noop anyway), `VersionCommandDetector`, `ReadingFollowService` (não avança versículo).
- **Continua mas sem confirmação**: `IncrementalBiblicalParser` (publica `ReferenceCandidate`/`ReferenceAntecipada`/`ReferenceDetected`), `SemanticEngine` (publica `IntentCandidate`), `SermonMemoryEngine` (atualiza contexto).
- **Demora**: confirmação final do texto, dedup entre antecipada e definitiva, limpeza de estado do parser incremental (reset só em novo `correlation_id`).

---

## 2. Current Pipeline Audit

Auditoria estágio por estágio do fluxo atual. **Nenhuma correção é proposta aqui** — apenas documentação do comportamento existente.

### 2.1 Microphone / AudioCaptureService

| Aspecto | Valor |
|---|---|
| **Arquivo** | `microfone/audio_capture_service.py` |
| **Input** | Áudio nativo do dispositivo (ex.: 44100 Hz, stereo) |
| **Output** | `float32` numpy array, 16000 Hz, mono (após downmix + resample) |
| **Evento** | Nenhum (callback `on_audio_data(float32, timestamp)`) |
| **Dependências** | `sounddevice`/PortAudio, `config.audio` |
| **Estado interno** | device index, native_sr, native_ch, output_sr, output_ch |
| **Buffering** | Nenhum (streaming direto via callback) |
| **Threading** | Thread PortAudio (real-time) |
| **Latência** | < 10ms (callback) |
| **Bug corrigido** | `channels: 2` causava flatten interleaved em vez de downmix; corrigido para `channels: 1` (commit `d2c0263`) |
| **Dependência de `SpeechTranscribed`** | Nenhuma |
| **Dependência de silêncio** | Nenhuma |

### 2.2 VAD / SpeechPipelineService

| Aspecto | Valor |
|---|---|
| **Arquivo** | `microfone/speech_pipeline.py` |
| **Input** | chunks `float32` 16kHz mono do AudioCaptureService |
| **Output** | `SpeechSegment` (áudio int16 PCM) na `SpeechQueue` |
| **Eventos** | `SpeechStarted`, `SpeechEnded`, `SpeechSegmentCreated` |
| **Dependências** | `VadSegmenter` (Silero VAD), `AudioChunkQueue` (bounded 200), `SpeechQueue` (bounded 10) |
| **Estado interno** | segmenter, chunk_queue, running |
| **Buffering** | `_chunk_queue` (200 chunks), `SpeechQueue` (10 segmentos) |
| **Debounce/timeout** | `min_speech_ms=600`, `max_silence_ms=800`, `max_segment_ms=30000`, `vad_mode=3` |
| **Condição de execução** | pipeline running |
| **Condição de descarte** | chunk_queue cheio → descarta mais antigo; SpeechQueue cheio → descarta segmento |
| **Dependência de `SpeechTranscribed`** | Nenhuma (produz upstream) |
| **Dependência de silêncio** | **Sim** — `max_silence_ms` fecha o segmento |
| **Threading** | Thread própria "VAD" |
| **Latência** | Fim da fala → segmento: `max_silence_ms` (800ms) |

### 2.3 SpeechWorker (segmentos finais)

| Aspecto | Valor |
|---|---|
| **Arquivo** | `microfone/speech_worker.py` |
| **Input** | `SpeechSegment` da `SpeechQueue` |
| **Output** | `SpeechTranscribed` |
| **Eventos** | `SpeechTranscribing`, `SpeechTranscribed` |
| **Dependências** | `STT` (faster-whisper), `STTExecutor` (serializa com streaming) |
| **Estado interno** | running, métricas |
| **Buffering** | `SpeechQueue` (10) |
| **Threading** | Thread própria "SpeechWorker" |
| **Latência** | < 1500ms (alvo), ~500ms GPU / ~3000ms CPU |
| **Dependência de `SpeechTranscribed`** | É o **publisher** |
| **Dependência de silêncio** | Indireta (segmento só existe após silêncio fechar) |

### 2.4 RingBuffer + SlidingWindow

| Aspecto | Valor |
|---|---|
| **Arquivos** | `microfone/ring_buffer.py`, `microfone/sliding_window.py` |
| **Input** | `float32` 16kHz mono (escrito pelo AudioCapture hook) |
| **Output** | janela de 6s de áudio a cada 400ms via callback `on_window` |
| **Eventos** | Nenhum |
| **Dependências** | RingBuffer (20s circular, thread-safe) |
| **Estado interno** | running, total_extractions, total_empty |
| **Buffering** | RingBuffer 20s (~640KB) |
| **Threading** | Thread própria "SlidingWindow-Extractor" (daemon) |
| **Latência** | Extração < 5ms |
| **Independência do VAD** | **Sim** — extrai continuamente, independente de fala/silêncio |
| **Dependência de `SpeechTranscribed`** | Nenhuma |
| **Dependência de silêncio** | Nenhuma |

### 2.5 StreamingSTTService

| Aspecto | Valor |
|---|---|
| **Arquivo** | `microfone/streaming_stt_service.py` |
| **Input** | janela 6s de áudio (callback `on_window`) |
| **Output** | `SpeechPartial` (primeira), `SpeechPartialUpdated` (evolução com diff) |
| **Dependências** | `STTExecutor` (serializa Whisper), `EventBus` |
| **Estado interno** | `_current_text`, `_current_correlation_id`, `_current_causation_id`, `_current_language`, métricas |
| **Buffering** | Nenhum (transcrição síncrona no callback) |
| **Debounce/timeout** | `min_text_change=3` chars, `min_rms=0.005`, `min_confidence=0.30`, descarta áudio < 1s |
| **Condição de descarte** | silêncio (RMS baixo), confiança baixa, texto vazio, mudança trivial |
| **Diff** | Alinhamento por prefixo de palavras; `appended_text` = sufixo novo |
| **`is_stable`** | **Sempre `False`** — não há lógica de estabilidade |
| **Threading** | Thread da SlidingWindow (callback síncrono) |
| **Latência** | < 500ms GPU / < 3000ms CPU por janela |
| **Dependência de `SpeechTranscribed`** | Nenhuma |
| **Dependência de silêncio** | Nenhuma (mas filtra silêncio via RMS) |

### 2.6 IncrementalBiblicalParser

| Aspecto | Valor |
|---|---|
| **Arquivo** | `pipeline/incremental_parser.py` |
| **Input** | `SpeechPartial`, `SpeechPartialUpdated` |
| **Output** | `ReferenceCandidate`, `ReferenceAntecipada`, `ReferenceDetected` |
| **Dependências** | `ParserBookTable`, `Normalizer`, `EventBus` |
| **Estado interno** | `_current_book`, `_current_chapter`, `_current_verse`, `_current_verse_end`, `_seen_text`, `_correlation_id`, `_expecting` ("book"/"chapter"/"verse"/"done"), `_detected_published`, `_anticipation_published` |
| **Buffering** | `_seen_text` (acumula texto normalizado) |
| **Thresholds** | detection=0.90, anticipation=0.60, C_BOOK_ONLY=0.40, C_BOOK_CHAPTER=0.75, C_BOOK_CHAPTER_VERSE=0.98 |
| **Condição de descarte** | `_detected_published=True` ignora até reset; texto vazio |
| **Reset** | Novo `correlation_id` em `SpeechPartialUpdated`, ou chamada externa |
| **Threading** | Thread do StreamingSTT (via EventBus síncrono) |
| **Latência** | < 10ms |
| **Dependência de `SpeechTranscribed`** | **Nenhuma** — opera em partials |
| **Dependência de silêncio** | Nenhuma |
| **Problema** | Reset só em novo correlation_id; se VAD nunca fecha, estado persiste indefinidamente para o mesmo fluxo |

### 2.7 BiblicalNLUService (parser determinístico stateless)

| Aspecto | Valor |
|---|---|
| **Arquivo** | `pipeline/nlu.py` |
| **Input** | `SpeechTranscribed` |
| **Output** | `ReferenceDetected`, `ReferenceInvalid`, `IntentUnknown` |
| **Dependências** | `Parser` (stateless), `EventBus` |
| **Estado interno** | Nenhum (stateless) |
| **Threading** | Thread do SpeechWorker (via EventBus) |
| **Latência** | < 50ms |
| **Dependência de `SpeechTranscribed`** | **Total** — só funciona com `SpeechTranscribed` |
| **Dependência de silêncio** | Indireta (precisa do segmento fechar) |
| **Problema** | Duplica o trabalho do `IncrementalBiblicalParser`; pode gerar `ReferenceDetected` duplicado |

### 2.8 SemanticEngine

| Aspecto | Valor |
|---|---|
| **Arquivo** | `semantic/engine.py` |
| **Input** | `SpeechPartial`, `SpeechPartialUpdated` |
| **Output** | `IntentCandidate`, `SemanticInferenceCompleted` (telemetria) |
| **Dependências** | `SemanticProvider` (Ollama), `ContextEngine`, `SemanticCache`, `BibleRetriever` (RAG), `ContextPolicy` |
| **Estado interno** | `_debounce_timer`, `_pending_text`, `_pending_meta`, `_last_inferred_text`, `_last_inference_monotonic`, `_growth_fired` |
| **Debounce** | 400ms (timer); cancelado a cada novo partial |
| **Growth trigger** | `growth_chars >= 22` AND `append_words >= 3` AND `elapsed_ms >= 1000` → dispara imediato |
| **Rate limiting** | `min_interval_ms=1000` |
| **Cache** | `SemanticCache` por `context_hash`; sem expiração |
| **Timeout** | 5000ms (config `semantic.timeout_ms`) |
| **Cancelamento** | Debounce timer cancelável; **inferência em curso NÃO é cancelável** |
| **Threading** | Handler no thread do EventBus; inferência no mesmo thread (síncrono) ou via timer |
| **Dependência de `SpeechTranscribed`** | Nenhuma |
| **Dependência de silêncio** | Indireta (debounce expira em pausa) |
| **Problemas** | Sem cancelamento de inferência stale; Ollama serial causa timeout; cache sem expiração cresce indefinidamente |

### 2.9 ContextEngine

| Aspecto | Valor |
|---|---|
| **Arquivo** | `semantic/context_engine.py` |
| **Input** | `bus.history()` (varre EventStore), `sermon_context_fn()` |
| **Output** | `SemanticContext` |
| **Dependências** | `EventBus.history()`, `SermonMemoryEngine` |
| **Janela** | 45s de fala recente, max 500 chars |
| **Problema** | O(n) sobre EventStore a cada inferência; não escala |

### 2.10 SermonMemoryEngine

| Aspecto | Valor |
|---|---|
| **Arquivo** | `sermon/engine.py` |
| **Input** | `SpeechPartial`, `SpeechPartialUpdated`, `ReferenceDetected` |
| **Output** | `SermonContextUpdated`, `SermonBookChanged`, `SermonChapterChanged`, `SermonTopicChanged` |
| **Dependências** | `EventBus` |
| **Estado interno** | `SermonContext` (current_book, current_chapter, entities, topics, references) |
| **Janelas** | text=45s, reference=300s, topic=600s, entity_half_life=120s |
| **Threading** | Lock interno; handlers no thread do EventBus |
| **Dependência de `SpeechTranscribed`** | Nenhuma (opera em partials) |

### 2.11 ReferenceResolver

| Aspecto | Valor |
|---|---|
| **Arquivo** | `semantic/resolver.py` |
| **Input** | `IntentCandidate` |
| **Output** | `ReferenceDetected` (se validado), `SemanticResolutionCompleted` |
| **Dependências** | `Searcher` (valida via Bible DB), `EventBus` |
| **Regras** | Parser vence (dedup por correlation_id); min_confidence=0.50; kill switch |
| **Dependência de `SpeechTranscribed`** | Nenhuma |

### 2.12 StateOrchestrator (CAP-01)

| Aspecto | Valor |
|---|---|
| **Arquivo** | `pipeline/state_orchestrator.py` |
| **Input** | `ReferenceCandidate`, `ReferenceDetected`, `IntentUnknown`, `SpeechTranscribed`, `IntentCandidate` |
| **Output** | `StateChanged` (especificado mas **não publicado** — esqueleto) |
| **Estados** | WAIT, PREPARE, PRESENT, IGNORE (definidos, não implementados) |
| **Estado interno** | `OrchestratorContext` (current_state, active_book, active_chapter, pending_reference, last_presented_reference) |
| **Threading** | `threading.Lock` |
| **Status** | **Esqueleto** — todos os handlers são `pass`/TODO |
| **Dependência de `SpeechTranscribed`** | Assina mas handler é noop |

### 2.13 VersePresentationService

| Aspecto | Valor |
|---|---|
| **Arquivo** | `presentation/verse_presentation_service.py` |
| **Input** | `ReferenceDetected`, `ReferenceAntecipada` |
| **Output** | `VerseResolving`, `VerseResolved`, `VersePresented`, `VersePresentationFailed` |
| **Dependências** | `Searcher`, `HolyricsClient`, `EventBus` |
| **Estado interno** | Nenhum (stateless) |
| **Threading** | Thread do EventBus (síncrono) |
| **Latência** | < 2500ms (500ms search + 2000ms holyrics) |
| **Dependência de `SpeechTranscribed`** | Nenhuma (consome `ReferenceDetected`/`ReferenceAntecipada`) |
| **Problema** | Sem coordenação com StateOrchestrator; pode apresentar duplicado se parser incremental + NLU ambos emitem `ReferenceDetected` |

### 2.14 ReadingFollowService

| Aspecto | Valor |
|---|---|
| **Arquivo** | `presentation/reading_follow_service.py` |
| **Input** | `ReferenceDetected` (ativa), `SpeechTranscribed` (avança), `VersionChanged` |
| **Output** | `ReadingFollowStarted`, `ReadingFollowAdvanced`, `ReadingFollowEnded` |
| **Dependências** | `Searcher`, `HolyricsClient`, `EventBus`, `rapidfuzz` |
| **Threshold** | fuzzy 0.70 |
| **Threading** | Thread do EventBus |
| **Dependência de `SpeechTranscribed`** | **Total** — avança versículo apenas em `SpeechTranscribed` |
| **Dependência de silêncio** | Indireta |
| **Problema** | Latência alta entre versículos durante leitura contínua |

### 2.15 VersionCommandDetector

| Aspecto | Valor |
|---|---|
| **Arquivo** | `presentation/version_command_detector.py` |
| **Input** | `SpeechTranscribed` |
| **Output** | `VersionChanged` |
| **Dependência de `SpeechTranscribed`** | **Total** |

### 2.16 EventBus

| Aspecto | Valor |
|---|---|
| **Arquivo** | `pipeline/bus.py` |
| **Tipo** | Síncrono, genérico, tipado por classe |
| **Isolamento** | Sprint 23.0 — exceções de handler capturadas e logadas, não propagam |
| **Persistência** | `OperationalEvent` → EventStore; `TelemetryEvent` → não persistido |
| **Thread safety** | Snapshot da lista de handlers durante iteração |

---

## 3. Complete `SpeechTranscribed` Consumer Map

Busca exaustiva no repositório por todos os consumidores de `SpeechTranscribed`. Cada uso é classificado:

- **A** — genuinamente requer texto final
- **B** — pode operar com `SpeechPartial`
- **C** — pode operar com partial + confirmação posterior
- **D** — deve permanecer apenas em `SpeechTranscribed`
- **E** — requer refatoração

| # | Arquivo | Componente | Método | Class. | Razão | Migração proposta |
|---|---|---|---|---|---|---|
| 1 | `pipeline/nlu.py` | `BiblicalNLUService` | `_on_transcribed` | **D→reformula** | Parser determinístico stateless duplica o `IncrementalBiblicalParser`. Na arquitetura streaming-first, `SpeechTranscribed` deixa de disparar parsing (o incremental já tratou). | Reformular: `BiblicalNLUService` deixa de assinar `SpeechTranscribed`. O parser incremental passa a ser o único caminho de parsing. `SpeechTranscribed` torna-se apenas confirmação de texto final (ver §5). |
| 2 | `pipeline/state_orchestrator.py` | `StateOrchestrator` | `_handle_speech_transcribed` | **C** | Hoje é noop (esqueleto). No futuro, deve usar `SpeechTranscribed` para: (a) confirmar texto final e limpar estado PREPARE se nenhuma referência foi detectada; (b) classificar IGNORE vs WAIT. Pode operar com partials para PREPARE e usar `SpeechTranscribed` apenas para finalização. | Implementar: assinar também `SpeechPartial`/`Updated` para transições PREPARE; manter `SpeechTranscribed` para transições WAIT/IGNORE (finalização). |
| 3 | `presentation/reading_follow_service.py` | `ReadingFollowService` | `_on_speech_transcribed` | **B** | Fuzzy-match do versículo lido. Pode operar com partials estáveis + debounce, avançando assim que o texto do versículo atual for suficientemente reconhecido. | Migrar para `SpeechPartial`/`Updated` com janela de estabilidade + debounce. `SpeechTranscribed` usado apenas como fallback/confirmação. |
| 4 | `presentation/version_command_detector.py` | `VersionCommandDetector` | handler | **C** | Detecta "muda pra NVI" etc. Pode operar com partials estáveis (comando é curto e determinístico). Risco: falso positivo em partial incompleto. | Migrar para partials com threshold de estabilidade alta (ex.: texto não mudou por 800ms) OU manter em `SpeechTranscribed` se o comando for sempre seguido de pausa. **Decisão: manter em `SpeechTranscribed` por segurança** (comando de versão é intencional, geralmente seguido de pausa). |
| 5 | `api/websocket/events.py` | WebSocket broadcaster | broadcast | **D** | Frontend usa `SpeechTranscribed` para exibir texto final na transcrição. Partial já é transmitido separadamente. | Manter: `SpeechTranscribed` confirma texto final no frontend. Partials já fluem por handler separado. |
| 6 | `frontend/src/stream/handlers.ts` | Frontend handlers | múltiplos | **D** | Exibe texto final, atualiza estado de transcrição. | Manter — frontend já consome partials e final separadamente. |
| 7 | `frontend/src/stores/domain.ts` | Frontend store | — | **D** | Estado de domínio do frontend. | Manter. |
| 8 | `frontend/src/components/operational/TranscriptPanel.tsx` | UI | — | **D** | Exibe transcrição. | Manter. |
| 9 | `frontend/src/components/console/*` | Console UI | — | **D** | Debug/timeline. | Manter. |
| 10 | `tests/test_*.py` (múltiplos) | Testes | — | **D** | Testes existentes. | Atualizar conforme migração; manter testes de `SpeechTranscribed` para o caminho de finalização. |
| 11 | `datasets/benchmarks/.../event_contracts.md` | Event Contracts | spec | **D** | Documento de contrato. | **Flag**: se `SpeechTranscribed` muda de semântica (de "texto reconhecido" para "confirmação de finalização"), o Event Contract deve ser atualizado explicitamente. |
| 12 | `datasets/benchmarks/.../runtime_execution_spec.md` | Runtime Spec | spec | **D** | Documento de execução. | **Flag**: Runtime Spec descreve o fluxo segmentado como caminho principal; deve ser atualizado para refletir streaming-first. |
| 13 | `datasets/benchmarks/.../rfc_capabilities.md` | RFCs CAP-01..07 | spec | **D** | RFCs referenciam `SpeechTranscribed` em input_events. | **Flag**: CAP-01 (StateOrchestrator) input_events devem incluir `SpeechPartial`/`Updated`. Outros RFCs podem precisar revisão. |

### Resumo de migração

| Classificação | Count | Ação |
|---|---|---|
| A (requer final) | 0 | — |
| B (pode usar partial) | 1 | ReadingFollow → migrar |
| C (partial + confirmação) | 2 | StateOrchestrator → implementar híbrido; VersionCommand → manter por segurança |
| D (mantém em final) | 10 | Manter |
| E (refatorar) | 1 | BiblicalNLUService → reformular (deixa de disparar parsing) |

---

## 4. Proposed Text State Model

### 4.1 Estados conceituais

```
PARTIAL → STABLE → FINAL → CONFIRMED
  ↑          ↑        ↑         ↑
  texto      texto    VAD       downstream
  sendo      parou    fechou    aceitou
  formado    de       segmento  referência
             mudar
```

| Estado | Definição | Quem seta | Eventos associados |
|---|---|---|---|
| **PARTIAL** | Texto ainda sendo formado pelo Whisper; pode mudar a qualquer momento | `StreamingSTTService` (default) | `SpeechPartial`, `SpeechPartialUpdated` (com `is_stable=False`) |
| **STABLE** | Texto permaneceu inalterado por ≥ `stability_window_ms` (ex.: 600ms) sem novas atualizações | `StreamingSTTService` ou `TextStabilityTracker` | `SpeechPartialUpdated` com `is_stable=True` (novo) |
| **FINAL** | VAD fechou o segmento; `SpeechWorker` transcreveu o segmento completo; texto não mudará mais | `SpeechWorker` | `SpeechTranscribed` (semântica reformulada: confirmação de finalização) |
| **CONFIRMED** | Downstream (StateOrchestrator / VersePresentationService) aceitou a referência como válida e apresentada | `StateOrchestrator` | `StateChanged` (to_state=PRESENT) |

### 4.2 Transições

| De → Para | Condição | Quem detecta |
|---|---|---|
| PARTIAL → STABLE | Nenhuma `SpeechPartialUpdated` por `stability_window_ms` | `TextStabilityTracker` |
| STABLE → PARTIAL | Nova `SpeechPartialUpdated` chega (texto mudou) | `TextStabilityTracker` |
| PARTIAL/STABLE → FINAL | VAD fecha segmento + `SpeechWorker` transcreve | `SpeechWorker` |
| FINAL → CONFIRMED | `StateOrchestrator` transita para PRESENT | `StateOrchestrator` |
| STABLE → CONFIRMED (antecipação) | `ReferenceAntecipada` validada + apresentada | `VersePresentationService` + `StateOrchestrator` |

### 4.3 Representação de revisões

- `SpeechPartialUpdated.text` contém o texto **completo** atualizado (não apenas diff).
- `appended_text` contém apenas o trecho novo.
- Revisões regressivas (Whisper reescreveu o início): `_compute_diff` retorna `new` inteiro quando não há prefixo comum. O parser incremental deve detectar isso e **resetar estado** (não acumular sobre texto obsoleto).

### 4.4 Rejeição de partials stale

- Cada `SpeechPartial`/`Updated` carrega `correlation_id` e `meta.timestamp`.
- Downstream mantém `_last_processed_timestamp` por `correlation_id`. Se um evento chega com timestamp **anterior** ao último processado para o mesmo `correlation_id`, é **rejeitado** como stale.
- `SemanticEngine`: inferência em curso cujo `correlation_id` mudou deve ter resultado **descartado** ao completar (ver §9).

### 4.5 Evitar trabalho duplicado downstream

- **Parser incremental**: `_detected_published=True` bloqueia reprocessamento até reset.
- **SemanticEngine**: `_last_inferred_text` + cache por `context_hash` evita reinferência do mesmo texto.
- **StateOrchestrator**: `last_presented_reference` (book_id, chapter, verse) evita reapresentação da mesma referência.
- **VersePresentationService**: dedup por (book_id, chapter, verse) dentro da mesma janela de tempo.

### 4.6 Confirmação vs processamento parcial

- Processamento parcial (parser, semantic, sermon) é **especulativo**: produz candidatos/antecipadas que podem ser confirmados ou corrigidos.
- `SpeechTranscribed` (FINAL) é o ponto de **confirmação**: o texto não mudará mais.
- `StateOrchestrator` usa FINAL para: (a) confirmar antecipadas já apresentadas (marcar `is_confirmed=True`); (b) corrigir antecipadas erradas (apresentar referência correta); (c) limpar PREPARE se nada foi detectado (→ WAIT/IGNORE).

---

## 5. Streaming-First Architecture

### 5.1 Princípios

1. **`SpeechPartial`/`SpeechPartialUpdated` é o fluxo operacional primário.** Parser, semântica, contexto, estado e Reading Follow operam continuamente sobre partials.
2. **`SpeechTranscribed` é o evento de finalização/confirmação.** Não dispara parsing (o incremental já tratou). Confirma texto final, permite correção de antecipadas, e limpa estado.
3. **VAD permanece relevante.** Fecha segmentos, produz `SpeechTranscribed`, e fornece o sinal de "fim de fala" para finalização.
4. **EventBus não é substituído.** A arquitetura existente (síncrona, tipada, isolada) suporta o modelo streaming-first sem mudanças estruturais — apenas novos subscribers e novos eventos de estabilidade.
5. **Custo controlado.** Nem todo partial vai para LLM. Debounce, growth trigger, rate limiting, cache e estabilidade limitam chamadas caras.
6. **LLM não controla Holyrics.** `IntentCandidate` → `ReferenceResolver` → `ReferenceDetected` → `StateOrchestrator` → `VersePresentationService` → Holyrics. O LLM nunca publica `ReferenceDetected` diretamente.

### 5.2 Novo componente: TextStabilityTracker

Componente **novo** que observa `SpeechPartial`/`SpeechPartialUpdated` e publica `SpeechPartialUpdated` com `is_stable=True` quando o texto permanece inalterado por `stability_window_ms`.

| Aspecto | Valor |
|---|---|
| **Input** | `SpeechPartial`, `SpeechPartialUpdated` |
| **Output** | `SpeechStableText` (novo evento) ou republica `SpeechPartialUpdated` com `is_stable=True` |
| **Estado interno** | `_last_text`, `_last_change_timestamp` por `correlation_id` |
| **Config** | `stability_window_ms` (default 600ms) |
| **Threading** | Timer thread + handler no EventBus |

**Decisão de design**: preferir um **novo evento `SpeechStableText`** em vez de modificar `SpeechPartialUpdated.is_stable`, para evitar quebrar o Event Contract existente. `SpeechStableText` carrega o texto estável + `correlation_id` + `completeness` (nível do parser).

### 5.3 Fluxo streaming-first proposto

```
AudioCapture (16kHz mono)
    ├─→ SpeechPipelineService (VAD) → SpeechQueue → SpeechWorker
    │                                              → SpeechTranscribed (FINAL/CONFIRMAÇÃO)
    │
    └─→ RingBuffer → SlidingWindow (400ms) → StreamingSTTService
                                              ↓
                                    SpeechPartial / SpeechPartialUpdated
                                              ↓
                                    ┌─────────┼─────────────┬───────────────┐
                                    ↓         ↓             ↓               ↓
                          IncrementalBiblical  TextStability  SermonMemory  SemanticEngine
                            Parser            Tracker        Engine         (debounce/growth)
                              ↓                ↓               ↓               ↓
                          ReferenceCandidate  SpeechStableText  SermonContextUpdated  IntentCandidate
                          ReferenceAntecipada    ↓               ↓               ↓
                          ReferenceDetected   (sinal de         (contexto)   ReferenceResolver
                                  ↓          estabilidade)          ↓               ↓
                                  ↓                ↓               ↓         ReferenceDetected
                                  ↓                ↓               ↓               ↓
                                  └────────────────┴───────────────┴───────────────┘
                                                      ↓
                                            StateOrchestrator (CAP-01)
                                                      ↓
                                                StateChanged
                                                      ↓
                                            VersePresentationService
                                                      ↓
                                            VerseResolving → VerseResolved → VersePresented
                                                      ↓
                                                  Holyrics

  [FINAL] SpeechTranscribed → StateOrchestrator (confirma/corrige/limpa)
                            → ReadingFollowService (fallback de confirmação)
                            → VersionCommandDetector (mantém)
                            → Frontend (texto final)

  [Reading Follow] SpeechStableText → ReadingFollowService (avança versículo)
```

### 5.4 Como o EventBus suporta isso sem substituição

- **Síncrono**: handlers executam na thread do publisher. StreamingSTT publica na thread SlidingWindow; parser/sermon executam síncrono (< 10ms cada). SemanticEngine agenda debounce em timer separado.
- **Tipado**: novos eventos (`SpeechStableText`) são novas classes dataclass; inscrição existente não é afetada.
- **Isolamento (Sprint 23.0)**: exceção em um handler não afeta outros.
- **Correlation**: `EventMetadata.correlation_id` já vincula partials ao mesmo fluxo.
- **Backpressure**: EventBus não tem fila própria (síncrono); backpressure é nos buffers upstream (RingBuffer, SpeechQueue) e no rate limiting do SemanticEngine.

### 5.5 Questões arquiteturais endereçadas

| Questão | Solução |
|---|---|
| **Fala contínua** | SlidingWindow extrai independentemente do VAD; StreamingSTT transcreve continuamente |
| **Revisões de partial** | `_compute_diff` por prefixo; parser reset em regressão; stale rejection por timestamp |
| **Supressão de duplicados** | Parser `_detected_published`; StateOrchestrator `last_presented_reference`; VersePresentationService dedup por (book, chapter, verse) |
| **Debounce/stability** | SemanticEngine debounce 400ms + growth trigger; TextStabilityTracker 600ms |
| **Custo limitado** | Rate limiting `min_interval_ms=1000`; cache por `context_hash`; partials triviais descartados (`min_text_change=3`) |
| **Ordering** | EventBus síncrono preserva ordem de publicação dentro da mesma thread |
| **Correlation/session** | `EventMetadata.correlation_id` + `session_id` |
| **Backpressure** | RingBuffer circular; SpeechQueue bounded; SemanticEngine rate-limited |
| **Thread safety** | Locks por componente; EventBus snapshot de handlers |
| **Cancelamento** | Debounce timer cancelável; inferência stale rejeitada ao completar (novo) |
| **Timeout** | Semantic 5000ms; Holyrics 2000ms; Whisper sem timeout explícito |
| **Isolamento de erro** | Sprint 23.0 — handler exception não propaga |
| **Finalização VAD** | `SpeechTranscribed` confirma/corrige/limpa estado |

---

## 6. Component-by-Component Changes

### 6.1 VAD / SpeechPipelineService

| Aspecto | Atual | Alvo |
|---|---|---|
| Papel | Produz segmentos para SpeechWorker | **Idem** — mantém papel de fechamento de segmento |
| Mudança | — | Nenhuma mudança estrutural. VAD continua fechando segmentos e produzindo `SpeechTranscribed` via SpeechWorker. |
| Risco | — | Nenhum (VAD não é alterado) |
| Testes | Existentes | Manter |

### 6.2 STT / Whisper / STTExecutor

| Aspecto | Atual | Alvo |
|---|---|---|
| Compartilhamento | STTExecutor serializa entre SpeechWorker e StreamingSTT | **Idem** — manter serialização |
| Mudança | — | Nenhuma. O bug stereo→mono já foi corrigido. Garantir que downstream sempre receba 16kHz mono. |
| Risco | Concorrência GPU entre Whisper e Ollama | Manter monitoramento; não aumentar carga de Whisper |
| Testes | Existentes | Manter |

### 6.3 SpeechSegment

| Aspecto | Atual | Alvo |
|---|---|---|
| Papel | Áudio do segmento VAD | **Idem** |
| Mudança | — | Nenhuma |

### 6.4 SpeechPartial / SpeechPartialUpdated

| Aspecto | Atual | Alvo |
|---|---|---|
| `is_stable` | Sempre `False` | Permanece `False` nestes eventos; estabilidade é sinalizada por novo evento `SpeechStableText` |
| Mudança | — | **Nenhuma mudança no dataclass** (preserva Event Contract). Estabilidade é evento separado. |
| Risco | — | Nenhum |

### 6.5 SpeechTranscribed

| Aspecto | Atual | Alvo |
|---|---|---|
| Semântica | "Texto reconhecido do segmento" | **"Confirmação de finalização"** — texto final após VAD fechar |
| Consumidores | BiblicalNLUService, StateOrchestrator, ReadingFollow, VersionCommand, Frontend | StateOrchestrator (confirma/corrige/limpa), ReadingFollow (fallback), VersionCommand (mantém), Frontend (mantém). **BiblicalNLUService deixa de consumir.** |
| Mudança | — | **Flag: Event Contract de `SpeechTranscribed` deve ser atualizado** para refletir nova semântica ("confirmação de finalização" em vez de "texto reconhecido"). |
| Risco | BiblicalNLUService desativado pode perder referências que só aparecem no texto final | Mitigação: parser incremental já detecta durante partials; se texto final difere, StateOrchestrator corrige |

### 6.6 IncrementalBiblicalParser

| Aspecto | Atual | Alvo |
|---|---|---|
| Input | SpeechPartial, SpeechPartialUpdated | **Idem** + `SpeechStableText` (para confirmar referência em texto estável) |
| Reset | Novo correlation_id ou chamada externa | **Idem** + reset em `SpeechTranscribed` (finalização confirma e limpa para próximo fluxo) |
| Revisão regressiva | Não trata explicitamente | **Detectar** quando `_compute_diff` retorna texto inteiro (sem prefixo comum) → resetar estado incremental |
| Múltiplas referências | Não suporta (uma por fluxo) | **Futuro**: suportar múltiplas referências no mesmo fluxo (ex.: "João 3:16 e Romanos 8:28"). **Fora de escopo desta migração** — flag para sprint futuro. |
| Confiança | Fixa por completude | **Idem** |
| Antecipação | ReferenceAntecipada em confidence ≥ 0.60 | **Idem** — mantém |
| Risco | Reset prematuro em revisão regressiva | Mitigação: só resetar se o novo texto não contém o livro atualmente detectado |

### 6.7 BiblicalNLUService

| Aspecto | Atual | Alvo |
|---|---|---|
| Status | Ativo, consome SpeechTranscribed | **Desativado** (ou reformulado como fallback de confirmação) |
| Migração | — | Remover inscrição em `SpeechTranscribed`. O parser incremental é o único caminho de parsing. `BiblicalNLUService` pode ser mantido como código morto ou removido. **Decisão: desativar inscrição, manter classe para teste/replay.** |
| Risco | Perda de parsing em texto final que difere de partials | Mitigada pelo StateOrchestrator que compara `SpeechTranscribed.text` com referências detectadas e corrige se necessário |

### 6.8 ContextEngine

| Aspecto | Atual | Alvo |
|---|---|---|
| Fonte | `bus.history()` (varre EventStore O(n)) | **Cache incremental**: manter buffer circular próprio de últimos N partials + último ReferenceDetected, atualizado por inscrição em eventos |
| Janela | 45s | **Idem** |
| Mudança | — | Inscrever em `SpeechPartial`/`Updated`/`ReferenceDetected` para manter cache interno; parar de varrer `bus.history()` |
| Risco | Inconsistência se eventos perdidos | Mitigação: cache é best-effort; ContextEngine já tolera falha de leitura |

### 6.9 SermonMemoryEngine

| Aspecto | Atual | Alvo |
|---|---|---|
| Input | SpeechPartial, SpeechPartialUpdated, ReferenceDetected | **Idem** + `SpeechTranscribed` (para confirmar referências no contexto do sermão) |
| Mudança | — | Adicionar inscrição em `SpeechTranscribed` para marcar referências como "confirmadas" no SermonContext |
| Risco | — | Baixo |

### 6.10 SemanticEngine

| Aspecto | Atual | Alvo |
|---|---|---|
| Input | SpeechPartial, SpeechPartialUpdated | **Idem** + respeitar `SpeechStableText` (priorizar inferência em texto estável) |
| Cancelamento stale | Não tem | **Adicionar**: ao iniciar inferência, registrar `correlation_id` + `timestamp`. Ao completar, se `correlation_id` mudou ou texto atual difere, **descartar resultado** |
| Concorrência Ollama | Sem controle | **Adicionar**: semaphore/lock de concorrência máxima 1 (Ollama serial); se ocupado, **coalescer** (descartar partial atual, agendar novo debounce) |
| Cache | Sem expiração | **Adicionar** LRU com max_entries (ex.: 200) |
| Debounce | 400ms | **Idem** |
| Growth trigger | 22 chars / 3 words / 1000ms | **Idem** |
| Rate limiting | min_interval_ms=1000 | **Idem** |
| Timeout | 5000ms | **Idem** (não aumentar arbitrariamente) |
| Risco | Inferência stale chega depois de nova | Mitigado por stale rejection |

### 6.11 LocalLLMProvider / OllamaBackend

| Aspecto | Atual | Alvo |
|---|---|---|
| Concorrência | Sem controle | **Semaphore máximo 1** no OllamaBackend (Ollama processa serialmente) |
| Timeout | 5000ms | **Idem** |
| Mudança | — | Adicionar métrica de queue depth no OllamaBackend |

### 6.12 ReferenceResolver

| Aspecto | Atual | Alvo |
|---|---|---|
| Input | IntentCandidate | **Idem** |
| Dedup | Por correlation_id (parser vence) | **Idem** + verificar `StateOrchestrator.last_presented_reference` para evitar republicar referência já apresentada |
| Mudança | — | Adicionar consulta ao StateOrchestrator antes de publicar `ReferenceDetected` |
| Risco | — | Baixo |

### 6.13 StateOrchestrator (CAP-01)

| Aspecto | Atual | Alvo |
|---|---|---|
| Status | Esqueleto (TODO) | **Implementado** — transições WAIT/PREPARE/PRESENT/IGNORE |
| Input | ReferenceCandidate, ReferenceDetected, IntentUnknown, SpeechTranscribed, IntentCandidate | **+ SpeechPartial, SpeechPartialUpdated, SpeechStableText, ReferenceAntecipada** |
| Output | StateChanged (não publicado) | **StateChanged publicado** em toda transição |
| Transições | — | Ver §13 |
| Risco | Lógica incorreta causa apresentação duplicada ou perdida | Mitigado por testes + benchmark |

### 6.14 VersePresentationService

| Aspecto | Atual | Alvo |
|---|---|---|
| Input | ReferenceDetected, ReferenceAntecipada | **Idem** + só apresenta se `StateOrchestrator.current_state == PRESENT` |
| Coordenação | Nenhuma (age direto) | **Consultar StateOrchestrator** antes de apresentar |
| Dedup | Nenhum | **Dedup por (book_id, chapter, verse)** dentro de janela de tempo |
| Risco | — | StateOrchestrator pode rejeitar apresentação |

### 6.15 Holyrics integration

| Aspecto | Atual | Alvo |
|---|---|---|
| API | `show_verse_references()` | **Idem** |
| Token | Configurado | **Idem** |
| Mudança | — | Nenhuma. Holyrics permanece downstream de StateOrchestrator + VersePresentationService |

### 6.16 EventBus e isolamento

| Aspecto | Atual | Alvo |
|---|---|---|
| Isolamento | Sprint 23.0 (exceção não propaga) | **Idem** |
| Mudança | — | Nenhuma estrutural. Apenas novos eventos e novos subscribers. |

### 6.17 Reading Follow

| Aspecto | Atual | Alvo |
|---|---|---|
| Input | ReferenceDetected (ativa), SpeechTranscribed (avança) | **+ SpeechStableText (avança primário)**, SpeechTranscribed (fallback/confirmação) |
| Migração | — | Assinar `SpeechStableText`; fuzzy-match em texto estável; debounce próprio; `SpeechTranscribed` como confirmação |
| Risco | Avanço prematuro em texto estável incorreto | Mitigado por threshold fuzzy 0.70 + estabilidade 600ms |

### 6.18 Replay / Benchmark

| Aspecto | Atual | Alvo |
|---|---|---|
| Status | ReplayAdapter é contrato abstrato (não implementado) | **Manter** — não implementar replay nesta migração |
| Benchmark | Dataset `morning-prayer-27-07-2026` com specs | **Atualizar** specs após migração (event_contracts, runtime_execution_spec, rfc_capabilities) |
| Mudança | — | Flag: atualizar documentos de benchmark após implementação |

### 6.19 Telemetry / Metrics

| Aspecto | Atual | Alvo |
|---|---|---|
| Hooks | `telemetry/hooks.py` com stt_window, stt_partial_published, semantic_input, etc. | **+ novos hooks**: `text_stability_detected`, `state_changed`, `stale_inference_rejected`, `ollama_queue_depth` |
| Métricas | StreamingSTT, SemanticEngine, SpeechWorker | **+**: partial-to-stable latency, partial-to-candidate latency, partial-to-presentation latency, stale rejections, LLM calls per utterance, cache hit rate |

### 6.20 Resumo de novos eventos

| Evento | Publisher | Consumidores |
|---|---|---|
| `SpeechStableText` | `TextStabilityTracker` | `IncrementalBiblicalParser`, `SemanticEngine`, `ReadingFollowService`, `StateOrchestrator` |

**Flag**: `SpeechStableText` deve ser adicionado ao Event Contract (`event_contracts.md`) e ao Runtime Spec.

---

## 7. Event and Lifecycle Semantics

### 7.1 Eventos de fala (reformulados)

| Evento | Quando | Publisher | `is_stable` | Semântica |
|---|---|---|---|---|
| `SpeechPartial` | Primeira transcrição do fluxo | StreamingSTTService | `False` | Texto parcial inicial |
| `SpeechPartialUpdated` | Texto evoluiu (diff ≥ 3 chars) | StreamingSTTService | `False` | Texto parcial atualizado |
| `SpeechStableText` (novo) | Texto inalterado por `stability_window_ms` | TextStabilityTracker | — | Sinal de estabilidade para downstream |
| `SpeechTranscribed` | VAD fechou + SpeechWorker transcreveu | SpeechWorker | — | **Confirmação de finalização** (não dispara parsing) |

### 7.2 Correlation ID

- `SpeechPartial` inicia um novo `correlation_id` (via `EventMetadata.for_initial`).
- Todos `SpeechPartialUpdated` e `SpeechStableText` do mesmo fluxo compartilham o `correlation_id`.
- `SpeechTranscribed` do segmento correspondente **deve** carregar o mesmo `correlation_id` (requer mudança no SpeechWorker ou no SpeechPipelineService para propagar o correlation_id do fluxo streaming ativo).

**Flag**: Propagação de `correlation_id` entre fluxo streaming e segmento VAD requer análise. Hoje SpeechWorker gera novo `correlation_id` via `for_initial`. **Solução proposta**: SpeechPipelineService rastreia o `correlation_id` ativo do StreamingSTTService (via evento ou consulta) e o passa ao SpeechSegment; SpeechWorker o reusa em `SpeechTranscribed`.

### 7.3 Finalização

Quando `SpeechTranscribed` chega:
1. **StateOrchestrator**: compara texto final com referências detectadas durante o fluxo.
   - Se referência já apresentada (antecipada) == referência no texto final → marca `is_confirmed=True` (sem reapresentar).
   - Se referência no texto final difere da antecipada → apresenta a correta.
   - Se nenhuma referência no texto final → limpa PREPARE → WAIT/IGNORE.
2. **IncrementalBiblicalParser**: `reset()` para próximo fluxo.
3. **SermonMemoryEngine**: marca referências como confirmadas.
4. **ReadingFollowService**: confirma versículo atual (fallback se stable text não avançou).
5. **Frontend**: exibe texto final.

### 7.4 Ciclo de vida de um fluxo streaming

```
[SlidingWindow extrai janela]
  → StreamingSTT transcreve
  → SpeechPartial (corr_id = X)
  → [mais janelas]
  → SpeechPartialUpdated (corr_id = X, appended="capítulo três")
  → IncrementalBiblicalParser detecta book+chapter → ReferenceCandidate
  → StateOrchestrator: WAIT → PREPARE
  → [600ms sem mudança]
  → TextStabilityTracker → SpeechStableText (corr_id = X)
  → SemanticEngine dispara (texto estável)
  → [mais janelas]
  → SpeechPartialUpdated (appended="versículo dezesseis")
  → IncrementalBiblicalParser detecta verse → ReferenceDetected (conf 0.98)
  → StateOrchestrator: PREPARE → PRESENT
  → VersePresentationService → Holyrics
  → [VAD fecha segmento]
  → SpeechWorker → SpeechTranscribed (corr_id = X, texto final)
  → StateOrchestrator confirma/corrige/limpa
  → IncrementalBiblicalParser reset()
  → [próximo fluxo: novo corr_id = Y]
```

---

## 8. Backpressure and Concurrency Strategy

### 8.1 Buffers e filas (mantidos)

| Buffer | Tamanho | Política | Mudança |
|---|---|---|---|
| RingBuffer | 20s circular | Sobrescreve antigo | Nenhuma |
| `_chunk_queue` (VAD) | 200 chunks | Descarta mais antigo | Nenhuma |
| SpeechQueue | 10 segmentos | Descarta segmento | Nenhuma |
| SemanticCache | Ilimitado | — | **LRU max 200 entries** |

### 8.2 Concorrência de GPU

| Recurso | Consumidores | Estratégia |
|---|---|---|
| Whisper (GPU) | StreamingSTT + SpeechWorker | `STTExecutor` serializa (lock) — **mantido** |
| Ollama (GPU) | SemanticEngine | **Semaphore max 1** no OllamaBackend; coalescing de partials enquanto ocupado |

### 8.3 Coalescing de partials

Quando Ollama está ocupado e novo `SpeechPartialUpdated` chega:
1. SemanticEngine **não enfileira** nova inferência.
2. Atualiza `_pending_text` com o texto mais recente (descarta o anterior pendente).
3. Quando Ollama libera, dispara inferência com o texto **mais recente** acumulado.
4. Resultado: no máximo 1 inferência em curso + 1 pendente coalescida.

### 8.4 Stale inference rejection

```python
# SemanticEngine._fire_inference
with self._lock:
    text = self._pending_text
    meta = self._pending_meta
    inference_corr_id = meta.correlation_id if meta else ""
    inference_text = text

# ... chama Ollama (pode demorar 5s) ...

# Ao completar:
with self._lock:
    if (self._current_correlation_id != inference_corr_id
            or self._pending_text != inference_text):
        # Stale — descartar resultado
        logger.debug("SemanticEngine: stale inference discarded")
        return
```

### 8.5 Backpressure do EventBus

- EventBus é síncrono: não tem fila própria. Se um handler demora (ex.: SemanticEngine síncrono), bloqueia a thread do publisher.
- **Mitigação atual**: SemanticEngine usa `threading.Timer` para debounce (não bloqueia).
- **Mantido**: handlers rápidos (parser < 10ms, sermon < 5ms) executam síncrono sem problema.

---

## 9. SemanticEngine Impact

### 9.1 Evitar uma requisição LLM por partial

| Mecanismo | Status | Mantido? |
|---|---|---|
| Debounce 400ms | Atual | **Sim** |
| Growth trigger (22 chars / 3 words / 1000ms) | Atual | **Sim** |
| Rate limiting `min_interval_ms=1000` | Atual | **Sim** |
| Cache por `context_hash` | Atual | **Sim** + LRU max 200 |
| `min_text_change=3` (StreamingSTT) | Atual | **Sim** — partials triviais nem chegam ao SemanticEngine |
| Coalescing quando Ollama ocupado | **Novo** | — |
| Stale rejection | **Novo** | — |
| Priorizar `SpeechStableText` | **Novo** | Texto estável tem prioridade sobre partial em movimento |

### 9.2 Interação com Ollama

- Ollama roda **um modelo por vez** na GPU (RTX 4060 Ti 8GB).
- Whisper também usa a GPU.
- **Semaphore max 1** no OllamaBackend garante que apenas uma inferência é submetida por vez.
- Se Whisper está transcrevendo e Ollama é chamado, ambos competem por GPU — **timeout de 5s** é o limite.
- **Não aumentar timeout arbitrariamente** — em vez disso, coalescer e rejeitar stale.

### 9.3 LLM não controla Holyrics

- **Mantido**: `IntentCandidate` → `ReferenceResolver` → `ReferenceDetected` → `StateOrchestrator` → `VersePresentationService` → Holyrics.
- O LLM **nunca** publica `ReferenceDetected`. Apenas o `ReferenceResolver` (após validação via Searcher) e o `IncrementalBiblicalParser` (determinístico) publicam.

### 9.4 Inferência em partial/stable com confirmação posterior

- SemanticEngine pode inferir em `SpeechPartial` (texto em movimento) ou `SpeechStableText` (texto estável).
- Resultado (`IntentCandidate`) é **hipótese** — `ReferenceResolver` valida via Searcher.
- Se `SpeechTranscribed` chega depois e o texto final difere, `StateOrchestrator` pode:
  - Confirmar a referência (se igual à detectada via semantic).
  - Corrigir (se diferente) — apresenta a referência correta do texto final.
  - Descartar (se texto final não tem referência).

---

## 10. Parser Impact

### 10.1 Parser incremental contínuo

O `IncrementalBiblicalParser` já opera em partials. Mudanças propostas:

| Aspecto | Mudança |
|---|---|
| Reset em `SpeechTranscribed` | **Adicionar** — finalização confirma e limpa estado |
| Revisão regressiva | **Detectar** (diff sem prefixo comum) → reset se livro não está no novo texto |
| Confirmação em `SpeechStableText` | **Adicionar** — quando texto estável, publicar `ReferenceDetected` se confidence ≥ threshold (em vez de apenas `ReferenceCandidate`) |
| Múltiplas referências | **Fora de escopo** — flag para sprint futuro |

### 10.2 Referências explícitas

- "Gênesis 3:17" → detectado incrementalmente: book → chapter → verse.
- Confidence: 0.40 → 0.75 → 0.98.
- `ReferenceDetected` em confidence ≥ 0.90.

### 10.3 Referências incompletas

- "João capítulo" (sem versículo) → `ReferenceCandidate` (completeness="chapter", conf=0.75).
- Se texto estabiliza sem versículo → `ReferenceAntecipada` (apresenta capítulo, versículo default 1 ou último conhecido).
- Se `SpeechTranscribed` confirma sem versículo → `StateOrchestrator` decide (pode manter antecipada ou limpar).

### 10.4 Correções do Whisper

- Whisper pode corrigir "Gênesis três dezessete" → "Gênesis 3:17" em janela posterior.
- Diff detecta mudança; parser reprocessa o trecho novo.
- Se revisão regressiva (reescreveu início), parser reset e reprocessa texto completo.

### 10.5 Candidatos vs detectados vs confirmados

| Estado | Evento | Quem publica | Ação |
|---|---|---|---|
| Candidato | `ReferenceCandidate` | Parser | Telemetria/visualização |
| Antecipada | `ReferenceAntecipada` | Parser (conf ≥ 0.60) | VersePresentationService apresenta |
| Detectada | `ReferenceDetected` | Parser (conf ≥ 0.90) ou Resolver | StateOrchestrator → PRESENT |
| Confirmada | `StateChanged(PRESENT)` | StateOrchestrator | Apresentação confirmada |

### 10.6 Evitar eventos duplicados

- Parser: `_detected_published=True` bloqueia até reset.
- StateOrchestrator: `last_presented_reference` bloqueia reapresentação.
- VersePresentationService: dedup por (book, chapter, verse) + janela temporal.

---

## 11. VAD/STT Impact

### 11.1 VAD

- **Mantido** — não se torna irrelevante.
- Papel: fecha segmentos → `SpeechTranscribed` (finalização/confirmação).
- `max_silence_ms=800` continua controlando quando o "fim da fala" é declarado.

### 11.2 STT partials durante fala

- SlidingWindow extrai 6s a cada 400ms, independente do VAD.
- StreamingSTT transcreve e publica `SpeechPartial`/`Updated`.
- `STTExecutor` serializa com SpeechWorker (segmentos finais).

### 11.3 Fechamento de segmento

- VAD detecta silêncio ≥ `max_silence_ms` → fecha segmento.
- SpeechSegment → SpeechQueue → SpeechWorker → `SpeechTranscribed`.
- `SpeechTranscribed` confirma/corrige/limpa estado do fluxo streaming.

### 11.4 Normalização de áudio

- **Mantido**: 16kHz mono obrigatório para VAD e Whisper.
- Bug stereo→mono corrigido (commit `d2c0263`).
- AudioCaptureService faz downmix + resample quando nativo ≠ configurado.

### 11.5 Latência e GPU

- Whisper GPU: ~500ms por janela 6s.
- SlidingWindow 400ms: se Whisper demora > 400ms, próxima extração espera (síncrono).
- **Não aumentar** carga de Whisper — manter janela 6s / intervalo 400ms.

### 11.6 Queue/backpressure

- RingBuffer circular 20s: sempre aceita escrita.
- SpeechQueue bounded 10: descarta em overflow.
- STTExecutor lock: serializa acesso, não enfileira.

---

## 12. EventBus Impact

### 12.1 Mudanças estruturais

- **Nenhuma**. EventBus síncrono, tipado, isolado (Sprint 23.0) suporta o modelo streaming-first.

### 12.2 Novos eventos

- `SpeechStableText` — nova classe dataclass, `OperationalEvent`.

### 12.3 Novos subscribers

- `TextStabilityTracker` assina `SpeechPartial`/`Updated`.
- `StateOrchestrator` passa a assinar `SpeechPartial`/`Updated`/`SpeechStableText`/`ReferenceAntecipada`.
- `ReadingFollowService` passa a assinar `SpeechStableText`.
- `IncrementalBiblicalParser` passa a assinar `SpeechStableText` e `SpeechTranscribed` (reset).
- `SermonMemoryEngine` passa a assinar `SpeechTranscribed` (confirmação).

### 12.4 Isolamento

- Sprint 23.0 mantido: exceção em handler não propaga.
- **Risco**: novo subscriber `TextStabilityTracker` com timer pode ter race condition → mitigar com lock.

---

## 13. StateOrchestrator Impact

### 13.1 Transições a implementar

```
                    ReferenceCandidate (book)
              WAIT ─────────────────────────────→ PREPARE
                ↑                                     │
                │ IntentUnknown (sem pista bíblica)    │ ReferenceDetected
                │ SpeechTranscribed (sem ref)          ↓
                └─────────────────────────────────→ PRESENT
                                                     │
                                                     │ IntentUnknown
                                                     │ SpeechTranscribed (sem ref)
                                                     ↓
                                                    WAIT
              WAIT ──────segmento sem pista──────→ IGNORE
              IGNORE ────nova referência────────→ PREPARE
```

### 13.2 Handlers a implementar

| Handler | Evento | Transição |
|---|---|---|
| `_handle_reference_candidate` | `ReferenceCandidate` | WAIT/IGNORE → PREPARE (book_detected); PREPARE → PREPARE (chapter_detected) |
| `_handle_reference_detected` | `ReferenceDetected` | PREPARE/WAIT/IGNORE → PRESENT (first); PRESENT → PRESENT (repeat, mesma ref = noop); PRESENT → PRESENT (nova ref) |
| `_handle_reference_antecipada` (novo) | `ReferenceAntecipada` | PREPARE → PRESENT (antecipada); marca `is_anticipation=True` |
| `_handle_intent_unknown` | `IntentUnknown` | PRESENT → WAIT; PREPARE → WAIT (se sem pista) |
| `_handle_speech_transcribed` | `SpeechTranscribed` | Confirma/corrige antecipadas; PREPARE → WAIT/IGNORE se sem ref; incrementa segment_count |
| `_handle_speech_partial` (novo) | `SpeechPartial` | Atualiza `_has_biblical_content` (heurística) |
| `_handle_intent_candidate` | `IntentCandidate` | Noop (resolver converte em ReferenceDetected) |

### 13.3 Estado interno

| Campo | Uso |
|---|---|
| `current_state` | WAIT/PREPARE/PRESENT/IGNORE |
| `active_book` | Livro em PREPARE |
| `active_chapter` | Capítulo em PREPARE |
| `pending_reference` | "João 3:?" em PREPARE |
| `last_presented_reference` | (book_id, chapter, verse) — dedup |
| `segment_count_since_last_state_change` | Contador de segmentos |
| `has_biblical_content` | Heurística (livro mencionado?) |
| `_state_entered_at` | Timestamp para timeout de PREPARE |

### 13.4 Quando uma referência é elegível para apresentação

1. `ReferenceDetected` com confidence ≥ 0.90 (parser) **ou** `ReferenceDetected` do Resolver (semantic validado).
2. `StateOrchestrator.current_state` transita para PRESENT.
3. `StateChanged` é publicado.
4. `VersePresentationService` consome `ReferenceDetected` **e** verifica `StateOrchestrator.current_state == PRESENT` antes de apresentar.

### 13.5 Correção de antecipada

- Se `ReferenceAntecipada` apresentou "Salmos 23" e `ReferenceDetected` final é "Salmos 23:4":
  - StateOrchestrator detecta que (book, chapter) é igual mas verse difere.
  - Publica `StateChanged(PRESENT, repeat=False, detail="corrected")`.
  - `VersePresentationService` apresenta "Salmos 23:4" (versículo corrigido).
- Se `ReferenceAntecipada` apresentou "Salmos 23" e `SpeechTranscribed` confirma "Salmos 23" (sem verse):
  - StateOrchestrator marca `is_confirmed=True`.
  - `VersePresentationService` **não reapresenta**.

---

## 14. Presentation / Holyrics Impact

### 14.1 VersePresentationService

| Aspecto | Atual | Alvo |
|---|---|---|
| Gatilho | `ReferenceDetected` / `ReferenceAntecipada` direto | **+ verificar `StateOrchestrator.current_state == PRESENT`** |
| Dedup | Nenhum | **Dedup por (book_id, chapter, verse)** + consulta `last_presented_reference` |
| Correção | `ReferenceAntecipada` + `ReferenceDetected` (is_confirmed) | **Idem** + StateOrchestrator coordena |
| API Holyrics | `show_verse_references()` | **Idem** |

### 14.2 Holyrics

- **Mantido**: token, base_url, timeout, `show_verse_references()`.
- **Rate**: limitado por dedup do StateOrchestrator + VersePresentationService.
- **Não** recebe comandos diretos do LLM ou do parser.

---

## 15. Reading Follow Impact

### 15.1 Migração para partials

| Aspecto | Atual | Alvo |
|---|---|---|
| Ativação | `ReferenceDetected` (verse_end != verse_start) | **Idem** |
| Avanço | `SpeechTranscribed` (fuzzy match) | **`SpeechStableText` (primário)** + `SpeechTranscribed` (fallback/confirmação) |
| Debounce | Nenhum | **Debounce próprio 400ms** após `SpeechStableText` antes de fuzzy-match |
| Threshold | fuzzy 0.70 | **Idem** |
| Feedback visual | Nenhum | **Futuro**: frontend mostra progresso do fuzzy-match em partials (fora de escopo) |

### 15.2 Fluxo

```
ReferenceDetected (verse_end != verse_start)
  → ReadingFollowService ativa
  → pré-carrega versículos
  → HolyricsClient.show_verse(verse_start)
  → ReadingFollowStarted

SpeechStableText (corr_id = X)
  → fuzzy match texto estável vs versículo atual
  → se similaridade ≥ 0.70:
    → current_verse += 1
    → se current_verse > verse_end → ReadingFollowEnded(completed)
    → senão → HolyricsClient.show_verse(current_verse) + ReadingFollowAdvanced

SpeechTranscribed (corr_id = X)
  → fuzzy match texto final (fallback se stable não avançou)
  → mesma lógica de avanço
```

### 15.3 Não criar pipeline STT paralelo

- ReadingFollowService **não** cria seu próprio STT.
- Consome o mesmo stream (`SpeechStableText`/`SpeechTranscribed`) que os outros componentes.
- É um consumer especializado do stream compartilhado.

---

## 16. Replay / Benchmark Impact

### 16.1 Replay

- `ReplayAdapter` é contrato abstrato (não implementado).
- **Não implementar** replay nesta migração.
- **Flag**: quando replay for implementado, deve reproduzir `SpeechStableText` e `StateChanged` além dos eventos existentes.

### 16.2 Benchmark

- Dataset `morning-prayer-27-07-2026` contém specs que referenciam `SpeechTranscribed` como evento principal.
- **Flag**: após implementação, atualizar:
  - `event_contracts.md` — adicionar `SpeechStableText`; atualizar semântica de `SpeechTranscribed`.
  - `runtime_execution_spec.md` — atualizar fluxo para streaming-first.
  - `rfc_capabilities.md` — CAP-01 input_events devem incluir `SpeechPartial`/`Updated`/`SpeechStableText`/`ReferenceAntecipada`.
  - `adr_architecture_decisions.md` — adicionar ADR sobre streaming-first.

---

## 17. Telemetry and Metrics

### 17.1 Novos hooks

| Hook | Quando | Campos |
|---|---|---|
| `text_stability_detected` | TextStabilityTracker detecta estabilidade | correlation_id, text, stability_window_ms, latency_ms |
| `state_changed` | StateOrchestrator publica StateChanged | from_state, to_state, reason, active_book, active_chapter |
| `stale_inference_rejected` | SemanticEngine descarta inferência stale | correlation_id, expected_text, actual_text |
| `ollama_queue_depth` | OllamaBackend reporta fila | depth, wait_ms |
| `presentation_dedup` | VersePresentationService suprime duplicado | book_id, chapter, verse, reason |

### 17.2 Métricas de performance

| Métrica | Fonte | Alvo |
|---|---|---|
| partial-to-parser latency | StreamingSTT → parser | < 15ms |
| partial-to-candidate latency | StreamingSTT → ReferenceCandidate | < 30ms |
| partial-to-stable latency | StreamingSTT → SpeechStableText | < 600ms + 400ms |
| partial-to-presentation latency | StreamingSTT → VersePresented | < 3000ms (GPU) |
| finalization latency | SpeechTranscribed → StateChanged | < 50ms |
| duplicate suppression count | VersePresentationService | métrica |
| event throughput | EventBus | events/s |
| LLM calls per utterance | SemanticEngine | ≤ 2 (debounce + growth) |
| cache hit rate | SemanticEngine | > 30% |
| GPU utilization | nvidia-smi / telemetry | < 80% |
| Ollama concurrency | OllamaBackend | max 1 |
| Holyrics request rate | VersePresentationService | < 1/5s |
| stale rejections | SemanticEngine | métrica |
| dropped/coalesced partials | SemanticEngine | métrica |

### 17.3 Estratégia de medição

- Hooks de telemetria já existentes (`telemetry/hooks.py`).
- Adicionar novos hooks sem alterar comportamento (mesmo padrão Sprint 21.9).
- Métricas expostas via WebSocket e endpoint `/metrics`.

---

## 18. Incremental Migration Phases

### Fase 1 — Auditoria e Instrumentação

| Aspecto | Valor |
|---|---|
| **Objetivo** | Adicionar telemetria e TextStabilityTracker sem alterar comportamento |
| **Arquivos** | `telemetry/hooks.py`, novo `pipeline/text_stability_tracker.py`, `api/startup/composition.py` |
| **Contratos** | Adicionar `SpeechStableText` ao Event Contract |
| **Dependências** | Nenhuma |
| **Riscos** | TextStabilityTracker com race condition → mitigar com lock |
| **Testes** | `test_text_stability_tracker.py` — estabilidade detectada após 600ms; reset em novo partial |
| **Critério de conclusão** | `SpeechStableText` publicado em teste; telemetria visível |

### Fase 2 — Streaming-First Parser

| Aspecto | Valor |
|---|---|
| **Objetivo** | Parser incremental consome `SpeechStableText`; reset em `SpeechTranscribed`; detecta revisão regressiva |
| **Arquivos** | `pipeline/incremental_parser.py` |
| **Contratos** | Nenhum novo |
| **Dependências** | Fase 1 |
| **Riscos** | Reset prematuro → mitigar verificando se livro atual está no novo texto |
| **Testes** | `test_incremental_parser_streaming.py` — reset em finalização; revisão regressiva; stable text |
| **Critério de conclusão** | Parser reseta corretamente em `SpeechTranscribed`; detecta revisão |

### Fase 3 — Streaming-First SemanticEngine

| Aspecto | Valor |
|---|---|
| **Objetivo** | Stale rejection; coalescing; cache LRU; semaphore Ollama |
| **Arquivos** | `semantic/engine.py`, `semantic/ollama_backend.py`, `semantic/cache.py` |
| **Contratos** | Nenhum |
| **Dependências** | Fase 1 |
| **Riscos** | Coalescing perde inferências intermediárias → aceitável (queremos a mais recente) |
| **Testes** | `test_semantic_stale_rejection.py`, `test_ollama_semaphore.py`, `test_cache_lru.py` |
| **Critério de conclusão** | Inferência stale descartada; Ollama max 1 concorrente; cache LRU funcional |

### Fase 4 — ContextEngine Incremental

| Aspecto | Valor |
|---|---|
| **Objetivo** | ContextEngine para de varrer `bus.history()`; mantém cache próprio |
| **Arquivos** | `semantic/context_engine.py` |
| **Contratos** | Nenhum |
| **Dependências** | Fase 1 |
| **Riscos** | Inconsistência se eventos perdidos → mitigar com fallback best-effort |
| **Testes** | `test_context_engine_incremental.py` |
| **Critério de conclusão** | ContextEngine não chama `bus.history()`; contexto correto em teste |

### Fase 5 — StateOrchestrator (CAP-01) Implementação

| Aspecto | Valor |
|---|---|
| **Objetivo** | Implementar transições WAIT/PREPARE/PRESENT/IGNORE; publicar StateChanged |
| **Arquivos** | `pipeline/state_orchestrator.py` |
| **Contratos** | `StateChanged` já definido; adicionar inscrições em novos eventos |
| **Dependências** | Fases 1, 2 |
| **Riscos** | Lógica incorreta → apresentação duplicada/perdida → mitigar com testes + benchmark |
| **Testes** | `test_state_orchestrator.py` — todas as transições; dedup; correção de antecipada |
| **Critério de conclusão** | StateChanged publicado em todas as transições; dedup funcional |

### Fase 6 — VersePresentationService Coordenação

| Aspecto | Valor |
|---|---|
| **Objetivo** | VersePresentationService consulta StateOrchestrator; dedup por (book, chapter, verse) |
| **Arquivos** | `presentation/verse_presentation_service.py` |
| **Contratos** | Nenhum |
| **Dependências** | Fase 5 |
| **Riscos** | StateOrchestrator rejeita apresentação legítima → mitigar com fallback |
| **Testes** | `test_verse_presentation_coordination.py` |
| **Critério de conclusão** | Apresentação coordenada; dedup funcional |

### Fase 7 — Reading Follow Migração

| Aspecto | Valor |
|---|---|
| **Objetivo** | ReadingFollowService consome `SpeechStableText`; debounce próprio |
| **Arquivos** | `presentation/reading_follow_service.py` |
| **Contratos** | Nenhum |
| **Dependências** | Fase 1 |
| **Riscos** | Avanço prematuro → mitigar com threshold fuzzy 0.70 + estabilidade 600ms |
| **Testes** | `test_reading_follow_streaming.py` |
| **Critério de conclusão** | ReadingFollow avança em stable text; fallback em SpeechTranscribed |

### Fase 8 — Desativar BiblicalNLUService

| Aspecto | Valor |
|---|---|
| **Objetivo** | BiblicalNLUService deixa de assinar `SpeechTranscribed` |
| **Arquivos** | `pipeline/nlu.py`, `api/startup/composition.py` |
| **Contratos** | **Flag: atualizar Event Contract de `SpeechTranscribed`** |
| **Dependências** | Fases 2, 5 (parser incremental + StateOrchestrator cobrem o gap) |
| **Riscos** | Perda de parsing em texto final que difere → mitigada por StateOrchestrator |
| **Testes** | `test_nlu_disabled.py` — confirmar que `SpeechTranscribed` não dispara parsing |
| **Critério de conclusão** | BiblicalNLUService desativado; parser incremental é único caminho |

### Fase 9 — Propagação de Correlation ID

| Aspecto | Valor |
|---|---|
| **Objetivo** | `SpeechTranscribed` carrega o `correlation_id` do fluxo streaming ativo |
| **Arquivos** | `microfone/speech_pipeline.py`, `microfone/speech_worker.py`, `microfone/streaming_stt_service.py` |
| **Contratos** | Nenhum novo |
| **Dependências** | Fase 5 |
| **Riscos** | Correlation_id incorreto → finalização não casa com antecipadas |
| **Testes** | `test_correlation_propagation.py` |
| **Critério de conclusão** | `SpeechTranscribed.correlation_id` == `SpeechPartial.correlation_id` do mesmo fluxo |

### Fase 10 — Atualização de Documentos

| Aspecto | Valor |
|---|---|
| **Objetivo** | Atualizar event_contracts, runtime_execution_spec, rfc_capabilities, ADRs |
| **Arquivos** | `datasets/benchmarks/morning-prayer-27-07-2026/*.md` |
| **Contratos** | **Sim** — atualizar oficialmente |
| **Dependências** | Fases 1-9 |
| **Riscos** | Documento desincronizado de código |
| **Testes** | Revisão manual |
| **Critério de conclusão** | Documentos refletem streaming-first |

### Fase 11 — Testes em Hardware Real

| Aspecto | Valor |
|---|---|
| **Objetivo** | Validar end-to-end com microfone USB + GPU + Holyrics + Ollama |
| **Arquivos** | Nenhum (validação) |
| **Dependências** | Fases 1-10 |
| **Riscos** | Latência real, timeout Ollama, GPU contention |
| **Testes** | Manual: dizer "João 3:16", "Salmos 23", "Romanos 8 28 a 39" |
| **Critério de conclusão** | Apresentação correta < 3s GPU; Reading Follow avança em leitura contínua |

---

## 19. Dependencies

### 19.1 Dependências entre fases

```
Fase 1 (Instrumentação + TextStabilityTracker)
  ├─→ Fase 2 (Parser)
  ├─→ Fase 3 (SemanticEngine)
  ├─→ Fase 4 (ContextEngine)
  └─→ Fase 7 (Reading Follow)

Fase 2 + Fase 5 (StateOrchestrator)
  └─→ Fase 6 (VersePresentation coordenação)
  └─→ Fase 8 (Desativar NLU)
  └─→ Fase 9 (Correlation propagation)

Fases 1-9 → Fase 10 (Documentos) → Fase 11 (Hardware)
```

### 19.2 Dependências externas

- `rapidfuzz` — já usado por ReadingFollowService.
- `faster-whisper` / `ctranslate2` — mantido.
- `ollama` — mantido.
- Nenhuma nova dependência.

---

## 20. Risks and Mitigations

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| StateOrchestrator com lógica incorreta → apresentação duplicada/perdida | Média | Alto | Testes exaustivos + benchmark; fallback: VersePresentationService dedup independente |
| Inferência stale não rejeitada corretamente | Média | Médio | Stale rejection por correlation_id + texto; testes |
| Ollama timeout persiste mesmo com coalescing | Média | Médio | Semaphore max 1; coalescing; não aumentar timeout; monitorar GPU |
| TextStabilityTracker race condition | Baixa | Baixo | Lock interno; testes de concorrência |
| Correlation_id não propaga entre streaming e segmento | Média | Alto | Fase 9 dedicada; testes |
| Parser reset prematuro em revisão regressiva | Baixa | Médio | Verificar se livro atual está no novo texto antes de reset |
| ReadingFollow avanço prematuro | Baixa | Médio | Threshold fuzzy 0.70 + estabilidade 600ms + fallback SpeechTranscribed |
| Performance regression (mais eventos, mais subscribers) | Baixa | Médio | Hooks síncronos < 1ms; parser < 10ms; telemetria monitora |
| Event Contract desincronizado | Média | Médio | Fase 10 dedicada; flag explícita |

---

## 21. Testing Strategy

### 21.1 Testes unitários (por fase)

| Fase | Arquivo de teste | Cobertura |
|---|---|---|
| 1 | `test_text_stability_tracker.py` | Detecção de estabilidade; reset; race |
| 2 | `test_incremental_parser_streaming.py` | Reset em finalização; revisão regressiva; stable |
| 3 | `test_semantic_stale_rejection.py` | Stale discard; coalescing; cache LRU; semaphore |
| 4 | `test_context_engine_incremental.py` | Cache interno; sem bus.history() |
| 5 | `test_state_orchestrator.py` | Todas as transições; dedup; correção |
| 6 | `test_verse_presentation_coordination.py` | Consulta StateOrchestrator; dedup |
| 7 | `test_reading_follow_streaming.py` | Stable text; debounce; fallback |
| 8 | `test_nlu_disabled.py` | NLU não dispara em SpeechTranscribed |
| 9 | `test_correlation_propagation.py` | Correlation_id consistente |

### 21.2 Testes de integração

- `test_streaming_first_e2e.py` (novo): simula fluxo completo AudioCapture → SpeechPartial → Parser → StateOrchestrator → VersePresentation com mocks.
- `test_streaming_first_semantic_e2e.py` (novo): fluxo com SemanticEngine + Ollama mock.

### 21.3 Testes existentes

- Manter `test_sprint21_4_streaming_first.py`, `test_sprint19_streaming.py`, `test_state_orchestrator.py`, `test_reading_follow.py`, `test_verse_presentation_service.py`.
- Atualizar conforme migração.

### 21.4 Benchmark

- Dataset `morning-prayer-27-07-2026` para validação de latência e corretude.
- Comparar antes/depois com métricas de §17.

### 21.5 Validação manual (Fase 11)

- Microfone USB + GPU + Holyrics + Ollama.
- Cenários: referência explícita, implícita, leitura contínua, comando de versão.

---

## 22. Acceptance Criteria

- [ ] `SpeechStableText` é publicado quando texto permanece estável por 600ms.
- [ ] `IncrementalBiblicalParser` reseta em `SpeechTranscribed` e detecta revisão regressiva.
- [ ] `SemanticEngine` rejeita inferência stale; coalesce partials; cache LRU funcional.
- [ ] `ContextEngine` não varre `bus.history()`; mantém cache incremental.
- [ ] `StateOrchestrator` publica `StateChanged` em todas as transições WAIT/PREPARE/PRESENT/IGNORE.
- [ ] `VersePresentationService` consulta `StateOrchestrator` e faz dedup.
- [ ] `ReadingFollowService` avança em `SpeechStableText` com fallback em `SpeechTranscribed`.
- [ ] `BiblicalNLUService` desativado; parser incremental é único caminho de parsing.
- [ ] `SpeechTranscribed.correlation_id` == `SpeechPartial.correlation_id` do mesmo fluxo.
- [ ] Latência partial-to-presentation < 3000ms (GPU) em teste de hardware.
- [ ] LLM calls por utterance ≤ 2.
- [ ] Nenhuma apresentação duplicada em teste de integração.
- [ ] Documentos de benchmark atualizados.
- [ ] Suite de testes existente passa (com atualizações).

---

## 23. Decisions Still Requiring Approval

| # | Decisão | Status |
|---|---|---|
| 1 | Criar `SpeechStableText` como novo evento (vs. modificar `is_stable` em `SpeechPartialUpdated`) | **Proposto** — preferido por preservar Event Contract |
| 2 | Desativar `BiblicalNLUService` (vs. manter como fallback) | **Proposto** — confirmado pelo usuário (fluxo segmentado vira confirmação) |
| 3 | Implementar StateOrchestrator transições (vs. manter esqueleto) | **Aprovado** pelo usuário |
| 4 | Migrar ReadingFollow para partials (vs. manter em SpeechTranscribed) | **Aprovado** pelo usuário |
| 5 | Manter VersionCommandDetector em `SpeechTranscribed` (vs. migrar para partials) | **Proposto** — segurança contra falso positivo |
| 6 | Atualizar Event Contract de `SpeechTranscribed` (semântica "confirmação de finalização") | **Flag** — requer revisão explícita |
| 7 | Adicionar ADR sobre streaming-first | **Proposto** |
| 8 | Cache LRU max 200 entries (vs. ilimitado) | **Proposto** |
| 9 | Semaphore max 1 no OllamaBackend | **Proposto** |
| 10 | Propagação de correlation_id entre streaming e segmento VAD | **Proposto** — requer análise de implementação |

---

## 24. Final ASCII Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AUDIO CAPTURE (16kHz mono)                          │
│                    AudioCaptureService (PortAudio thread)                   │
└──────────────┬──────────────────────────────┬───────────────────────────────┘
               │                              │
               ▼                              ▼
    ┌──────────────────┐          ┌─────────────────────┐
    │  VAD Pipeline    │          │   RingBuffer (20s)  │
    │ SpeechPipeline   │          │                     │
    │   Service        │          │   SlidingWindow     │
    │  (VAD thread)    │          │   (400ms, 6s win)   │
    └────────┬─────────┘          └──────────┬──────────┘
             │                               │
             ▼                               ▼
    ┌──────────────────┐          ┌─────────────────────┐
    │  SpeechQueue     │          │ StreamingSTTService │
    │  (bounded 10)    │          │  (STTExecutor lock) │
    └────────┬─────────┘          └──────────┬──────────┘
             │                               │
             ▼                               ▼
    ┌──────────────────┐    ╔═══════════════════════════════════════════╗
    │  SpeechWorker    │    ║              EVENT BUS                     ║
    │  (Whisper)       │    ║   SpeechPartial  ──────────────────────►  ║
    └────────┬─────────┘    ║   SpeechPartialUpdated ───────────────►  ║
             │              ║   SpeechStableText (novo) ────────────►  ║
             ▼              ║   SpeechTranscribed (FINAL/CONFIRMAÇÃO)►  ║
    ╔══════════════════╗    ╚═══════════┬════════════════════════════════╝
    ║   EVENT BUS      ║                │
    ║ SpeechTranscribed║                │
    ║   ────────────►  ║     ┌──────────┼──────────┬──────────────┬─────────────┐
    ╚════════╤═════════╝     ▼          ▼          ▼              ▼             ▼
             │         ┌──────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
             │         │Incremental│ │  Text   │ │  Sermon  │ │ Semantic │ │   State  │
             │         │Biblical   │ │Stability│ │  Memory  │ │  Engine  │ │  Orchest.│
             │         │  Parser   │ │ Tracker │ │  Engine  │ │(debounce)│ │  (CAP-01)│
             │         └─────┬────┘ └────┬────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘
             │               │           │           │            │            │
             │               ▼           ▼           ▼            ▼            │
             │         RefCandidate  StableText   SermonCtx   IntentCand       │
             │         RefAntecip.                Updated         │            │
             │         RefDetected                                 │            │
             │               │           │                        ▼            │
             │               │           │                 ┌──────────┐        │
             │               │           │                 │Reference │        │
             │               │           │                 │ Resolver │        │
             │               │           │                 └────┬─────┘        │
             │               │           │                      │ RefDetected │
             │               │           │                      ▼             │
             │               │           │              ┌──────────────┐      │
             │               └───────────┴──────────────│   State      │      │
             │                            ┌─────────────│ Orchestrate  │      │
             │                            │             │  (CAP-01)    │      │
             │                            │             └──────┬───────┘      │
             │                            │                    │ StateChanged│
             │                            │                    ▼             │
             │                            │             ┌──────────────┐     │
             │                            └─────────────│   Verse      │     │
             │                                          │ Presentation │     │
             │                                          │   Service    │     │
             │                                          └──────┬───────┘     │
             │                                                 │             │
             │                                                 ▼             │
             │                                          ┌──────────────┐    │
             └──────────────────────────────────────────│   HOLYRICS   │◄───┘
                                                        │  show_verse_ │
                                                        │  references  │
                                                        └──────────────┘

  Reading Follow (consumer especializado do stream):
    SpeechStableText ──► ReadingFollowService ──► Holyrics (show_verse)
    SpeechTranscribed ──► (fallback/confirmação)

  Version Command (mantém em SpeechTranscribed):
    SpeechTranscribed ──► VersionCommandDetector ──► VersionChanged

  Frontend:
    SpeechPartial/Updated ──► (transcrição ao vivo)
    SpeechTranscribed     ──► (texto final confirmado)
    StateChanged          ──► (estado do sistema)
```

---

## Apêndice A — Traceability Matrix

| Mudança | Documento afetado | Ação |
|---|---|---|
| Novo evento `SpeechStableText` | `event_contracts.md` | **Adicionar seção** |
| `SpeechTranscribed` muda semântica | `event_contracts.md` | **Atualizar seção** — flag |
| StateOrchestrator implementa transições | `rfc_capabilities.md` CAP-01 | **Atualizar input_events** — flag |
| StateOrchestrator assina partials | `rfc_capabilities.md` CAP-01 | **Atualizar input_events** — flag |
| Fluxo streaming-first | `runtime_execution_spec.md` §1, §5 | **Atualizar** — flag |
| BiblicalNLUService desativado | `runtime_execution_spec.md` §5 | **Atualizar** — flag |
| ReadingFollow em stable text | `runtime_execution_spec.md` §5 | **Atualizar** — flag |
| Performance budget | `runtime_execution_spec.md` §20 | **Atualizar** com novas métricas |
| ADR streaming-first | `adr_architecture_decisions.md` | **Adicionar ADR** — flag |
| Replay deve incluir novos eventos | `adr_architecture_decisions.md` | **Flag** |

## Apêndice B — Referências de Arquivo

| Componente | Arquivo |
|---|---|
| AudioCaptureService | `microfone/audio_capture_service.py` |
| SpeechPipelineService (VAD) | `microfone/speech_pipeline.py` |
| SpeechWorker | `microfone/speech_worker.py` |
| RingBuffer | `microfone/ring_buffer.py` |
| SlidingWindow | `microfone/sliding_window.py` |
| StreamingSTTService | `microfone/streaming_stt_service.py` |
| STTExecutor | `microfone/stt_executor.py` |
| EventBus | `pipeline/bus.py` |
| Events | `pipeline/events.py` |
| IncrementalBiblicalParser | `pipeline/incremental_parser.py` |
| BiblicalNLUService | `pipeline/nlu.py` |
| StateOrchestrator | `pipeline/state_orchestrator.py` |
| SemanticEngine | `semantic/engine.py` |
| ContextEngine | `semantic/context_engine.py` |
| OllamaBackend | `semantic/ollama_backend.py` |
| SemanticCache | `semantic/cache.py` |
| ReferenceResolver | `semantic/resolver.py` |
| SermonMemoryEngine | `sermon/engine.py` |
| VersePresentationService | `presentation/verse_presentation_service.py` |
| ReadingFollowService | `presentation/reading_follow_service.py` |
| VersionCommandDetector | `presentation/version_command_detector.py` |
| Composition Root | `api/startup/composition.py` |
| Telemetry Hooks | `telemetry/hooks.py` |
| Event Contracts | `datasets/benchmarks/morning-prayer-27-07-2026/event_contracts.md` |
| Runtime Spec | `datasets/benchmarks/morning-prayer-27-07-2026/runtime_execution_spec.md` |
| RFCs | `datasets/benchmarks/morning-prayer-27-07-2026/rfc_capabilities.md` |
| ADRs | `datasets/benchmarks/morning-prayer-27-07-2026/adr_architecture_decisions.md` |

---
