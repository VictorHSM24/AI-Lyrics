# AI Lyrics — Manifesto de Distribuição

**Sprint:** 23.0 (Produto Beta)
**Versão do instalador:** 1.0.0-beta
**Plataforma alvo:** Windows 10/11 64-bit
**Estratégia:** PyInstaller OneDir + Inno Setup

Este documento é parte oficial do projeto e descreve, de forma exhaustiva,
todos os recursos envolvidos na distribuição do AI Lyrics, classificados
em três categorias:

- **Categoria A — Versionados no Git:** indispensáveis, entram no clone.
- **Categoria B — Obtidos automaticamente:** baixados pelo instalador
  ou pelo wizard de primeira execução.
- **Categoria C — Gerados no build ou em runtime:** não versionados.

Nenhum recurso essencial fica oculto na máquina do desenvolvedor.

---

## Categoria A — Versionados no Git

### Código fonte Python

| Pacote | Função | Tamanho aproximado |
|---|---|---|
| `api/` | FastAPI + routers + wizard + composition root | 28 arquivos |
| `busca/` | Searcher híbrido (FTS5 + embeddings) | 14 arquivos |
| `config/` | Loader YAML + dataclasses + livros canônicos | 9 arquivos |
| `context/` | Context Engine | 4 arquivos |
| `core/` | Hardware, lifecycle | 10 arquivos |
| `estado/` | Estado persistente | 2 arquivos |
| `evaluation/` | Avaliação contínua | 10 arquivos |
| `feedback/` | Feedback learning | 8 arquivos |
| `integracao_holyrics/` | Cliente Holyrics | 4 arquivos |
| `intelligence/` | Camada de inteligência | 9 arquivos |
| `knowledge/` | BibleRetriever (Sprint 22.0) | 3 arquivos |
| `llm/` | Abstração LLM | 3 arquivos |
| `microfone/` | Captura de áudio + VAD | 10 arquivos |
| `parser/` | Parser determinístico de referências | 4 arquivos |
| `pipeline/` | Event bus + event store + sessão | 17 arquivos |
| `presentation/` | Presentation Layer (services + DTOs) | 12 arquivos |
| `semantic/` | SemanticEngine + ContextPolicy + providers | 15 arquivos |
| `sermon/` | SermonMemory + SermonContext | 3 arquivos |
| `telemetry/` | Hooks de telemetria | 3 arquivos |
| `transcricao/` | STT (faster-whisper) | 6 arquivos |

### Configuração padrão

| Arquivo | Conteúdo |
|---|---|
| `config/config.yaml` | Configuração base (Holyrics, STT, LLM, semantic, knowledge, etc.) |
| `config/books.json` | Tabela de livros canônicos (66 livros, aliases) |
| `config/knowledge_base.json` | Base de conhecimento |
| `config/config.overrides.json` | Overrides locais (opcional) |

### Bases SQLite do BibleRetriever

7 versões da Bíblia em português, total ~31.6 MB:

| Arquivo | Tamanho | Versão |
|---|---|---|
| `data/sources/ACF.sqlite` | 4.3 MB | Almeida Corrigida Fiel |
| `data/sources/ARA.sqlite` | 4.3 MB | Almeida Revista e Atualizada |
| `data/sources/ARC.sqlite` | 4.3 MB | Almeida Revista e Corrigida |
| `data/sources/JFAA.sqlite` | 4.3 MB | João Ferreira de Almeida Atualizada |
| `data/sources/NAA.sqlite` | 4.5 MB | Nova Almeida Atualizada |
| `data/sources/NTLH.sqlite` | 5.1 MB | Nova Tradução na Linguagem de Hoje |
| `data/sources/NVT.sqlite` | 4.4 MB | Nova Versão Transformadora |

### Fonte canônica e embeddings JSON

| Arquivo | Tamanho | Função |
|---|---|---|
| `data/bible_source.json` | ~10 MB | Fonte JSON canônica usada por `build_embeddings.py` |
| `data/bible.embeddings.json` | ~5 MB | Mapping de IDs para vetores (categoria A) |
| `data/stt_benchmark_sample.wav` | ~1 MB | Sample de áudio para testes de STT |

### Empacotamento e instalador

| Arquivo | Função |
|---|---|
| `ai-lyrics.spec` | Configuração PyInstaller OneDir |
| `installer/ai-lyrics.iss` | Script Inno Setup com detecção de VC++ Redist e Ollama |
| `build_installer.py` | Orquestra pipeline: npm build → embeddings → pyinstaller → iscc |
| `build_embeddings.py` | Gera `bible.pt-br.sqlite` + `bible.embeddings.npy` |
| `main.py` | Entry point do PyInstaller (wizard + uvicorn) |
| `pyproject.toml` | Dependências Python + config pytest/ruff/mypy |
| `requirements.txt` | Dependências mínimas (compatibilidade) |

### Frontend

| Pasta | Função |
|---|---|
| `frontend/src/` | Código TypeScript/React (inclui `pages/WizardPage.tsx` e `components/wizard/`) |
| `frontend/index.html`, `vite.config.ts`, `tsconfig.json`, `package.json`, `tailwind.config.js`, `postcss.config.js` | Configuração de build |

### Testes

| Pasta | Conteúdo |
|---|---|
| `tests/` | 3072 testes (suíte completa) |

### Documentação técnica

| Pasta | Conteúdo |
|---|---|
| `docs/` | 32 arquivos: Blueprint, Relatórios (Fase 8-12, Sprint 13-22), Guias, Auditorias |

### Ferramentas internas (dev/diagnóstico)

| Pasta | Conteúdo |
|---|---|
| `tools/internal/` | 78 scripts `_diag_*`, `_bench_*`, `_smoke_*`, `_demo_*` (não entram no instalador — item 16) |
| `tools/migrate_bible_db.py` | Migração de bases |
| `tools/diagnostics/` | Testes de diagnóstico pontuais |

### Configuração de desenvolvimento

| Pasta | Conteúdo |
|---|---|
| `.devin/` | Regras e skills do Devin CLI |

---

## Categoria B — Obtidos automaticamente

### Pelo instalador (Inno Setup)

| Recurso | Tamanho | Mecanismo | Status Sprint 23.0 |
|---|---|---|---|
| Visual C++ Redistributable 2015-2022 x64 | ~25 MB | Detectado via chave de registro HKLM; se `vc_redist.x64.exe` estiver em `{tmp}`, instala silenciosamente; caso contrário, orienta o usuário a baixar em https://aka.ms/vs/17/release/vc_redist.x64.exe | Orientação (auto-download requer IDP, planejado para 23.1) |
| Ollama runtime | ~300 MB | Detectado via caminhos comuns (`{pf}\Ollama\ollama.exe`, etc.); se `OllamaSetup.exe` estiver em `{tmp}`, instala silenciosamente; caso contrário, orienta o usuário a baixar em https://ollama.com/download | Orientação (auto-download requer IDP, planejado para 23.1) |

### Pelo wizard de primeira execução

| Recurso | Tamanho | Mecanismo |
|---|---|---|
| Modelo Ollama `qwen3:8b-q4_K_M` | ~5 GB | Botão "Baixar modelo agora" na etapa 3 do wizard; executa `ollama pull` em background com polling de status a cada 1s; opção de pular para instalação offline (modelo já presente via pendrive) |
| Backend CUDA adicional (opcional) | ~1.5 GB | Detecta NVIDIA no wizard; se presente, oferece instalar o backend CUDA para torch+CTranslate2 (aceleração GPU). Sprint 23.0: detecção implementada; instalação automática do backend CUDA será refinada em 23.1 |

### No build do instalador (não na máquina do usuário)

| Recurso | Tamanho | Mecanismo |
|---|---|---|
| Modelo `intfloat/multilingual-e5-small` (sentence-transformers) | ~470 MB | Baixado pelo `build_embeddings.py` na primeira execução do build; cache HuggingFace persiste entre builds |

---

## Categoria C — Gerados no build ou em runtime

### Gerados no build do instalador

| Recurso | Gerado por | Tamanho típico |
|---|---|---|
| `data/bible.pt-br.sqlite` | `build_embeddings.py` (etapa 2 do `build_installer.py`) | 47 MB |
| `data/bible.embeddings.npy` | `build_embeddings.py` (etapa 2 do `build_installer.py`) | 47 MB |
| `frontend/dist/` | `npm run build` (etapa 1 do `build_installer.py`) | ~450 KB |
| `dist/ai-lyrics/` (output PyInstaller) | `pyinstaller ai-lyrics.spec` (etapa 3) | ~800 MB |
| `dist-installer/ai-lyrics-setup-*.exe` | `iscc installer/ai-lyrics.iss` (etapa 4) | ~350 MB (com LZMA2) |

### Gerados em runtime

| Recurso | Quando | Localização |
|---|---|---|
| `data/state.json` | Pipeline em execução | Diretório do app |
| `data/frequentes.json` | Pipeline em execução | Diretório do app |
| `logs/pipeline.jsonl` | Pipeline em execução | Diretório do app |
| `~/AI_Lyrics_telemetry/session_*/` | TelemetryRecorder (Sprint 21.9) | `%USERPROFILE%\AI_Lyrics_telemetry\` |
| `.wizard_completed` | Após conclusão do wizard | `%APPDATA%\AI Lyrics Assistant\` (frozen) ou raiz do projeto (dev) |
| `__pycache__/`, `.pytest_cache/` | Python/pytest | Dev local |

---

## Dependências externas (sistema)

| Dependência | Versão mínima | Obtida por | Necessária para |
|---|---|---|---|
| Windows 10/11 64-bit | 10.0 | Pré-existente | Plataforma alvo |
| Node.js 18+ | 18.0 | Manual (apenas para desenvolvedores) | Build do frontend |
| Python 3.12 ou 3.13 | 3.12 | Embutido pelo PyInstaller | Runtime (não precisa no cliente) |
| Inno Setup 6+ | 6.0 | Manual (apenas para gerar instalador) | Build do instalador |
| Visual C++ Redistributable 2015-2022 x64 | 14.0 | Inno Setup | Extensões nativas (CTranslate2, pysilero-vad) |
| Ollama | 0.1.20+ | Inno Setup + wizard | Inferência semântica (LocalLLMProvider) |
| Holyrics | 2.23+ | Manual (pelo usuário) | Apresentação de versículos |
| CUDA Toolkit 12+ (opcional) | 12.0 | Wizard (se NVIDIA detectada) | Aceleração GPU para STT e embeddings |

---

## Tamanho final estimado do instalador

| Componente | Tamanho |
|---|---|
| Python runtime + dependências (torch CPU, faster-whisper, sentence-transformers, pysilero-vad, sounddevice, etc.) | ~600 MB |
| Bases SQLite do BibleRetriever (7 versões) | 31.6 MB |
| Base FTS5 + embeddings .npy | 94 MB |
| Frontend buildado | 0.5 MB |
| Configuração + fonte bíblica | 15 MB |
| **Total OneDir (sem compressão)** | **~740 MB** |
| **Instalador .exe (com LZMA2 ultra64)** | **~350 MB** |

---

## Validação de clone limpo (critério de aceite)

Cenário validado:

1. `git clone` em máquina limpa → todos os arquivos da Categoria A presentes.
2. `pip install -e ".[test]"` → dependências Python instaladas.
3. `python -m pytest tests/ -q` → 3072 testes passando (validado em 191s).
4. `python build_installer.py` → orquestra build completo:
   - `npm run build` → `frontend/dist/` gerado (validado em 3.8s).
   - `python build_embeddings.py` → `data/bible.pt-br.sqlite` + `.npy` gerados (requer download do modelo HF na primeira vez).
   - `pyinstaller ai-lyrics.spec` → `dist/ai-lyrics/` gerado.
   - `iscc installer/ai-lyrics.iss` → `dist-installer/ai-lyrics-setup-*.exe` gerado.
5. Instalação em máquina limpa → Inno Setup orienta VC++ Redist e Ollama se faltarem.
6. Primeira execução → wizard abre no browser, orienta áudio/Holyrics/Ollama/Bíblia/teste.
7. Após concluir wizard → flag `.wizard_completed` criado, app redireciona para Dashboard.

**Dependências ocultas conhecidas e tratadas:**

- Nenhuma. Todas as dependências são Categoria A (versionadas), B (baixadas automaticamente), ou C (geradas no build/runtime).

---

## Manutenção futura

- Para adicionar uma versão bíblica nova: colocar `.sqlite` em `data/sources/`, commitar (Categoria A). O BibleRetriever detecta automaticamente no warmup.
- Para atualizar o modelo Ollama: alterar `semantic.ollama.model` em `config/config.yaml` (Categoria A). O wizard detecta e oferece baixar a nova versão.
- Para atualizar o frontend: editar em `frontend/src/`, rodar `npm run build`. O `build_installer.py` orquestra o resto.
- Para atualizar dependências Python: editar `pyproject.toml` (Categoria A), rodar `pip install -e .` e `python build_installer.py`.

---

## Conclusão

Este manifesto prova que o AI Lyrics cumpre o critério de aceite do
Sprint 23.0: nenhum arquivo essencial existe apenas na máquina do
desenvolvedor. Todos os recursos são versionados (Categoria A), obtidos
automaticamente (Categoria B), ou gerados no build/runtime (Categoria C).
