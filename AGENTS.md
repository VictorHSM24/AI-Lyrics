# AGENTS.md

Guia para agentes de código trabalhando no **AI Lyrics** — assistente de
apoio a pregações que transcreve áudio em tempo real (STT), detecta
referências bíblicas na fala e projeta versículos via Holyrics.

Idioma do projeto: **português (pt-BR)** — código, comentários, commits e
documentação são em pt-BR. Mantenha esse padrão.

## Documentação viva (obrigatória)

| Arquivo | Conteúdo |
|---|---|
| `docs/historico.md` | Log cronológico de **tudo que foi feito** no sistema |
| `docs/backlog.md` | **Ações pendentes** (priorizadas P0–P3) |
| `docs/` | Relatórios de sprints/fases e planos arquiteturais |

**Protocolo de atualização:**

1. Ao **concluir** qualquer mudança relevante (feature, fix, refatoração,
   decisão arquitetural), adicione uma entrada no topo de
   `docs/historico.md` com data, bullets do que mudou e hash do commit.
2. Ao **descobrir** trabalho pendente (TODO, dívida técnica, validação de
   campo), registre em `docs/backlog.md`.
3. Ao **concluir** um item do backlog, remova-o de lá e registre no
   histórico. Nunca delete histórico.
4. Mudanças triviais (typos, formatação) não precisam de entrada.

## Comandos

```bash
# Backend (FastAPI + uvicorn, porta 8000) — a partir da raiz
uvicorn api.app:app --reload --port 8000

# Frontend (Vite + React + TS, porta 5173) — a partir de frontend/
cd frontend && npm run dev

# Testes backend
pytest

# Frontend: testes, typecheck e lint
cd frontend && npm test
cd frontend && npm run typecheck
cd frontend && npm run lint

# Empacotamento (PyInstaller → ai-lyrics.exe)
pyinstaller ai-lyrics.spec
# Entry point de produção: main.py (wizard de 1ª execução + loop de
# supervisão com POST /system/restart)
```

## Arquitetura (mapa rápido)

- `api/` — FastAPI: `app.py` (create_app), `routers/`, `websocket/`,
  `startup/composition.py` (composition root — instancia e liga tudo).
- `microfone/` — captura e STT streaming: `audio_capture_service.py`,
  `ring_buffer.py`, `sliding_window.py`, `streaming_stt_service.py`.
- `transcricao/` — faster-whisper (modelo `large-v3-turbo`, CUDA float16).
- `pipeline/` — `bus.py` (EventBus), `incremental_parser.py`,
  `state_orchestrator.py`, métricas.
- `parser/` — parsing incremental de referências bíblicas na fala.
- `busca/` — `Searcher` (SQLite FTS por versão bíblica, RRF).
- `knowledge/` — `BibleRetriever` (10 versões, ~311k versículos).
- `semantic/` — busca semântica via Ollama (`qwen3:1.7b`, `/api/chat`).
- `presentation/` — serviços de apresentação: verse presentation,
  reading follow, version command detector, integração Holyrics.
- `frontend/` — React 18 + Vite + Tailwind; rotas em `src/router`,
  páginas em `src/pages`, streaming WS em `src/stream`.
- `config/` — loader/persistence de config (`config.overrides.json`).
- `telemetry/` — TelemetryRecorder (sessões em `~/AI_Lyrics_telemetry/`).
- `integracao_holyrics/` — cliente da API do Holyrics.
- `data/` — bases SQLite das versões bíblicas (`data/sources/`).

## Convenções

- **Sprints/fases**: trabalho é organizado em sprints nomeadas
  (ex.: "Sprint 28"); relatórios ficam em `docs/Relatorio_*.md`.
- **EventBus**: componentes se comunicam por eventos
  (`SpeechTranscribed`, `ReferenceDetected`, `VersePresented`, etc.);
  wildcard `"*"` recebe todos os eventos.
- **Streaming-first**: SlidingWindow + LocalAgreement-2 é o único caminho
  de STT; VAD/SpeechWorker estão desativados (Sprint 28).
- **Arquivos grandes**: evite criar/editar arquivos com mais de ~500
  linhas de uma vez; escreva em etapas e continue editando (regra do
  projeto em `.devin/rules/`).
- **Windows + CUDA**: `core/cuda_setup.py` deve registrar DLLs CUDA antes
  de qualquer import de ctranslate2/faster_whisper.

## Verificação antes de concluir

- Backend: `pytest` verde; mudanças em pipeline/áudio merecem smoke test
  com o servidor rodando.
- Frontend: `npm run typecheck` e `npm test` verdes.
- Atualizar `docs/historico.md` / `docs/backlog.md` conforme protocolo.
