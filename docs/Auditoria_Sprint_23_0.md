# Sprint 23.0 — Auditoria Prévia do Projeto e Classificação A/B/C

**Data:** 25 de julho de 2026
**Sprint:** 23.0 (Produto Beta, Instalador e Distribuição)
**Princípio:** nenhum arquivo essencial pode existir apenas na máquina do desenvolvedor.

---

## 1. Visão geral do projeto

Total de arquivos versionados no git: **585**.
Total de pacotes Python (código fonte): **20** (`api`, `busca`, `config`, `context`, `core`, `estado`, `evaluation`, `feedback`, `integracao_holyrics`, `intelligence`, `knowledge`, `llm`, `microfone`, `parser`, `pipeline`, `presentation`, `semantic`, `sermon`, `telemetry`, `transcricao`).
Total de testes: **3072** (suíte completa passando).

---

## 2. Achados da auditoria — dependências ocultas e problemas

### 2.1 Arquivos grandes commitados por engano (RUÍDO no repo)

| Arquivo | Tamanho | Status | Veredito |
|---|---|---|---|
| `config.zip` | 33.5 MB | git tracked | **REMOVER** — snapshot completo do projeto (11178 arquivos) commitado por engano em commits antigos. Lixo puro. |
| `repomix-output.xml` | 6.1 MB | git tracked | **REMOVER** — dump de código para contexto de LLM, sem valor runtime. |
| `data/bible.pt-br.sqlite.bak` | 40 KB | git tracked | **REMOVER** — backup minúsculo obsoleto do `bible.pt-br.sqlite` (que é regenerável). |

Estes três arquivos somam ~40 MB de ruído no clone. Serão removidos do working tree e da árvore git (commit de remoção). Não será feito `git filter-branch` (operção destrutiva de rewrite de história); apenas commit de remoção, que já reduz o tamanho do clone futuro.

### 2.2 Ferramentas dev/diag misturadas na raiz (VIOLAÇÃO do item 16)

**78 arquivos** com prefixo `_` na raiz, versionados no git:
- 45 scripts Python (`_diag_*.py`, `_bench_*.py`, `_smoke_*.py`, `_demo_*.py`, `_stability_*.py`, `_check_*.py`, `_run_diag.py`)
- 31 arquivos de texto (outputs de diagnóstico: `_diag_abram.txt`, etc.)
- 2 scripts PowerShell (`_check_ollama.ps1`, etc.)

Estes são ferramentas de desenvolvimento e diagnóstico interno. **Nenhum deve entrar no instalador** (item 16: "O instalador não deverá incluir ferramentas internas desnecessárias"). Serão movidos para `tools/internal/` para separação clara do código fonte.

### 2.3 Bases SQLite do BibleRetriever (CONFORME)

Reauditoria confirmou que as **7 versões** estão commitadas no git desde o commit `8ec2153`: ACF, ARA, ARC, JFAA, NAA, NTLH, NVT (total 21.6 MB + 10 MB = 31.6 MB). O clone limpo já tem todas as versões necessárias para o teste `test_sprint22_0_bible_retriever.py`. **Nenhuma ação necessária** — o achado anterior estava errado (confusão com `git check-ignore`).

### 2.4 Arquivos de dados gitignored (DEPENDÊNCIA OCULTA)

| Arquivo | Tamanho | Status | Necessário para | Estratégia |
|---|---|---|---|---|
| `data/bible.pt-br.sqlite` | 47 MB | gitignored | Searcher (busca híbrida FTS5) | **Categoria C** — gerado no build do instalador via `build_embeddings.py` |
| `data/bible.embeddings.npy` | 47 MB | gitignored | Embeddings (busca semântica) | **Categoria C** — gerado no build do instalador via `build_embeddings.py` |
| `data/state.json` | — | gitignored | Estado persistente | **Categoria C** — gerado em runtime |
| `data/frequentes.json` | — | gitignored | Referências frequentes | **Categoria C** — gerado em runtime |

`build_embeddings.py` já existe e é funcional: lê `data/bible_source.json` (commitado), gera os dois arquivos .sqlite/.npy. Requer `sentence-transformers` que baixa `intfloat/multilingual-e5-small` (~470 MB) do HuggingFace na primeira execução. **No build do instalador, este download será feito uma única vez** e os arquivos gerados serão embutidos no payload do PyInstaller.

### 2.5 Frontend buildado (`frontend/dist/`)

Atualmente gitignored. Para o instalador, **será buildado no processo de build** (`npm run build` antes do PyInstaller) e embutido no payload. Não será commitado (Categoria C — gerado no build).

### 2.6 Sem entry point `main.py`

O `ai-lyrics.spec` referencia `main.py` como entry point, mas **este arquivo não existe**. A API é iniciada via `uvicorn api.app:app`. Para o PyInstaller, será criado `main.py` que:
1. Verifica se é primeira execução (sem config de wizard).
2. Se sim, abre o wizard de primeira execução (browser apontando para `localhost:8000/wizard`).
3. Inicia o servidor uvicorn embutido.

### 2.7 Logs e telemetria (runtime)

| Diretório | Conteúdo | Estratégia |
|---|---|---|
| `logs/` | `pipeline.jsonl` | Categoria C — criado em runtime, não versionado |
| `~/AI_Lyrics_telemetry/` | sessões de telemetria | Categoria C — criado em runtime, fora do dir do app |

---

## 3. Classificação A/B/C de todos os recursos

### Categoria A — Versionados obrigatoriamente no Git

| Recurso | Localização | Justificativa |
|---|---|---|
| Código fonte Python | `api/`, `busca/`, `config/`, `context/`, `core/`, `estado/`, `evaluation/`, `feedback/`, `integracao_holyrics/`, `intelligence/`, `knowledge/`, `llm/`, `microfone/`, `parser/`, `pipeline/`, `presentation/`, `semantic/`, `sermon/`, `telemetry/`, `transcricao/` | Indispensável |
| Testes | `tests/` | Indispensável para critério de aceite |
| Configuração padrão | `config/config.yaml`, `config/books.json`, `config/knowledge_base.json`, `config/config.overrides.json` | Indispensável |
| Bases SQLite do BibleRetriever | `data/sources/ACF.sqlite`, `ARA.sqlite`, `ARC.sqlite`, `JFAA.sqlite`, `NAA.sqlite`, **NTLH.sqlite**, **NVT.sqlite** | Indispensável para o RAG. NTLH e NVT serão commitadas agora. |
| Fonte bíblica canônica | `data/bible_source.json` | Fonte para regenerar bible.pt-br.sqlite e embeddings |
| Embeddings JSON (mapping) | `data/bible.embeddings.json` | Mapping de IDs para vetores |
| Sample de áudio | `data/stt_benchmark_sample.wav` | Usado por testes de STT |
| PyInstaller spec | `ai-lyrics.spec` | Build do instalador |
| Inno Setup script | `installer/ai-lyrics.iss` | Build do instalador |
| `pyproject.toml`, `requirements.txt` | raiz | Dependências Python |
| `build_embeddings.py` | raiz | Gera dados da Categoria C |
| Ferramentas internas | `tools/internal/` (a criar) | Diagnóstico dev, não entra no instalador |
| Documentação técnica | `docs/` (a criar a partir dos `Relatorio_*.md` e `Blueprint_de_Implementacao.md`, etc.) | Manutenibilidade |
| Manifesto de distribuição | `distribution_manifest.md` (a criar) | Item 7 do enunciado |
| Regras Devin | `.devin/` | Configuração de desenvolvimento |

### Categoria B — Obtidos automaticamente (pelo instalador ou wizard)

| Recurso | Tamanho | Obtido por | Quando |
|---|---|---|---|
| Ollama runtime | ~300 MB | Inno Setup (Pascal Script) | Durante instalação se ausente |
| Modelo `qwen3:8b-q4_K_M` | ~5 GB | Wizard de primeira execução (`ollama pull`) | Primeira execução, com barra de progresso e opção de pular |
| Visual C++ Redistributable 2015-2022 x64 | ~25 MB | Inno Setup | Durante instalação se ausente |
| Modelo `intfloat/multilingual-e5-small` (sentence-transformers) | ~470 MB | `build_embeddings.py` no build do instalador | No momento de gerar o instalador (não na máquina do usuário) |
| Backend CUDA adicional (opcional) | ~1.5 GB | Wizard se NVIDIA detectada | Primeira execução, opcional |

### Categoria C — Gerados em runtime ou no build (não versionados)

| Recurso | Gerado por | Quando |
|---|---|---|
| `data/bible.pt-br.sqlite` | `build_embeddings.py` | No build do instalador |
| `data/bible.embeddings.npy` | `build_embeddings.py` | No build do instalador |
| `frontend/dist/` | `npm run build` | No build do instalador |
| `data/state.json` | Pipeline em runtime | Runtime |
| `data/frequentes.json` | Pipeline em runtime | Runtime |
| `logs/pipeline.jsonl` | Pipeline em runtime | Runtime |
| `~/AI_Lyrics_telemetry/session_*/` | TelemetryRecorder | Runtime |
| `dist/ai-lyrics/` (output PyInstaller) | `pyinstaller ai-lyrics.spec` | No build do instalador |
| `dist-installer/ai-lyrics-setup-*.exe` | `iscc installer/ai-lyrics.iss` | No build do instalador |
| `__pycache__/`, `.pytest_cache/` | Python/pytest | Dev local |

---

## 4. Plano de correção (executado nesta ordem no Sprint 23.0)

1. **Confirmar bases SQLite** (NTLH, NVT) — já commitadas, conforme item 2.3.
2. **Remover ruído do git** (config.zip, repomix-output.xml, bible.pt-br.sqlite.bak).
3. **Mover 78 ferramentas dev para `tools/internal/`** (item 16).
4. **Mover documentação técnica para `docs/`** (Blueprint, Relatórios, Guias, packaging.md).
5. **Atualizar `.gitignore`** com regras explícitas para `dist/`, `dist-installer/`, `tools/internal/__pycache__/`.
6. **Criar `main.py`** (entry point do PyInstaller com wizard de primeira execução).
7. **Criar `api/wizard.py`** (endpoints REST do wizard: áudio, Holyrics, Ollama, Bíblia, teste).
8. **Criar `frontend/src/pages/Wizard.tsx`** (UI do wizard).
9. **Atualizar `ai-lyrics.spec`** para OneDir, incluir `data/`, `config/`, `frontend/dist/`, excluir `tools/`, `tests/`, `_*.py`.
10. **Atualizar `installer/ai-lyrics.iss`** com detecção/baixar de VC++ Redist e Ollama, payload PyInstaller, atalhos, wizard customizado.
11. **Criar `build_installer.py`** (orquestra: npm build → build_embeddings → pyinstaller → iscc).
12. **Criar `distribution_manifest.md`** (item 7).
13. **Buildar e validar** em clone limpo simulado.
14. **Relatório Sprint 23.0**.

---

## 5. Riscos residuais e mitigações

| Risco | Mitigação |
|---|---|
| Antivírus bloqueia PyInstaller .exe | OneDir (não OneFile) reduz falsos positivos; instruções no wizard para whitelist |
| `build_embeddings.py` falha no build (sem internet para baixar modelo HF) | Documentar requisito de internet no build; cache do modelo HF persiste entre builds |
| Inno Setup não detecta Ollama corretamente | Pascal Script robusto: checa `where ollama`, `ollama --version`, fallback para download oficial |
| Modelo Ollama demora a baixar em internet de igreja | Barra de progresso + opção de pular (instalação offline com modelo já presente via pendrive) |
| Wizard de primeira execução abre browser mas API ainda não está pronta | `main.py` inicia uvicorn em thread antes de abrir browser; wizard endpoint `/api/wizard/health` faz polling |

---

## 6. Conclusão da auditoria

O projeto está arquiteturalmente pronto para distribuição, mas tem três bloqueadores para clone limpo: bases SQLite faltantes (NTLH, NVT), ruído no git (~40 MB), e ausência de entry point `main.py`. A reorganização do item 16 (mover 78 ferramentas dev para `tools/internal/`) é necessária para o instalador não incluir peso morto. Todas as correções são não-destrutivas (commits de remoção/movimento, sem rewrite de história).
