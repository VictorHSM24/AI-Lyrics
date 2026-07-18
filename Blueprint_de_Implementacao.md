# Blueprint de Implementação — Assistente de IA Local para Versículos no Holyrics

> Versão: 1.0 · Data: 2026-07-13
> Documentos de referência:
> - `DOCUMENTACAO_TECNICA.md` (arquitetura v2.0) — fonte oficial de verdade
> - `Plano_de_Implementacao.md` (fases MVP → Release)
>
> Este documento especifica cada módulo em nível de implementação: interfaces, contratos, classes, funções, fluxo interno, desempenho, erros e critérios de conclusão. Um desenvolvedor deve conseguir implementar um módulo consultando apenas sua seção aqui + a arquitetura.

---

## 0. Convenções e Tipos Compartilhados

Antes de detalhar os módulos, define-se um conjunto de tipos e contratos compartilhados que todos os módulos usam. Estes vivem em `core/types.py` e **não devem ser redefinidos** em outros módulos.

> **Nota sobre `__init__.py`:** todo diretório de módulo Python do projeto (ex.: `config/`, `parser/`, `busca/`, `core/`, etc.) contém um arquivo `__init__.py` que expõe apenas a interface pública do módulo (conforme Guia de Desenvolvimento §2.3). Este arquivo está **implícito** em todas as estruturas de diretórios abaixo e não será repetido individualmente, exceto quando houver necessidade de esclarecer seu conteúdo.

### 0.1 Tipos canônicos

```python
# core/types.py
from dataclasses import dataclass, field
from typing import Literal

Action = Literal["show", "next", "previous", "search", "jump", "none", "uncertain"]

@dataclass
class Intent:
    """Saída do parser ou do LLM. Unidade de intenção interpretada."""
    action: Action
    book: str | None = None        # nome canônico (ex.: "João", "1 Coríntios")
    book_id: int | None = None     # 1..66
    chapter: int | None = None
    verse: int | None = None
    amount: int | None = None
    query: str | None = None       # frase para busca (action=search)
    version: str | None = None
    confidence: float = 0.0        # c_intent (parser ou LLM)
    source: Literal["parser", "llm"] = "parser"
    raw: str = ""                  # texto original transcrito

@dataclass
class VerseRef:
    """Referência bíblica resolvida e validada."""
    book_id: int          # 1..66
    book: str             # nome canônico PT-BR
    chapter: int
    verse: int | None     # None = capítulo inteiro
    version: str = "ACF"
    @property
    def id(self) -> str:  # BBCCCVVV
        v = self.verse or 0
        return f"{self.book_id:02d}{self.chapter:03d}{v:03d}"
    @property
    def reference(self) -> str:  # "João 3:16"
        v = f":{self.verse}" if self.verse else ""
        return f"{self.book} {self.chapter}{v}"

@dataclass
class SearchResult:
    ref: VerseRef
    text: str
    score: float          # score combinado (RRF normalizado)
    c_search: float       # confiança da busca (0..1)
    ambiguous: bool       # True se gap top1/top2 < search_gap

@dataclass
class Confidence:
    c_stt: float = 1.0
    c_intent: float = 1.0   # parser ou llm
    c_search: float = 1.0   # 1.0 se não é search
    @property
    def c_final(self) -> float:
        return self.c_stt * self.c_intent * self.c_search

@dataclass
class Decision:
    outcome: Literal["execute", "confirm", "ignore"]
    reason: str
    intent: Intent
    ref: VerseRef | None = None
    confidence: Confidence | None = None

@dataclass
class LogEntry:
    ts: str
    id: str
    audio_ms: int
    stt: dict
    parser: dict
    llm: dict
    search: dict
    confidence: dict
    decision: dict
    holyrics: dict
    cache: dict
    total_ms: int
```

### 0.2 Eventos (fila asyncio)

Toda comunicação entre tasks do pipeline é por `asyncio.Queue` com payloads tipados:

| Evento | Tipo | Produtor | Consumidor |
|---|---|---|---|
| `AudioChunk` | `bytes` (PCM 16kHz mono) | `microfone` | `transcricao` |
| `Utterance` | `dataclass{text, c_stt, audio_ms}` | `transcricao` | `core/pipeline` |
| `Intent` | `Intent` | `parser` ou `llm` | `core/decision` |
| `Decision` | `Decision` | `core/decision` | `core/pipeline` (execução) |

### 0.3 Configuração (`config/config.yaml`)

```yaml
holyrics:
  base_url: "http://127.0.0.1:3000/api"
  token: "${HOLYRICS_TOKEN}"      # lê de env
  timeout_ms: 2000
stt:
  model: "turbo"
  device: "cuda"
  compute_type: "int8_float16"
  language: "pt"
  chunk_length_s: 30
  vad:
    mode: "silero"                # silero | webrtcvad
    min_speech_ms: 250
    pause_threshold_ms: 600
llm:
  base_url: "http://127.0.0.1:11434"   # Ollama
  model: "qwen3:8b-q4_k_m"
  lazy_load: true
  timeout_ms: 5000
  max_tokens: 200
search:
  fts5_db: "data/bible.pt-br.sqlite"
  embeddings_path: "data/bible.embeddings.npy"
  embedding_model: "intfloat/multilingual-e5-small"
  embedding_device: "cpu"        # cpu | cuda
  rrf_k: 60
  top_k: 20
  search_gap: 0.15               # gap top1/top2 p/ ambiguidade
state:
  default_version: "ACF"
  persist_path: "data/state.json"
cache:
  recent_capacity: 50
  embedding_capacity: 200
  holyrics_ttl_s: 5
  current_verse_ttl_s: 60
confidence:
  min_execute: 0.85
  min_confirm: 0.60
  stt_min: 0.50
  parser_high: 0.90
  parser_compact: 0.85
mode: "auto"                      # auto | confirm | quick
log:
  path: "logs/pipeline.jsonl"
  level: "INFO"
```

---

## Módulo 1 — `config/`

### Objetivo
Centralizar toda configuração externalizada do sistema, separando código de valores ajustáveis.

### Responsabilidade
- Carregar `config.yaml` com validação de schema.
- Substituir variáveis de ambiente (`${VAR}`) no YAML.
- Expor objeto `Config` imutável para os demais módulos.
- Carregar `books.json` (tabela canônica de livros) e expor `BookTable`.

### Entradas
- `config/config.yaml` (arquivo)
- `config/books.json` (arquivo)
- Variáveis de ambiente (para segredos como `HOLYRICS_TOKEN`)

### Saídas
- Objeto `Config` (dataclass tipado)
- Objeto `BookTable` (índice de livros + aliases)

### Dependências
- `pyyaml` (leitura YAML)
- `json` (stdlib, leitura `books.json`)
- `os` (stdlib, env vars)

### Interfaces públicas
```python
# config/models.py — dataclasses de configuração (imutáveis)
@dataclass(frozen=True)
class HolyricsConfig: base_url: str; token: str; timeout_ms: int
@dataclass(frozen=True)
class VadConfig: mode: str; min_speech_ms: int; pause_threshold_ms: int
@dataclass(frozen=True)
class STTConfig: model: str; device: str; compute_type: str; language: str; chunk_length_s: int; vad: VadConfig
@dataclass(frozen=True)
class LLMConfig: base_url: str; model: str; lazy_load: bool; timeout_ms: int; max_tokens: int
@dataclass(frozen=True)
class SearchConfig: fts5_db: str; embeddings_path: str; embedding_model: str; embedding_device: str; rrf_k: int; top_k: int; search_gap: float
@dataclass(frozen=True)
class StateConfig: default_version: str; persist_path: str
@dataclass(frozen=True)
class CacheConfig: recent_capacity: int; embedding_capacity: int; holyrics_ttl_s: int; current_verse_ttl_s: int
@dataclass(frozen=True)
class ConfidenceConfig: min_execute: float; min_confirm: float; stt_min: float; parser_high: float; parser_compact: float
@dataclass(frozen=True)
class LogConfig: path: str; level: str
@dataclass(frozen=True)
class Config: holyrics: HolyricsConfig; stt: STTConfig; llm: LLMConfig; search: SearchConfig; state: StateConfig; cache: CacheConfig; confidence: ConfidenceConfig; log: LogConfig; mode: str

# config/books.py — tipos de domínio para livros bíblicos
@dataclass(frozen=True)
class Book: id: int; canonical: str; aliases: list[str]
@dataclass
class BookMatch: book: Book; matched_alias: str; start: int; end: int
class BookTable:
    def resolve(self, raw: str) -> BookMatch | None
    def by_id(self, book_id: int) -> Book
    def all_books(self) -> list[Book]

# config/loader.py — funções de carregamento
def load_config(path: str = "config/config.yaml") -> Config: ...
def load_books(path: str = "config/books.json") -> BookTable: ...
```

### Eventos produzidos
Nenhum (módulo de configuração, síncrono).

### Eventos consumidos
Nenhum.

### Estrutura de diretórios
```
config/
├── __init__.py        # expõe load_config, load_books, Config, BookTable
├── config.yaml        # configuração externalizada
├── books.json         # tabela canônica de 66 livros + aliases
├── models.py          # dataclasses: Config, HolyricsConfig, STTConfig, VadConfig,
│                      #   LLMConfig, SearchConfig, StateConfig, CacheConfig,
│                      #   ConfidenceConfig, LogConfig
├── books.py           # Book, BookMatch, BookTable
└── loader.py          # load_config(), load_books()
```

### Principais classes
```python
@dataclass(frozen=True)
class Book:
    id: int            # 1..66
    canonical: str     # "1 Coríntios"
    aliases: list[str] # ["1 coríntios","i coríntios","primeira coríntios",...]

@dataclass
class BookMatch:
    book: Book
    matched_alias: str
    start: int          # índice na string de entrada
    end: int

class BookTable:
    _by_alias: dict[str, Book]   # alias normalizada -> Book
    _by_id: dict[int, Book]
    _sorted_aliases: list[str]   # ordenado por len desc (longest-match)
```

### Principais funções
- `load_config(path)` → parse YAML, substitui `${VAR}`, valida campos obrigatórios, retorna `Config`.
- `BookTable.resolve(raw)` → normaliza `raw` (lowercase, sem acentos), encontra **longest-match** contra aliases, retorna `BookMatch` ou `None`.
- `BookTable.by_id(book_id)` → retorna `Book` ou levanta `KeyError`.
- `_normalize_alias(s)` → `lowercase + remove_diacritics + collapse_whitespace`.

### Contratos entre módulos
- Todos os módulos recebem `Config` por injeção (construtor ou parâmetro de factory). Nenhum módulo lê YAML diretamente.
- `BookTable` é **singleton** compartilhado entre `parser`, `estado` e `core/decision` para garantir consistência livro↔ID.
- `books.json` schema:
```json
[
  {"id":43,"canonical":"João","aliases":["joão","joao","jo","são joão","evangelho de joão"]},
  {"id":46,"canonical":"1 Coríntios","aliases":["1 coríntios","i coríntios","primeira coríntios","primeira carta aos coríntios","1co"]}
]
```

### Fluxo interno
1. `load_config` lê YAML → substitui `${VAR}` via `os.environ` → valida chaves obrigatórias (`holyrics.base_url`, `stt.model`, etc.) → retorna `Config`.
2. `load_books` lê JSON → para cada livro, normaliza aliases → popula `BookTable._by_alias` e `_by_id` → ordena aliases por len desc.
3. `BookTable.resolve(raw)` percorre aliases ordenadas (longest first) e retorna o primeiro match.

### Requisitos de desempenho
- `load_config` + `load_books`: < 100 ms (startup, one-shot).
- `BookTable.resolve`: < 0,1 ms por chamada (dict lookup).

### Tratamento de erros
- YAML inválido → `ConfigError` com mensagem apontando o campo.
- Variável de ambiente ausente → `ConfigError` listando qual `${VAR}` faltou.
- `books.json` ausente ou malformado → `ConfigError`.
- Alias duplicada entre livros → warning no log (não fatal; longest-match resolve).

### Critérios de teste
- Carregar `config.yaml` de exemplo → `Config` com todos os campos.
- Substituição de `${HOLYRICS_TOKEN}` funciona.
- `BookTable.resolve("primeira coríntios")` → `Book(id=46)`.
- `BookTable.resolve("joão")` → `Book(id=43)` (não confunde com "1 João").
- `BookTable.resolve("livro inexistente")` → `None`.
- Config sem campo obrigatório → `ConfigError`.

### Critérios para considerar o módulo concluído
- `Config` cobre 100% das chaves usadas pelos demais módulos.
- `BookTable` carrega os 66 livros com aliases de PT-BR.
- Testes unitários (`tests/test_config.py`) passando.
- Nenhum outro módulo lê YAML/JSON de config diretamente.

---

## Módulo 2 — `data/` e `scripts/build_index.py`

### Objetivo
Construir e manter os artefatos de dados: índice FTS5, embeddings pré-calculados, texto bíblico fonte e contadores de frequência.

### Responsabilidade
- Importar texto bíblico bruto (`bible_source.json`).
- Popular tabela FTS5 `verses` em `bible.pt-br.sqlite`.
- Pré-calcular embeddings de todos os versículos → `bible.embeddings.npy`.
- Inicializar `frequentes.json` (vazio).

### Entradas
- `data/bible_source.json` (formato abaixo)
- `config/config.yaml` (caminhos de saída, modelo de embedding)

### Saídas
- `data/bible.pt-br.sqlite` (tabela FTS5 populada)
- `data/bible.embeddings.npy` (array N×384, dtype float32)
- `data/frequentes.json` (inicializado como `{}`)

### Dependências
- `sqlite3` (stdlib)
- `sentence-transformers` (para embeddings)
- `numpy`

### Interfaces públicas
```python
# scripts/build_index.py
def build_fts5(source_path: str, db_path: str, version: str) -> int  # n_verses
def build_embeddings(db_path: str, model_name: str, out_path: str, device: str) -> int
def init_frequentes(path: str) -> None
def main() -> None  # CLI: python scripts/build_index.py [--with-embeddings]
```

### Eventos produzidos / consumidos
Nenhum (script offline, síncrono).

### Estrutura de diretórios
```
data/
├── bible_source.json       # input
├── bible.pt-br.sqlite      # output FTS5
├── bible.embeddings.npy    # output embeddings
└── frequentes.json         # output (contador)
scripts/
└── build_index.py
```

### Principais classes / funções
- `build_fts5(source_path, db_path, version)`: lê JSON, insere cada versículo como linha FTS5 com `tokenize='unicode61 remove_diacritics 2'`.
- `build_embeddings(db_path, model_name, out_path, device)`: consulta todos os versículos do SQLite, codifica com e5-small, salva como memmap float32.
- `init_frequentes(path)`: escreve `{}`.

### Formato `bible_source.json`
```json
[
  {"book":"João","book_id":43,"chapter":3,"verse":16,
   "text":"Porque Deus amou o mundo de tal maneira que deu o seu Filho unigênito...",
   "version":"ACF"}
]
```

### Contratos entre módulos
- `busca/searcher.py` abre `bible.pt-br.sqlite` em read-only e `bible.embeddings.npy` via `numpy.memmap`.
- `cache/cache.py` lê/escreve `frequentes.json`.
- `estado/state.py` lê/escreve `data/state.json` (não gerenciado aqui, mas mesmo diretório).

### Fluxo interno
1. `build_fts5`: conectar SQLite → `CREATE VIRTUAL TABLE verses USING fts5(...)` → insert batch (1000 por vez) → `commit` → fechar. Retorna contagem.
2. `build_embeddings`: carregar modelo e5-small → `SELECT id, text FROM verses` → `model.encode(texts, batch_size=128, normalize_embeddings=True)` → `np.save(out_path, arr)`.
3. `init_frequentes`: `json.dump({}, ...)`.

### Requisitos de desempenho
- `build_fts5`: < 5 s para ~31 k versículos.
- `build_embeddings`: ~5–10 min (CPU) ou ~1–2 min (GPU) para 31 k versículos com e5-small. One-shot no build.

### Tratamento de erros
- `bible_source.json` ausente → erro claro com caminho esperado.
- Versículo com `book_id` fora de 1..66 → pula + warning.
- Texto vazio → pula + warning.
- Falta de VRAM no build de embeddings → fallback para CPU com warning.

### Critérios de teste
- Após `build_fts5`: `SELECT COUNT(*) FROM verses` ≈ 31 000 ± 5%.
- `SELECT * FROM verses WHERE verses MATCH 'deus amou o mundo'` retorna João 3:16.
- Após `build_embeddings`: `arr.shape == (N, 384)` e `np.allclose(np.linalg.norm(arr, axis=1), 1.0)` (L2-normalizado).
- `frequentes.json` existe e é `{}`.

### Critérios para considerar o módulo concluído
- `build_index.py` roda ponta-a-ponta sem erros em `bible_source.json` de exemplo.
- FTS5 e embeddings gerados e validados pelos testes acima.
- Documentação no README de como obter `bible_source.json` (licença).

---

## Módulo 3 — `microfone/capture.py`

### Objetivo
Capturar áudio continuamente do microfone, aplicar VAD e emitir segmentos de fala para o pipeline.

### Responsabilidade
- Capturar PCM 16 kHz mono em chunks de 0,5 s.
- Aplicar VAD (Silero ou webrtcvad) para descartar silêncio.
- Acumular fala contínua; ao detectar pausa ≥ `pause_threshold_ms`, emitir o segmento acumulado.
- Expor métricas de captura (tempo, duração do segmento).

### Entradas
- Device de áudio (default do sistema ou ID configurado).
- `config.stt.vad` (modo, `min_speech_ms`, `pause_threshold_ms`).

### Saídas
- Eventos `AudioChunk` (bytes PCM 16kHz mono) na fila de saída.
- Segmentos completos (concatenação de chunks com fala) ao fim de cada enunciado.

### Dependências
- `sounddevice` (captura)
- `silero-vad` (VAD) ou `webrtcvad` (fallback)
- `numpy`
- `asyncio`

### Interfaces públicas
```python
class MicrophoneCapture:
    def __init__(self, config: Config, out_queue: asyncio.Queue): ...
    async def run(self) -> None        # loop de captura (task asyncio)
    async def stop(self) -> None
```

### Eventos produzidos
- `AudioChunk` (bytes PCM) na `out_queue` a cada 0,5 s de fala detectada.
- Ao fim do enunciado: sinal de fim (segmento completo acumulado disponível para STT).

### Eventos consumidos
- Sinal de `stop()` (do pipeline).

### Estrutura de diretórios
```
microfone/
└── capture.py
```

### Principais classes
```python
@dataclass
class UtteranceAudio:
    pcm: bytes            # PCM 16kHz mono, concatenado
    duration_ms: int
    started_at: float

class MicrophoneCapture:
    _vad: SileroVAD | WebRtcVAD
    _buffer: bytearray
    _in_speech: bool
    _silence_since: float | None
```

### Principais funções
- `run()`: loop async — lê chunk do sounddevice → consulta VAD → se fala: acumula no buffer → se silêncio após fala e pausa ≥ threshold: enfileira `UtteranceAudio` e zera buffer.
- `_detect_vad(pcm_chunk) -> bool`: chama modelo VAD.
- `_flush()`: enfileira buffer acumulado como `UtteranceAudio`.

### Contratos entre módulos
- Produz `UtteranceAudio` na fila consumida por `transcricao/stt.py`.
- Formato PCM: 16 kHz, mono, 16-bit signed little-endian (compatível com faster-whisper).

### Fluxo interno
```
sounddevice stream (0.5s chunks)
   │
   ▼
[VAD: silero.predict(pcm)] ── fala? ── sim ──▶ buffer += pcm; _in_speech=True
   │                                       
   não + _in_speech + pausa ≥ 600ms
   │
   ▼
[flush: enfileira UtteranceAudio(buffer)] ──▶ out_queue
```

### Requisitos de desempenho
- Latência de captura + VAD: < 20 ms por chunk.
- VAD Silero: ~5–10 ms por chunk em CPU (ou GPU).
- Não bloquear o pipeline: captura roda em task asyncio independente.

### Tratamento de erros
- Device de áudio indisponível → `AudioError` com lista de devices.
- Chunk com amplitude zero (microfone mudo) → warning + continua.
- VAD falha (modelo não carrega) → fallback para webrtcvad + warning.
- Buffer muito longo (> 30 s) → flush forçado (evita OOM e Whisper timeout).

### Critérios de teste
- Captura 5 s de silêncio → nenhum `UtteranceAudio` emitido.
- Captura "João três dezesseis" com pausa → 1 `UtteranceAudio` com duração ≈ 1–2 s.
- Buffer > 30 s → flush forçado.
- Device inválido → `AudioError`.

### Critérios para considerar o módulo concluído
- Captura contínua por 10 min sem crash nem vazamento de memória.
- VAD separa corretamente fala de silêncio em ambiente com ruído moderado.
- Latência captura+VAD < 20 ms por chunk (medir).

---

## Módulo 4 — `transcricao/stt.py`

### Objetivo
Transcrever segmentos de áudio (PCM) em texto, com confiança (`avg_logprob`).

### Responsabilidade
- Carregar faster-whisper (turbo, INT8) na GPU.
- Receber `UtteranceAudio` da fila.
- Transcrever com `condition_on_previous_text=False`.
- Extrair `avg_logprob` e converter em `c_stt` (0..1).
- Emitir `Utterance` (texto + c_stt) na fila de saída.

### Entradas
- `UtteranceAudio` (PCM bytes) da fila do `microfone`.
- `config.stt` (modelo, device, compute_type, language, chunk_length_s).

### Saídas
- `Utterance(text, c_stt, audio_ms)` na fila de saída.

### Dependências
- `faster-whisper` (CTranslate2)
- `numpy`
- `asyncio`

### Interfaces públicas
```python
class STT:
    def __init__(self, config: Config, in_queue: asyncio.Queue, out_queue: asyncio.Queue): ...
    async def run(self) -> None
    def c_stt_from_logprob(self, avg_logprob: float) -> float
```

### Eventos produzidos
- `Utterance` na `out_queue` (consumida por `core/pipeline`).

### Eventos consumidos
- `UtteranceAudio` da `in_queue` (produzida por `microfone`).

### Estrutura de diretórios
```
transcricao/
└── stt.py
```

### Principais classes
```python
@dataclass
class Utterance:
    text: str
    c_stt: float
    audio_ms: int
    segments: list   # segmentos brutos do faster-whisper (para debug)

class STT:
    _model: WhisperModel
    _batched: BatchedInferencePipeline | None
```

### Principais funções
- `run()`: loop async — consome `UtteranceAudio` → converte bytes para `np.float32` → `model.transcribe(audio, language="pt", condition_on_previous_text=False, chunk_length_s=30)` → acumula texto + `avg_logprob` médio → enfileira `Utterance`.
- `c_stt_from_logprob(lp)`: `sigmoid(lp * 2)` (mapeia logprob típico -1..0 para ~0,12..0,88; calibrar empiricamente).

### Contratos entre módulos
- Consome `UtteranceAudio` de `microfone/capture.py`.
- Produz `Utterance` para `core/pipeline.py`.
- `c_stt` é usado por `confidence/manager.py`.

### Fluxo interno
```
in_queue.get() ──▶ bytes → np.float32 ──▶ model.transcribe()
   │
   ▼
texto = " ".join(seg.text for seg in segments)
avg_logprob = mean(seg.avg_logprob for seg in segments)
c_stt = c_stt_from_logprob(avg_logprob)
   │
   ▼
out_queue.put(Utterance(text, c_stt, audio_ms))
```

### Requisitos de desempenho
- RTF < 0,1 para áudio de 1–5 s (turbo INT8 na 4060 Ti).
- VRAM: ~2,9 GB (INT8).
- Latência de transcrição de 1 s de áudio: < 100 ms.
- Não bloquear captura: STT roda em task asyncio independente.

### Tratamento de erros
- Modelo não carrega (CUDA indisponível) → `STTError` + fallback para CPU com warning.
- Áudio muito curto (< 100 ms) → ignora (provável ruído).
- `avg_logprob` ausente → `c_stt = 0,5` (neutro) + warning.
- Texto vazio → `Utterance(text="", c_stt=0, ...)` (pipeline ignora).

### Critérios de teste
- 10 clipes de áudio curtos → texto transcrito com WER percebido aceitável.
- `c_stt` em áudio limpo > 0,7; em áudio ruidoso < 0,5 (calibrar).
- Áudio de silêncio → texto vazio + c_stt baixo.
- Áudio de 30 s → transcreve sem OOM (chunked).

### Critérios para considerar o módulo concluído
- faster-whisper turbo INT8 carregado na GPU sem erros.
- 20 transcrições ponta-a-ponta com latência < 100 ms por segundo de áudio.
- `c_stt` correlaciona com qualidade percebida (validar empiricamente).

---

## Módulo 5 — `parser/`

### Objetivo
Interpretar comandos estruturados da fala transcrita **sem LLM**, produzindo `Intent` + `c_parser`.

### Responsabilidade
- Normalizar texto (lowercase, diacritics, extenso→dígito, ordinais, romanos).
- Detectar intenção de comando (gatilhos).
- Classificar tipo (referência direta, navegação, indireta).
- Extrair entidades (livro, cap, versículo, quantidade) via `BookTable`.
- Validar contra tabela canônica.
- Devolver `Intent` com `c_parser` ou `Intent(action="uncertain")` para o LLM.

### Entradas
- `Utterance.text` (string).
- `BookTable` (de `config`).
- `BibleState` (de `estado`) — para resolver "ainda nesse capítulo".

### Saídas
- `Intent` (com `source="parser"`, `confidence=c_parser`).

### Dependências
- `config.BookTable`
- `estado.BibleState` (read-only, para contexto)
- `re` (stdlib)

### Interfaces públicas
```python
class Parser:
    def __init__(self, books: BookTable): ...
    def parse(self, text: str, state: BibleState | None = None) -> Intent: ...
```

### Eventos produzidos / consumidos
- Síncrono (chamado pelo `core/pipeline`, não via fila). Produz `Intent` como retorno.

### Estrutura de diretórios
```
parser/
├── __init__.py
├── normalizer.py
├── books.py          # re-exporta BookTable e Book de config/books.py (não redefine)
└── parser.py
```

### Principais classes
```python
class Normalizer:
    def normalize(self, text: str) -> str   # lowercase, diacritics, whitespace
    def extenso_to_digit(self, token: str) -> int | None
    def ordinal_to_int(self, token: str) -> int | None
    def roman_to_int(self, token: str) -> int | None

class Parser:
    _norm: Normalizer
    _books: BookTable
    _patterns: list[re.Pattern]   # REF, REF_SHORT, NEXT, PREV, MORE, STAY
```

### Principais funções
- `Normalizer.normalize(text)`: lowercase → `unicodedata` remove diacritics → `re.sub(r'\s+', ' ', text).strip()`.
- `Normalizer.extenso_to_digit(token)`: consulta tabela de cardinais + composição ("vinte e três" → 23).
- `Normalizer.ordinal_to_int(token)`: "primeiro"→1, "segundo"→2, "terceiro"→3.
- `Normalizer.roman_to_int(token)`: "i"→1, "ii"→2, "iii"→3.
- `Parser.parse(text, state)`:
  1. `norm = normalize(text)`
  2. Para cada padrão regex em ordem de prioridade, tentar `match`.
  3. Se casou: extrair grupos, resolver livro via `BookTable.resolve`, converter números (dígito ou extenso), validar ranges, montar `Intent` com `c_parser` (0,98 com marcadores, 0,85 forma compacta).
  4. Se não casou: verificar gatilhos ("abre", "mostra", "aquele") → se há gatilho mas sem padrão, `Intent(action="uncertain", raw=text)`.
  5. Sem gatilho: `Intent(action="none")`.

### Padrões regex (esquemáticos)
```python
REF       = rf"{BOOK}\s+cap(?:ítulo)?\s+{NUM}\s+vers(?:ículo)?\s+{NUM}"   # c=0.98
REF_SHORT = rf"{BOOK}\s+{NUM}\s+{NUM}"                                    # c=0.85
NEXT      = r"(?:próximo|proximo|seguinte|avança)(?:\s+(?P<n>{NUM}))?"    # c=0.99
PREV      = r"(?:anterior|volt(?:ar|a|ou))(?:\s+(?P<n>{NUM}))?"           # c=0.99
MORE      = r"(?:mais|pula)\s+(?P<n>{NUM})"                               # c=0.97
STAY      = r"(?:ainda|continua)(?:\s+(?:neste|nesse))?\s+(?:capítulo|texto)"  # c=0.90
```

### Contratos entre módulos
- Recebe `Utterance.text` de `core/pipeline`.
- Produz `Intent` consumido por `core/pipeline` (que decide se encaminha ao LLM).
- Usa `BookTable` de `config` (mesma instância que `estado` e `decision`).
- Consulta `BibleState` (read-only) para `STAY` e desambiguação de livro.

### Fluxo interno
```
text ──▶ normalize ──▶ tentar padrões em ordem
                          │
                  casou?  ├── sim ──▶ extrair entidades ──▶ validar ──▶ Intent(c_parser)
                          │
                          ├── não, mas há gatilho ──▶ Intent(action="uncertain")
                          │
                          └── não, sem gatilho ──▶ Intent(action="none")
```

### Requisitos de desempenho
- `parse`: < 1 ms por chamada (regex + dict lookup).
- Sem alocação de GPU, sem rede.

### Tratamento de erros
- Livro não reconhecido → `Intent(action="uncertain")` (encaminha ao LLM).
- Cap/versículo fora do range bíblico → `Intent(action="none")` + log (inválido).
- Número por extenso não parseável → trata como `None` → baixa `c_parser`.
- Ambiguidade "João" vs "1 João" → longest-match do `BookTable`; se empate, preferir Evangelho (sem ordinal).

### Critérios de teste
- 30 casos de teste (`tests/test_parser.py`): refs diretas, navegação, extenso, ordinais, romanos, sinônimos → `Intent` esperado + `c_parser` esperado.
- "vamos abrir em joao capitulo tres versiculo dezesseis" → `show, João, 3, 16, c=0.98`.
- "o próximo" → `next, amount=1, c=0.99`.
- "volta dois" → `previous, amount=2, c=0.99`.
- "primeiro corintios treze" → `show, 1 Coríntios, 13, null, c=0.85`.
- "abre aquele texto da fé" → `uncertain` (encaminha ao LLM).
- "e então Jesus disse aos discípulos" → `none` (pregação, não comando).

### Critérios para considerar o módulo concluído
- 30 testes unitários passando.
- Cobertura de padrões: ref direta (com/sem marcadores), next/previous/mais/volta, stay, sinônimos de livros, extenso 1–199, ordinais, romanos.
- `parser.matched` rate ≥ 80% em amostra de 50 comandos falados reais.

---

## Módulo 6 — `llm/`

### Objetivo
Interpretar intenções não-estruturadas que o parser não resolveu, produzindo `Intent` + `c_llm`.

### Responsabilidade
- Conectar ao servidor LLM (Ollama/llama.cpp, OpenAI-compatible).
- Carregar modelo **lazy** (só na primeira chamada).
- Montar prompt (system + few-shot + estado atual).
- Validar JSON de resposta contra schema.
- Retornar `Intent` ou sinalizar falha.

### Entradas
- Texto transcrito (do `core/pipeline` quando parser devolve `uncertain`).
- `BibleState` atual (para contexto no prompt).
- `config.llm` (base_url, model, timeout, max_tokens).

### Saídas
- `Intent` (com `source="llm"`, `confidence=c_llm`).

### Dependências
- `requests` ou `httpx` (HTTP para Ollama)
- `json` (validação de schema)

### Interfaces públicas
```python
class LLMClient:
    def __init__(self, config: Config, books: BookTable): ...
    def interpret(self, text: str, state: BibleState | None = None) -> Intent: ...
    def is_available(self) -> bool
    def warmup(self) -> None   # preload opcional
```

### Eventos produzidos / consumidos
- Síncrono (chamado pelo `core/pipeline`). Produz `Intent` como retorno.

### Estrutura de diretórios
```
llm/
├── client.py
└── prompts.py
```

### Principais classes
```python
class LLMClient:
    _config: Config
    _books: BookTable
    _loaded: bool = False

# prompts.py
def system_prompt(state: BibleState | None) -> str: ...
def few_shot_examples() -> list[dict]: ...
def build_messages(text, state) -> list[dict]: ...
```

### Principais funções
- `interpret(text, state)`:
  1. Se `lazy_load` e não carregado: primeira chamada dispara load (pode demorar).
  2. Montar messages via `build_messages(text, state)`.
  3. POST `/api/chat` (Ollama) ou `/v1/chat/completions` (llama.cpp) com `response_format="json"`.
  4. Parsear JSON da resposta.
  5. Validar contra schema (`action` em valores válidos, tipos corretos).
  6. Se inválido: retry 1x com prompt de correção; se ainda inválido: `Intent(action="none", confidence=0)`.
  7. Mapear para `Intent` com `source="llm"`, `confidence=c_llm` (campo da resposta ou 0,7 default).
- `is_available()`: GET `/api/tags` (Ollama) ou HEAD no endpoint; retorna bool sem carregar modelo.
- `warmup()`: força load do modelo com prompt trivial.

### Schema de validação
```python
REQUIRED = {"action"}
VALID_ACTIONS = {"show","next","previous","search","jump","none"}
def validate(json_obj) -> bool:
    if "action" not in json_obj or json_obj["action"] not in VALID_ACTIONS:
        return False
    if json_obj["action"] == "show" and not json_obj.get("book"):
        return False
    if json_obj["action"] == "search" and not json_obj.get("query"):
        return False
    return True
```

### Contratos entre módulos
- Recebe texto + estado de `core/pipeline`.
- Produz `Intent` para `core/pipeline`.
- **Nunca** chama `busca` ou `integracao_holyrics` diretamente.
- `action=search` → `query` é passada ao `busca/searcher` pelo pipeline, não pelo LLM.

### Fluxo interno
```
text + state ──▶ build_messages ──▶ POST /api/chat
   │
   ▼
response.json ──▶ validate ── ok? ── sim ──▶ Intent(source="llm")
   │                                      
   não ──▶ retry 1x ── ainda não ──▶ Intent(action="none", c=0)
```

### Requisitos de desempenho
- Latência de inferência: ~200–500 ms para ~30 tokens de saída (Qwen3 8B Q4).
- Cold start (lazy load): pode chegar a 5–10 s na primeira chamada; mitigar com `warmup()` opcional.
- Timeout: 5 s (configurável); se excedido, `Intent(action="none")` + fallback ao parser.

### Tratamento de erros
- Servidor LLM indisponível → `Intent(action="none")` + log; pipeline faz fallback ao parser.
- Timeout → idem.
- JSON inválido → retry 1x; se persistir, `Intent(action="none")`.
- `action=show` com livro não canônico → `Intent(action="none")` (não alucina).
- VRAM insuficiente → erro logado; pipeline continua sem LLM.

### Critérios de teste
- 20 entradas não-estruturadas → `Intent` esperado + `c_llm ≥ 0,7`.
- "abre aquele texto que fala que Deus amou o mundo" → `search, query="Deus amou o mundo"`.
- "o versículo sobre todas as coisas cooperarem para o bem" → `search, query="todas as coisas cooperam para o bem"`.
- 10 entradas onde LLM poderia alucinar → `action` é sempre `search`/`none`/`show` com refs válidas.
- LLM desligado → `is_available() == False` e `interpret()` retorna `Intent(action="none")` sem crash.

### Critérios para considerar o módulo concluído
- 20 testes unitários passando.
- JSON validado em 100% das respostas (com retry).
- Lazy load funciona (VRAM ociosa < 4 GB antes da primeira chamada).
- Fallback gracioso quando LLM indisponível.

---

## Módulo 7 — `busca/`

### Objetivo
Encontrar versículos a partir de uma query textual, usando busca híbrida (FTS5 + embeddings + RRF).

### Responsabilidade
- `embeddings.py`: carregar modelo e5-small, codificar queries.
- `searcher.py`: executar busca FTS5 + busca por embeddings + fusão RRF + ranking + `c_search`.
- `indexer.py`: build do índice (usado por `scripts/build_index.py`).

### Entradas
- `query` (string, do `Intent.query` quando `action=search`).
- `config.search` (caminhos, modelo, rrf_k, top_k, search_gap).

### Saídas
- `list[SearchResult]` ordenado por score combinado, com `c_search` e `ambiguous`.

### Dependências
- `sqlite3` (FTS5)
- `sentence-transformers` (e5-small)
- `numpy` (memmap embeddings)
- `cache/cache.py` (embedding_cache, recent_searches)

### Interfaces públicas
```python
# busca/embeddings.py
class Embedder:
    def __init__(self, config: Config): ...
    def encode(self, text: str) -> np.ndarray   # (384,) L2-normalized

# busca/searcher.py
class Searcher:
    def __init__(self, config: Config, embedder: Embedder, cache: Cache): ...
    def search(self, query: str, top_k: int = 20) -> list[SearchResult]: ...
```

### Eventos produzidos / consumidos
- Síncrono (chamado por `core/decision`). Produz `list[SearchResult]`.

### Estrutura de diretórios
```
busca/
├── indexer.py       # funções de build (usado por scripts/build_index.py)
├── embeddings.py
└── searcher.py
```

### Principais classes
```python
class Embedder:
    _model: SentenceTransformer
    _device: str

class Searcher:
    _db: sqlite3.Connection        # read-only
    _embeddings: np.memmap         # (N, 384)
    _ids: list[str]                # BBCCCVVV por linha
    _embedder: Embedder
    _cache: Cache
    _rrf_k: int
    _search_gap: float
```

### Principais funções
- `Embedder.encode(text)`: `model.encode([text], normalize_embeddings=True)[0]`.
- `Searcher.search(query, top_k)`:
  1. Normalizar query (lowercase, sem diacritics).
  2. Consultar `recent_searches` cache → se hit, retornar.
  3. Busca lexical: `SELECT id, bm25(verses) FROM verses WHERE verses MATCH ? ORDER BY bm25(verses) LIMIT top_k`.
  4. Busca semântica: `embedder.encode(query)` → dot product com memmap → top_k por similaridade.
  5. RRF: `score(id) = Σ 1/(rrf_k + rank_i)` sobre os dois rankings.
  6. Ordenar por score combinado, montar `SearchResult` para cada.
  7. Calcular `c_search`: normalizar score top1 para 0..1; `ambiguous = (score_top1 - score_top2) < search_gap`.
  8. Atualizar `recent_searches` cache.
  9. Retornar top_k resultados.

### Contratos entre módulos
- Recebe `query` de `core/decision` (quando `Intent.action == "search"`).
- Produz `list[SearchResult]` para `core/decision`.
- Usa `cache/cache.py` para `recent_searches` e `embedding_cache`.
- `SearchResult.ref` é `VerseRef` validado (consumido por `core/decision` e `integracao_holyrics`).

### Fluxo interno
```
query ──▶ normalizar ──▶ cache hit? ── sim ──▶ retornar
   │                                
   não                             
   ├──▶ FTS5: SELECT ... MATCH ? ──▶ ranking_lexical
   │
   └──▶ Embedder.encode(query) · memmap ──▶ ranking_semantic
                          │
                          ▼
              RRF fusion (k=60)
                          │
                          ▼
              top_k + c_search + ambiguous
                          │
                          ▼
              atualizar cache ──▶ retornar
```

### Requisitos de desempenho
- FTS5: 1–5 ms.
- Embedding query: ~10–20 ms (CPU) ou ~3–8 ms (GPU).
- Dot product sobre 31 k vetores: < 5 ms (numpy memmap).
- RRF + ranking: < 1 ms.
- Total: < 30 ms p95.
- VRAM: ~0,5 GB se embedder na GPU; 0 se CPU.

### Tratamento de erros
- SQLite DB ausente → `SearchError` com caminho esperado.
- Embeddings file ausente → fallback para FTS5 puro + warning.
- Query vazia → retorna `[]`.
- Nenhum resultado FTS5 nem semântico → retorna `[]` + `c_search=0`.
- Modelo e5-small não carrega → fallback FTS5 puro + warning.

### Critérios de teste
- 50 paráfrases (`tests/paráfrases.json`) → recall@1 ≥ 90%, recall@5 ≥ 98%.
- "deus amou o mundo" → João 3:16 no top-1.
- "deus amou tanto o mundo" → João 3:16 no top-1 (semântica).
- "sal da terra" → Mateus 5:13 no top-1.
- "fé" → ambíguo (`ambiguous=True`), Hebreus 11:1 no top-5.
- Busca repetida → cache hit em < 1 ms.
- FTS5 offline (DB removido) → `SearchError`.

### Critérios para considerar o módulo concluído
- 50 testes de paráfrases passando com recall@1 ≥ 90%.
- Latência p95 < 30 ms em 50 buscas.
- Cache `recent_searches` funcional.
- Fallback gracioso quando embeddings indisponíveis.

---

## Módulo 8 — `estado/state.py`

### Objetivo
Manter o estado atual (livro/cap/versículo) e resolver navegação relativa.

### Responsabilidade
- Armazenar `BibleState` em memória.
- Resolver `next`/`previous` com `amount`, respeitando limites de capítulo e livro.
- Resolver `jump` com `chapter="current"`.
- Persistir estado em `data/state.json` (opcional, para recovery).

### Entradas
- `Intent` (quando `action` é `next`/`previous`/`jump`/`show`).
- `BookTable` (para limites de capítulo por livro).

### Saídas
- `VerseRef` resolvido.
- `BibleState` atualizado.

### Dependências
- `config.BookTable`
- `data/state.json` (persistência)

### Interfaces públicas
```python
class BibleStateManager:
    def __init__(self, books: BookTable, persist_path: str | None = None): ...
    def current(self) -> BibleState: ...
    def apply(self, intent: Intent) -> VerseRef: ...   # resolve e atualiza estado
    def set(self, ref: VerseRef) -> None: ...           # atualização direta
    def load(self) -> None: ...                          # de state.json
    def save(self) -> None: ...                          # para state.json
```

### Eventos produzidos / consumidos
- Síncrono (chamado por `core/decision`). Produz `VerseRef`.

### Estrutura de diretórios
```
estado/
└── state.py
```

### Principais classes
```python
@dataclass
class BibleState:
    book_id: int | None
    chapter: int | None
    verse: int | None
    version: str = "ACF"
    last_shown_at: float = 0.0

class BibleStateManager:
    _state: BibleState
    _books: BookTable
    _chapter_counts: dict[int, int]   # book_id -> n_capítulos
    _verse_counts: dict[tuple[int,int], int]  # (book_id, chapter) -> n_versículos
```

### Principais funções
- `apply(intent)`:
  - `show`: valida ref, atualiza estado, retorna `VerseRef`.
  - `next`: `verse += amount`; se passar do último versículo do capítulo, `chapter += 1, verse = 1`; se passar do último capítulo, `book_id += 1, chapter = 1, verse = 1`.
  - `previous`: análogo inverso.
  - `jump` com `chapter="current"`: mantém livro/capítulo, `verse = None` (capítulo inteiro).
- `set(ref)`: atualiza estado diretamente (após `ShowVerse` bem-sucedido).
- `load()`/`save()`: JSON em `data/state.json`.

### Contratos entre módulos
- Recebe `Intent` de `core/decision`.
- Produz `VerseRef` para `core/decision` (que chama `integracao_holyrics`).
- Usa `BookTable` para limites de capítulo/versículo.
- `_chapter_counts` e `_verse_counts` derivados do índice FTS5 (carregados no startup).

### Fluxo interno
```
intent ──▶ action?
   ├── show ──▶ validar ref ──▶ state = ref ──▶ VerseRef
   ├── next ──▶ verse += amount ──▶ overflow? ──▶ chapter++ ──▶ overflow? ──▶ book++
   ├── previous ──▶ análogo inverso
   └── jump ──▶ manter book/chapter, verse=None
                          │
                          ▼
                    state atualizado ──▶ save() ──▶ VerseRef
```

### Requisitos de desempenho
- `apply`: < 1 ms (tudo em memória).
- `save`: < 10 ms (JSON pequeno).

### Tratamento de erros
- Estado vazio + `next`/`previous` → `StateError` ("nenhum versículo aberto ainda").
- Ref inválida (capítulo > limite) → `StateError`.
- `state.json` corrompido → ignora + warning + estado vazio.

### Critérios de teste
- João 3:16 + `next(1)` → João 3:17.
- João 3:16 + `previous(2)` → João 3:14.
- João 21:25 + `next(1)` → Atos 1:1 (transição de livro).
- Gênesis 1:1 + `previous(1)` → `StateError` (não há anterior).
- `jump(current)` mantém livro/capítulo.
- `save()` + `load()` preserva estado.

### Critérios para considerar o módulo concluído
- Testes de navegação nos limites de capítulo e livro passando.
- Persistência `state.json` funcional.
- `_chapter_counts` e `_verse_counts` carregados do índice no startup.

---

## Módulo 9 — `cache/cache.py`

### Objetivo
Evitar reprocessamento e reduzir latência em comandos repetidos.

### Responsabilidade
- Manter `current_verse` (LRU 1, TTL 60 s).
- Manter `recent_searches` (LRU 50).
- Manter `embedding_cache` (LRU 200).
- Manter `holyrics_response` (TTL 5 s).
- Persistir `frequentes.json` (contador de uso).

### Entradas
- Queries de busca, versículos exibidos, respostas do Holyrics.

### Saídas
- Cache hits (resultados armazenados), contadores de frequência.

### Dependências
- `collections.OrderedDict` (LRU)
- `json` (frequentes.json)

### Interfaces públicas
```python
class Cache:
    def __init__(self, config: Config): ...
    # current_verse
    def get_current_verse(self) -> VerseRef | None: ...
    def set_current_verse(self, ref: VerseRef) -> None: ...
    # recent_searches
    def get_search(self, query_norm: str) -> list[SearchResult] | None: ...
    def put_search(self, query_norm: str, results: list[SearchResult]) -> None: ...
    # embedding_cache
    def get_embedding(self, query_norm: str) -> np.ndarray | None: ...
    def put_embedding(self, query_norm: str, vec: np.ndarray) -> None: ...
    # holyrics_response
    def get_holyrics(self, action: str) -> dict | None: ...
    def put_holyrics(self, action: str, response: dict) -> None: ...
    # frequent_verses
    def increment_frequent(self, ref: VerseRef) -> None: ...
    def get_frequent_score(self, ref: VerseRef) -> int: ...
    def save_frequentes(self) -> None: ...
```

### Eventos produzidos / consumidos
- Síncrono (chamado por `core/decision`, `busca/searcher`, `integracao_holyrics`).

### Estrutura de diretórios
```
cache/
└── cache.py
```

### Principais classes
```python
class Cache:
    _current_verse: VerseRef | None
    _current_verse_ts: float
    _recent: OrderedDict[str, list[SearchResult]]
    _embeddings: OrderedDict[str, np.ndarray]
    _holyrics: dict[str, tuple[dict, float]]   # action -> (response, ts)
    _frequentes: dict[str, int]                 # BBCCCVVV -> count
```

### Principais funções
- LRU: `get` move para fim; `put` evict do início se > capacity.
- TTL: `get_current_verse` retorna `None` se expirou (`now - ts > current_verse_ttl_s`).
- `increment_frequent`: `_frequentes[ref.id] += 1`; `save_frequentes()` persiste.

### Contratos entre módulos
- `busca/searcher` consulta `get_search`/`put_search` e `get_embedding`/`put_embedding`.
- `core/decision` consulta `get_current_verse` (para next/previous sem rebuscar) e `increment_frequent` (após ShowVerse).
- `integracao_holyrics` consulta `get_holyrics`/`put_holyrics` (para `GetBibleVersions` cacheado).
- `frequentes.json` é compartilhado entre sessões (persistente).

### Fluxo interno
```
get_search(query) ──▶ hit? ── sim ──▶ mover para fim (LRU) ──▶ retornar
   │
   não ──▶ None (caller busca e chama put_search)
```

### Requisitos de desempenho
- Todas as operações: < 0,1 ms (dict/OrderedDict em memória).
- `save_frequentes`: < 10 ms.

### Tratamento de erros
- `frequentes.json` corrompido → ignora + warning + inicia vazio.
- Cache em memória não persiste entre sessões (exceto `frequentes`).

### Critérios de teste
- `put_search` + `get_search` → hit.
- LRU evict após 51 puts (capacity=50).
- TTL expirado → `get_current_verse` retorna `None`.
- `increment_frequent` + `save_frequentes` + reload → contador preservado.

### Critérios para considerar o módulo concluído
- Todas as 5 camadas de cache funcionais.
- LRU e TTL testados.
- `frequentes.json` persiste entre sessões.

---

## Módulo 10 — `confidence/manager.py`

### Objetivo
Combinar confianças de múltiplas etapas (STT, parser/LLM, busca) e decidir executar/confirmar/ignorar.

### Responsabilidade
- Receber `c_stt`, `c_intent`, `c_search`, `ambiguous`.
- Calcular `c_final` (multiplicação).
- Aplicar tabela de decisão (§8.5 da doc. técnica).
- Retornar `Decision.outcome` + `reason`.

### Entradas
- `c_stt` (de `transcricao`).
- `Intent` (de `parser` ou `llm`, com `c_intent`).
- `c_search`, `ambiguous` (de `busca`, se `action=search`).
- `config.confidence` (limiares).

### Saídas
- `Decision(outcome, reason, intent, ref, confidence)`.

### Dependências
- `core/types.py` (Confidence, Decision)

### Interfaces públicas
```python
class ConfidenceManager:
    def __init__(self, config: Config): ...
    def evaluate(self, c_stt: float, intent: Intent,
                 c_search: float = 1.0, ambiguous: bool = False,
                 ref: VerseRef | None = None) -> Decision: ...
```

### Eventos produzidos / consumidos
- Síncrono (chamado por `core/decision`).

### Estrutura de diretórios
```
confidence/
└── manager.py
```

### Principais classes
```python
class ConfidenceManager:
    _min_execute: float
    _min_confirm: float
    _stt_min: float
```

### Principais funções
- `evaluate(c_stt, intent, c_search, ambiguous, ref)`:
  1. Se `c_stt < stt_min` → `Decision(outcome="ignore", reason="stt too low")`.
  2. Se `ambiguous` → `Decision(outcome="confirm", reason="search ambiguous")`.
  3. `c_final = c_stt * intent.confidence * c_search`.
  4. Se `c_final ≥ min_execute` → `execute`.
  5. Se `c_final ≥ min_confirm` → `confirm`.
  6. Senão → `ignore`.

### Contratos entre módulos
- Recebe confianças de `core/decision` (que agregou de `transcricao`, `parser`/`llm`, `busca`).
- Produz `Decision` para `core/decision`.

### Fluxo interno
```
c_stt < stt_min? ── sim ──▶ ignore
   │
   não
   ▼
ambiguous? ── sim ──▶ confirm
   │
   não
   ▼
c_final = c_stt * c_intent * c_search
   │
   ├── ≥ min_execute ──▶ execute
   ├── ≥ min_confirm ──▶ confirm
   └── < min_confirm ──▶ ignore
```

### Requisitos de desempenho
- `evaluate`: < 0,1 ms.

### Tratamento de erros
- Confiança fora de [0,1] → clamp + warning.
- `Intent.action == "none"` → `Decision(outcome="ignore")` direto.

### Critérios de teste
- 20 cenários (`tests/test_confidence.py`): combinações de c_stt/c_intent/c_search/ambiguous → outcome esperado.
- `c_stt=0.3` → ignore (mesmo com c_intent alta).
- `c_stt=0.9, c_intent=0.98, c_search=1.0` → execute (c_final=0.88).
- `c_stt=0.9, c_intent=0.7, c_search=0.8` → confirm (c_final=0.504).
- `ambiguous=True` → confirm independentemente do score.

### Critérios para considerar o módulo concluído
- 20 testes unitários passando.
- Tabela de decisão (§8.5) coberta 100%.
- Limiares configuráveis via `config.confidence`.

---

## Módulo 11 — `integracao_holyrics/client.py`

### Objetivo
Comunicar com o Holyrics via API REST oficial.

### Responsabilidade
- Enviar `ShowVerse` (por ID ou referência natural).
- Consultar `GetBibleVersions`.
- Healthcheck (verificar se Holyrics está reachável).
- Timeout e retry limitado.

### Entradas
- `VerseRef` (para `ShowVerse`).
- `config.holyrics` (base_url, token, timeout).

### Saídas
- Resposta JSON do Holyrics (`{"status":"ok"}` ou erro).

### Dependências
- `requests` (HTTP)

### Interfaces públicas
```python
class HolyricsClient:
    def __init__(self, config: Config, cache: Cache): ...
    def show_verse(self, ref: VerseRef, quick: bool = False) -> dict: ...
    def get_bible_versions(self) -> list[dict]: ...
    def healthcheck(self) -> bool: ...
```

### Eventos produzidos / consumidos
- Síncrono (chamado por `core/pipeline` após decisão `execute`).

### Estrutura de diretórios
```
integracao_holyrics/
└── client.py
```

### Principais classes
```python
class HolyricsClient:
    _base_url: str
    _token: str
    _timeout: float
    _cache: Cache
```

### Principais funções
- `show_verse(ref, quick)`: POST `/api/ShowVerse?token=...` com `{"input":{"id":ref.id}, "version":ref.version, "quick_presentation":quick}`. Retorna JSON. Atualiza `cache.put_holyrics`.
- `get_bible_versions()`: consulta `cache.get_holyrics("GetBibleVersions")`; se miss, POST `/api/GetBibleVersions` e cacheia.
- `healthcheck()`: tenta `get_bible_versions()` com timeout curto (1 s); retorna bool.

### Contratos entre módulos
- Recebe `VerseRef` de `core/pipeline`.
- Usa `cache/cache.py` para `holyrics_response`.
- Formato ID: `BBCCCVVV` (string, zero-padded).

### Fluxo interno
```
show_verse(ref) ──▶ POST /api/ShowVerse
   │
   ├── 200 + status:ok ──▶ retornar response
   ├── timeout ──▶ retry 1x ──▶ ainda timeout ──▶ HolyricsError
   └── erro HTTP ──▶ HolyricsError com status code
```

### Requisitos de desempenho
- Latência local: 5–20 ms.
- Timeout: 2 s (configurável).
- Retry: no máximo 1x.

### Tratamento de erros
- Timeout → `HolyricsError`; pipeline loga e continua (não derruba o sistema).
- HTTP 4xx/5xx → `HolyricsError` com code.
- Token inválido → `HolyricsError` (403) com mensagem clara.
- Holyrics offline → `healthcheck() == False`.

### Critérios de teste
- `show_verse(João 3:16)` → Holyrics exibe o versículo (teste manual com Holyrics rodando).
- `get_bible_versions()` → lista não vazia.
- `healthcheck()` com Holyrics offline → `False`.
- Timeout simulado → `HolyricsError` após 2 s.
- Cache: 2ª chamada a `get_bible_versions()` em < 1 ms.

### Critérios para considerar o módulo concluído
- `ShowVerse` funcional com ID e com referência natural.
- `healthcheck` usado no startup do pipeline.
- Cache de `GetBibleVersions` funcional.
- Erros de rede não derrubam o pipeline.

---

## Módulo 12 — `interface/tray.py`

### Objetivo
Fornecer interface visual mínima (tray icon) para status e confirmação de comandos ambíguos.

### Responsabilidade
- Exibir ícone no system tray com status do pipeline (running/stopped/error).
- Notificar quando um comando aguarda confirmação.
- Permitir confirmar/cancelar via clique.
- Alternar modo (`auto`/`confirm`/`quick`).

### Entradas
- Status do pipeline (de `core/pipeline`).
- Pedidos de confirmação (de `core/decision` quando `outcome="confirm"`).

### Saídas
- Decisão do usuário (confirm/cancel) para `core/pipeline`.
- Mudança de modo para `config`.

### Dependências
- `pystray` (tray icon) ou similar
- `Pillow` (ícone)

### Interfaces públicas
```python
class TrayUI:
    def __init__(self, config: Config): ...
    def run(self) -> None           # bloqueante (thread separada)
    def request_confirmation(self, decision: Decision) -> bool: ...  # sync
    def set_status(self, status: str) -> None: ...
    def set_mode(self, mode: str) -> None: ...
```

### Eventos produzidos / consumidos
- Consome `Decision` com `outcome="confirm"` de `core/pipeline`.
- Produz bool (confirm/cancel) para `core/pipeline`.

### Estrutura de diretórios
```
interface/
└── tray.py
```

### Principais classes
```python
class TrayUI:
    _icon: pystray.Icon
    _pending: Decision | None
    _mode: str
```

### Principais funções
- `run()`: inicia loop do tray em thread separada.
- `request_confirmation(decision)`: exibe notificação com `ref` e aguarda clique (timeout 10 s → default cancel).
- `set_status(status)`: atualiza ícone/tooltip.

### Contratos entre módulos
- Opcional: pipeline funciona sem UI (modo `auto`).
- Quando UI está ativa e modo é `confirm`, `core/pipeline` chama `request_confirmation` antes de `show_verse`.

### Fluxo interno
```
pipeline: outcome=confirm ──▶ tray.request_confirmation(decision)
   │
   ▼
tray: notificação "Confirmar João 3:16?" [Sim] [Não]
   │
   ├── Sim (ou timeout 10s) ──▶ True ──▶ pipeline executa show_verse
   └── Não ──▶ False ──▶ pipeline ignora
```

### Requisitos de desempenho
- Não bloquear o pipeline (UI em thread separada).
- Notificação aparece em < 500 ms.

### Tratamento de erros
- pystray indisponível (headless) → warning + pipeline continua sem UI (modo `auto` forçado).
- Timeout de confirmação → default cancel.

### Critérios de teste
- Tray aparece com status "running".
- `request_confirmation` retorna `True` ao clicar "Sim".
- `request_confirmation` retorna `False` após timeout.
- Troca de modo persiste em `config`.

### Critérios para considerar o módulo concluído
- Tray funcional em Windows.
- Confirmação não bloqueia o pipeline.
- Fallback gracioso em modo headless.

---

## Módulo 13 — `logs/`

### Objetivo
Registrar cada execução do pipeline em log estruturado (JSONL) para auditoria e otimização.

### Responsabilidade
- Expor utilitário `Logger` que grava `LogEntry` em `logs/pipeline.jsonl`.
- Garantir que cada linha é JSON válido.
- Rotação opcional por tamanho.

### Entradas
- `LogEntry` (de `core/pipeline`).

### Saídas
- Linhas JSONL em `logs/pipeline.jsonl`.

### Dependências
- `json` (stdlib)
- `logging` (stdlib, para logs não-estruturados)

### Interfaces públicas
```python
class PipelineLogger:
    def __init__(self, path: str): ...
    def log(self, entry: LogEntry) -> None: ...
    def flush(self) -> None: ...
```

### Eventos produzidos / consumidos
- Consome `LogEntry` de `core/pipeline`.

### Estrutura de diretórios
```
logs/
└── pipeline.jsonl   # (gerado em runtime)
```

### Principais classes
```python
class PipelineLogger:
    _file: TextIO
    _lock: threading.Lock
```

### Principais funções
- `log(entry)`: `json.dumps(asdict(entry))` + `\n` + write + flush.
- `flush()`: garante escrita em disco.

### Contratos entre módulos
- `core/pipeline` constrói `LogEntry` com timing e confiança de cada etapa e chama `logger.log(entry)`.

### Fluxo interno
```
pipeline ──▶ LogEntry ──▶ json.dumps ──▶ file.write ──▶ flush
```

### Requisitos de desempenho
- `log`: < 1 ms por entrada.
- Não bloquear o pipeline (write síncrono mas rápido; se necessário, buffer async).

### Tratamento de erros
- Arquivo inacessível (permissão) → warning + log em stderr.
- `LogEntry` muito grande → truncar campos grandes (ex.: `raw` > 500 chars).

### Critérios de teste
- 10 entradas logadas → 10 linhas JSONL válidas (`json.loads` em cada).
- Campos obrigatórios presentes: `ts, id, total_ms, stt, parser, decision, holyrics`.

### Critérios para considerar o módulo concluído
- Log JSONL válido e parseable.
- Timing por etapa presente em 100% das entradas.
- Rotação por tamanho (opcional) implementada.

---

## Módulo 14 — `core/pipeline.py`

### Objetivo
Orquestrar o fluxo completo: microfone → STT → parser → (LLM se necessário) → confidence → decisão → (busca se necessário) → estado/cache → Holyrics → log.

### Responsabilidade
- Criar e gerenciar `asyncio.Queue`s entre tasks.
- Iniciar tasks: `microfone.run()`, `stt.run()`, `_orchestrator()`.
- No orquestrador: consumir `Utterance`, chamar parser, decidir se chama LLM, chamar confidence, executar decisão, chamar Holyrics, logar.
- Healthcheck no startup.
- Graceful shutdown.

### Entradas
- `Config`, `BookTable`, instâncias de todos os módulos.

### Saídas
- Versículos exibidos no Holyrics.
- Logs em `logs/pipeline.jsonl`.

### Dependências
- Todos os módulos (microfone, transcricao, parser, llm, busca, estado, cache, confidence, integracao_holyrics, interface, logs).

### Interfaces públicas
```python
class Pipeline:
    def __init__(self, config: Config): ...
    async def start(self) -> None: ...    # inicia tasks
    async def stop(self) -> None: ...     # graceful shutdown
    def healthcheck(self) -> dict: ...     # status de cada componente
```

### Eventos produzidos / consumidos
- Orquestra todos os eventos (AudioChunk, Utterance, Intent, Decision).

### Estrutura de diretórios
```
core/
├── pipeline.py
└── decision.py
```

### Principais classes
```python
class Pipeline:
    _config: Config
    _books: BookTable
    _mic: MicrophoneCapture
    _stt: STT
    _parser: Parser
    _llm: LLMClient
    _searcher: Searcher
    _state: BibleStateManager
    _cache: Cache
    _confidence: ConfidenceManager
    _holyrics: HolyricsClient
    _tray: TrayUI | None
    _logger: PipelineLogger
    _queues: dict[str, asyncio.Queue]
    _tasks: list[asyncio.Task]
```

### Principais funções
- `start()`:
  1. Healthcheck: Holyrics reachable, índice carregado, STT carregado.
  2. Criar queues: `audio_queue`, `utterance_queue`.
  3. Iniciar tasks: `microfone.run()`, `stt.run()`, `_orchestrator()`.
- `_orchestrator()`:
  1. Consome `Utterance` da `utterance_queue`.
  2. `intent = parser.parse(utterance.text, state.current())`.
  3. Se `intent.action == "uncertain"`: `intent = llm.interpret(utterance.text, state.current())`.
  4. Se `intent.action == "search"`: `results = searcher.search(intent.query)`; pegar top-1; `c_search`, `ambiguous` do resultado.
  5. Se `intent.action in ("next","previous","jump","show")`: `ref = state.apply(intent)`.
  6. `decision = confidence.evaluate(utterance.c_stt, intent, c_search, ambiguous, ref)`.
  7. Switch `decision.outcome`:
     - `execute`: `holyrics.show_verse(ref)`; `cache.set_current_verse(ref)`; `cache.increment_frequent(ref)`.
     - `confirm`: se UI ativa, `tray.request_confirmation(decision)`; se True, executar; senão ignorar.
     - `ignore`: log only.
  8. Construir `LogEntry` com timing de cada etapa e `logger.log(entry)`.
- `stop()`: cancela tasks, fecha conexões, salva estado e frequentes.

### Contratos entre módulos
- É o **único** módulo que chama `integracao_holyrics` (após decisão `execute`).
- É o **único** módulo que chama `llm` (após parser `uncertain`).
- É o **único** módulo que chama `busca` (após `action=search`).
- Parser, estado, cache, confidence são chamados pelo orquestrador de forma síncrona.

### Fluxo interno
```
Utterance ──▶ parser.parse() ──▶ Intent
   │
   ├── action=none ──▶ log + descartar
   ├── action=uncertain ──▶ llm.interpret() ──▶ Intent
   ├── action=show/next/previous/jump ──▶ state.apply() ──▶ VerseRef
   └── action=search ──▶ searcher.search() ──▶ SearchResult ──▶ VerseRef
                          │
                          ▼
              confidence.evaluate() ──▶ Decision
                          │
              ├── execute ──▶ holyrics.show_verse() + cache + frequent
              ├── confirm ──▶ tray.request() ──▶ execute ou ignore
              └── ignore ──▶ log
                          │
                          ▼
                    logger.log(LogEntry)
```

### Requisitos de desempenho
- Overhead do orquestrador (excluindo STT/LLM/busca): < 5 ms.
- Não bloquear captura nem STT (orquestrador roda em task própria).

### Tratamento de erros
- Exceção em qualquer etapa → log + continua (não derruba pipeline).
- Holyrics timeout → log + continua.
- LLM timeout → fallback ao parser; se parser também falhou, `ignore`.
- Crash de task asyncio → reiniciar task + log.

### Critérios de teste
- Pipeline ponta-a-ponta com 20 comandos estruturados → versículos corretos no Holyrics.
- 5 comandos não-estruturados → LLM acionado → versículos corretos.
- 5 min de pregação sem comandos → < 5% falsos positivos.
- `stop()` fecha tudo graciosamente (sem threads órfãs).
- Log JSONL gerado para cada execução.

### Critérios para considerar o módulo concluído
- Pipeline roda ponta-a-ponta sem crash por 30 min.
- Healthcheck no startup funcional.
- Graceful shutdown sem recursos órfãos.
- Log de cada execução com timing por etapa.

---

## Módulo 15 — `core/decision.py`

### Objetivo
Aplicar regras determinísticas de segurança após o Confidence Manager, antes de executar no Holyrics.

### Responsabilidade
- Validar `Intent` contra schema e tabela canônica.
- Normalizar livro/cap/versículo.
- Coordenar `estado.apply`, `busca.search`, `cache`, `confidence.evaluate`.
- Retornar `Decision` final para o pipeline executar.

### Entradas
- `Intent` (parser ou LLM), `c_stt`, `BibleState`.

### Saídas
- `Decision` (com `ref` resolvido se `outcome=execute`).

### Dependências
- `estado.BibleStateManager`, `busca.Searcher`, `cache.Cache`, `confidence.ConfidenceManager`, `config.BookTable`.

### Interfaces públicas
```python
class DecisionEngine:
    def __init__(self, books, state, searcher, cache, confidence): ...
    def decide(self, c_stt: float, intent: Intent) -> Decision: ...
```

### Eventos produzidos / consumidos
- Síncrono (chamado por `core/pipeline`).

### Estrutura de diretórios
```
core/
└── decision.py
```

### Principais classes
```python
class DecisionEngine:
    _books: BookTable
    _state: BibleStateManager
    _searcher: Searcher
    _cache: Cache
    _confidence: ConfidenceManager
```

### Principais funções
- `decide(c_stt, intent)`:
  1. Se `intent.action == "none"` → `Decision(outcome="ignore", reason="no action")`.
  2. Se `intent.action in ("show","next","previous","jump")`: `ref = state.apply(intent)`; `c_search = 1.0`; `ambiguous = False`.
  3. Se `intent.action == "search"`:
     - `results = searcher.search(intent.query)`.
     - Se vazio → `Decision(outcome="ignore", reason="no results")`.
     - `top = results[0]`; `ref = top.ref`; `c_search = top.c_search`; `ambiguous = top.ambiguous`.
     - Se `ambiguous` e `frequent_verses` tem candidato → desempatar.
  4. `decision = confidence.evaluate(c_stt, intent, c_search, ambiguous, ref)`.
  5. Retornar `decision`.

### Contratos entre módulos
- Recebe `Intent` + `c_stt` de `core/pipeline`.
- Produz `Decision` para `core/pipeline`.
- É o **único** que coordena estado + busca + cache + confidence (o pipeline só executa o resultado).

### Fluxo interno
```
intent ──▶ action?
   ├── none ──▶ ignore
   ├── show/next/previous/jump ──▶ state.apply() ──▶ ref
   └── search ──▶ searcher.search() ──▶ top result ──▶ ref + c_search + ambiguous
                          │
                          ▼
              confidence.evaluate() ──▶ Decision
```

### Requisitos de desempenho
- `decide`: < 5 ms (excluindo busca, que é assíncrona ao caller mas síncrona aqui).

### Tratamento de erros
- `state.apply` levanta `StateError` → `Decision(outcome="ignore", reason="invalid state")`.
- `searcher.search` levanta `SearchError` → `Decision(outcome="ignore", reason="search failed")`.
- `Intent` com livro não canônico → `ignore`.

### Critérios de teste
- `show João 3:16` + `c_stt=0.9` → `execute, ref=João 3:16`.
- `search "deus amou o mundo"` + `c_stt=0.9` → `execute` ou `confirm` (depende do score).
- `search "fé"` (ambíguo) → `confirm`.
- `next` sem estado → `ignore` (StateError).
- `none` → `ignore`.

### Critérios para considerar o módulo concluído
- Testes unitários (`tests/test_decision.py`) passando.
- Coordena estado + busca + cache + confidence sem duplicar lógica no pipeline.
- Erros de estado/busca não propagam (viram `ignore` com reason).

---

## Módulo 16 — `scripts/benchmark.py`

### Objetivo
Benchmark de STT (Whisper turbo vs Parakeet v3) e de busca híbrida com áudio real PT-BR.

### Responsabilidade
- Rodar N clipes de áudio por cada modelo STT e medir WER + latência.
- Rodar conjunto de paráfrases pela busca híbrida e medir recall@1/@5 + latência.
- Produzir relatório JSON/Markdown com resultados.

### Entradas
- Diretório de clipes de áudio + transcrições de referência (ground truth).
- `tests/paráfrases.json` (query → versículo esperado).

### Saídas
- `scripts/benchmark_report.json` + `scripts/benchmark_report.md`.

### Dependências
- `faster-whisper`, `nemo` (opcional, para Parakeet), `busca.Searcher`.

### Interfaces públicas
```python
def benchmark_stt(audio_dir: str, gt_dir: str, models: list[str]) -> dict: ...
def benchmark_search(paraphrases_path: str, searcher: Searcher) -> dict: ...
def main() -> None  # CLI
```

### Estrutura de diretórios
```
scripts/
└── benchmark.py
```

### Fluxo interno
```
para cada modelo STT:
   para cada clipe:
      transcrever ──▶ comparar com ground truth ──▶ WER + latência
   agregar média/p50/p95

para cada paráfrase:
   searcher.search(query) ──▶ top-1 == esperado? ──▶ recall@1
   medir latência
agregar recall@1/@5 + latência p50/p95
```

### Requisitos de desempenho
- Benchmark STT: ~1 min por clipe (Whisper) + ~1 min (Parakeet).
- Benchmark busca: < 5 s para 50 paráfrases.

### Critérios de teste
- Roda sem crash em conjunto de 10 clipes + 50 paráfrases.
- Relatório gerado com WER, recall@1, latências.

### Critérios para considerar o módulo concluído
- Benchmark reproduzível.
- Decisão Whisper vs Parakeet documentada com dados.
- Recall@1 ≥ 90% confirmado (ou plano de melhoria).

---

## 17. Matriz de Contratos Resumida

| Módulo | Consome de | Produz para |
|---|---|---|
| `microfone` | — | `transcricao` (AudioChunk) |
| `transcricao` | `microfone` (AudioChunk) | `core/pipeline` (Utterance) |
| `parser` | `config` (BookTable), `estado` (state) | `core/pipeline` (Intent) |
| `llm` | `core/pipeline` (text+state) | `core/pipeline` (Intent) |
| `busca` | `core/decision` (query), `cache` | `core/decision` (SearchResult) |
| `estado` | `core/decision` (Intent), `config` (BookTable) | `core/decision` (VerseRef) |
| `cache` | todos (query/put) | todos (get) |
| `confidence` | `core/decision` (c_stt, c_intent, c_search) | `core/decision` (Decision) |
| `integracao_holyrics` | `core/pipeline` (VerseRef), `cache` | Holyrics (HTTP) |
| `interface` | `core/pipeline` (Decision) | `core/pipeline` (bool) |
| `logs` | `core/pipeline` (LogEntry) | arquivo JSONL |
| `core/pipeline` | todos | Holyrics (via `integracao_holyrics`) |
| `core/decision` | `parser`/`llm` (Intent), `estado`, `busca`, `cache`, `confidence` | `core/pipeline` (Decision) |
| `config` | arquivos YAML/JSON | todos (Config, BookTable) |

---

## 18. Ordem de Implementação Recomendada (alinhada ao Plano)

| Ordem | Módulo | Fase do Plano |
|---|---|---|
| 1 | `config/` | Fase 0 |
| 2 | `data/` + `scripts/build_index.py` (FTS5 apenas) | Fase 0 |
| 3 | `integracao_holyrics/client.py` | Fase 0 |
| 4 | `logs/` | Fase 0 |
| 5 | `core/decision.py` (esqueleto: valida ref + chama Holyrics) | Fase 0 |
| 6 | `estado/state.py` | Fase 1 (MVP) |
| 7 | `parser/` (normalizer, books, parser) | Fase 1 (MVP) |
| 8 | `cache/cache.py` (current_verse apenas) | Fase 1 (MVP) |
| 9 | `microfone/capture.py` | Fase 1 (MVP) |
| 10 | `transcricao/stt.py` | Fase 1 (MVP) |
| 11 | `core/pipeline.py` (parser-first, sem LLM/busca) | Fase 1 (MVP) |
| 12 | `llm/` (client, prompts) | Fase 2 (Alpha) |
| 13 | `busca/searcher.py` (FTS5 puro) | Fase 2 (Alpha) |
| 14 | `confidence/manager.py` (parcial: c_stt, c_intent, c_search lexical) | Fase 2 (Alpha) |
| 15 | `core/decision.py` estendido (LLM + busca lexical) | Fase 2 (Alpha) |
| 16 | `core/pipeline.py` estendido (LLM + busca) | Fase 2 (Alpha) |
| 17 | `busca/embeddings.py` + `busca/searcher.py` (híbrida) | Fase 3 (Beta) |
| 18 | `cache/cache.py` completo | Fase 3 (Beta) |
| 19 | `confidence/manager.py` completo (c_search híbrido + ambiguous) | Fase 3 (Beta) |
| 20 | `interface/tray.py` | Fase 3 (Beta) |
| 21 | `scripts/benchmark.py` | Fase 4 (Release) |
| 22 | `core/pipeline.py` (intenção refinada + fallback) | Fase 4 (Release) |

---

## 19. Conclusão

Este Blueprint especifica cada módulo em nível de implementação: interfaces públicas, contratos, classes, funções, fluxo interno, desempenho, erros e critérios de teste/conclusão. Junto com a arquitetura (`DOCUMENTACAO_TECNICA.md`) e o plano de fases (`Plano_de_Implementacao.md`), um desenvolvedor tem tudo o que precisa para implementar um módulo sem reinterpretar decisões de arquitetura.

Pontos-chave para evitar ambiguidade na implementação:
- **Tipos canônicos** em `core/types.py` — nenhum módulo redefine `Intent`, `VerseRef`, `SearchResult`, `Confidence`, `Decision`, `LogEntry`.
- **`BookTable` singleton** compartilhado entre parser, estado e decision.
- **`core/pipeline` é o único orquestrador** — só ele chama LLM, busca e Holyrics (via decision).
- **`core/decision` coordena** estado + busca + cache + confidence; o pipeline apenas executa o resultado.
- **Contratos via dataclasses**, não via dicts opacos — todas as trocas entre módulos usam os tipos de §0.1.
- **Ordem de implementação** em §18 respeita dependências e o plano de fases.
