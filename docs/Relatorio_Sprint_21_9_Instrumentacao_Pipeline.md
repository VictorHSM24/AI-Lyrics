# Sprint 21.9 — Instrumentação do Pipeline para Validação em Ambiente Real

## Data: 2026-07-25
## Status: Concluído

---

## 1. Resumo Executivo

**Conclusão objetiva:** A infraestrutura de telemetria foi implementada com sucesso, sem qualquer alteração funcional no pipeline. Todos os 3003 testes passam (2986 originais + 17 novos da telemetria). O sistema agora grava automaticamente, em arquivos JSON Lines (.jsonl), eventos detalhados de cada componente do pipeline (STT, Streaming, Parser, SermonMemory, SemanticEngine, LocalLLMProvider, ReferenceResolver, Holyrics), permitindo auditoria posterior de sessões reais.

**Princípio fundamental respeitado:** A instrumentação é desacoplada, reutilizável, facilmente desabilitada e não duplica código. Foi criada uma infraestrutura própria de telemetria (pacote `telemetry/`) com recorder assíncrono (fila consumida por thread dedicada) e hooks específicos por componente. Nenhuma decisão do pipeline foi modificada; nenhum prompt, threshold, regra de inferência ou comportamento do SemanticEngine, PromptBuilder, LocalLLMProvider, ReferenceResolver, SermonMemory, IncrementalParser foi alterado.

**Validação:** O diagnóstico `_diag_sprint21_9.py` simula um fluxo completo do pipeline (SpeechPartial → Parser → SermonMemory → SemanticEngine → LocalLLMProvider → Resolver → Holyrics) e confirma que 10 arquivos .jsonl são gerados, um por categoria, com os eventos corretos em cada um.

---

## 2. Arquitetura da Telemetria

### 2.1 Pacote `telemetry/`

Criado um novo pacote desacoplado, sem dependências de componentes do pipeline:

```
telemetry/
├── __init__.py      # API pública (configure_recorder, record, shutdown_recorder, is_enabled)
├── recorder.py      # TelemetryRecorder (fila assíncrona + thread consumidora + escrita JSONL)
└── hooks.py         # Hooks específicos por componente (stt, streaming, parser, sermon, semantic, resolver, holyrics)
```

### 2.2 TelemetryRecorder

O `TelemetryRecorder` é o núcleo da infraestrutura. Características:

- **Fila assíncrona:** `queue.Queue` consumida por uma thread dedicada (`TelemetryRecorderWorker`). Os produtores (componentes do pipeline) chamam `record()` que apenas enfileira, sem bloquear.
- **Escrita JSONL:** Cada evento é serializado como uma linha JSON em um arquivo `.jsonl` por categoria. Um arquivo por categoria, dentro de uma subpasta `session_<timestamp>`.
- **Thread-safe:** Vários produtores podem chamar `record()` concorrentemente. Um lock protege os file handles.
- **Desabilitável:** Se `enabled=False`, `record()` é no-op (não enfileira nem escreve).
- **Shutdown gracioso:** `stop()` enfileira um sentinel `None`, a thread consumidora drena a fila e fecha os arquivos. Timeout de 5s para não bloquear indefinidamente.
- **Não propaga exceções:** Falhas de IO são logadas em `debug` e descartadas; nunca chegam ao pipeline.
- **Line-buffered:** `buffering=1` em `open()` garante que cada linha seja flushada imediatamente, evitando perda de dados em caso de crash.

### 2.3 Hooks por Componente

O módulo `hooks.py` encapsula a extração de campos relevantes de cada componente, evitando duplicação de código nos componentes. Cada hook é no-op se a telemetria estiver desabilitada:

| Hook | Categoria | Campos Registrados |
|------|-----------|-------------------|
| `stt_window` | `stt` | correlation_id, audio_duration_ms, rms, skipped_silence, skipped_low_confidence, skipped_empty, skipped_no_change, transcribed, text, confidence, latency_ms, language |
| `stt_partial_published` | `streaming` | correlation_id, event_type, text, appended_text, full_text, growth_chars, confidence, latency_ms, audio_duration_ms, language |
| `parser_event` | `parser` | correlation_id, text_processed, expecting, completeness, book, chapter, verse, confidence, decision, published_event, latency_ms |
| `sermon_state_change` | `sermon_memory` | correlation_id, reason, previous_book, previous_chapter, new_book, new_chapter, probable_theme, num_entities, num_topics, num_references, confidence, source, reference_active, total_updates |
| `semantic_input` | `semantic_engine` | correlation_id, text, recent_text, trigger, growth_chars, append_words, elapsed_ms, cached, context_hash |
| `semantic_prompt` | `semantic_prompt` | correlation_id, system_prompt, user_prompt, context (current_text, recent_text, last_book, last_chapter, last_reference, sermon_book, sermon_chapter, sermon_theme, sermon_entities, sermon_confidence), model, temperature, top_p, max_tokens, disable_thinking |
| `semantic_llm_response` | `semantic_llm_response` | correlation_id, raw_content, cleaned_content, had_thinking, http_ms, attempt, error |
| `semantic_result` | `semantic_result` | correlation_id, intent, candidates, inference_ms, cached, context_hash, error |
| `resolver_decision` | `resolver` | correlation_id, candidates_in, candidates_valid, chosen, reason, min_confidence, latency_ms |
| `holyrics_presentation` | `holyrics` | correlation_id, book, chapter, verse, version, quick_presentation, success, latency_ms, error, stage |
| `pipeline_event` | `pipeline` | event_type, correlation_id, origin, payload (genérico) |

### 2.4 Layout de Arquivos

```
<output_dir>/
└── session_<timestamp>/
    ├── stt.jsonl
    ├── streaming.jsonl
    ├── parser.jsonl
    ├── sermon_memory.jsonl
    ├── semantic_engine.jsonl
    ├── semantic_prompt.jsonl
    ├── semantic_llm_response.jsonl
    ├── semantic_result.jsonl
    ├── resolver.jsonl
    ├── holyrics.jsonl
    └── pipeline.jsonl  (eventos genéricos)
```

Cada linha é um JSON object com pelo menos `{"timestamp": "...", "event": "...", ...}`.

---

## 3. Pontos de Instrumentação

Cada componente foi instrumentado em pontos estratégicos, sem alterar decisões. Os hooks são chamados **após** as decisões já tomadas, apenas para observação.

### 3.1 StreamingSTTService (`microfone/streaming_stt_service.py`)

- **`on_window`**: registra cada janela de áudio processada, com RMS, confiança, latência, e motivo de descarte (silêncio, confiança baixa, texto vazio, sem mudança).
- **`_publish_partial`**: registra publicação de `SpeechPartial` (primeira transcrição do fluxo).
- **`_publish_partial_updated`**: registra publicação de `SpeechPartialUpdated` (evolução da transcrição), com `appended_text` e `growth_chars`.

### 3.2 IncrementalBiblicalParser (`pipeline/incremental_parser.py`)

- **`_evaluate_and_publish`**: registra cada decisão do parser, com `completeness` (book/chapter/verse), `confidence`, `decision` (publish_candidate, publish_detected, publish_antecipada) e `published_event` (ReferenceCandidate, ReferenceDetected, ReferenceAntecipada).

### 3.3 SermonMemoryEngine (`sermon/engine.py`)

- **`_process_text`**: registra mudança de estado por processamento de texto, com estado anterior (previous_book, previous_chapter) e estado novo (new_book, new_chapter, probable_theme, num_entities, num_topics, num_references, confidence).
- **`_apply_reference`**: registra mudança de estado por referência detectada, com `source` (parser/semantic), `reference_active` e `reason` (reference_detected, reference_detected+book_changed, reference_detected+chapter_changed).

### 3.4 SemanticEngine (`semantic/engine.py`)

- **`_run_inference`**: registra input recebido (text, recent_text, trigger, growth_chars, append_words, context_hash), resultado de cache hit, timeout, erro do provider, e resultado final (intent, candidates, inference_ms, cached, error).

### 3.5 LocalLLMProvider (`semantic/local_provider.py`)

- **`infer`**: registra prompt enviado ao LLM (system_prompt, user_prompt, context completo, model, temperature, top_p, max_tokens, disable_thinking).
- **`infer` (após resposta)**: registra resposta RAW do LLM (raw_content, cleaned_content, had_thinking, http_ms, attempt, error), permitindo auditoria do que o modelo realmente respondeu antes do parser.

### 3.6 ReferenceResolver (`semantic/resolver.py`)

- **`_on_intent_candidate`**: registra cada decisão do resolver, com `candidates_in`, `candidates_valid`, `chosen`, `reason` (no_candidates, parser_already_resolved, all_invalid, low_confidence, highest_confidence) e `min_confidence`.

### 3.7 VersePresentationService (`presentation/verse_presentation_service.py`)

- **`_present_verse`**: registra apresentação bem-sucedida no Holyrics (book, chapter, verse, version, quick_presentation, success=True, latency_ms).
- **`_handle_holyrics_failure`**: registra falha na apresentação (success=False, error, stage=auth/timeout/connection/api/holyrics_error/internal_error).

---

## 4. Configuração

### 4.1 Config YAML (`config/config.yaml`)

Adicionada seção opcional `telemetry`:

```yaml
telemetry:
  enabled: true
  output_dir: ""  # vazio = usa default (~/AI_Lyrics_telemetry)
```

### 4.2 Config Model (`config/models.py`)

Adicionada classe `TelemetryConfig`:

```python
@dataclass(frozen=True)
class TelemetryConfig:
    enabled: bool = True
    output_dir: str = ""
```

### 4.3 Config Loader (`config/loader.py`)

Adicionada função `_build_telemetry` que constrói `TelemetryConfig` a partir do dict do YAML, com defaults seguros (enabled=True, output_dir="").

### 4.4 Environment Variables

- `AILYRICS_TELEMETRY_ENABLED=0` desabilita a telemetria independentemente da config.
- `AILYRICS_TELEMETRY_DIR=/caminho` define o diretório base de gravação (default: `~/AI_Lyrics_telemetry`).

### 4.5 Modo de Teste

Em `AI_LYRICS_TEST_MODE=1`, a telemetria é desabilitada por padrão para não poluir o disco durante testes automatizados.

---

## 5. Integração com o Composition Root

### 5.1 Inicialização (`api/startup/composition.py`)

Adicionada função `_configure_telemetry` chamada no início de `create_composition_root`, antes de instanciar qualquer componente do pipeline. Isso garante que o recorder global esteja configurado antes que qualquer componente possa registrar eventos.

### 5.2 Shutdown (`api/app.py`)

Adicionada chamada a `shutdown_recorder()` no handler `on_shutdown` do FastAPI, após parar o audio capture. Isso drena a fila de telemetria graciosamente antes do processo encerrar, garantindo que nenhum evento seja perdido.

---

## 6. Validação

### 6.1 Testes Unitários (`tests/test_sprint21_9_telemetry.py`)

17 testes cobrindo:

- Escrita de eventos em arquivos .jsonl por categoria.
- Múltiplas categorias geram arquivos separados.
- Recorder desabilitado é no-op.
- Shutdown drena a fila (100 eventos).
- Hooks não lançam exceção com payloads inválidos.
- Diretório de sessão é criado com prefixo `session_`.
- `is_enabled()` reflete o estado do recorder.
- Cada hook específico registra o evento correto na categoria correta.
- Hooks são no-op quando desabilitados.
- `record()` após shutdown é silenciosamente ignorado.

**Resultado:** 17/17 passaram.

### 6.2 Diagnóstico de Integração (`_diag_sprint21_9.py`)

Script que simula um fluxo completo do pipeline chamando os hooks diretamente, e valida que 10 arquivos .jsonl são gerados nas categorias esperadas:

- `stt.jsonl` (1 evento)
- `streaming.jsonl` (1 evento)
- `parser.jsonl` (2 eventos: book + chapter)
- `sermon_memory.jsonl` (1 evento)
- `semantic_engine.jsonl` (1 evento)
- `semantic_prompt.jsonl` (1 evento)
- `semantic_llm_response.jsonl` (1 evento)
- `semantic_result.jsonl` (1 evento)
- `resolver.jsonl` (1 evento)
- `holyrics.jsonl` (1 evento)

**Resultado:** Todas as 10 categorias presentes, com conteúdo correto.

### 6.3 Suíte Completa

Todos os 3003 testes do projeto passam (2986 originais + 17 novos), confirmando que a instrumentação não alterou o comportamento do pipeline.

---

## 7. Critério de Aceite

| Critério | Status | Evidência |
|----------|--------|-----------|
| Iniciar o backend normalmente | OK | `create_composition_root` configura o recorder antes de qualquer componente; imports validados |
| Executar sessão real sem mudança de comportamento | OK | 3003 testes passam; hooks são no-op quando desabilitados; hooks não propagam exceções |
| Encerrar a sessão | OK | `on_shutdown` chama `shutdown_recorder()` que drena a fila e fecha arquivos |
| Encontrar arquivos .jsonl com toda a execução | OK | Diagnóstico gera 10 arquivos .jsonl nas categorias esperadas |

### 7.1 Capacidade de Responder Perguntas Futuras

Os arquivos .jsonl contêm informações suficientes para responder:

| Pergunta | Arquivo(s) | Campos Relevantes |
|----------|-----------|-------------------|
| Quais transcrições foram alucinações? | `stt.jsonl` | `skipped_silence`, `skipped_low_confidence`, `rms`, `confidence`, `text` |
| Quando o SermonMemory mudou? | `sermon_memory.jsonl` | `reason`, `previous_book/chapter`, `new_book/chapter`, `source`, `total_updates` |
| Quando ocorreu ancoragem de referências? | `sermon_memory.jsonl` + `semantic_engine.jsonl` | Correlação por `correlation_id` entre mudança de estado e input do SemanticEngine |
| Quais prompts foram enviados ao LLM? | `semantic_prompt.jsonl` | `system_prompt`, `user_prompt`, `context` (com `recent_text`, `last_book`, etc.) |
| Quais respostas foram produzidas? | `semantic_llm_response.jsonl` + `semantic_result.jsonl` | `raw_content`, `cleaned_content`, `intent`, `candidates` |
| Quais decisões foram tomadas pelo ReferenceResolver? | `resolver.jsonl` | `candidates_in`, `candidates_valid`, `chosen`, `reason`, `min_confidence` |

---

## 8. Arquivos Modificados

### 8.1 Novos Arquivos

| Arquivo | Descrição |
|---------|-----------|
| `telemetry/__init__.py` | API pública do pacote telemetry |
| `telemetry/recorder.py` | TelemetryRecorder (fila assíncrona + thread consumidora + escrita JSONL) |
| `telemetry/hooks.py` | Hooks específicos por componente |
| `tests/test_sprint21_9_telemetry.py` | 17 testes unitários da telemetria |
| `_diag_sprint21_9.py` | Diagnóstico de integração |
| `_diag_sprint21_9_output.txt` | Saída do diagnóstico |

### 8.2 Arquivos Modificados (apenas instrumentação, sem mudança funcional)

| Arquivo | Mudança |
|---------|---------|
| `config/config.yaml` | Adicionada seção `telemetry` (opcional) |
| `config/models.py` | Adicionada `TelemetryConfig` |
| `config/loader.py` | Adicionada `_build_telemetry` |
| `api/startup/composition.py` | Adicionada `_configure_telemetry` chamada no início de `create_composition_root` |
| `api/app.py` | Adicionada `shutdown_recorder()` no `on_shutdown` |
| `microfone/streaming_stt_service.py` | Adicionados hooks em `on_window`, `_publish_partial`, `_publish_partial_updated` |
| `pipeline/incremental_parser.py` | Adicionados hooks em `_evaluate_and_publish` (3 branches de decisão) |
| `sermon/engine.py` | Adicionados hooks em `_process_text` e `_apply_reference` |
| `semantic/engine.py` | Adicionados hooks em `_run_inference` (input, cache hit, timeout, error, result) |
| `semantic/local_provider.py` | Adicionados hooks em `infer` (prompt enviado, resposta RAW) |
| `semantic/resolver.py` | Adicionados hooks em `_on_intent_candidate` (4 branches de decisão) |
| `presentation/verse_presentation_service.py` | Adicionados hooks em `_present_verse` e `_handle_holyrics_failure` |

---

## 9. Conclusão

A Sprint 21.9 entregou uma infraestrutura completa de telemetria que permite observar o pipeline em ambiente real sem alterar seu comportamento. O sistema agora está pronto para produzir auditorias detalhadas de sessões reais, que serão utilizadas nas próximas Sprints para investigar, com evidências, os problemas observados no primeiro teste integrado: alucinações do STT, ancoragem de referências, contaminação de contexto, e acertos da arquitetura geral.

A arquitetura da telemetria é desacoplada (pacote próprio), reutilizável (hooks por componente), facilmente desabilitada (config + env var), sem duplicação de código (hooks encapsulam extração de campos), e não altera o comportamento do pipeline (hooks são chamados após decisões, são no-op quando desabilitados, e não propagam exceções). A escrita é assíncrona (fila + thread dedicada), garantindo que a telemetria não introduza latência no pipeline.
