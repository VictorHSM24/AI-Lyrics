# Event Contracts — AI Lyrics Pipeline EventBus

Especificação oficial do barramento de eventos do AI Lyrics.

Este documento é autocontido: um desenvolvedor deve conseguir implementar completamente o EventBus sem consultar nenhum outro documento.

---

## Índice

1. [Arquitetura do EventBus](#arquitetura-do-eventbus)
2. [EventMetadata](#eventmetadata)
3. [Eventos do Fluxo Principal](#eventos-do-fluxo-principal)
4. [Eventos de Ciclo de Vida](#eventos-de-ciclo-de-vida)
5. [Eventos de Fala Contínua (Sprint 16/19/28)](#eventos-de-fala-contínua)
6. [Eventos de Referência Bíblica](#eventos-de-referência-bíblica)
7. [Eventos de Apresentação](#eventos-de-apresentação)
8. [Eventos Semânticos](#eventos-semânticos)
9. [Eventos de Contexto do Sermão](#eventos-de-contexto-do-sermão)
10. [Eventos dos RFCs (CAP-01 a CAP-07)](#eventos-dos-rfcs)
11. [Sequências Oficiais](#sequências-oficiais)
12. [Invalid Event Flows](#invalid-event-flows)
13. [Event Invariants](#event-invariants)
14. [Event Versioning](#event-versioning)
15. [Observability](#observability)

---

## Arquitetura do EventBus

O `PipelineEventBus` é o barramento síncrono de eventos do AI Lyrics. Todos os componentes se comunicam exclusivamente via eventos publicados no bus. Nenhum componente chama outro diretamente.

### Características

- **Síncrono:** handlers executam na ordem de inscrição, na thread do publisher.
- **Tipado:** inscrição é por tipo de evento (classe Python). Handlers recebem apenas eventos do tipo inscrito.
- **Imutável:** todos os eventos são `frozen dataclass`. Nenhum handler modifica um evento.
- **Rastreável:** todo evento carrega `EventMetadata` com `event_id`, `correlation_id`, `causation_id`.
- **Categorizado:** eventos são `OperationalEvent` (persistidos no EventStore) ou `TelemetryEvent` (não persistidos).

### Contrato do Bus

```
publish(event: PipelineEvent) -> None
    Armazena no EventStore se OperationalEvent.
    Notifica todos os handlers inscritos no tipo do evento.

subscribe(event_type: type, handler: Callable) -> None
    Registra handler para receber eventos do tipo especificado.

unsubscribe(event_type: type, handler: Callable) -> bool
    Remove registro de handler.
```

### Regras

1. Um evento tem exatamente um publisher primário. Alguns eventos têm publisher secundário (definido nos RFCs).
2. Múltiplos subscribers podem existir para o mesmo evento.
3. Handlers não podem lançar exceções que propaguem para o bus. Erros são tratados internamente.
4. O bus não filtra, transforma ou reordena eventos.
5. `OperationalEvent` é persistido no `EventStore`. `TelemetryEvent` não é persistido.

---

## EventMetadata

Todo evento carrega exatamente um `EventMetadata` no campo `meta`. É o primeiro campo de todo evento.

### Campos

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `event_id` | str | Sim | Identificador único do evento (UUID) |
| `correlation_id` | str | Sim | Identificador do fluxo de processamento |
| `causation_id` | str \| None | Sim | `event_id` do evento predecessor (None se inicial) |
| `session_id` | str | Sim | Identificador da sessão atual |
| `timestamp` | float | Sim | Momento de criação (segundos desde epoch) |
| `origin` | str | Sim | Componente que criou o evento |
| `metadata` | tuple | Não | Pares (chave, valor) extras |

### Fábricas

- `EventMetadata.for_initial(session_id, origin, correlation_id=None)`: cria metadados para o primeiro evento de um fluxo. Gera novo `correlation_id` (se não fornecido). `causation_id = None`. **Sprint 28 (Fase 10)**: se `correlation_id` fornecido, reusa-o (propagação de correlation_id do fluxo streaming ativo).
- `EventMetadata.for_next(previous, origin)`: cria metadados para evento subsequente. Preserva `correlation_id` e `session_id`. `causation_id = previous.event_id`.
- `EventMetadata.for_session_event(session_id, origin)`: cria metadados para eventos de ciclo de vida. Pode gerar novo `correlation_id`.

### Garantias

- `correlation_id` é constante dentro de um fluxo de processamento.
- `causation_id` forma uma cadeia que pode ser percorrida para reconstruir a sequência de eventos.
- `event_id` é único globalmente.
- `metadata` é imutável (tuple, não dict).

---

## Eventos do Fluxo Principal

Estes eventos formam o pipeline linear original (Sprint 12). O fluxo principal processa segmentos de fala completos (não streaming).

### SpeechSegmentReceived

| Campo | Valor |
|---|---|
| **Nome** | `SpeechSegmentReceived` |
| **Descrição** | Segmento de fala recebido do STT/captura. Ponto de entrada do fluxo. |
| **Publisher** | `AudioCaptureService` |
| **Publisher secundário** | Nenhum |
| **Subscribers** | `RecognitionHandler` |
| **Quando é publicado** | Quando um segmento de áudio completo é capturado e enfileirado para transcrição. |
| **Quando NÃO deve ser publicado** | Durante streaming parcial (usar `SpeechPartial`). Após pipeline parado. |
| **Predecessores** | Nenhum (evento inicial de fluxo). |
| **Sucessores** | `SpeechRecognized` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | Metadados de rastreabilidade |
| `audio` | bytes | Não | Áudio raw do segmento (pode ser vazio em testes) |
| `start_time` | float | Não | Timestamp de início da captura |
| `end_time` | float | Não | Timestamp de fim da captura |
| `duration_ms` | int | Não | Duração em milissegundos |
| `chunk_count` | int | Não | Número de chunks de áudio |

**Garantias:** Inicia novo `correlation_id`. `causation_id = None`.

**Idempotência:** Não é idempotente. Publicar duas vezes cria dois fluxos.

**Exemplo JSON:**
```json
{
  "event_type": "SpeechSegmentReceived",
  "meta": {
    "event_id": "evt-001",
    "correlation_id": "corr-001",
    "causation_id": null,
    "session_id": "sess-001",
    "timestamp": 1756342800.0,
    "origin": "AudioCaptureService"
  },
  "audio": "",
  "start_time": 1756342790.0,
  "end_time": 1756342800.0,
  "duration_ms": 10000,
  "chunk_count": 5
}
```

**Exemplo positivo:** Áudio de 10 segundos capturado, pipeline ativo.
**Exemplo negativo:** Publicar com pipeline pausado (o evento é ignorado pelo handler).

---

### SpeechRecognized

| Campo | Valor |
|---|---|
| **Nome** | `SpeechRecognized` |
| **Descrição** | Texto reconhecido do segmento de fala. |
| **Publisher** | `RecognitionHandler` |
| **Publisher secundário** | Nenhum |
| **Subscribers** | `SearchHandler`, `ContextHandler`, `BiblicalNLUService` |
| **Quando é publicado** | Após STT transcrever o segmento. |
| **Quando NÃO deve ser publicado** | Se `SpeechSegmentReceived` não chegou. Se STT falhou (publicar `PipelineError`). |
| **Predecessores** | `SpeechSegmentReceived` |
| **Sucessores** | `SearchRequested`, `SpeechTranscribed` (via NLU) |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `text` | str | Sim | Texto reconhecido |
| `language` | str | Não | Idioma detectado |
| `confidence` | float | Não | Confiança do STT (0.0 a 1.0) |
| `processing_ms` | int | Não | Latência de processamento |

**Garantias:** `correlation_id` preservado de `SpeechSegmentReceived`.

---

### SearchRequested

| Campo | Valor |
|---|---|
| **Nome** | `SearchRequested` |
| **Descrição** | Pedido de busca emitido (texto reconhecido convertido em query). |
| **Publisher** | `SearchHandler` |
| **Subscribers** | Nenhum (evento de telemetria intermediária) |
| **Predecessores** | `SpeechRecognized` |
| **Sucessores** | `SearchCompleted` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `query` | str | Sim | Query de busca |
| `intent_action` | str | Não | Ação identificada pelo parser |
| `intent_book` | str \| None | Não | Livro identificado |
| `intent_chapter` | int \| None | Não | Capítulo identificado |
| `intent_verse` | int \| None | Não | Versículo identificado |

---

### SearchCompleted

| Campo | Valor |
|---|---|
| **Nome** | `SearchCompleted` |
| **Descrição** | Busca completada com resultados. |
| **Publisher** | `SearchHandler` |
| **Subscribers** | `RankingHandler` |
| **Predecessores** | `SearchRequested` |
| **Sucessores** | `RankingCompleted` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `query` | str | Sim | Query original |
| `results` | tuple | Não | Tuple de SearchResult |
| `result_count` | int | Não | Número de resultados |
| `search_ms` | int | Não | Latência de busca |

---

### RankingCompleted

| Campo | Valor |
|---|---|
| **Nome** | `RankingCompleted` |
| **Descrição** | Ranking dos resultados completado. |
| **Publisher** | `RankingHandler` |
| **Subscribers** | `IntelligenceHandler` |
| **Predecessores** | `SearchCompleted` |
| **Sucessores** | `IntelligenceCompleted` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `query` | str | Sim | Query original |
| `ranked_candidates` | tuple | Não | Tuple de CandidateInfo |
| `candidate_count` | int | Não | Número de candidatos |

---

### IntelligenceCompleted

| Campo | Valor |
|---|---|
| **Nome** | `IntelligenceCompleted` |
| **Descrição** | Sermon Intelligence produziu recomendação. |
| **Publisher** | `IntelligenceHandler` |
| **Subscribers** | `PresentationHandler` |
| **Predecessores** | `RankingCompleted` |
| **Sucessores** | `PresentationRequested` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `query` | str | Sim | Query original |
| `recommendation` | Any | Não | IntelligenceRecommendation |
| `best_candidate_id` | str | Não | ID do melhor candidato |
| `confidence_level` | str | Não | Nível de confiança |

---

### PresentationRequested

| Campo | Valor |
|---|---|
| **Nome** | `PresentationRequested` |
| **Descrição** | Pedido de apresentação enviado ao Holyrics. |
| **Publisher** | `PresentationHandler` |
| **Subscribers** | Nenhum (evento intermediário) |
| **Predecessores** | `IntelligenceCompleted` |
| **Sucessores** | `PresentationCompleted` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `candidate_id` | str | Sim | ID do candidato |
| `book_id` | int | Sim | ID do livro |
| `chapter` | int | Sim | Capítulo |
| `verse` | int \| None | Não | Versículo |
| `version` | str | Não | Versão bíblica (default "ACF") |

---

### PresentationCompleted

| Campo | Valor |
|---|---|
| **Nome** | `PresentationCompleted` |
| **Descrição** | Apresentação executada no Holyrics. |
| **Publisher** | `PresentationHandler` |
| **Subscribers** | `FeedbackHandler` |
| **Predecessores** | `PresentationRequested` |
| **Sucessores** | `FeedbackRecorded` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `candidate_id` | str | Sim | ID do candidato |
| `status` | str | Sim | Status da apresentação ("ok", "error") |
| `verse_id` | str | Não | ID do versículo no Holyrics |
| `presented` | bool | Sim | True se apresentado com sucesso |

---

### FeedbackRecorded

| Campo | Valor |
|---|---|
| **Nome** | `FeedbackRecorded` |
| **Descrição** | Feedback registrado no Feedback Learning. |
| **Publisher** | `FeedbackHandler` |
| **Subscribers** | `EvaluationHandler` |
| **Predecessores** | `PresentationCompleted` |
| **Sucessores** | `EvaluationRecorded` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `candidate_id` | str | Sim | ID do candidato |
| `feedback_type` | str | Sim | "accepted" ou "rejected" |
| `scope` | str | Não | Escopo (default "GLOBAL") |
| `query` | str | Não | Query original |

---

### EvaluationRecorded

| Campo | Valor |
|---|---|
| **Nome** | `EvaluationRecorded` |
| **Descrição** | Métrica registrada no Continuous Evaluation. |
| **Publisher** | `EvaluationHandler` |
| **Subscribers** | Nenhum (evento terminal) |
| **Predecessores** | `FeedbackRecorded` |
| **Sucessores** | Nenhum (fim do fluxo) |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `query` | str | Não | Query original |
| `classification` | str | Não | Classificação |
| `candidate_id` | str | Não | ID do candidato |
| `duration_ms` | int | Não | Duração total |

---

## Eventos de Ciclo de Vida

### PipelineStarted

| Campo | Valor |
|---|---|
| **Nome** | `PipelineStarted` |
| **Descrição** | Pipeline iniciado. |
| **Publisher** | `PipelineEngine` |
| **Subscribers** | Todos os componentes que precisam inicializar |
| **Quando é publicado** | Quando o pipeline é iniciado pelo operador. |
| **Quando NÃO deve ser publicado** | Se o pipeline já está ativo. |
| **Predecessores** | Nenhum. |
| **Sucessores** | Nenhum (evento de ciclo de vida). |
| **Categoria** | Operational |

**Payload:** Apenas `meta`. Sem campos adicionais.

**Garantias:** Inicia novo `correlation_id` próprio (não pertence a fluxo de segmento).

---

### PipelineStopped

| Campo | Valor |
|---|---|
| **Nome** | `PipelineStopped` |
| **Descrição** | Pipeline parado. |
| **Publisher** | `PipelineEngine` |
| **Subscribers** | Todos os componentes que precisam finalizar |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `reason` | str | Não | Motivo da parada |

---

### PipelinePaused

| Campo | Valor |
|---|---|
| **Nome** | `PipelinePaused` |
| **Descrição** | Pipeline pausado. |
| **Publisher** | `PipelineEngine` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `reason` | str | Não | Motivo da pausa |

---

### PipelineResumed

| Campo | Valor |
|---|---|
| **Nome** | `PipelineResumed` |
| **Descrição** | Pipeline retomado. |
| **Publisher** | `PipelineEngine` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `reason` | str | Não | Motivo da retomada |

---

### PipelineError

| Campo | Valor |
|---|---|
| **Nome** | `PipelineError` |
| **Descrição** | Erro durante processamento do Pipeline. Não interrompe o pipeline. |
| **Publisher** | `BaseHandler._publish_error()` |
| **Subscribers** | `PipelineEngine` (para logging e telemetria) |
| **Quando é publicado** | Quando qualquer handler captura uma exceção durante processamento. |
| **Quando NÃO deve ser publicado** | Para erros esperados (ex.: referência inválida usa `ReferenceInvalid`). |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `error_type` | str | Sim | Tipo da exceção |
| `error_message` | str | Sim | Mensagem de erro |
| `handler_name` | str | Sim | Nome do handler que falhou |
| `recoverable` | bool | Sim | True se o pipeline pode continuar |

**Garantias:** O pipeline continua operando após `PipelineError`. Apenas o handler que falhou é afetado.

**Failure semantics:** Se `recoverable=true`, o pipeline continua. Se `recoverable=false`, o pipeline deve parar.

---

## Eventos de Fala Contínua (Sprint 16, 19 e 28)

### SpeechStarted

| Campo | Valor |
|---|---|
| **Nome** | `SpeechStarted` |
| **Descrição** | VAD detectou início de fala. |
| **Publisher** | `SpeechPipelineService` |
| **Subscribers** | Componentes que preparam para receber parciais |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `timestamp_start` | float | Não | Timestamp de início |

**Garantias:**
- Inicia novo `correlation_id` para o fluxo de fala contínua.
- **Sprint 28 (Fase 10)**: Se há `StreamingSTTService` com correlation_id ativo, o `SpeechPipelineService` reusa-o em vez de gerar novo, garantindo que `SpeechTranscribed` case com `SpeechPartial` do mesmo fluxo.

---

### SpeechEnded

| Campo | Valor |
|---|---|
| **Nome** | `SpeechEnded` |
| **Descrição** | VAD detectou fim da fala. |
| **Publisher** | `SpeechPipelineService` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `timestamp_end` | float | Não | Timestamp de fim |
| `duration_ms` | int | Não | Duração total da fala |

---

### SpeechSegmentCreated

| Campo | Valor |
|---|---|
| **Nome** | `SpeechSegmentCreated` |
| **Descrição** | Segmento criado e enfileirado para transcrição. |
| **Publisher** | `SpeechPipelineService` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `duration_ms` | int | Não | Duração do segmento |
| `chunk_count` | int | Não | Número de chunks |
| `sample_rate` | int | Não | Sample rate (default 16000) |
| `channels` | int | Não | Número de canais (default 1) |

---

### SpeechTranscribing

| Campo | Valor |
|---|---|
| **Nome** | `SpeechTranscribing` |
| **Descrição** | Worker começou a transcrever o segmento. |
| **Publisher** | `SpeechWorker` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `duration_ms` | int | Não | Duração do segmento sendo transcrito |

---

### SpeechTranscribed

| Campo | Valor |
|---|---|
| **Nome** | `SpeechTranscribed` |
| **Descrição** | Confirmação de finalização — texto final após VAD fechar o segmento. **Sprint 28**: Não dispara mais parsing (o parser incremental já tratou em `SpeechCommittedWords`). |
| **Publisher** | `SpeechWorker` |
| **Publisher secundário** | `RecognitionHandler` (via `SpeechRecognized`) |
| **Subscribers** | `SermonMemoryEngine`, `StateOrchestrator` (CAP-01: confirma/corrige/limpa), `ReadingFollowService` (fallback), `VersionCommandDetector` (mantém para mudança de versão) |
| **Quando é publicado** | Quando a transcrição de um segmento VAD é finalizada. |
| **Quando NÃO deve ser publicado** | Durante streaming parcial (usar `SpeechPartial`/`SpeechCommittedWords`). |
| **Predecessores** | `SpeechTranscribing` ou `SpeechRecognized` |
| **Sucessores** | `StateChanged` (confirmação/correção/limpeza), `ReadingFollowAdvanced` (fallback) |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `text` | str | Sim | Texto transcrito |
| `language` | str | Não | Idioma detectado |
| `confidence` | float | Não | Confiança do STT |
| `latency_ms` | int | Não | Latência total (captura até transcrição) |
| `duration_ms` | int | Não | Duração do áudio transcrito |

**Garantias:**
- `correlation_id` preservado do fluxo de fala. **Sprint 28 (Fase 10)**: `correlation_id` é propagado do fluxo streaming ativo (`StreamingSTTService.current_correlation_id`), garantindo que `SpeechTranscribed.correlation_id == SpeechPartial.correlation_id` do mesmo fluxo.
- Texto é final (não muda).
- **Sprint 28 (Fase 9)**: `BiblicalNLUService` não é mais subscriber por padrão (`enabled=False`). O parser incremental é o único caminho de parsing.

**Exemplo positivo:** "Abra comigo no livro de Primeiro Coríntios" com confidence 0.95.
**Exemplo negativo:** Texto vazio (deveria publicar `IntentUnknown` com `reason="empty_text"`).

---

### SpeechPartial

| Campo | Valor |
|---|---|
| **Nome** | `SpeechPartial` |
| **Descrição** | Transcrição parcial de streaming. |
| **Publisher** | `StreamingSTTService` |
| **Subscribers** | `IncrementalBiblicalParser` (Sprint 28: `SemanticEngine` migrou para `SpeechCommittedWords`) |
| **Quando é publicado** | Quando uma janela de áudio é transcrita pela primeira vez (~400ms). |
| **Quando NÃO deve ser publicado** | Após `SpeechEnded` (usar `SpeechTranscribed`). |
| **Predecessores** | `SpeechStarted` |
| **Sucessores** | `SpeechPartialUpdated`, `ReferenceCandidate`, `IntentCandidate` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `text` | str | Sim | Texto parcial reconhecido |
| `language` | str | Não | Idioma |
| `confidence` | float | Não | Confiança |
| `latency_ms` | int | Não | Latência captura até parcial |
| `audio_duration_ms` | int | Não | Duração da janela |
| `is_stable` | bool | Não | True se texto não deve mudar mais |

**Garantias:** `correlation_id` compartilhado entre todos `SpeechPartial`/`SpeechPartialUpdated` do mesmo fluxo.

---

### SpeechPartialUpdated

| Campo | Valor |
|---|---|
| **Nome** | `SpeechPartialUpdated` |
| **Descrição** | Atualização de transcrição parcial de streaming. |
| **Publisher** | `StreamingSTTService` |
| **Subscribers** | `IncrementalBiblicalParser` (Sprint 28: `SemanticEngine` migrou para `SpeechCommittedWords`) |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `text` | str | Sim | Texto completo atualizado |
| `appended_text` | str | Não | Apenas o trecho novo (diff) |
| `language` | str | Não | Idioma |
| `confidence` | float | Não | Confiança |
| `latency_ms` | int | Não | Latência |
| `audio_duration_ms` | int | Não | Duração da janela |
| `is_stable` | bool | Não | True se texto não deve mudar mais |

**Garantias:** `text` contém o texto completo (não apenas o diff). `appended_text` contém apenas o trecho novo.

---

### SpeechCommittedWords

| Campo | Valor |
|---|---|
| **Nome** | `SpeechCommittedWords` |
| **Descrição** | Palavras confirmed por LocalAgreement-2 (duas transcrições concordam). Fluxo operacional primário para parser, semântica, contexto, estado, reading follow. |
| **Publisher** | `StreamingSTTService` (após LocalAgreement-2 confirmar palavras) |
| **Subscribers** | `IncrementalBiblicalParser`, `SemanticEngine`, `ReadingFollowService`, `SermonMemoryEngine`, `ContextEngine`, `VersionCommandDetector` |
| **Quando é publicado** | A cada ciclo onde novas palavras são committed (~1s). |
| **Quando NÃO deve ser publicado** | Durante partials não-confirmed. Após `SpeechEnded`. |
| **Predecessores** | `SpeechPartial` ou `SpeechPartialUpdated` |
| **Sucessores** | `ReferenceCandidate`, `ReferenceDetected`, `IntentCandidate`, `NavigationCommandDetected` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `committed_text` | str | Sim | Palavras novas confirmed nesta janela |
| `full_committed_text` | str | Sim | Texto acumulado de todas as palavras committed |
| `words` | tuple | Não | Lista de (word, start, end) |
| `language` | str | Não | Idioma |
| `confidence` | float | Não | Confiança média |
| `latency_ms` | int | Não | Latência |
| `audio_duration_ms` | int | Não | Duração da janela de áudio |

**Garantias:**
- `correlation_id` é o mesmo do `SpeechPartial` que originou o fluxo.
- `full_committed_text` é acumulativo (contém todas as palavras committed desde o início do fluxo).
- Palavras committed são estáveis por definição (LocalAgreement-2: duas transcrições concordam).
- **Sprint 28**: Este é o fluxo operacional primário. Parser, semântica, contexto, estado e reading follow operam em committed words durante fala contínua, sem esperar `SpeechTranscribed`.

**Idempotência:** Não é idempotente. Cada evento carrega palavras novas.

---

## Eventos de Referência Bíblica

### ReferenceCandidate

| Campo | Valor |
|---|---|
| **Nome** | `ReferenceCandidate` |
| **Descrição** | Candidato a referência bíblica detectada incrementalmente. Não é definitivo. |
| **Publisher** | `IncrementalBiblicalParser` |
| **Publisher secundário** | `StateOrchestrator` (CAP-02: pode publicar ao completar referência cross-segmento) |
| **Subscribers** | `StateOrchestrator` (CAP-01), `VersePresentationService` (para pré-carregamento opcional) |
| **Quando é publicado** | Quando o parser identifica parcialmente uma referência (livro, ou livro+capítulo) com confiança abaixo do threshold de detecção (0.90). |
| **Quando NÃO deve ser publicado** | Se confiança atingiu threshold de detecção (publicar `ReferenceDetected`). Se nenhum livro foi identificado. |
| **Predecessores** | `SpeechPartial` ou `SpeechPartialUpdated` |
| **Sucessores** | `StateChanged` (PREPARE), `ReferenceDetected` (quando completada) |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `book` | str | Sim | Nome canônico do livro |
| `book_id` | int | Sim | ID do livro |
| `chapter` | int | Não | Capítulo (0 se não identificado) |
| `verse_start` | int | Não | Versículo inicial (0 se não identificado) |
| `verse_end` | int | Não | Versículo final (0 se intervalo não identificado) |
| `confidence` | float | Sim | Confiança da detecção (0.40 a 0.89) |
| `completeness` | str | Sim | "book", "chapter", ou "verse" |
| `normalized_text` | str | Não | Texto normalizado que gerou o candidato |

**Garantias:**
- `confidence` está entre 0.40 (apenas livro) e 0.89 (quase completo).
- `completeness` indica o nível de completude da referência.
- `correlation_id` é o mesmo do `SpeechPartial` que originou a detecção.
- `verse_start` é 0 quando `completeness` é "book" ou "chapter".

**Idempotência:** Não é idempotente. Múltiplos `ReferenceCandidate` podem ser publicados para o mesmo fluxo conforme a confiança cresce.

**Exemplo positivo:** "Primeiro Coríntios" detectado com confidence 0.40, completeness="book".
**Exemplo negativo:** Publicar `ReferenceCandidate` com confidence 0.98 (deveria ser `ReferenceDetected`).

---

### ReferenceDetected

| Campo | Valor |
|---|---|
| **Nome** | `ReferenceDetected` |
| **Descrição** | Referência bíblica detectada e validada. Evento definitivo que dispara apresentação. |
| **Publisher primário** | `IncrementalBiblicalParser` (via `_publish_detected`) |
| **Publisher secundário** | `ReferenceResolver` (a partir de `IntentCandidate` do LLM, após validação lexical CAP-06) |
| **Publisher terciário** | `StateOrchestrator` (CAP-02: completar referência cross-segmento) |
| **Nota Sprint 28 (Fase 9)** | `BiblicalNLUService` não é mais publisher — desativado por padrão (`enabled=False`). O parser incremental é o único caminho de parsing. |
| **Subscribers** | `VersePresentationService`, `StateOrchestrator` (CAP-01), `SermonMemoryEngine` |
| **Quando é publicado** | Quando uma referência bíblica é completamente identificada com confiança >= 0.90 (parser) ou validada via Searcher (resolver). |
| **Quando NÃO deve ser publicado** | Se a referência está incompleta (publicar `ReferenceCandidate`). Se a referência é inválida (publicar `ReferenceInvalid`). Se o livro não foi explicitamente mencionado e a fonte é LLM (CAP-06 rejeita). |
| **Predecessores** | `SpeechTranscribed`, `ReferenceCandidate`, ou `IntentCandidate` |
| **Sucessores** | `VerseResolving`, `StateChanged` (PRESENT), `SermonContextUpdated` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `intent` | str | Não | Tipo de intenção (default "OPEN_REFERENCE") |
| `book` | str | Sim | Nome canônico do livro |
| `book_id` | int | Sim | ID do livro |
| `chapter` | int | Sim | Capítulo |
| `verse_start` | int | Sim | Versículo inicial |
| `verse_end` | int | Não | Versículo final (0 se versículo único) |
| `confidence` | float | Sim | Confiança da detecção (>= 0.90 para parser) |
| `raw_text` | str | Não | Texto original que gerou a detecção |
| `normalized_text` | str | Não | Texto normalizado |

**Garantias:**
- `book_id` é não-zero.
- `chapter` é não-zero.
- `verse_start` é não-zero.
- `confidence` >= 0.90 quando publicado pelo parser.
- `correlation_id` é o mesmo do evento que originou a detecção.
- O `SemanticEngine` nunca publica este evento diretamente (ADR-004).

**Idempotência:** O `ReferenceResolver` verifica `_parser_already_resolved` antes de publicar, evitando duplicação com o parser.

**CorrelationId:** Preservado do fluxo de fala que originou a detecção.

**Failure semantics:** Se `ReferenceDetected` é publicado mas o versículo não existe no Searcher, `VersePresentationFailed` é publicado com `failure_stage="search"`.

**Exemplo positivo:** "Primeiro Coríntios capítulo 14 versículo 10" com confidence 0.98, book="1 Coríntios", book_id=46, chapter=14, verse_start=10.
**Exemplo negativo:** Publicar `ReferenceDetected` para "igreja de Tessalônica" sem menção explícita de "Tessalonicenses" (violaria CAP-06).

---

### ReferenceInvalid

| Campo | Valor |
|---|---|
| **Nome** | `ReferenceInvalid` |
| **Descrição** | Referência bíblica inválida detectada pelo parser. **Sprint 28 (Fase 9)**: `BiblicalNLUService` desativado por padrão; evento só é publicado em modo de compatibilidade (`enabled=True`). |
| **Publisher** | `BiblicalNLUService` (via `_publish_invalid` — apenas com `enabled=True`) |
| **Subscribers** | `StateOrchestrator` (CAP-01), componentes de telemetria |
| **Quando é publicado** | Quando o parser identifica um livro mas capítulo/versículo são inválidos. |
| **Quando NÃO deve ser publicado** | Se a referência é válida (publicar `ReferenceDetected`). Se nenhum livro foi identificado (publicar `IntentUnknown`). |
| **Predecessores** | `SpeechTranscribed` |
| **Sucessores** | `StateChanged` (WAIT ou IGNORE) |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `book` | str | Sim | Nome do livro identificado |
| `book_id` | int | Sim | ID do livro |
| `chapter` | int | Não | Capítulo inválido |
| `verse_start` | int | Não | Versículo inválido |
| `reason` | str | Sim | "invalid_chapter", "invalid_verse", "zero_chapter" |
| `raw_text` | str | Não | Texto original |

---

### IntentUnknown

| Campo | Valor |
|---|---|
| **Nome** | `IntentUnknown` |
| **Descrição** | Intenção não reconhecida pelo parser. **Sprint 28 (Fase 9)**: `BiblicalNLUService` desativado por padrão; evento só é publicado em modo de compatibilidade (`enabled=True`). |
| **Publisher** | `BiblicalNLUService` (via `_publish_unknown` — apenas com `enabled=True`) |
| **Subscribers** | `StateOrchestrator` (CAP-01), componentes de telemetria |
| **Quando é publicado** | Quando o parser não identifica nem referência nem navegação nem gatilhos bíblicos. |
| **Quando NÃO deve ser publicado** | Se uma referência foi detectada (publicar `ReferenceDetected` ou `ReferenceInvalid`). |
| **Predecessores** | `SpeechTranscribed` |
| **Sucessores** | `StateChanged` (WAIT ou IGNORE) |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `raw_text` | str | Não | Texto que não foi reconhecido |
| `reason` | str | Sim | "no_book", "no_pattern", "empty_text", "navigation_not_supported", "uncertain" |

---

### ReferenceAntecipada

| Campo | Valor |
|---|---|
| **Nome** | `ReferenceAntecipada` |
| **Descrição** | Referência bíblica antecipada detectada durante a fala (antes do silêncio fechar o segmento). |
| **Publisher** | `IncrementalBiblicalParser` |
| **Subscribers** | `VersePresentationService` |
| **Quando é publicado** | Quando confiança está entre `anticipation_threshold` e `detection_threshold`, e `completeness >= "chapter"`. |
| **Quando NÃO deve ser publicado** | Se `completeness == "book"` (muito incerto). Se confiança atingiu `detection_threshold` (publicar `ReferenceDetected`). |
| **Predecessores** | `SpeechPartial` ou `SpeechPartialUpdated` |
| **Sucessores** | `VersePresented` (apresentação antecipada), `ReferenceDetected` (confirmação ou correção) |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `book` | str | Sim | Nome canônico do livro |
| `book_id` | int | Sim | ID do livro |
| `chapter` | int | Sim | Capítulo |
| `verse_start` | int | Não | Versículo (0 se não identificado) |
| `verse_end` | int | Não | Versículo final |
| `confidence` | float | Sim | Confiança (entre anticipation e detection thresholds) |
| `completeness` | str | Sim | "chapter" ou "verse" |
| `normalized_text` | str | Não | Texto normalizado |

**Garantias:**
- `completeness` é sempre "chapter" ou "verse", nunca "book".
- Pode ser confirmada por `ReferenceDetected` posterior com mesmo `correlation_id`.
- Pode ser corrigida por `ReferenceDetected` posterior com mesmo `correlation_id` mas referência diferente.

---

### NavigationCommandDetected

| Campo | Valor |
|---|---|
| **Nome** | `NavigationCommandDetected` |
| **Descrição** | Comando de navegação por voz detectado em `SpeechCommittedWords` (Sprint 28 — Fase 8). |
| **Publisher** | `VersionCommandDetector` |
| **Subscribers** | `ReadingFollowService` (executa retrocesso/avanço/pulo) |
| **Quando é publicado** | Quando o detector identifica comandos como "verso anterior", "volta", "pula", "próximo verso", "capítulo N", "versículo N" com confiança >= 0.90 (0.85 para goto). |
| **Quando NÃO deve ser publicado** | Durante leitura normal (threshold alto evita falsos positivos). Se texto vazio. |
| **Predecessores** | `SpeechCommittedWords` |
| **Sucessores** | `ReadingFollowAdvanced` (reason="voice_command_back"/"voice_command_forward"/"voice_command_goto") |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `command` | str | Sim | "back", "forward", "goto_chapter", "goto_verse" |
| `target_value` | int | Não | N para "capítulo N" / "versículo N" (0 para back/forward) |
| `raw_text` | str | Não | Texto original que disparou o comando |
| `confidence` | float | Sim | Score do fuzzy match (>= 0.90 para back/forward, >= 0.85 para goto) |

**Garantias:**
- `command` é um dos quatro valores canônicos.
- `confidence` >= 0.90 para comandos de retrocesso/avanço.
- `confidence` >= 0.85 para comandos de pulo (goto_chapter/goto_verse).
- Threshold alto evita falsos positivos durante leitura normal.
- `correlation_id` é o mesmo do `SpeechCommittedWords` que originou o comando.

**Comandos suportados (§15.4):**

| Comando (PT-BR) | Ação | Confiança mínima |
|---|---|---|
| "verso anterior" / "versículo anterior" | Retrocede 1 versículo | 0.90 |
| "volta" / "voltar" | Retrocede 1 versículo | 0.90 |
| "próximo verso" / "próximo versículo" | Avança 1 versículo | 0.90 |
| "pula" / "pular" | Avança 1 versículo | 0.90 |
| "capítulo N" | Pula para capítulo N, versículo 1 | 0.85 |
| "versículo N" | Pula para versículo N do capítulo atual | 0.85 |

---

### ReadingFollowAdvanced

| Campo | Valor |
|---|---|
| **Nome** | `ReadingFollowAdvanced` |
| **Descrição** | Reading Follow avançou para um novo versículo durante leitura contínua (Sprint 28 — Fases 7/8). |
| **Publisher** | `ReadingFollowService` |
| **Subscribers** | Componentes de telemetria, UI (para acompanhar leitura) |
| **Quando é publicado** | Quando o fuzzy match atinge threshold adaptativo em `SpeechCommittedWords`, ou quando comando de voz navega. |
| **Quando NÃO deve ser publicado** | Se Reading Follow inativo. Se buffer < 5 palavras. |
| **Predecessores** | `SpeechCommittedWords` (fuzzy match) ou `NavigationCommandDetected` (comando de voz) |
| **Sucessores** | `VersePresented` (apresentação do novo versículo) |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `book` | str | Sim | Nome do livro |
| `book_id` | int | Sim | ID do livro |
| `chapter` | int | Sim | Capítulo |
| `verse` | int | Sim | Novo versículo apresentado |
| `reason` | str | Sim | "fuzzy_match", "voice_command_forward", "voice_command_back", "voice_command_goto" |
| `confidence` | float | Não | Score do fuzzy match (0 se comando de voz) |

**Garantias:**
- `reason` é um dos quatro valores canônicos.
- `verse` está dentro do range ativo `[verse_start, verse_end]`.
- Threshold adaptativo: `< 30` palavras → `0.65`; `30-79` → `0.70`; `>= 80` → `0.75`.
- Buffer resetado após avanço.
- `correlation_id` é o mesmo do `SpeechCommittedWords` ou `NavigationCommandDetected`.

---

## Eventos de Apresentação

### VerseResolving

| Campo | Valor |
|---|---|
| **Nome** | `VerseResolving` |
| **Descrição** | VersePresentationService iniciou resolução da referência no Searcher. |
| **Publisher** | `VersePresentationService` |
| **Subscribers** | Componentes de telemetria |
| **Quando é publicado** | Quando o serviço recebe `ReferenceDetected` e começa a buscar. |
| **Predecessores** | `ReferenceDetected` ou `ReferenceAntecipada` |
| **Sucessores** | `VerseResolved` ou `VersePresentationFailed` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `book` | str | Sim | Nome do livro |
| `book_id` | int | Sim | ID do livro |
| `chapter` | int | Sim | Capítulo |
| `verse_start` | int | Não | Versículo inicial |
| `verse_end` | int | Não | Versículo final |
| `normalized_text` | str | Não | Texto normalizado |

---

### VerseResolved

| Campo | Valor |
|---|---|
| **Nome** | `VerseResolved` |
| **Descrição** | Searcher retornou o versículo resolvido com texto. |
| **Publisher** | `VersePresentationService` |
| **Subscribers** | Componentes de telemetria |
| **Predecessores** | `VerseResolving` |
| **Sucessores** | `VersePresented` ou `VersePresentationFailed` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `book` | str | Sim | Nome do livro |
| `book_id` | int | Sim | ID do livro |
| `chapter` | int | Sim | Capítulo |
| `verse` | int | Sim | Versículo |
| `version` | str | Sim | Versão bíblica |
| `verse_text` | str | Sim | Texto do versículo |
| `reference` | str | Sim | Referência formatada (ex.: "João 10:27") |
| `search_ms` | int | Não | Latência de busca |

---

### VersePresented

| Campo | Valor |
|---|---|
| **Nome** | `VersePresented` |
| **Descrição** | HolyricsClient.show_verse() executou com sucesso. |
| **Publisher** | `VersePresentationService` |
| **Subscribers** | `SermonMemoryEngine`, componentes de telemetria, `StateOrchestrator` (CAP-07: atualiza `last_presented_reference`) |
| **Quando é publicado** | Após o Holyrics confirmar a apresentação do versículo. |
| **Quando NÃO deve ser publicado** | Se o Holyrics falhou (publicar `VersePresentationFailed`). Se `repeat=true` em `StateChanged` (CAP-07: apresentação suprimida). |
| **Predecessores** | `VerseResolved` |
| **Sucessores** | Nenhum (evento terminal de apresentação) |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `book` | str | Sim | Nome do livro |
| `book_id` | int | Sim | ID do livro |
| `chapter` | int | Sim | Capítulo |
| `verse` | int | Sim | Versículo |
| `version` | str | Sim | Versão bíblica |
| `reference` | str | Sim | Referência formatada |
| `quick_presentation` | bool | Não | True se foi apresentação antecipada confirmada |
| `holyrics_status` | str | Sim | Status retornado pelo Holyrics |
| `holyrics_latency_ms` | int | Não | Latência da chamada ao Holyrics |
| `total_latency_ms` | int | Não | Latência total (ReferenceDetected até ShowVerse) |

**Garantias:**
- `book_id`, `chapter`, `verse` são não-zero.
- `reference` é uma string não-vazia.
- `holyrics_status` indica sucesso.

**Exemplo positivo:** João 10:27 apresentado com holyrics_status="ok", total_latency_ms=450.
**Exemplo negativo:** Publicar `VersePresented` sem `ReferenceDetected` predecessor (fluxo inválido).

---

### VersePresentationFailed

| Campo | Valor |
|---|---|
| **Nome** | `VersePresentationFailed` |
| **Descrição** | Falha em qualquer etapa da apresentação do versículo. |
| **Publisher** | `VersePresentationService` |
| **Subscribers** | Componentes de telemetria |
| **Quando é publicado** | Quando Searcher não encontra o versículo, Holyrics falha, ou erro interno. |
| **Predecessores** | `VerseResolving` ou `VerseResolved` |
| **Sucessores** | Nenhum (evento terminal de falha) |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `book` | str | Não | Nome do livro |
| `book_id` | int | Não | ID do livro |
| `chapter` | int | Não | Capítulo |
| `verse` | int | Não | Versículo |
| `reference` | str | Não | Referência formatada |
| `failure_stage` | str | Sim | "search", "holyrics", "internal" |
| `error_type` | str | Sim | "book_not_found", "verse_not_found", "connection", "timeout", "auth", "api", "internal_error" |
| `error_message` | str | Sim | Mensagem de erro |
| `latency_ms` | int | Não | Latência até a falha |

**Garantias:** Não altera o Health do componente Holyrics. Falhas pontuais não significam indisponibilidade.

**Failure semantics:** O pipeline continua. O versículo não é apresentado. O operador pode intervir manualmente.

---

## Eventos Semânticos

### IntentCandidate

| Campo | Valor |
|---|---|
| **Nome** | `IntentCandidate` |
| **Descrição** | Candidatos semânticos gerados pelo SemanticEngine (LLM). Hipótese, não definitivo. |
| **Publisher** | `SemanticEngine` |
| **Publisher secundário** | Nenhum (apenas o SemanticEngine publica) |
| **Subscribers** | `ReferenceResolver` |
| **Quando é publicado** | Quando o SemanticProvider (LLM) identifica possíveis referências implícitas a partir de `SpeechPartial`/`SpeechPartialUpdated`. |
| **Quando NÃO deve ser publicado** | Se o provider está indisponível (publicar `SemanticProviderUnavailable`). Se o texto é vazio. |
| **Predecessores** | `SpeechPartial` ou `SpeechPartialUpdated` |
| **Sucessores** | `ReferenceDetected` (se aceito pelo resolver), `IntentRejected` (se rejeitado por CAP-06), `SemanticResolutionCompleted` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `intent` | str | Não | "show_reference" ou "none" |
| `candidates_json` | str | Sim | JSON serializado de SemanticCandidate[] |
| `inference_ms` | int | Não | Tempo de inferência do LLM |
| `provider` | str | Não | "local-llm", "stub", "openai", etc. |
| `model` | str | Não | "llama3.2:3b", etc. |
| `context_hash` | str | Não | Hash do contexto (para dedup de cache) |
| `cached` | bool | Não | True se veio do cache |

**Garantias:**
- O SemanticEngine NUNCA publica `ReferenceDetected` diretamente (ADR-004).
- `candidates_json` contém pelo menos um candidato quando `intent="show_reference"`.
- `correlation_id` é o mesmo do `SpeechPartial` que originou a análise.

**Idempotência:** Se `cached=true`, o mesmo `candidates_json` pode ser produzido para o mesmo `context_hash`.

**Exemplo positivo:** LLM sugere "1 Coríntios 14:10" a partir de "Primeiro Coríntios capítulo 14 versículo 10" (livro explícito no texto).
**Exemplo negativo:** LLM sugere "1 Tessalonicenses 5:23" a partir de "igreja de Tessalônica" (será rejeitado por CAP-06).

---

### SemanticInferenceCompleted

| Campo | Valor |
|---|---|
| **Nome** | `SemanticInferenceCompleted` |
| **Descrição** | Telemetria da inferência semântica. |
| **Publisher** | `SemanticEngine` |
| **Subscribers** | Componentes de telemetria e depuração |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `intent` | str | Não | Intenção identificada |
| `num_candidates` | int | Não | Número de candidatos gerados |
| `inference_ms` | int | Não | Tempo de inferência |
| `provider` | str | Não | Provider usado |
| `model` | str | Não | Modelo usado |
| `cached` | bool | Não | True se veio do cache |
| `error` | str | Não | "" se sucesso, mensagem se falha |
| `context_text` | str | Não | Texto analisado (para depuração) |
| `context_hash` | str | Não | Hash do contexto |

---

### SemanticResolutionCompleted

| Campo | Valor |
|---|---|
| **Nome** | `SemanticResolutionCompleted` |
| **Descrição** | Resultado da resolução semântica pelo ReferenceResolver. |
| **Publisher** | `ReferenceResolver` |
| **Subscribers** | Componentes de telemetria e depuração |
| **Predecessores** | `IntentCandidate` |
| **Sucessores** | `ReferenceDetected` (se resolvido) ou nenhum (se não resolvido) |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `resolved` | bool | Sim | True se `ReferenceDetected` foi publicado |
| `chosen_book` | str | Não | Livro escolhido |
| `chosen_chapter` | int | Não | Capítulo escolhido |
| `chosen_verse` | int | Não | Versículo escolhido |
| `chosen_confidence` | float | Não | Confiança do escolhido |
| `reason` | str | Sim | "highest_confidence", "all_invalid", "parser_already_resolved", "no_lexical_match" |
| `num_candidates_in` | int | Não | Candidatos recebidos |
| `num_candidates_valid` | int | Não | Candidatos válidos após Searcher |
| `skipped_due_to_parser` | bool | Não | True se parser já resolveu |

---

### SemanticProviderUnavailable

| Campo | Valor |
|---|---|
| **Nome** | `SemanticProviderUnavailable` |
| **Descrição** | Provider semântico indisponível. Sistema continua operacional sem camada semântica. |
| **Publisher** | `SemanticEngine` |
| **Subscribers** | Componentes de telemetria, UI (para indicar modo degradado) |
| **Quando é publicado** | Quando o SemanticEngine não consegue validar o provider LLM. |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `provider` | str | Sim | "ollama", "stub", etc. |
| `model` | str | Não | Modelo esperado |
| `reason` | str | Sim | "server_offline", "model_not_found", etc. |
| `base_url` | str | Não | URL consultada |

**Garantias:** O `IncrementalBiblicalParser` e o restante do pipeline NÃO são afetados.

---

## Eventos de Contexto do Sermão

### SermonContextUpdated

| Campo | Valor |
|---|---|
| **Nome** | `SermonContextUpdated` |
| **Descrição** | Contexto do sermão atualizado. Snapshot serializado do contexto vivo. |
| **Publisher** | `SermonMemoryEngine` |
| **Subscribers** | `SemanticEngine` (para enriquecer contexto enviado ao LLM) |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `context_json` | str | Sim | JSON serializado de SermonContext.to_dict() |
| `current_book` | str | Não | Livro atual (vazio se None) |
| `current_chapter` | int | Não | Capítulo atual (0 se None) |
| `probable_theme` | str | Não | Tema provável |
| `num_entities` | int | Não | Número de entidades |
| `num_topics` | int | Não | Número de temas |
| `num_references` | int | Não | Número de referências recentes |
| `confidence` | float | Não | Confiança geral |
| `total_updates` | int | Não | Total de atualizações |
| `is_empty` | bool | Não | True se contexto vazio |

---

### SermonBookChanged

| Campo | Valor |
|---|---|
| **Nome** | `SermonBookChanged` |
| **Descrição** | Livro atual do sermão mudou. |
| **Publisher** | `SermonMemoryEngine` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `previous_book` | str | Não | Livro anterior |
| `new_book` | str | Sim | Novo livro |
| `confidence` | float | Não | Confiança da mudança |

---

### SermonChapterChanged

| Campo | Valor |
|---|---|
| **Nome** | `SermonChapterChanged` |
| **Descrição** | Capítulo atual do sermão mudou dentro do mesmo livro. |
| **Publisher** | `SermonMemoryEngine` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `book` | str | Sim | Livro |
| `previous_chapter` | int | Não | Capítulo anterior |
| `new_chapter` | int | Sim | Novo capítulo |

---

### SermonTopicChanged

| Campo | Valor |
|---|---|
| **Nome** | `SermonTopicChanged` |
| **Descrição** | Tema provável do sermão mudou. |
| **Publisher** | `SermonMemoryEngine` |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `previous_theme` | str | Não | Tema anterior |
| `new_theme` | str | Sim | Novo tema |
| `confidence` | float | Não | Confiança da mudança |

---

## Eventos dos RFCs

Estes eventos são definidos pelos RFCs CAP-01 a CAP-07. **Sprint 28**: `StateChanged` e `StateOrchestrator` já estão implementados (Fase 5). Os demais permanecem como contratos formais para implementação futura.

### StateChanged

| Campo | Valor |
|---|---|
| **Nome** | `StateChanged` |
| **Descrição** | Transição de estado do sistema (WAIT, PREPARE, PRESENT, IGNORE). |
| **Publisher** | `StateOrchestrator` (CAP-01) |
| **Publisher secundário** | Nenhum (apenas o orquestrador publica) |
| **Subscribers** | `VersePresentationService` (CAP-07: para respeitar `repeat`), componentes de telemetria, Replay engine |
| **Quando é publicado** | Quando o sistema transita entre estados da máquina de estados. |
| **Quando NÃO deve ser publicado** | Se o estado não mudou (mesmo estado). Se o pipeline está pausado. |
| **Predecessores** | `ReferenceCandidate`, `ReferenceDetected`, `IntentUnknown`, `IntentClassified`, `SpeechTranscribed` |
| **Sucessores** | Depende do estado: `VersePresented` (PRESENT), nenhum (WAIT, PREPARE, IGNORE) |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `from_state` | str | Sim | Estado anterior ("WAIT", "PREPARE", "PRESENT", "IGNORE") |
| `to_state` | str | Sim | Novo estado ("WAIT", "PREPARE", "PRESENT", "IGNORE") |
| `reason` | str | Sim | Motivo da transição (ver valores abaixo) |
| `repeat` | bool | Não | True se é re-citação (CAP-07). Default false. |
| `detail` | str | Não | Informação adicional sobre a transição |
| `active_book` | str | Não | Livro ativo após transição |
| `active_chapter` | int | Não | Capítulo ativo após transição |
| `pending_reference` | str | Não | Referência pendente (em PREPARE) |

**Valores de `reason`:**

| Reason | De | Para | Descrição |
|---|---|---|---|
| `book_detected` | WAIT | PREPARE | Livro identificado sem capítulo/versículo |
| `chapter_detected` | PREPARE | PREPARE | Capítulo identificado, versículo pendente |
| `reference_complete` | WAIT/PREPARE | PRESENT | Referência completa detectada |
| `repeat` | WAIT/PREPARE | PRESENT | Re-citação de referência já apresentada (CAP-07) |
| `first` | WAIT/PREPARE | PRESENT | Primeira apresentação de referência (CAP-07) |
| `prepare_expired` | PREPARE | WAIT | Expiração por mudança de assunto ou timeout (CAP-05) |
| `no_reference` | WAIT | WAIT | Segmento sem referência (sem transição real) |
| `narrative_mention` | WAIT | IGNORE | Menção narrativa ignorada (CAP-03) |
| `invalid_reference` | PREPARE | WAIT | Referência inválida detectada |
| `segment_ignored` | any | IGNORE | Segmento sem conteúdo bíblico |

**Garantias:**
- `from_state != to_state` (exceto quando `reason="no_reference"` que é um noop).
- `reason` é sempre não-vazio.
- `repeat=true` só ocorre quando `to_state="PRESENT"`.
- `correlation_id` é o mesmo do evento que causou a transição.

**Idempotência:** Não é idempotente. Cada transição publica um evento.

**Versionamento:** v1. Campo `repeat` adicionado em v1.1 (CAP-07).

**Exemplo JSON:**
```json
{
  "event_type": "StateChanged",
  "meta": {
    "event_id": "evt-042",
    "correlation_id": "corr-001",
    "causation_id": "evt-041",
    "session_id": "sess-001",
    "timestamp": 1756342810.0,
    "origin": "StateOrchestrator"
  },
  "from_state": "WAIT",
  "to_state": "PREPARE",
  "reason": "book_detected",
  "repeat": false,
  "detail": "book=1 Coríntios, completeness=book",
  "active_book": "1 Coríntios",
  "active_chapter": 0,
  "pending_reference": "1 Coríntios"
}
```

**Exemplo positivo:** WAIT → PREPARE com reason="book_detected" ao detectar "Primeiro Coríntios".
**Exemplo negativo:** Publicar `StateChanged` com `from_state=PRESENT` e `to_state=PREPARE` sem passar por WAIT (fluxo inválido).

---

### IntentClassified

| Campo | Valor |
|---|---|
| **Nome** | `IntentClassified` |
| **Descrição** | Classificação da intenção do pregador ao mencionar um livro (CAP-03). |
| **Publisher** | `StateOrchestrator` (CAP-03: IntentClassifier interno) |
| **Subscribers** | Componentes de telemetria, `StateOrchestrator` (para decidir PREPARE vs IGNORE) |
| **Quando é publicado** | Quando um livro bíblico é detectado no texto e a intenção é classificada. |
| **Quando NÃO deve ser publicado** | Se nenhum livro foi detectado. Se o texto é vazio. |
| **Predecessores** | `SpeechTranscribed` ou `ReferenceCandidate` |
| **Sucessores** | `StateChanged` (PREPARE se OPEN_REQUEST/ACTIVE_CITATION, IGNORE se NARRATIVE_MENTION) |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `book` | str | Sim | Livro mencionado |
| `book_id` | int | Sim | ID do livro |
| `intent_type` | str | Sim | "OPEN_REQUEST", "ACTIVE_CITATION", "NARRATIVE_MENTION" |
| `trigger_phrase` | str | Não | Frase de gatilho identificada (ex.: "abra comigo") |
| `confidence` | float | Sim | Confiança da classificação (0.0 a 1.0) |
| `raw_text` | str | Não | Texto que gerou a classificação |

**Garantias:**
- `intent_type` é um dos três valores canônicos.
- `confidence` >= 0.60 para OPEN_REQUEST (padrões lexicais).
- `confidence` >= 0.50 para NARRATIVE_MENTION (ausência de gatilho).

---

### IntentRejected

| Campo | Valor |
|---|---|
| **Nome** | `IntentRejected` |
| **Descrição** | IntentCandidate do LLM rejeitado pelo guardão conservador (CAP-06). |
| **Publisher** | `ReferenceResolver` (após validação lexical CAP-06) |
| **Subscribers** | Componentes de telemetria e auditoria |
| **Quando é publicado** | Quando o `IntentCandidate` não tem correspondência lexical do livro no texto transcrito. |
| **Quando NÃO deve ser publicado** | Se o `IntentCandidate` foi aceito (publicar `ReferenceDetected`). Se o parser já resolveu (publicar `SemanticResolutionCompleted` com `skipped_due_to_parser=true`). |
| **Predecessores** | `IntentCandidate` |
| **Sucessores** | Nenhum (evento terminal de rejeição) |
| **Categoria** | Operational |

**Payload:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `meta` | EventMetadata | Sim | |
| `reason` | str | Sim | "no_lexical_match", "book_mismatch", "no_verse_match", "no_book_in_candidate", "no_book_id" |
| `candidate_book` | str | Não | Livro sugerido pelo LLM |
| `candidate_chapter` | int | Não | Capítulo sugerido |
| `candidate_verse` | int | Não | Versículo sugerido |
| `raw_text` | str | Não | Texto transcrito que não continha o livro |
| `correlation_id` | str | Sim | Mesmo correlation_id do IntentCandidate |

**Garantias:**
- Nenhum `ReferenceDetected` é publicado após `IntentRejected`.
- `reason` é sempre não-vazio.
- `correlation_id` é o mesmo do `IntentCandidate` rejeitado.

**Idempotência:** Cada `IntentCandidate` rejeitado produz exatamente um `IntentRejected`.

**Exemplo positivo:** LLM sugere "1 Tessalonicenses 5:23" a partir de "igreja de Tessalônica". Rejeitado com reason="no_lexical_match".
**Exemplo negativo:** Publicar `IntentRejected` para um `IntentCandidate` onde "Tessalonicenses" está explicitamente no texto (deveria ser aceito).

---

## Sequências Oficiais

### Fluxo Principal (Streaming First — Sprint 28)

```
SpeechStarted
    ↓
SpeechPartial
    ↓
SpeechPartialUpdated (múltiplos)
    ↓
SpeechCommittedWords (LocalAgreement-2 confirma palavras — fluxo operacional primário)
    ↓
    ├─→ IncrementalBiblicalParser
    │       ↓
    │   ReferenceCandidate (confiança crescente)
    │       ↓
    │   ReferenceAntecipada (anticipation_threshold <= confidence < detection_threshold)
    │       ↓
    │   VersePresented (apresentação antecipada)
    │       ↓
    │   ReferenceDetected (quando confidence >= 0.90)
    │       ↓
    │   StateChanged (WAIT → PREPARE → PRESENT)
    │       ↓
    │   VerseResolving → VerseResolved → VersePresented
    │
    ├─→ SemanticEngine
    │       ↓
    │   IntentCandidate
    │       ↓
    │   ReferenceResolver
    │       ↓
    │   ├─→ ReferenceDetected (se aceito e validado)
    │   │       ↓
    │   │   StateChanged (PRESENT)
    │   │       ↓
    │   │   VerseResolving → VerseResolved → VersePresented
    │   │
    │   ├─→ IntentRejected (se rejeitado por CAP-06)
    │   │
    │   └─→ SemanticResolutionCompleted (telemetria)
    │
    ├─→ ReadingFollowService (se Reading Follow ativo)
    │       ↓
    │   ReadingFollowAdvanced (fuzzy_match em committed words)
    │       ↓
    │   VersePresented
    │
    └─→ VersionCommandDetector
            ↓
        NavigationCommandDetected (comando de voz)
            ↓
        ReadingFollowAdvanced (voice_command_*)
            ↓
        VersePresented
```

### Fluxo de Finalização (Sprint 28 — Fase 9/10)

```
[VAD fecha segmento]
    ↓
SpeechEnded
    ↓
SpeechTranscribed (corr_id = mesmo do SpeechPartial — Fase 10)
    ↓
    ├─→ StateOrchestrator (confirma/corrige/limpa estado)
    ├─→ ReadingFollowService (fallback se committed words não avançaram)
    ├─→ VersionCommandDetector (mudança de versão)
    └─→ Frontend (exibe transcrição final)
    
[Nota: BiblicalNLUService NÃO consome — desativado por padrão (Fase 9)]
```

### Fluxo de Referência Incompleta (PREPARE — Sprint 28)

```
SpeechCommittedWords
    ↓
ReferenceCandidate (completeness="book", confidence=0.40)
    ↓
StateChanged (WAIT → PREPARE, reason="book_detected")
    ↓
[mais committed words no mesmo fluxo]
    ↓
SpeechCommittedWords (capítulo e versículo completam)
    ↓
ReferenceDetected (confidence >= 0.90)
    ↓
StateChanged (PREPARE → PRESENT, reason="reference_complete")
    ↓
VerseResolving → VerseResolved → VersePresented
```

### Fluxo de Expiração (CAP-05)

```
StateChanged (WAIT → PREPARE, reason="book_detected")
    ↓
[novo livro detectado ou timeout de segmentos]
    ↓
StateChanged (PREPARE → WAIT, reason="prepare_expired")
    ↓
[active_book, active_chapter, pending_reference limpos]
```

### Fluxo de Repeat (CAP-07)

```
ReferenceDetected (1 Cor 14:10)
    ↓
StateChanged (WAIT → PRESENT, reason="first", repeat=false)
    ↓
VersePresented
    ↓
[mais tarde, mesma referência]
    ↓
ReferenceDetected (1 Cor 14:10 novamente)
    ↓
StateChanged (→ PRESENT, reason="repeat", repeat=true)
    ↓
[VersePresentationService suprime re-apresentação]
```

### Fluxo de Menção Narrativa (CAP-03 — Sprint 28)

```
SpeechCommittedWords ("pregava ontem sobre Gênesis")
    ↓
IntentClassified (intent_type="NARRATIVE_MENTION")
    ↓
StateChanged (WAIT → IGNORE, reason="narrative_mention")
    ↓
[nenhum ReferenceDetected, nenhum VersePresented]
```

### Fluxo de Inferência Rejeitada (CAP-06 — Sprint 28)

```
SpeechCommittedWords ("igreja de Tessalônica")
    ↓
SemanticEngine
    ↓
IntentCandidate (LLM sugere 1 Tess 5:23)
    ↓
ReferenceResolver (validação lexical CAP-06)
    ↓
IntentRejected (reason="no_lexical_match")
    ↓
[nenhum ReferenceDetected, nenhum VersePresented]
```

### Fluxo de Pipeline Linear (Legacy, não-streaming)

```
SpeechSegmentReceived
    ↓
SpeechRecognized
    ↓
SearchRequested → SearchCompleted
    ↓
RankingCompleted
    ↓
IntelligenceCompleted
    ↓
PresentationRequested → PresentationCompleted
    ↓
FeedbackRecorded
    ↓
EvaluationRecorded
```

---

## Invalid Event Flows

Fluxos proibidos. Se qualquer um destes padrões é observado, é um bug.

### 1. ReferenceDetected sem StateChanged

```
ReferenceDetected
    ↓
VersePresented
```

**Sem `StateChanged` no meio.** Todo `ReferenceDetected` deve causar uma transição de estado PUBLICADA antes de `VersePresented`.

### 2. VersePresented sem PRESENT

```
VersePresented
```

**Sem `StateChanged` com `to_state=PRESENT` predecessor.** A apresentação só pode ocorrer após o sistema estar em PRESENT.

### 3. SemanticEngine publica ReferenceDetected diretamente

```
SemanticEngine
    ↓
ReferenceDetected
```

**Sem `IntentCandidate` e `ReferenceResolver` no meio.** O LLM nunca publica `ReferenceDetected` (ADR-004).

### 4. PRESENT → PREPARE sem WAIT

```
StateChanged (→ PRESENT)
    ↓
StateChanged (PRESENT → PREPARE)
```

**Sem passar por WAIT.** A máquina de estados não permite PRESENT → PREPARE diretamente. O fluxo correto é PRESENT → WAIT → PREPARE.

### 5. Dois ReferenceDetected para a mesma referência sem dedup

```
ReferenceDetected (1 Cor 14:10, source=parser)
    ↓
ReferenceDetected (1 Cor 14:10, source=resolver)
```

**Sem `_parser_already_resolved` verificar.** O resolver deve verificar se o parser já resolveu antes de publicar.

### 6. IntentRejected seguido de ReferenceDetected

```
IntentRejected (reason="no_lexical_match")
    ↓
ReferenceDetected (mesma referência)
```

**Após rejeitar, a referência não pode ser apresentada.** `IntentRejected` é terminal.

### 7. StateChanged sem reason

```
StateChanged (from_state=WAIT, to_state=PREPARE, reason="")
```

**`reason` é obrigatório.** Toda transição tem um motivo.

### 8. ReferenceCandidate com verse_start e completeness="book"

```
ReferenceCandidate (completeness="book", verse_start=10)
```

**`verse_start` deve ser 0 quando `completeness` é "book".** Não há versículo antes do capítulo.

### 9. StateChanged com repeat=true e to_state != PRESENT

```
StateChanged (to_state=PREPARE, repeat=true)
```

**`repeat=true` só é válido quando `to_state=PRESENT`.** Repeat é uma re-citação, que é uma apresentação.

### 10. VersePresented sem ReferenceDetected ou ReferenceAntecipada

```
VersePresented
```

**Sem predecessor de referência.** Toda apresentação origina-se de uma detecção.

### 11. PipelineError sem handler_name

```
PipelineError (handler_name="")
```

**`handler_name` é obrigatório.** Toda erro tem um handler de origem.

### 12. SermonContextUpdated sem SpeechTranscribed predecessor

```
SermonContextUpdated
```

**Sem fala transcrita.** O contexto só é atualizado em resposta a fala ou referência detectada.

---

## Event Invariants

Invariantes que devem ser verdade em TODO momento. Violação de qualquer invariante é um bug.

1. **Todo evento possui `meta: EventMetadata` não-null.**
2. **Todo `EventMetadata` possui `event_id` único.**
3. **Todo `EventMetadata` possui `correlation_id` não-vazio.**
4. **Todo `ReferenceDetected` possui `correlation_id`.**
5. **Todo `ReferenceDetected` possui `book_id` não-zero.**
6. **Todo `ReferenceDetected` possui `chapter` não-zero.**
7. **Todo `ReferenceDetected` possui `verse_start` não-zero.**
8. **Todo `StateChanged` possui `reason` não-vazio.**
9. **Todo `StateChanged` possui `from_state` e `to_state` em {WAIT, PREPARE, PRESENT, IGNORE}.**
10. **`repeat=true` em `StateChanged` só ocorre quando `to_state=PRESENT`.**
11. **Todo `VersePresented` possui `reference` não-vazia.**
12. **Todo `VersePresented` possui `book_id`, `chapter`, `verse` não-zero.**
13. **`ReferenceCandidate` nunca possui `verse_start` obrigatório (pode ser 0).**
14. **`ReferenceCandidate` com `completeness="book"` tem `verse_start=0` e `chapter=0`.**
15. **`ReferenceCandidate` com `completeness="chapter"` tem `verse_start=0`.**
16. **`IntentRejected` nunca gera `ReferenceDetected` ou `VersePresented`.**
17. **`IntentCandidate` nunca é publicado por componente que não seja `SemanticEngine`.**
18. **`ReferenceDetected` nunca é publicado pelo `SemanticEngine` diretamente.**
19. **`StateChanged` nunca é publicado por componente que não seja `StateOrchestrator`.**
20. **Todo `PipelineError` possui `handler_name` não-vazio.**
21. **Todo `IntentClassified` possui `intent_type` em {OPEN_REQUEST, ACTIVE_CITATION, NARRATIVE_MENTION}.**
22. **`SemanticProviderUnavailable` não afeta o `IncrementalBiblicalParser`.**
23. **`correlation_id` é constante dentro de um fluxo de processamento.**
24. **`causation_id` aponta para o `event_id` do evento predecessor na cadeia.**
25. **Eventos `TelemetryEvent` não são persistidos no `EventStore`.**
26. **Eventos `OperationalEvent` são persistidos no `EventStore`.**
27. **`SpeechCommittedWords.correlation_id` é o mesmo do `SpeechPartial` do mesmo fluxo.** (Sprint 28)
28. **`SpeechTranscribed.correlation_id` é o mesmo do `SpeechPartial` do mesmo fluxo.** (Sprint 28 — Fase 10)
29. **`NavigationCommandDetected.command` é um de {"back", "forward", "goto_chapter", "goto_verse"}.** (Sprint 28)
30. **`NavigationCommandDetected.confidence` >= 0.90 para back/forward, >= 0.85 para goto.** (Sprint 28)
31. **`ReadingFollowAdvanced.reason` é um de {"fuzzy_match", "voice_command_forward", "voice_command_back", "voice_command_goto"}.** (Sprint 28)
32. **`BiblicalNLUService` desativado por padrão em produção (`enabled=False`).** (Sprint 28 — Fase 9)
33. **Parser incremental é o único caminho de parsing em produção.** (Sprint 28 — Fase 9)

---

## Event Versioning

### Princípios

1. **Eventos são imutáveis após publicação.** Não há atualização de eventos no EventStore.
2. **Novos campos são opcionais com default.** Adicionar um campo a um evento existente não quebra consumidores antigos, desde que o campo tenha valor default.
3. **Remover campos é breaking change.** Consumidores que dependem do campo removido quebram.
4. **Mudar tipo de campo é breaking change.** `str` para `int`, por exemplo.
5. **Renomear evento é breaking change.** Consumidores inscritos no nome antigo não recebem o novo.

### Estratégia de Evolução

| Tipo de Mudança | Breaking? | Estratégia |
|---|---|---|
| Adicionar campo opcional com default | Não | Adicionar ao final da dataclass com default |
| Adicionar campo obrigatório | Sim | Criar nova versão do evento (ex.: `StateChangedV2`) |
| Remover campo | Sim | Manter campo com default e marcar como deprecated |
| Mudar tipo de campo | Sim | Criar nova versão do evento |
| Mudar publisher | Sim | Coordenar migração de subscribers |
| Mudar semântica de campo | Sim | Criar nova versão do evento |
| Adicionar novo valor de enum | Não | Consumidores devem tratar valores desconhecidos com default |

### Versionamento de Eventos dos RFCs

- `StateChanged`: v1 (CAP-01). v1.1 adiciona `repeat` (CAP-07). Campo `repeat` tem default `false`, então consumidores v1 não quebram.
- `IntentClassified`: v1 (CAP-03).
- `IntentRejected`: v1 (CAP-06).

### Versionamento de Eventos do Sprint 28

- `SpeechCommittedWords`: v1 (Sprint 28 — Fase 1). Novo evento. Fluxo operacional primário.
- `NavigationCommandDetected`: v1 (Sprint 28 — Fase 8). Novo evento.
- `ReadingFollowAdvanced`: v1 (Sprint 28 — Fase 7). v1.1 adiciona `reason` (Fase 8). Campo `reason` tem default `"fuzzy_match"`, então consumidores v1 não quebram.
- `SpeechTranscribed`: v1 (Sprint 16). v2 (Sprint 28 — Fase 9) muda semântica: não dispara mais parsing. v2.1 (Fase 10) propaga `correlation_id` do fluxo streaming ativo.
- `BiblicalNLUService`: desativado por padrão em Sprint 28 (Fase 9). `enabled=True` mantém comportamento legacy para testes.

### Backward Compatibility

Consumidores devem ser resilientes a campos desconhecidos. Se um evento contém um campo que o consumidor não conhece, o consumidor deve ignorar o campo e processar o evento normalmente. Não deve lançar exceção.

---

## Observability

### Persistência no EventStore

| Evento | Persistir? | Justificativa |
|---|---|---|
| `SpeechSegmentReceived` | Sim | Ponto de entrada, rastreabilidade |
| `SpeechRecognized` | Sim | Resultado do STT, auditoria |
| `SpeechTranscribed` | Sim | Texto final, replay |
| `SpeechPartial` | Não | Alta frequência, valor transitório |
| `SpeechPartialUpdated` | Não | Alta frequência, valor transitório |
| `SpeechCommittedWords` | Sim | Sprint 28 — fluxo operacional primário, rastreabilidade |
| `SpeechStarted` | Sim | Início de fluxo de fala |
| `SpeechEnded` | Sim | Fim de fluxo de fala |
| `SpeechSegmentCreated` | Sim | Criação de segmento |
| `SpeechTranscribing` | Não | Evento transitório de progresso |
| `ReferenceCandidate` | Sim | Rastreabilidade de PREPARE |
| `ReferenceDetected` | Sim | Evento crítico, replay, benchmark |
| `ReferenceInvalid` | Sim | Auditoria de referências inválidas |
| `ReferenceAntecipada` | Sim | Rastreabilidade de antecipação |
| `NavigationCommandDetected` | Sim | Sprint 28 — auditoria de comandos de voz |
| `ReadingFollowAdvanced` | Sim | Sprint 28 — rastreabilidade de leitura contínua |
| `IntentUnknown` | Sim | Rastreabilidade de segmentos sem referência |
| `IntentCandidate` | Sim | Auditoria de inferência do LLM |
| `IntentRejected` | Sim | Auditoria de rejeições conservadoras |
| `IntentClassified` | Sim | Rastreabilidade de classificação de intenção |
| `StateChanged` | Sim | Evento crítico, replay, benchmark |
| `VerseResolving` | Não | Evento transitório |
| `VerseResolved` | Não | Evento transitório |
| `VersePresented` | Sim | Evento crítico, auditoria de apresentação |
| `VersePresentationFailed` | Sim | Auditoria de falhas |
| `SemanticInferenceCompleted` | Sim | Telemetria de LLM |
| `SemanticResolutionCompleted` | Sim | Telemetria de resolução |
| `SemanticProviderUnavailable` | Sim | Evento de saúde do sistema |
| `SermonContextUpdated` | Não | Alta frequência, estado derivado |
| `SermonBookChanged` | Sim | Mudança de contexto significativa |
| `SermonChapterChanged` | Sim | Mudança de contexto significativa |
| `SermonTopicChanged` | Sim | Mudança de contexto significativa |
| `PipelineStarted` | Sim | Ciclo de vida |
| `PipelineStopped` | Sim | Ciclo de vida |
| `PipelinePaused` | Sim | Ciclo de vida |
| `PipelineResumed` | Sim | Ciclo de vida |
| `PipelineError` | Sim | Auditoria de erros |
| `SearchRequested` | Sim | Rastreabilidade |
| `SearchCompleted` | Sim | Rastreabilidade |
| `RankingCompleted` | Sim | Rastreabilidade |
| `IntelligenceCompleted` | Sim | Rastreabilidade |
| `PresentationRequested` | Sim | Rastreabilidade |
| `PresentationCompleted` | Sim | Rastreabilidade |
| `FeedbackRecorded` | Sim | Auditoria de feedback |
| `EvaluationRecorded` | Sim | Métricas contínuas |

### Eventos no Replay

O replay do benchmark (ADR-009) consome eventos persistidos para comparar com o `benchmark.yaml`.

| Evento | Entra no Replay? | Justificativa |
|---|---|---|
| `StateChanged` | Sim | Evento crítico do benchmark |
| `ReferenceDetected` | Sim | Evento crítico do benchmark |
| `ReferenceCandidate` | Sim | Rastreabilidade de PREPARE |
| `IntentRejected` | Sim | Rastreabilidade de supressão conservadora |
| `IntentClassified` | Sim | Rastreabilidade de classificação |
| `VersePresented` | Sim | Confirmação de apresentação |
| `SpeechTranscribed` | Sim | Input do benchmark |
| `SpeechCommittedWords` | Sim | Sprint 28 — fluxo operacional primário |
| `NavigationCommandDetected` | Sim | Sprint 28 — auditoria de comandos de voz |
| `ReadingFollowAdvanced` | Sim | Sprint 28 — rastreabilidade de leitura contínua |
| Todos os outros | Não | Não fazem parte do benchmark |

### Eventos no Benchmark

O benchmark valida a sequência de `StateChanged` e `ReferenceDetected`. A correspondência é estrita: todos os campos definidos no benchmark YAML devem ser iguais aos do evento produzido.

### Eventos Descartáveis

Eventos marcados como "Não" na tabela de persistência podem ser descartados após dispatch. Não há necessidade de armazenamento. São úteis apenas para UI em tempo real (ex.: `SpeechPartial` para exibir transcrição ao vivo).

### Telemetria

Eventos de telemetria (`TelemetryEvent`) não são persistidos nem exibidos na Timeline. São dispatchados aos handlers mas não entram no EventStore. Exemplos: `AudioLevel`, `CpuUsage`, `GpuUsage`, `LatencyUpdate`.
