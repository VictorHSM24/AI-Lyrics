# Guia de Desenvolvimento — Assistente de IA Local para Versículos no Holyrics

> Versão: 1.0 · Data: 2026-07-13
> Documentos de referência:
> - `DOCUMENTACAO_TECNICA.md` (arquitetura v2.0)
> - `Plano_de_Implementacao.md` (fases MVP → Release)
> - `Blueprint_de_Implementacao.md` (especificação por módulo)
>
> Este documento é o **manual oficial de convenções** do projeto. Toda contribuição deve segui-lo. Conflitos entre este guia e qualquer outro documento devem ser resolvidos a favor deste guia em questões de estilo/convenção, e a favor da arquitetura em questões de design.

---

## 1. Padrões de Nomenclatura

### 1.1 Geral

| Elemento | Convenção | Exemplo |
|---|---|---|
| Arquivos Python | `snake_case.py` | `capture.py`, `state.py`, `pipeline.py` |
| Diretórios | `snake_case` | `integracao_holyrics/`, `core/` |
| Classes | `PascalCase` | `MicrophoneCapture`, `BibleStateManager` |
| Funções / métodos | `snake_case` | `def parse(self, text):` |
| Variáveis | `snake_case` | `c_stt`, `book_id`, `avg_logprob` |
| Constantes | `UPPER_SNAKE_CASE` | `MIN_SPEECH_MS`, `RRF_K_DEFAULT` |
| Dataclasses | `PascalCase`, campos em `snake_case` | `@dataclass class Intent: action: Action` |
| Enums / Literals | `PascalCase`, valores em `lower_snake` | `Literal["show","next","previous"]` |
| Arquivos de dados | `kebab-case.ext` | `bible.pt-br.sqlite`, `pipeline.jsonl` |
| Arquivos de config | `snake_case.yaml/json` | `config.yaml`, `books.json` |

### 1.2 Nomes de domínio

Para consistência com a arquitetura, usar sempre estes termos:

| Termo | Significado | Não usar |
|---|---|---|
| `Intent` | intenção interpretada (parser ou LLM) | "command", "request" |
| `VerseRef` | referência bíblica resolvida | "verse", "reference" (ambíguo) |
| `SearchResult` | resultado de busca híbrida | "match", "hit" |
| `Confidence` | confianças multi-etapa | "score" (ambíguo) |
| `Decision` | decisão final do motor | "result", "outcome" (use `outcome` só para o campo) |
| `Utterance` | texto transcrito + c_stt | "transcription", "text" |
| `c_stt`, `c_intent`, `c_search`, `c_final` | confianças por etapa | `stt_conf`, `confidence_stt` |
| `book_id` | ID 1..66 | `book_number`, `bid` |
| `BBCCCVVV` | formato de ID do Holyrics | "holyrics_id", "verse_code" |

### 1.3 Prefixos e sufixos

| Sufixo | Uso | Exemplo |
|---|---|---|
| `Manager` | gerencia estado/ciclo de vida | `BibleStateManager`, `ConfidenceManager` |
| `Client` | cliente externo (HTTP, LLM) | `HolyricsClient`, `LLMClient` |
| `Capture` | captura de I/O contínua | `MicrophoneCapture` |
| `Embedder` | codificador de embeddings | `Embedder` |
| `Searcher` | buscador | `Searcher` |
| `Parser` | parser determinístico | `Parser` |
| `Logger` | logger estruturado | `PipelineLogger` |
| `Error` | exceção de domínio | `ConfigError`, `STTError`, `HolyricsError` |

Não usar `Helper`, `Util`, `Utils`, `Manager` para classes estáticas (preferir funções livres em módulo).

---

## 2. Organização de Diretórios

### 2.1 Estrutura canônica

A estrutura de diretórios é **fixa** e definida pela arquitetura (§16 da doc. técnica). Reproduzida aqui para referência:

```
ai-lyrics/
├── config/           # config.yaml, books.json, models.py, books.py, loader.py, __init__.py
├── data/             # artefatos de build (sqlite, npy, json) — não versionar binários
├── microfone/        # captura + VAD
├── transcricao/      # faster-whisper
├── parser/           # normalizer, books, parser
├── llm/              # client, prompts
├── busca/            # indexer, embeddings, searcher
├── estado/           # state
├── cache/            # cache
├── confidence/       # manager
├── integracao_holyrics/  # client
├── interface/        # tray
├── logs/             # pipeline.jsonl (runtime, .gitignore)
├── core/             # types, pipeline, decision, config
├── tests/            # test_*.py, paráfrases.json
├── scripts/          # build_index.py, benchmark.py
├── docs/             # DOCUMENTACAO_TECNICA.md, Plano, Blueprint, este Guia
├── requirements.txt
├── README.md
└── .gitignore
```

### 2.2 Regras

1. **Um módulo = um diretório.** Cada diretório de módulo contém apenas os arquivos especificados no Blueprint. Não criar subdiretórios arbitrários.
2. **`core/` é para código transversal:** `types.py` (tipos canônicos), `pipeline.py` (orquestrador), `decision.py` (motor). Nenhum outro módulo define tipos em `core/`. O loader de configuração vive em `config/loader.py` (não em `core/`).
3. **`data/` contém apenas artefatos gerados.** Não versionar `bible.pt-br.sqlite`, `bible.embeddings.npy`, `state.json`, `frequentes.json` — adicionar ao `.gitignore`. Versionar apenas `bible_source.json` (input) se a licença permitir.
4. **`logs/` é runtime.** Adicionar `logs/*.jsonl` ao `.gitignore`.
5. **`tests/` espelha a estrutura de módulos:** `test_parser.py` testa `parser/`, `test_search.py` testa `busca/`, etc.
6. **`scripts/` é para CLIs offline:** build, benchmark. Não importar de `scripts/` em módulos de produção.
7. **`docs/` contém apenas documentação.** Nenhum código executável.

### 2.3 `__init__.py`

Cada diretório de módulo deve ter `__init__.py` expondo apenas a interface pública:

```python
# parser/__init__.py
from parser.parser import Parser
__all__ = ["Parser"]
```

Não expor internals (`Normalizer`, regex patterns, etc.).

---

## 3. Estilo de Código

### 3.1 Padrão

- **Python 3.11+** (necessário para `type | None` syntax e `Literal`).
- **PEP 8** como base, com as exceções abaixo.
- **Line length: 100 caracteres** (não 79).
- **Indentação: 4 espaços** (sem tabs).
- **Aspas: duplas (`"`) para strings** (consistência com f-strings e JSON).
- **Imports:**
  1. stdlib
  2. terceiros
  3. projeto (cada grupo separado por linha em branco)
  4. dentro do projeto: absolutos (`from parser.parser import Parser`, não `from .parser import Parser`)

### 3.2 Ferramentas

| Ferramenta | Uso | Config |
|---|---|---|
| `ruff` | linter + formatter | `line-length = 100`, regras `E,W,F,I,UP,B,SIM` |
| `mypy` | type checker | `strict = true`, `disallow_untyped_defs = true` |
| `isort` (via ruff) | ordenação de imports | `profile = "black"` |

### 3.3 Regras específicas

- **Sem `print()` em código de produção.** Usar `logging` ou `PipelineLogger`. `print` permitido apenas em `scripts/`.
- **Sem `# type: ignore`** sem justificativa em comentário adjacente.
- **Sem `Any`** em interfaces públicas. Usar tipos específicos ou `object` com `isinstance`.
- **Sem `dict` opaco** em contratos entre módulos. Usar dataclasses de `core/types.py`.
- **f-strings** para formatação (não `%` nem `.format()`).
- **Comprehensions** quando legíveis; senão, loop explícito.
- **Early return** para reduzir aninhamento.
- **Não usar mutable default arguments:** `def f(x: list = [])` → `def f(x: list | None = None): if x is None: x = []`.

### 3.4 Exemplo canônico

```python
"""Parser determinístico para comandos de versículo."""

from __future__ import annotations

import re

from config.books import BookTable
from core.types import BibleState, Intent
from parser.normalizer import Normalizer


class Parser:
    """Interpreta comandos estruturados sem LLM."""

    def __init__(self, books: BookTable) -> None:
        self._norm = Normalizer()
        self._books = books
        self._patterns = self._compile_patterns()

    def parse(self, text: str, state: BibleState | None = None) -> Intent:
        norm = self._norm.normalize(text)
        for pattern, handler, confidence in self._patterns:
            m = pattern.match(norm)
            if m:
                return handler(m, state, confidence)
        return Intent(action="none", raw=text)
```

---

## 4. Princípios Arquiteturais

### 4.1 Princípios obrigatórios

1. **Parser-first, LLM fallback.** Comandos estruturados são resolvidos por parser determinístico; o LLM só é invocado quando o parser devolve `uncertain`. (Doc. técnica §1.3)
2. **LLM nunca controla o Holyrics.** O LLM só produz JSON; um motor de decisão determinístico valida e executa. (Doc. técnica §11)
3. **Tudo offline.** Nenhuma chamada de rede externa. A única rede é HTTP local para o Holyrics e para o servidor LLM (Ollama/llama.cpp em localhost). (Doc. técnica §0)
4. **Pipeline assíncrono** com `asyncio.Queue` em processo único. (Doc. técnica §18)
5. **Auditável.** Cada execução grava `LogEntry` em JSONL com timing e confiança por etapa. (Doc. técnica §13)
6. **Confidence Manager multi-etapa.** Combinação multiplicativa de `c_stt`, `c_intent`, `c_search`. (Doc. técnica §8)
7. **Busca híbrida.** FTS5 + embeddings + RRF. Não FTS5 puro, não embeddings puros. (Doc. técnica §5)
8. **Holyrics API REST oficial.** Não AutoHotkey, não OCR, não automação de UI. (Doc. técnica §9)

### 4.2 Princípios de design

1. **Responsabilidade única.** Cada módulo tem uma responsabilidade clara definida no Blueprint. Não adicionar responsabilidades extras a um módulo existente — criar novo módulo ou estender no Blueprint.
2. **Dependência unidirecional.** Módulos de baixo nível (`config`, `data`, `logs`) não importam de módulos de alto nível (`core`, `interface`). Verificar com `import-linter`.
3. **Sem estado global.** Exceto `BookTable` (singleton explícito via `config.load_books()`), nenhum módulo mantém estado global. Estado é passado por parâmetro ou gerenciado por `BibleStateManager`.
4. **Fallback gracioso.** Toda falha externa (LLM, Holyrics, embeddings) degrada graciosamente — o pipeline continua, mesmo que com funcionalidade reduzida.
5. **Lazy loading.** Modelos pesados (LLM, embeddings) são carregados sob demanda, não no startup.
6. **Configuração externalizada.** Nenhum valor mágico no código. Tudo em `config.yaml` ou constantes nomeadas.

### 4.3 Módulos que não devem ser contornados

| Regra | Motivo |
|---|---|
| `core/pipeline` é o único que chama `llm`, `busca`, `integracao_holyrics` | Evita chamadas diretas que contornam o Confidence Manager |
| `core/decision` é o único que coordena `estado` + `busca` + `cache` + `confidence` | Centraliza a lógica de segurança |
| `core/types` é o único que define `Intent`, `VerseRef`, etc. | Garante contratos consistentes |
| `config` é o único que lê YAML/JSON de config | Nenhum módulo lê config diretamente |

---

## 5. Uso de Tipagem

### 5.1 Regras

- **Type hints obrigatórias** em todas as funções e métodos públicos.
- **`mypy --strict`** deve passar sem erros.
- **Usar tipos de `core/types.py`** em todos os contratos entre módulos. Não criar tipos paralelos.
- **`dataclass`** para todos os tipos de domínio (`Intent`, `VerseRef`, etc.).
- **`Literal`** para enums fechados (`Action`, `outcome`).
- **`| None`** (não `Optional[T]`) para opcionais.
- **Sem `Any`** em interfaces públicas.

### 5.2 Exemplos

```python
# correto
def parse(self, text: str, state: BibleState | None = None) -> Intent: ...

# incorreto
def parse(self, text, state=None): ...  # sem hints
def parse(self, text: Any) -> dict: ...  # Any + dict opaco
def parse(self, text: str) -> Optional[Intent]: ...  # Optional em vez de | None
```

### 5.3 Tipos canônicos (não redefinir)

Definidos em `core/types.py` (Blueprint §0.1):
- `Action` (Literal)
- `Intent` (dataclass)
- `VerseRef` (dataclass com `id` e `reference` properties)
- `SearchResult` (dataclass)
- `Confidence` (dataclass com `c_final` property)
- `Decision` (dataclass)
- `LogEntry` (dataclass)
- `Utterance` (dataclass)
- `UtteranceAudio` (dataclass)

Definidos em `config/models.py` (Blueprint §1) — igualmente canônicos, não redefinir:
- `Config` (dataclass raiz)
- `HolyricsConfig`, `STTConfig`, `VadConfig`, `LLMConfig`, `SearchConfig`, `StateConfig`, `CacheConfig`, `ConfidenceConfig`, `LogConfig` (dataclasses de seção)

Definidos em `config/books.py` (Blueprint §1) — igualmente canônicos, não redefinir:
- `Book` (dataclass frozen)
- `BookMatch` (dataclass)
- `BookTable` (classe com `resolve`, `by_id`, `all_books`)

---

## 6. Documentação do Código

### 6.1 Docstrings

- **Todas as funções e classes públicas** devem ter docstring.
- **Formato: Google style** (succinto, com `Args:`, `Returns:`, `Raises:` apenas quando não óbvio).
- **Uma linha** para funções triviais; **multilinha** para APIs públicas de módulo.

```python
def search(self, query: str, top_k: int = 20) -> list[SearchResult]:
    """Busca híbrida por versículos.

    Combina FTS5 (lexical) e embeddings (semântico) via RRF.

    Args:
        query: frase de busca (ex.: "Deus amou o mundo").
        top_k: número máximo de resultados.

    Returns:
        Resultados ordenados por score combinado; o primeiro é o melhor.
    """
```

### 6.2 Comentários

- **Não comentar o óbvio.** Código limpo > comentário.
- **Comentar decisões não óbvias** (ex.: por que `rrf_k=60`, por que multiplicação em vez de média para `c_final`).
- **Não remover comentários existentes** sem entender o motivo.
- **TODOs** devem ter issue link: `# TODO(#42): calibrar c_stt com áudio real`.

### 6.3 Headers de arquivo

Cada arquivo `.py` começa com docstring de uma linha:

```python
"""Parser determinístico para comandos de versículo."""
```

---

## 7. Logging

### 7.1 Dois canais

| Canal | Uso | Destino |
|---|---|---|
| `PipelineLogger` (JSONL) | log estruturado de cada execução do pipeline | `logs/pipeline.jsonl` |
| `logging` (stdlib) | log de aplicação (startup, warnings, erros) | stderr + arquivo rotativo |

### 7.2 `PipelineLogger`

- Uma linha JSONL por execução do pipeline (não por etapa).
- Schema: `LogEntry` em `core/types.py` (Blueprint §0.1).
- Campos obrigatórios: `ts`, `id`, `total_ms`, `stt`, `parser`, `llm`, `search`, `confidence`, `decision`, `holyrics`, `cache`.
- Campos de etapa incluem `duration_ms` e métricas específicas (`c_stt`, `c_parser`, `matched`, etc.).
- `flush()` após cada write (não perder logs em crash).

### 7.3 `logging` (stdlib)

```python
import logging
logger = logging.getLogger(__name__)  # nome do módulo

logger.info("STT model loaded", extra={"model": "turbo", "vram_mb": 2900})
logger.warning("Embeddings unavailable, falling back to FTS5 only")
logger.error("Holyrics timeout", exc_info=True)
```

- Níveis: `DEBUG` (desenvolvimento), `INFO` (startup/shutdown), `WARNING` (fallback/degradação), `ERROR` (falha recuperável), `CRITICAL` (falha não recuperável).
- **Sem PII** em logs (texto transcrito do pregador pode ir no JSONL estruturado, mas não em logs de aplicação que vão para stderr).
- Formato: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`.

### 7.4 Proibições

- **Sem `print()`** em código de produção (use `logging`).
- **Sem `logging.basicConfig`** em módulos de biblioteca (só no entrypoint `main.py`).
- **Sem logs verbosos em loop quente** (captura de áudio, VAD) — usar `DEBUG` e desativar por default.

---

## 8. Tratamento de Exceções

### 8.1 Hierarquia de exceções de domínio

```python
# core/exceptions.py
class AILyricsError(Exception):
    """Base para todas as exceções do projeto."""

class ConfigError(AILyricsError): ...
class AudioError(AILyricsError): ...
class STTError(AILyricsError): ...
class LLMError(AILyricsError): ...
class SearchError(AILyricsError): ...
class StateError(AILyricsError): ...
class HolyricsError(AILyricsError): ...
```

Cada módulo levanta sua exceção específica. O pipeline captura `AILyricsError` no topo para não derrubar o sistema.

### 8.2 Regras

1. **Levantar exceções de domínio**, não `Exception` ou `RuntimeError` genéricos.
2. **Mensagens com contexto:** `ConfigError(f"missing env var: {name}")`, não `ConfigError("error")`.
3. **Capturar no ponto certo:**
   - Módulo de baixo nível: propaga (não captura).
   - `core/pipeline`: captura `AILyricsError` por etapa e loga (não derruba).
   - `core/decision`: captura `StateError`/`SearchError` e vira `Decision(outcome="ignore")`.
4. **Sem `except:` bare.** Usar `except AILyricsError:` ou `except (TimeoutError, ConnectionError):`.
5. **Sem `except Exception: pass`.** Se capturar, logar com `exc_info=True`.
6. **`try` o mais específico possível** — não envolver funções inteiras se só uma linha pode falhar.
7. **`raise ... from err`** para preservar causa:
   ```python
   try:
       resp = requests.post(...)
   except requests.Timeout as e:
       raise HolyricsError(f"timeout calling {action}") from e
   ```

### 8.3 Fallback obrigatório

| Falha | Fallback |
|---|---|
| LLM indisponível/timeout | `Intent(action="none")`; pipeline continua só com parser |
| Embeddings indisponíveis | busca FTS5 pura + warning |
| Holyrics timeout | log + não exibir; pipeline continua |
| STT erro (CUDA OOM) | `STTError`; pipeline para graciosamente |
| `state.json` corrompido | ignora + warning + estado vazio |
| `frequentes.json` corrompido | ignora + warning + vazio |

---

## 9. Gerenciamento de Configuração

### 9.1 Fonte única

- **`config/config.yaml`** é a única fonte de configuração.
- **`config/books.json`** é a única fonte da tabela de livros.
- Nenhum módulo lê YAML/JSON diretamente — todos recebem `Config` ou `BookTable` por injeção.

### 9.2 Variáveis de ambiente

- Segredos (token do Holyrics) via `${HOLYRICS_TOKEN}` no YAML, substituído por `os.environ` no loader.
- **Nunca** hardcodear tokens no código ou no YAML commitado.
- `.env` suportado opcionalmente (via `python-dotenv`), mas não versionado.

### 9.3 Schema de `config.yaml`

Definido no Blueprint §0.3. Seções: `holyrics`, `stt`, `llm`, `search`, `state`, `cache`, `confidence`, `mode`, `log`.

### 9.4 Validação

- `load_config()` valida campos obrigatórios e tipos no startup.
- Campo obrigatório ausente → `ConfigError` com mensagem apontando o campo.
- Valores fora de range (ex.: `min_execute > 1.0`) → `ConfigError`.

### 9.5 Hot-reload (parcial)

- `config.yaml` e `books.json` suportam hot-reload via sinal `SIGHUP` (ou botão no tray).
- Limiares de confidence e pesos RRF podem ser ajustados sem reiniciar o pipeline.
- Modelo STT/LLM **não** suportam hot-reload (requer restart).

---

## 10. Injeção de Dependência

### 10.1 Princípio

Módulos recebem suas dependências pelo construtor, não as instanciam internamente. Exceção: `Config` e `BookTable` podem ser passadas ou acessadas via factory central.

### 10.2 Padrão

```python
# correto
class Searcher:
    def __init__(self, config: Config, embedder: Embedder, cache: Cache) -> None:
        self._db = sqlite3.connect(config.search.fts5_db)
        self._embedder = embedder
        self._cache = cache

# incorreto
class Searcher:
    def __init__(self) -> None:
        self._config = load_config()           # acoplado ao loader
        self._embedder = Embedder()            # instanciado internamente
        self._cache = Cache()                  # instanciado internamente
```

### 10.3 Composição no pipeline

`core/pipeline.py` é o **único** ponto que instancia todos os módulos e os conecta:

```python
class Pipeline:
    def __init__(self, config: Config) -> None:
        books = load_books(config.books_path)
        cache = Cache(config)
        state = BibleStateManager(books, config.state.persist_path)
        embedder = Embedder(config)
        searcher = Searcher(config, embedder, cache)
        confidence = ConfidenceManager(config)
        holyrics = HolyricsClient(config, cache)
        parser = Parser(books)
        llm = LLMClient(config, books)
        logger = PipelineLogger(config.log.path)
        self._decision = DecisionEngine(books, state, searcher, cache, confidence)
        # ... tasks
```

### 10.4 Testes

Em testes, injetar mocks/fakes:

```python
def test_searcher_with_fake_embedder():
    fake_embedder = FakeEmbedder(dim=384)
    fake_cache = FakeCache()
    searcher = Searcher(test_config, fake_embedder, fake_cache)
    results = searcher.search("deus amou o mundo")
    assert results[0].ref.book_id == 43  # João
```

---

## 11. Convenções para Eventos

### 11.1 Fila asyncio

- Toda comunicação entre tasks do pipeline é por `asyncio.Queue` com payloads tipados (Blueprint §0.2).
- **Não usar callbacks** entre tasks — preferir queues para desacoplar.
- **Não usar `asyncio.Event`** para dados — só para sinais (stop, pause).

### 11.2 Eventos canônicos

| Evento | Tipo | Produtor | Consumidor |
|---|---|---|---|
| `AudioChunk` | `bytes` (PCM) | `microfone` | `transcricao` |
| `UtteranceAudio` | `dataclass` | `microfone` | `transcricao` |
| `Utterance` | `dataclass` | `transcricao` | `core/pipeline` |
| `Intent` | `dataclass` | `parser`/`llm` | `core/pipeline` |
| `Decision` | `dataclass` | `core/decision` | `core/pipeline` |

### 11.3 Regras

- **Eventos são imutáveis** (dataclass `frozen=True` onde aplicável).
- **Cada queue tem um produtor e um consumidor** (1:1). Não publicar em múltiplas queues.
- **Tamanho de queue limitado** (`asyncio.Queue(maxsize=N)`) para evitar OOM em backpressure:
  - `audio_queue`: `maxsize=10` (5 s de áudio)
  - `utterance_queue`: `maxsize=20`
- **Poison pill para shutdown:** `None` na queue sinaliza fim.

---

## 12. Convenções para JSON

### 12.1 Saída do LLM

- Schema definido no Blueprint §4.4 e doc. técnica §4.4.
- Validado por `validate()` em `llm/client.py` (Blueprint §6).
- Campos obrigatórios: `action`. Condicional: `book` se `show`, `query` se `search`, `amount` se `next`/`previous`.
- **Nunca aceitar `verse` direto do LLM** para `action=show` sem validar contra `BookTable`.

### 12.2 `LogEntry` (JSONL)

- Uma linha por execução, `json.dumps(asdict(entry))`.
- Sem pretty-print (uma linha por entrada).
- Campos de etapa sempre presentes (mesmo se etapa não executou — preencher com `{"used": false, "duration_ms": 0}`).

### 12.3 Arquivos de dados JSON

| Arquivo | Schema |
|---|---|
| `books.json` | `list[{id, canonical, aliases}]` |
| `bible_source.json` | `list[{book, book_id, chapter, verse, text, version}]` |
| `frequentes.json` | `{"BBCCCVVV": count}` |
| `state.json` | `{book_id, chapter, verse, version, last_shown_at}` |
| `tests/paráfrases.json` | `list[{query, expected_id, expected_ref}]` |

### 12.4 Regras

- **Indentação: 2 espaços** em arquivos JSON commitados (human-readable).
- **Sem trailing commas** (JSON válido).
- **UTF-8** com BOM opcional (preferir sem BOM).
- **Keys em snake_case** (consistência com Python).

---

## 13. Critérios para Criação de Testes

### 13.1 Estrutura

- **Framework:** `pytest`.
- **Localização:** `tests/test_<modulo>.py` espelhando a estrutura de módulos.
- **Fixtures:** `tests/conftest.py` com fixtures compartilhadas (`test_config`, `test_books`, `fake_embedder`, `fake_cache`, `sample_state`).
- **Dados de teste:** `tests/paráfrases.json`, `tests/fixtures/audio/` (clipes curtos).

### 13.2 Tipos de teste

| Tipo | Quando | Exemplo |
|---|---|---|
| **Unitário** | Funções/classes isoladas, com dependências mockadas | `test_parser.py`, `test_confidence.py` |
| **Integração** | Módulos interagindo (sem serviços externos) | `test_decision.py` (decision + estado + busca com FTS5 real) |
| **E2E** | Pipeline ponta-a-ponta (com Holyrics real ou mock) | `test_pipeline.py` (áudio → versículo) |
| **Benchmark** | Latência/throughput | `scripts/benchmark.py` |

### 13.3 Regras

1. **Todo módulo deve ter testes unitários** antes de ser considerado concluído (critério do Blueprint).
2. **Cobertura mínima: 80%** por módulo (medir com `pytest-cov`).
3. **Testes determinísticos:** não depender de rede, GPU (quando possível), ou tempo. Mockar STT/LLM/Holyrics em unitários.
4. **Nomes:** `test_<cenario>_<resultado_esperado>`:
   ```python
   def test_parse_joao_capitulo_tres_versiculo_dezesseis_returns_show_intent():
       ...
   def test_confidence_stt_below_min_returns_ignore():
       ...
   ```
5. **Asserções específicas:** `assert result.action == "show"`, não `assert result is not None`.
6. **Cada teste testa uma coisa.** Se precisa de múltiplas asserções independentes, são testes separados.
7. **Testes de paráfrases** (`tests/paráfrases.json`) são data-driven:
   ```python
   @pytest.mark.parametrize("case", load_paraphrases())
   def test_search_recall(case):
       results = searcher.search(case["query"])
       assert results[0].ref.id == case["expected_id"]
   ```

### 13.4 Testes do conjunto de paráfrases

- Mínimo 50 casos cobrindo: termos exatos, paráfrases, abreviações, sinônimos, ambíguos.
- Recall@1 ≥ 90% é critério de conclusão da Fase 3 (Beta).
- Casos de falha conhecidos devem ser documentados (não removidos) com `pytest.mark.xfail`.

### 13.5 Critérios de não-regressão

- Antes de iniciar uma fase do Plano, reexecutar testes de todas as fases anteriores.
- Se um teste quebra, corrigir antes de avançar (Plano §4).

---

## 14. Critérios para Revisão de Código

### 14.1 Checklist do revisor

- [ ] **Tipagem:** mypy --strict passa sem erros novos.
- [ ] **Lint:** ruff passa sem erros novos.
- [ ] **Estilo:** segue PEP 8 + exceções deste guia (line length 100, aspas duplas).
- [ ] **Arquitetura:** não contorna `core/pipeline` ou `core/decision` (chamadas diretas a LLM/busca/Holyrics).
- [ ] **Tipos canônicos:** usa dataclasses de `core/types.py`, não cria tipos paralelos nem dicts opacos.
- [ ] **Config:** nenhum valor mágico; tudo em `config.yaml` ou constante nomeada.
- [ ] **DI:** dependências injetadas, não instanciadas internamente.
- [ ] **Erros:** levanta exceções de domínio; captura no ponto certo; fallback gracioso.
- [ ] **Logs:** `PipelineLogger` para execução; `logging` para aplicação; sem `print`.
- [ ] **Testes:** testes unitários cobrem o novo código; cobertura ≥ 80% no módulo.
- [ ] **Docstrings:** funções/classes públicas documentadas.
- [ ] **Sem segredos:** tokens/URLs externas não hardcodeadas.
- [ ] **Offline:** nenhuma chamada de rede externa adicionada.

### 14.2 Aprovação

- **1 aprovação** de revisor é obrigatória para merge.
- **CI verde** é obrigatório (ruff + mypy + pytest).
- **Revisor pode solicitar** benchmark se a mudança afeta STT/LLM/busca.

### 14.3 Tamanho de PR

- **< 400 linhas** ideal.
- **> 800 linhas** requer justificativa (ex.: novo módulo inteiro).
- Quebrar PRs grandes em menores por módulo/feature.

---

## 15. Estratégia de Versionamento

### 15.1 SemVer

```
MAJOR.MINOR.PATCH
```

| Parte | Quando incrementa | Exemplo |
|---|---|---|
| `MAJOR` | mudança incompatível na API/arquitetura | parser-first (v1 → v2) |
| `MINOR` | nova funcionalidade compatível | novo modo `quick_presentation` |
| `PATCH` | bugfix compatível | corrigir regex de extenso |

### 15.2 Pré-release

- `0.x.y` durante MVP e Alpha (instável).
- `1.0.0-beta.1`, `1.0.0-beta.2` durante Beta.
- `1.0.0-rc.1` durante Release candidate.
- `1.0.0` no Release.

### 15.3 Versionamento de dados

- `bible.pt-br.sqlite` e `bible.embeddings.npy` têm versão interna (tabela `_meta` no SQLite com `schema_version`).
- Se o schema FTS5 mudar, bumpar `schema_version` e forçar rebuild no startup.

---

## 16. Organização de Branches

### 16.1 Modelo

```
main              # estável, sempre deployable
├── develop       # integração (opcional se time pequeno)
├── feature/<nome>   # nova funcionalidade
├── fix/<nome>       # bugfix
├── refactor/<nome>  # refatoração
└── release/<x.y.z>  # preparação de release
```

### 16.2 Regras

| Branch | Origem | Destino | Tempo de vida |
|---|---|---|---|
| `feature/*` | `main` (ou `develop`) | `main` via PR | curto (dias) |
| `fix/*` | `main` | `main` via PR | curto |
| `refactor/*` | `main` | `main` via PR | curto |
| `release/*` | `main` | `main` (tag) | até release |
| `main` | — | — | permanente |

- **`main` sempre verde:** CI passa, pipeline roda.
- **Sem commits diretos em `main`** — sempre via PR.
- **Branches antigas** deletadas após merge.

### 16.3 Alinhamento com fases do Plano

| Fase do Plano | Tag/Release |
|---|---|
| MVP (Fases 0+1) | `v0.1.0` |
| Alpha (Fase 2) | `v0.2.0` |
| Beta (Fase 3) | `v0.3.0-beta.1` |
| Release (Fase 4) | `v1.0.0` |

---

## 17. Padrão de Commits

### 17.1 Formato Conventional Commits

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### 17.2 Types

| Type | Uso |
|---|---|
| `feat` | nova funcionalidade |
| `fix` | bugfix |
| `refactor` | refatoração sem mudança de comportamento |
| `perf` | melhoria de desempenho |
| `test` | adição/correção de testes |
| `docs` | documentação |
| `build` | build, dependências |
| `ci` | CI/CD |
| `chore` | tarefas misc |

### 17.3 Scopes

Usar o nome do módulo: `parser`, `stt`, `llm`, `busca`, `estado`, `cache`, `confidence`, `holyrics`, `pipeline`, `config`, `logs`, `interface`, `core`.

### 17.4 Exemplos

```
feat(parser): reconhecer números romanos em referências

Adiciona `roman_to_int` ao normalizer e padrão regex para
"i joão", "ii timóteo", "iii joão".

Closes #42
```

```
fix(busca): normalizar query antes de consultar FTS5

Queries com acento não casavam com o tokenizer
`remove_diacritics 2`. Aplicar `Normalizer.normalize` na
entrada do searcher.
```

```
perf(stt): usar int8_float16 em vez de float16

Reduz VRAM de 4.5GB para 2.9GB sem perda significativa
de WER em testes com 10 clipes.
```

### 17.5 Regras

- **Mensagem em imperativo:** "add regex" (não "added regex").
- **< 72 caracteres** na primeira linha.
- **Body explica o porquê**, não o quê (o diff mostra o quê).
- **Referenciar issue:** `Closes #42`, `Refs #42`.
- **Squash commits** de uma branch antes do merge (PR merge com squash).

---

## 18. Critérios de Aceitação antes de Integrar um Módulo

### 18.1 Checklist obrigatório

Antes de um módulo ser integrado ao `main` (ou antes de a próxima fase do Plano depender dele), **todos** os itens abaixo devem estar satisfeitos:

#### 18.1.1 Código

- [ ] Implementa todas as interfaces públicas definidas no Blueprint.
- [ ] Usa tipos canônicos de `core/types.py`.
- [ ] `mypy --strict` passa sem erros.
- [ ] `ruff` passa sem erros.
- [ ] Sem `print()`, `Any`, `type: ignore` sem justificativa, dict opaco em contrato.
- [ ] Docstrings em todas as funções/classes públicas.
- [ ] Sem valores mágicos (tudo em `config.yaml` ou constante).

#### 18.1.2 Arquitetura

- [ ] Não contorna `core/pipeline` ou `core/decision`.
- [ ] Dependências injetadas (não instanciadas internamente).
- [ ] Não importa de módulo de nível superior.
- [ ] Lazy loading implementado para modelos pesados (LLM, embeddings).
- [ ] Fallback gracioso para falhas externas.

#### 18.1.3 Testes

- [ ] Testes unitários cobrem o módulo (≥ 80% cobertura).
- [ ] Testes determinísticos (sem rede/GPU/tempo onde mockable).
- [ ] Testes de edge cases (estado vazio, query vazia, timeout, ambiguidade).
- [ ] Testes do Blueprint §X "Critérios de teste" todos passando.
- [ ] Sem regressão: testes de fases anteriores ainda passam.

#### 18.1.4 Desempenho

- [ ] Latência dentro dos requisitos do Blueprint §X "Requisitos de desempenho".
- [ ] Sem vazamento de memória em loop (testar 10 min para microfone/STT/pipeline).
- [ ] VRAM dentro do orçamento (medir com `nvidia-smi`).

#### 18.1.5 Erros e logs

- [ ] Exceções de domínio (`AILyricsError` e subclasses).
- [ ] `PipelineLogger` registra a etapa do módulo em `LogEntry`.
- [ ] `logging` para warnings/erros de aplicação.
- [ ] Fallback testado (LLM/Holyrics/embeddings indisponíveis).

#### 18.1.6 Configuração

- [ ] Todos os parâmetros ajustáveis em `config.yaml`.
- [ ] `load_config()` valida os campos novos.
- [ ] Sem segredos hardcodeados.

#### 18.1.7 Documentação

- [ ] Blueprint atualizado se interface mudou.
- [ ] README atualizado se setup mudou.
- [ ] CHANGELOG entry (opcional em pré-1.0).

### 18.2 Validação por fase

Além do checklist por módulo, cada fase do Plano tem critérios de conclusão próprios (Plano §1–4) que devem ser validados antes de avançar:

| Fase | Critério adicional |
|---|---|
| MVP | 20 comandos estruturados ponta-a-ponta em < 200 ms; falso positivo < 5% |
| Alpha | 20 comandos não-estruturados em < 1 s; VRAM ociosa < 4 GB; regressão MVP |
| Beta | Recall@1 ≥ 90% em 50 paráfrases; cache hit < 50 ms; UI tray funcional |
| Release | Falso positivo < 1% em 30 min; fallback com LLM off; benchmark documentado |

### 18.3 Ritual de integração

1. **PR aberto** com referência à fase do Plano.
2. **CI roda** (ruff + mypy + pytest + cobertura).
3. **Revisor** preenche checklist §18.1.
4. **Benchmark** se aplicável (STT/LLM/busca).
5. **Squash merge** para `main`.
6. **Tag** se for fim de fase (`v0.1.0`, `v0.2.0`, etc.).
7. **Reexecutar testes de regressão** em `main` após merge.

---

## 19. Resumo Executivo do Guia

| Seção | Regra de ouro |
|---|---|
| Nomenclatura | `snake_case` em Python, `PascalCase` em classes, termos de domínio fixos |
| Diretórios | estrutura fixa da arquitetura; `data/` e `logs/` não versionados |
| Estilo | PEP 8 + line 100 + aspas duplas + ruff + mypy strict |
| Arquitetura | parser-first, LLM não controla Holyrics, tudo offline, asyncio.Queue |
| Tipagem | hints obrigatórias, tipos canônicos em `core/types.py`, sem `Any` |
| Documentação | docstrings Google style, comentários só para não-óbvio |
| Logging | JSONL estruturado por execução + `logging` para aplicação, sem `print` |
| Exceções | hierarquia `AILyricsError`, fallback gracioso, captura no ponto certo |
| Config | `config.yaml` única fonte, env vars para segredos, sem hardcode |
| DI | dependências pelo construtor, pipeline é o único compositor |
| Eventos | `asyncio.Queue` com dataclasses imutáveis, 1:1, poison pill para stop |
| JSON | schemas definidos, snake_case, UTF-8 sem BOM |
| Testes | pytest, ≥ 80% cobertura, determinísticos, 50 paráfrases data-driven |
| Revisão | checklist §14, 1 aprovação, CI verde, PR < 400 linhas |
| Versionamento | SemVer, pré-release para Alpha/Beta/RC |
| Branches | `main` verde, feature/fix/refactor via PR, squash merge |
| Commits | Conventional Commits, scope = módulo, imperativo, < 72 chars |
| Aceitação | checklist §18 por módulo + critérios por fase do Plano |

---

## 20. Conclusão

Este guia consolida as convenções do projeto em um manual único. Junto com a arquitetura (`DOCUMENTACAO_TECNICA.md`), o plano de fases (`Plano_de_Implementacao.md`) e a especificação por módulo (`Blueprint_de_Implementacao.md`), forma a base completa para que qualquer desenvolvedor contribua de forma consistente e sem reinterpretar decisões.

Aderência a este guia é **obrigatória** para todo PR. Desvios devem ser justificados e documentados no PR. Mudanças neste guia seguem o mesmo fluxo de PR (commit `docs(guide): ...`).
