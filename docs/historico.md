# Histórico do Sistema

Registro cronológico de tudo que foi implementado no AI Lyrics. Mantido por
agentes e humanos — **toda mudança relevante deve gerar uma entrada aqui**
(ver protocolo em `AGENTS.md`).

Entradas mais recentes no topo. Formato:

```
## YYYY-MM-DD — Título curto
- O que foi feito (bullets objetivos)
- Arquivos/áreas afetadas
- Commit(s): hash (se houver)
```

---

## 2026-10-02 — Fix: LocalAgreement-2 re-commitava bloco reescrito (1 Crônicas 28 não apresentado)

- Diagnóstico da gravação `gravacao_20261002_195356` (~00:15): o
  pregador disse "1ª Crônica, capítulo 28, versículo 9" e nada foi
  apresentado. Causa-raiz no STT, não no parser: o Whisper reescreveu
  palavras já committed ("crônia" → "crônicas", removeu "versículo"),
  quebrando o prefix-match exato de `_local_agreement` contra a cauda
  do committed → `already_committed=0` → o bloco estável
  "crônicas, capítulo 28, 9." foi re-emitido como novo **5×**. O parser
  acumulou tokens duplicados ("...cronicas capitulo cronicas capitulo
  28 9...") e a gramática não reconheceu a referência ("cronicas"
  sozinho não é alias — exige prefixo numérico, por ambiguidade 1ª/2ª).
- `microfone/streaming_stt_service.py`: novo helper
  `_committed_prefix_consumed` alinha o prefixo estável com a cauda do
  committed via `difflib.SequenceMatcher` — bloco que alcança o fim do
  committed consome o prefixo; sem bloco no fim, blocos interiores ≥2
  também consomem (reescrita na cauda). `_local_agreement` passa a
  emitir só o sufixo realmente novo.
- `tests/test_committed_diff.py`: 7 testes de regressão (reproduz o
  cenário da gravação: reescrita no fim não re-commita; continuação
  emite só o sufixo; fluxo normal intocado).
- Verificado: replay exato dos deltas gravados reproduziu a falha e
  passa com o fix; suíte completa 3583 verde.
- Commit: `823eef1`

## 2026-10-02 — Follow retoma por voz após parada manual

- Diagnóstico da gravação `gravacao_20261002_195356`: o pregador disse
  "apocalipse 2", o versículo foi apresentado (Ap 2:2, origem
  `VersePresentationService`) e o follow não iniciou — porque o
  operador havia parado o follow às 00:14:48 (`manual_stop`), e a regra
  da Sprint 31 só liberava `_auto_follow_paused` via painel
  (`OperatorPanel`). A ancoragem só aconteceu 51s depois, quando o
  operador apresentou Ap 2:3 manualmente.
- Comportamento alterado a pedido do usuário: `/follow/stop` continua
  pausando a ancoragem, mas a **próxima apresentação por voz**
  (`VersePresentationService*`) também limpa `_auto_follow_paused` e
  re-ancora — o pregador retoma o acompanhamento falando uma nova
  referência, sem exigir intervenção do operador. Painel continua
  liberando; origem `ReadingFollowService` continua ignorada (sem
  loop); referência detectada sem apresentação não retoma.
- `presentation/reading_follow_service.py`: `_on_verse_presented` —
  condição de liberação ampliada para `OperatorPanel` ou
  `origin.startswith("VersePresentationService")` (cobre o sufixo
  `.navigation`); docstrings de `deactivate`, `_on_reference_detected`
  e `_on_verse_presented` atualizados.
- `tests/test_sprint31_follow_incidents.py`: incidente (f) reescrito
  — `test_incident_f_stop_pauses_until_next_presentation` valida
  retomada por voz E por painel após `deactivate()`.
- Verificado: 84 testes de follow/voz verdes; backend reiniciado com o
  código novo.
- Commit: `78765db`

## 2026-10-02 — Botão "Encerrar apresentação" (ESC) no painel do operador

- Novo `POST /operator/close-presentation`: chama a action
  `CloseCurrentPresentation` da API REST do Holyrics (equivalente ao
  ESC — libera o telão) e publica o novo evento operacional
  `VersePresentationClosed`.
- `integracao_holyrics/client.py`: método `close_presentation()`;
  `pipeline/events.py` + `__init__.py`: `VersePresentationClosed`.
- Frontend: botão "Encerrar" no card "Apresentado"
  (`PresentationCards.tsx`), `operator.closePresentation` no
  SDK/transport/service, `VersePresentationClosedDTO` em types; o
  handler do stream limpa o card ao receber o evento (event-driven,
  como `VersePresented`).
- Verificado: typecheck OK; endpoint respondeu contra o Holyrics real
  (HTTP 401 na action — token configurado sem permissão; o problema
  é de config do Holyrics, não do endpoint — ver backlog).
- Commit: `5120637`

## 2026-10-02 — Seletor nativo de pastas do Windows (página Sessões)

- O campo de texto "Personalizar pasta" foi substituído por um botão
  "Selecionar pasta…" que abre o **seletor nativo do Windows**
  (IFileOpenDialog, estilo Explorer). O browser não expõe o caminho real
  de pastas, então o diálogo abre no backend — que também escreve os
  arquivos. O caminho escolhido é aplicado e persistido automaticamente
  (`POST /recording/output-dir`).
- Novo `core/folder_dialog.py` — `pick_folder()` implementa o diálogo
  COM via **ctypes puro**, sem dependências. Escolha deliberada:
  tkinter é excluído do build PyInstaller (`ai-lyrics.spec`) e pywin32
  não é dependência do projeto — ctypes funciona em dev e no exe.
- Novo endpoint `POST /recording/browse` (síncrono → threadpool: o
  diálogo modal não bloqueia o event loop; pasta inicial = output_dir
  atual; janela-pai = janela em foreground para o seletor aparecer na
  frente do browser). Retorna `{path, cancelled}`; 501 fora do Windows.
- Frontend: `recording.browse` no SDK/transport, `browse()` no
  `RecordingService` (+ stubs em `api/client.ts` e `createStubServices`),
  `RecordingBrowseDTO` em `types/index.ts`.
- Testes: `tests/test_recording_browse.py` (4 casos com pick_folder
  mockado); `routing.test.tsx` atualizado para o novo testid.
- Verificado: mecânica COM validada direto no Windows (CoCreateInstance,
  Get/SetOptions, SetFolder — todos S_OK); E2E real — diálogo abriu na
  tela e o cancelamento retornou `{path: null, cancelled: true}`;
  typecheck OK; 21 testes backend OK; 18 testes de rota OK.

## 2026-10-02 — Gravação de auditoria do pipeline (página Sessões)

- Novo `pipeline/audit_recorder.py` — `PipelineAuditRecorder`: gravação
  sob demanda do resultado do pipeline para auditoria completa.
  Inscreve-se no EventBus via wildcard `"*"` apenas durante a gravação
  (custo zero fora dela). Produz por sessão:
  `events.jsonl` (todos os OperationalEvents com meta + payload),
  `errors.jsonl` (eventos de erro + registros de logging ERROR+ —
  captura exceções de handlers que o EventBus engole e só loga),
  `telemetry.jsonl` (TelemetryEvents separados) e `summary.json`
  (índice da auditoria: duração, contagens por tipo, lista de erros).
- Diretório de saída personalizável, default
  `~/Documents/AI-Lyrics/gravacoes`; preferência persistida em
  `data/recording_prefs.json` (via `core.paths.writable_path`).
- Novo router `api/routers/recording.py` (`/recording`): `GET /status`,
  `GET /recordings`, `POST /start`, `POST /stop`, `POST /output-dir`.
- `pipeline/bus.py`: `unsubscribe()` agora aceita `"*"` (handlers
  wildcard não podiam ser removidos — gap da implementação anterior).
- `composition.py`: campo `audit_recorder` no CompositionRoot.
- `api/app.py`: prefixo `recording` no catch-all SPA + parada graciosa
  da gravação no shutdown (escreve summary.json).
- Frontend: `RecordingService` em `services/index.ts` + endpoints em
  `sdk/transports/rest.ts` + stubs em `api/client.ts` + DTOs em
  `types/index.ts`.
- `frontend/src/pages/SessionsPage.tsx`: página Sessões sai do stub —
  controles Iniciar/Parar, rótulo da gravação, badge GRAVANDO com
  cronômetro, contadores de eventos/telemetria/erros, campo de pasta de
  destino (desabilitado durante gravação) e tabela de gravações
  anteriores.
- Testes: `routing.test.tsx` atualizado (Sessões funcional);
  `transcript-panel.test.tsx` corrigido (texto stale pré-existente).
- Verificado: 3572 testes backend OK, typecheck OK, 624 testes frontend
  OK, smoke test E2E via browser (gravação capturou PipelineStarted,
  SpeechPartial, SpeechCommittedWords, PipelineStopped).

## 2026-09-30 — Observabilidade e graceful shutdown (commitado em d42b7eb)

- Novo `pipeline/auditing_event_store.py`: event store com auditoria.
- `pipeline/bus.py`: suporte a handlers wildcard `"*"` que recebem TODOS os
  eventos publicados (incluindo TelemetryEvents).
- `api/app.py`: shutdown graceful fecha WebSockets abertos
  (`get_ws_manager().close_all()`) e para SlidingWindow/StreamingSTTService —
  corrige travamento do reload do uvicorn esperando receiver WS.
- `api/routers/audio.py`, `api/routers/pipeline.py`, `api/schemas/models.py`,
  `api/websocket/events.py`, `presentation/{dtos,mappers,services}.py`:
  exposição de eventos/telemetria ao frontend.
- `frontend/src/contexts/OperationContext.tsx`: ajuste de contexto operacional.
- `tests/test_observability_fixes.py`: testes das correções de observabilidade.
- `microfone/streaming_stt_service.py`: +13 linhas (diagnóstico/métricas).

## 2026-09-25 — Fix: falsos positivos no pipeline de voz

- Elimina falsos positivos e referências impossíveis no pipeline de voz.
- Commit: `56a4e0d`

## 2026-09 — Acompanhamento de leitura + versões bíblicas

- Reading Follow por cursor sequencial + seletor de versão (`6bda4b2`).
- Novas fontes bíblicas AS21, NBV e NVI + utilitários de versão (`00f5aeb`) —
  base passou a 10 versões / ~311k versículos.
- Resolução do dispositivo de áudio no startup; prevenção de falsos comandos
  de navegação (`f7e1eee`).
- Command Palette resolve abreviações com espaço e sem pontuação (`a0c5cf2`).
- Busca semântica com Ollama (`qwen3:1.7b`) + toggle e navegação rápida
  automática (`c4b87a2`).
- LocalAgreement-2 com alinhamento de SlidingWindow + `word_timestamps` no
  BackendFallbackManager (`1d896ca`).

## 2026-08/09 — Sprint 28: Pipeline Streaming-First

- Pipeline streaming-first implementado (Fases 6–11): SlidingWindow (6s/400ms)
  + LocalAgreement-2 como único caminho de STT; VAD e SpeechWorker
  desativados (`e7552f1`).
- StateOrchestrator coordena VersePresentationService (Sprint 28 Fase 6).
- SemanticSearchService com OllamaBackend nativo `/api/chat` (Fase 9).
- Plano arquitetural: `docs/streaming_first_pipeline_plan.md`.

## 2026-08 — Sprint 27: STT GPU, Holyrics e restart

- Registro de DLLs CUDA antes de importar ctranslate2/faster-whisper
  (`core/cuda_setup.py`) — necessário no Windows com GPU NVIDIA.
- Loop de supervisão em `main.py`: `POST /system/restart` recarrega config e
  reinicia uvicorn sem derrubar o processo.
- Correção de `channels` (2→1, downmix stereo→mono) e acionamento do
  Holyrics via `show_verse_references`.
- Commits: `573dee1`, `d2c0263`, `8bf7159`.

## 2026-08 — Sprint 23.2 / 24: Reading Follow, Version Management, Painel do Operador

- `ReadingFollowService` (fuzzy 0.70, debounce 300ms) e
  `VersionCommandDetector` (troca de versão por voz, auto_enabled).
- Painel do Operador com navegação bíblica estruturada (Sprint 24).
- CAP-01: infraestrutura do StateOrchestrator.
- Commits: `cd6224e`, `6fe7bf0`, `6434ae3`.

## 2026-08 — Sprint 23: Produto Beta

- Empacotamento PyInstaller (`ai-lyrics.spec` → `ai-lyrics.exe`), instalador,
  wizard de primeira execução (`api/wizard.py` + `frontend/src/pages/Wizard.tsx`).
- Reorganização do projeto para distribuição.
- Relatórios: `docs/Relatorio_Sprint_23_0_Produto_Beta.md`,
  `Relatorio_Sprint_23_1_Wizard_Stabilization.md` (raiz).

## 2026 — Sprints 21.x: Sermon Memory Engine e validações

- Sprint 21: Sermon Memory Engine.
- Sprint 21.1.1: hardening do LocalLLMProvider.
- Sprints 21.5–21.9: auditorias do SemanticEngine, validação do EventBus,
  auditoria de inferência, engenharia de prompt, validação estatística,
  classificador de contexto, instrumentação/telemetria do pipeline.
- Relatórios em `docs/Relatorio_Sprint_21_*.md`.

## 2026 — Sprints 13–20: fundação do pipeline

- Sprint 13: integração de dados. Sprint 14: backend capability.
- Sprint 15.1: captura de áudio ao vivo (`AudioCaptureService`).
- Sprint 16/17: runtime STT faster-whisper (auditoria em
  `Relatorio_Sprint_17_3_STT_Runtime_Audit.md`).
- Sprint 18: `VersePresentationService`.
- Sprint 19: streaming speech pipeline (ring buffer 20s, janela 6s/400ms,
  parser incremental).
- Sprint 22: Bible Knowledge Base (`BibleRetriever`, SQLite por versão) +
  priorização RAG + auditoria do pipeline semântico.

## 2026 — Fases 8–12: inteligência e infraestrutura

- Fase 8: Sermon Context Engine. Fase 9: Feedback Learning.
- Fase 10: Continuous Evaluation. Fase 11: Sermon Intelligence.
- Fase 12: Event Store + Streaming Pipeline.
- Presentation Layer, API FastAPI, frontend React e Console Operacional.
- Operational Foundation: startup, configurações e estado operacional.
- Integração com Holyrics funcionando.
- Relatórios em `docs/Relatorio_Fase_*.md` e `Relatorio_*Layer*.md`.
