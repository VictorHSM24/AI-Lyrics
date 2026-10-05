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

## 2026-10-04 — Fix: parser — dedup de número na fronteira de chunk + aliases singulares

Análise das gravações reais `gravacao_20261004_181352`/`_185211` contra
anotações do operador identificou duas causas certeiras; corrigidas:

- **Versículo fantasma por número re-emitido na fronteira de chunk** —
  o LocalAgreement-2 re-emite a última palavra do chunk anterior como
  primeira do próximo ("jeremias 29." + "29, 7."). Quando a palavra é
  número, virava versículo fantasma: Jr 29:**29** (corrigiu só após
  repetição), 2Ts 2:**2** (nunca corrigiu — a continuação órfã ficava
  `open` e bloqueava o scan da menção completa seguinte), 2Jo 1:**1**.
  `IncrementalBiblicalParser._dedup_boundary_numeric()` remove 1 token
  numérico inicial que repita exatamente o último token normalizado do
  chunk anterior; a cauda (`_committed_tail`) acompanha só o ingerido
  e reseta por utterance. Reprodução dos 3 incidentes passa a detectar
  o versículo certo na **primeira emissão**.
- **Demônimos singulares não resolviam livro** — pregador disse
  "segunda tessalonicense 3, 14" e nada foi emitido: aliases singulares
  não existiam e, mesmo adicionados ao `books.json`, eram descartados
  por `SpeechBookMatcher._eligible` (token fora do vocab canônico).
  Adicionados em `_SPEECH_EXTRA_ALIASES` (`1/2 tessalonicense`,
  `1/2 corintio`, `1/2 cronica`) — forma ordinal resolve via `_numbered`.
  Aliases equivalentes também mantidos em `books.json` (busca digitada).
  "Reis" singular foi **omitido de propósito** ("segundo rei" é fala
  comum sobre monarcas — risco de falso positivo).
- **Teste ambiental corrigido** — `test_present_with_quick_flag` assumia
  default `ACF`, mas `config.overrides.json` (commitado) persiste
  `pt_ra`. Agora fixa `root.config.state.default_version` em memória.
- Testes novos em `tests/test_incremental_parser_committed.py`
  (`TestBoundaryNumericDedup` 3 casos, `TestSingularAliases` 3 casos).
- Arquivos: `pipeline/incremental_parser.py`,
  `pipeline/speech_reference_grammar.py`, `config/books.json`,
  `tests/test_incremental_parser_committed.py`,
  `tests/test_sprint24_operator_panel.py`.
- Commit(s): pendente.

## 2026-10-04 — Fix: transcrição lenta/alucinada — cadência 400ms + diff de commit estrito

- Reporte do usuário: transcrição e apresentação mais lentas que nos
  commits de 01/10 + Whisper "alucinando" mais.
- Causa 1 — cadência: `streaming.update_interval_ms` estava 700ms
  (commit `1e3a2dc`, feito para aliviar GPU). Volta a **400ms**
  (yaml/models/loader) — a proteção da UI já está no frontend
  (EventStore cap 2000 + TimelinePanel cap 300), então a GPU voltará a
  ~80% sem degradar a página.
- Causa 2 — diff fuzzy: `_committed_prefix_consumed` aceitava qualquer
  bloco ≥2 dentro do committed para consumir o prefixo estável; match
  coincidental distante da fronteira podia "comer" palavras novas
  (perda) — lido como alucinação no transcript. Agora: bloco que chega
  ao fim do committed vale sempre; bloco interior só vale se terminar
  perto do fim (último quarto, mín. 8 palavras).
- Causa 3 — TimelinePanel removida do Console (pedido do usuário):
  milhares de EventCards renderizando degradavam a página. O Console
  agora abre direto no streaming (TranscriptPanel roxa); o componente
  continua disponível e o auditor JSONL segue registrando tudo.
- Busca semântica: dropdown de versão de cada candidato agora
  pré-seleciona a **versão padrão global** (`GET /operator/version`
  mapeada via `toLocalVersion` para a base FTS5) em vez de
  `best_version`; fallback ao best_version quando a padrão não está
  entre as versões do candidato. `toLocalVersion`/`LOCAL_VERSION_MAP`
  movidos de `QuickNavigator.tsx` para `utils` (reuso).
- `tests/test_committed_diff.py`: suíte 258 testes verde após ajuste;
  frontend 624 testes + typecheck verdes (testes de página atualizados).

---

## 2026-10-02 — Painel do operador: botão Retroceder no follow + versão bíblica global persistente

- **Retroceder**: `ReadingFollowService.back()` espelha `advance()` —
  clamp em `verse_start`, reseta cursor/buffer/debounce, re-apresenta no
  Holyrics e publica `ReadingFollowAdvanced(reason="manual_back")`.
  Endpoint `POST /operator/follow/back`; frontend: `followBack` no
  transport/services/hook + botão "Retroceder" (ChevronLeft) ao lado de
  "Avançar" no `ReadingFollowPanel`.
- **Versão global**: `POST /operator/version` agora normaliza a key
  (`normalize_version_key`), propaga via `VersionChanged` e **persiste**
  `state.default_version` via `ConfigurationPresentationService`.
  `VersePresentationService` passa a assinar `VersionChanged` —
  apresentações por voz, painel e follow usam todas a versão escolhida.
- Fix `_default_version()`: lia a seção `verse` (inexistente) e sempre
  caía em "ACF"; agora prefere a versão viva do follow service e faz
  fallback a `state.default_version`.
- **Fix grave em `ConfigurationPresentationService`**: `_overrides`
  iniciava vazio sem carregar o arquivo — qualquer
  `update_configuration()` sobrescrevia `config.overrides.json` inteiro
  e apagava seções persistidas (holyrics/stt). Agora carrega
  `load_overrides()` no init; detectado no smoke test.
- Testes: `tests/test_operator_version_back.py` (11 casos: back delega/
  estado/falha, normalização, persistência, VersionChanged, fallback
  _default_version), `back()` em `test_reading_follow.py` (3 casos),
  `VersionChanged` no VPS em `test_verse_presentation_service.py`
  (2 casos). Suíte: 3606 backend + 624 frontend verdes; E2E validado
  (follow/start já ativa na versão global ARA, back clampa no início).
- Commit: `30b96d3`

---

## 2026-10-02 — Âncora de contexto: "capítulo X, versículo Y" sem nome do livro

- Pedido do usuário: pregador diz "João capítulo 3 versículo 16", prega
  um pouco e depois pede isoladamente "capítulo 5, versículo 10" ou
  "versículo 20" — o sistema deve manter o livro (e capítulo) da última
  referência. **Condição obrigatória: marcador explícito**
  ("capítulo"/"versículo"); número solto nunca continua.
- `pipeline/incremental_parser.py`: novo `_anchor` (book, conf,
  chapter, deadline) — sobrevive a resets e utterances completas, TTL
  configurável. Atualizado a cada referência reconhecida E a cada
  `VersePresented` (voz, painel ou follow — a âncora é o que está na
  tela). Limpo em `PipelineStopped`.
- `_evaluate` tenta `parse_continuation` contra a âncora no início da
  utterance (após carry); menção de livro próxima ao início desativa a
  tentativa (livro explícito sempre vence).
- `parse_continuation`: novo `allow_bare_pair=False` na âncora — o par
  compacto "14 10" no meio da fala NÃO resolve (carry mantém True).
- `incremental_parser.anchor_seconds` (default 600s, 0 desativa) no
  yaml/models/loader/composition.
- `tests/test_anchor_continuation.py`: 7 casos (capítulo+versículo,
  versículo isolado, troca de livro, número solto, par sem marcador,
  TTL, livro explícito). `test_carry_expires` isola carry com
  `anchor_seconds=0`.
- Verificado: 229 testes sprint31/âncora + 908 relacionados verdes.
- Commit: `06f9bec`

## 2026-10-02 — Fix: UI travava após poucos minutos de pipeline (GPU + EventStore sem cap)

- Sintoma: página do software extremamente lenta após poucos minutos
  (~3s para trocar de tela), GPU >80% constante, CPU baixo.
- **Causa 1 — GPU saturada**: a SlidingWindow disparava uma transcrição
  Whisper (janela de 6s, large-v3-turbo) a cada **400ms**; mediana de
  inferência ~265ms → duty ~65-80% contínuo na única GPU do sistema →
  compositor do Chrome/Electron faminto → jank em toda a UI.
  - `config.yaml`: nova seção `streaming:` (`window_seconds`,
    `update_interval_ms`) — default agora **700ms** (~35-40% GPU).
  - `config/models.py` + `loader.py`: `StreamingConfig` (opcional,
    backward-compatible); `composition.py` lê da config.
- **Causa 2 — EventStore sem cap** (`stream/bridge.ts`): cada evento
  operacional era appendado via `[...events, dto]` — cópia O(n) por
  evento (~3/s), array crescia sem limite (8k eventos em 42min) →
  trabalho O(n²) + pressão de GC. Cap: últimos 2000 eventos.
- **Causa 3 — TimelinePanel renderizava todos os eventos**: milhares de
  `EventCard` reconciliados a cada evento na página Console; desmontar
  a lista travava a navegação. Cap de renderização: últimos 300 cards
  (com aviso "mostrando os 300 mais recentes"); `clearEvents` migrado
  de offset para timestamp (robusto ao trim do store).
- Verificado: typecheck + 624 testes frontend; 224 testes backend
  (config/stream/loader); gravação usada como evidência (latência
  mediana de inferência 265ms a cada ~405ms).
- Commit: `1e3a2dc`

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
