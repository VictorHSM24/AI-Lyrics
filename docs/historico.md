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

## 2026-09-30 → presente — Observabilidade e graceful shutdown (EM ANDAMENTO, não commitado)

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
