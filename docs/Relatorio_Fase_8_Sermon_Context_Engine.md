# Relatório Técnico — Fase 8: Sermon Context Engine

**Data:** 2026-07-18
**Status:** Concluído
**Fase:** 8 — Sermon Context Engine
**Testes:** 1492 totais (116 novos) — todos passando

---

## 1. Arquitetura Criada

A Fase 8 introduz o **Sermon Context Engine** — um módulo isolado, puramente funcional, responsável por manter e evoluir o estado do sermão em andamento. A arquitetura segue o princípio de **responsabilidade única** e **desacoplamento total** do restante do sistema.

### Princípios de design

| Princípio | Implementação |
|-----------|---------------|
| Imutabilidade | `SermonContext` é `@dataclass(frozen=True)`; todas as coleções são `tuple`; `process()` retorna novo contexto |
| Desacoplamento | Engine não conhece Searcher, Ranking, Holyrics, LLM, Parser, KnowledgeBase, Embeddings |
| Eventos tipados | 10 eventos `frozen dataclass` herdam de `ContextEvent` |
| Sem estado global | Contexto é passado explicitamente; engine não mantém estado entre chamadas |
| Clock injetável | `clock: callable = time.time` permite testes determinísticos |
| Configuração explícita | `ContextWindowConfig` ajusta janela e expiração sem quebrar compatibilidade |

### Diagrama de fluxo

```
┌──────────────────┐     evento tipado     ┌─────────────────────┐
│  Pipeline futuro │ ────────────────────> │ SermonContextEngine │
│  (Streaming      │                        │   .process(ctx, ev) │
│   Speech)        │ <─── novo SermonContext ─────────────────────│
└──────────────────┘                        └─────────────────────┘
                                                      │
                                                      ▼
                                            ┌──────────────────┐
                                            │  SermonContext   │
                                            │  (imutável DTO)  │
                                            └──────────────────┘
```

### Estrutura de arquivos

```
context/
├── __init__.py      (64 linhas)  — API pública
├── dtos.py          (182 linhas) — SermonContext DTO
├── events.py        (252 linhas) — 10 eventos tipados
└── engine.py        (462 linhas) — SermonContextEngine + ContextWindowConfig

tests/
├── test_sermon_context_dto.py       (290 linhas, 40 testes)
├── test_sermon_context_engine.py    (464 linhas, 41 testes)
└── test_sermon_context_expiry.py    (486 linhas, 35 testes)
```

---

## 2. Novos Módulos

### `context/` (pacote Python)

Módulo novo, totalmente isolado do restante do código. Única dependência externa: `busca.bible_reference.BibleReference` (DTO canônico criado na Fase 7.6).

**API pública** (exportada via `context/__init__.py`):

- `SermonContext` — DTO imutável do estado
- `SermonContextEngine` — engine que evolui o contexto
- `ContextWindowConfig` — configuração da janela e expiração
- 10 eventos tipados: `BookChanged`, `ChapterChanged`, `ReferenceResolved`, `ReferenceRepeated`, `ReferenceCompleted`, `ThemeMentioned`, `EntityMentioned`, `ConceptMentioned`, `EventMentioned`, `ContextReset`
- `ContextEvent` — classe base abstrata
- `SermonContextEvent` — Union de todos os eventos (type hint)

---

## 3. Novos DTOs

### `SermonContext` (`context/dtos.py`)

DTO imutável (`@dataclass(frozen=True)`) representando o estado completo do sermão em andamento.

**Estado ativo:**
| Campo | Tipo | Descrição |
|-------|------|-----------|
| `book` | `str \| None` | Livro ativo (ex.: "João") |
| `book_id` | `int \| None` | ID do livro (1..66) |
| `chapter` | `int \| None` | Capítulo ativo |
| `last_reference` | `BibleReference \| None` | Última referência resolvida |

**Histórico recente** (mais recente primeiro, todos `tuple`):
| Campo | Tipo | Descrição |
|-------|------|-----------|
| `recent_references` | `tuple[BibleReference, ...]` | Últimas N referências |
| `recent_books` | `tuple[str, ...]` | Últimos N livros (dedup) |
| `recent_themes` | `tuple[str, ...]` | Últimos N temas (dedup) |
| `recent_characters` | `tuple[str, ...]` | Últimos N personagens (dedup) |
| `recent_concepts` | `tuple[str, ...]` | Últimos N conceitos (dedup) |
| `recent_events` | `tuple[str, ...]` | Últimos N eventos (dedup) |

**Contadores para expiração:**
| Campo | Tipo | Descrição |
|-------|------|-----------|
| `update_count` | `int` | Total de atualizações desde reset |
| `last_book_update` | `int` | `update_count` da última menção ao livro |
| `last_chapter_update` | `int` | `update_count` da última menção ao capítulo |
| `last_theme_update` | `int` | `update_count` do último tema |
| `last_character_update` | `int` | `update_count` do último personagem |
| `last_concept_update` | `int` | `update_count` do último conceito |
| `last_event_update` | `int` | `update_count` do último evento |

**Timestamps:**
| Campo | Tipo | Descrição |
|-------|------|-----------|
| `created_at` | `float` | Timestamp de criação |
| `updated_at` | `float` | Timestamp da última atualização |

**Properties:**
- `is_empty` — True se contexto vazio
- `has_active_book` — True se há livro ativo
- `has_active_chapter` — True se há capítulo ativo
- `has_active_reference` — True se há referência ativa

**Métodos:**
- `to_dict()` — serialização para debug/log/persistência futura
- `with_update(**changes)` — cria novo contexto com mudanças (incrementa `update_count`)

---

## 4. Novos Eventos

Todos os eventos são `@dataclass(frozen=True)` herdados de `ContextEvent` (que tem campo opcional `timestamp: float = 0.0`).

| Evento | Campos | Quando emitir |
|--------|--------|---------------|
| `BookChanged` | `book: str`, `book_id: int` | "Abram em João" |
| `ChapterChanged` | `chapter: int` | "capítulo três" |
| `ReferenceResolved` | `reference: BibleReference \| None` | "João 3:16" (referência completa) |
| `ReferenceCompleted` | `reference: BibleReference \| None` | "versículo 16" após "João 3" (completada do contexto) |
| `ReferenceRepeated` | `hint: str` | "aquele versículo", "volta naquele texto" |
| `ThemeMentioned` | `theme: str` | "armadura de Deus", "graça" |
| `EntityMentioned` | `name: str`, `entity_type: str` | "Pedro", "Jesus", "monte Sinai" |
| `ConceptMentioned` | `concept_id: str`, `concept_name: str` | "filho pródigo", "bom pastor" |
| `EventMentioned` | `event: str` | "parábola do filho pródigo" |
| `ContextReset` | `reason: str` | Entre sermões ou reset explícito |

**Type alias:** `SermonContextEvent = Union[...]` para type hints.

---

## 5. SermonContextEngine (`context/engine.py`)

Engine que evolui o contexto do sermão via eventos.

### API

```python
engine = SermonContextEngine(config=None, clock=time.time)
ctx = engine.reset()                                    # → SermonContext vazio
ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
ctx = engine.process(ctx, ChapterChanged(chapter=3))
ctx = engine.process(ctx, ReferenceCompleted(reference=ref))
```

### Características

- **`process(context, event) → SermonContext`**: nunca modifica o contexto recebido; sempre retorna novo contexto.
- **`reset(reason="") → SermonContext`**: retorna contexto vazio com timestamp atual.
- **Dispatch por tipo**: `isinstance(event, ...)` para cada tipo de evento.
- **Evento desconhecido**: retorna contexto com `update_count` incrementado (extensibilidade segura).
- **`ContextReset`**: tratado separadamente, retorna `reset()`.
- **Clock injetável**: para testes determinísticos.

### Handlers internos

| Handler | Comportamento |
|---------|---------------|
| `_handle_book_changed` | Atualiza livro ativo + adiciona ao histórico (dedup) |
| `_handle_chapter_changed` | Atualiza capítulo ativo |
| `_handle_reference_resolved` | Atualiza referência + livro + capítulo + históricos |
| `_handle_reference_completed` | Atualiza referência + capítulo + histórico |
| `_handle_reference_repeated` | Mantém referência ativa, re-adiciona ao topo do histórico |
| `_handle_theme_mentioned` | Adiciona tema ao histórico (dedup) |
| `_handle_entity_mentioned` | Adiciona personagem/lugar ao histórico (dedup) |
| `_handle_concept_mentioned` | Adiciona conceito ao histórico (dedup) |
| `_handle_event_mentioned` | Adiciona evento ao histórico (dedup) |

### Helpers

- `_prepend(tup, item, max_size)` — adiciona no início (sem dedup, para referências)
- `_prepend_unique(tup, item, max_size)` — adiciona no início com dedup (para livros, temas, etc.)
- `_apply_expiry(ctx)` — aplica política de expiração após cada evento

---

## 6. Política de Expiração

A expiração é **determinística e baseada em contadores** (não em tempo real). Após cada evento, `_apply_expiry()` verifica:

```
updates_since_book    = update_count - last_book_update
updates_since_chapter = update_count - last_chapter_update
```

| Item | Condição de expiração | Efeito |
|------|----------------------|--------|
| Livro ativo | `updates_since_book > book_expiry` | `book = None`, `book_id = None` |
| Capítulo ativo | `updates_since_chapter > chapter_expiry` | `chapter = None` |
| Referência ativa | `updates_since_book > book_expiry` (segue o livro) | `last_reference = None` |

**Importante:** A expiração remove apenas o **estado ativo**. O **histórico** (`recent_*`) é preservado (limitado apenas pela janela de contexto).

### Defaults (`ContextWindowConfig`)

| Parâmetro | Default | Significado |
|-----------|---------|-------------|
| `book_expiry` | 15 | 15 updates sem mencionar o livro → expira |
| `chapter_expiry` | 10 | 10 updates sem mencionar o capítulo → expira |
| `theme_expiry` | 12 | (reservado para expiração futura de temas) |
| `character_expiry` | 12 | (reservado) |
| `concept_expiry` | 12 | (reservado) |
| `event_expiry` | 12 | (reservado) |

### Renovação

Mencionar o item novamente renova o contador (`last_*_update = update_count`), reiniciando a janela de expiração.

---

## 7. Tamanho da Janela de Contexto

O histórico é limitado por configuração. Itudes mais antigos são descartados quando o limite é atingido.

| Parâmetro | Default | Descrição |
|-----------|---------|-----------|
| `max_references` | 10 | Máximo de referências no histórico |
| `max_books` | 5 | Máximo de livros no histórico |
| `max_themes` | 8 | Máximo de temas |
| `max_characters` | 10 | Máximo de personagens |
| `max_concepts` | 8 | Máximo de conceitos |
| `max_events` | 8 | Máximo de eventos |

**Ordem:** mais recente primeiro. Novo item é inserido no início da tuple; se exceder `max_*`, o último é descartado.

**Deduplicação:** livros, temas, personagens, conceitos e eventos usam `_prepend_unique` (item existente é movido para o início, sem duplicata). Referências usam `_prepend` (sem dedup — a mesma referência pode aparecer múltiplas vezes em momentos diferentes).

---

## 8. Quantidade de Novos Testes

**116 novos testes** distribuídos em 3 arquivos:

| Arquivo | Linhas | Testes | Cobertura |
|---------|--------|--------|-----------|
| `tests/test_sermon_context_dto.py` | 290 | 40 | DTO, imutabilidade, properties, serialização, timestamps, imutabilidade dos eventos |
| `tests/test_sermon_context_engine.py` | 464 | 41 | Engine: reset, BookChanged, ChapterChanged, ReferenceResolved/Completed/Repeated, ThemeMentioned, EntityMentioned, ConceptMentioned, EventMentioned, desacoplamento |
| `tests/test_sermon_context_expiry.py` | 486 | 35 | ContextReset, múltiplas atualizações, expiração (livro/capítulo/referência), janela de contexto, config customizada, cenário completo, persistência, imutabilidade após updates |
| **Total** | **1240** | **116** | |

### Cobertura detalhada

- **Contexto vazio**: 7 testes (is_empty, no_book, no_chapter, no_reference, empty_collections, zero_counters, no_active_state)
- **Imutabilidade**: 12 testes (frozen em DTO e eventos, with_update retorna novo, preserva originais)
- **Properties**: 9 testes (has_active_*, is_empty com各种 campos)
- **Serialização**: 5 testes (to_dict vazio/com dados/coleções/contadores)
- **Eventos**: 8 testes (cada tipo frozen)
- **Engine reset**: 3 testes
- **BookChanged**: 6 testes (set book, histórico, contador, imutabilidade, múltiplas mudanças)
- **ChapterChanged**: 3 testes
- **ReferenceResolved**: 5 testes (last_ref, histórico, atualiza book/chapter, ordem)
- **ReferenceCompleted**: 3 testes
- **ReferenceRepeated**: 3 testes
- **ThemeMentioned**: 4 testes (incl. dedup e empty ignorado)
- **EntityMentioned**: 4 testes
- **ConceptMentioned**: 3 testes
- **EventMentioned**: 3 testes
- **ContextReset**: 4 testes
- **Múltiplas atualizações**: 4 testes (contador, ordem cronológica, consecutivas, book+chapter+ref)
- **Expiração**: 7 testes (book, chapter, reference, renovação, dentro/fora da janela)
- **Janela de contexto**: 6 testes (max_references, max_books, max_themes, max_characters, max_concepts, max_events)
- **Config**: 3 testes (default, custom, engine usa config)
- **Cenário completo**: 2 testes (sermão completo, reset entre sermões)
- **Desacoplamento**: 7 testes (no Searcher, Ranking, LLM, Parser, KnowledgeBase, Holyrics, Embeddings)
- **Persistência**: 5 testes (recent_* persistidos após outros eventos)
- **Imutabilidade após updates**: 2 testes (contextos anteriores válidos, objetos distintos)

---

## 9. Exemplos de Evolução do Contexto Durante um Sermão

### Exemplo 1: Sermão completo

```python
engine = SermonContextEngine()
ctx = engine.reset()

# 1. "Abram em João capítulo 3"
ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
ctx = engine.process(ctx, ChapterChanged(chapter=3))
# → book="João", book_id=43, chapter=3, update_count=2

# 2. "versículo 16"
ctx = engine.process(ctx, ReferenceCompleted(
    reference=BibleReference(BibleBook.JOAO, 3, 16)))
# → last_reference="João 3:16", recent_references=("João 3:16",), update_count=3

# 3. "Pedro andou sobre as águas"
ctx = engine.process(ctx, EntityMentioned(name="Pedro", entity_type="person"))
ctx = engine.process(ctx, ConceptMentioned(concept_id="pedro_anda_sobre_aguas"))
# → recent_characters=("Pedro",), recent_concepts=("pedro_anda_sobre_aguas",)

# 4. "o tema hoje é fé e coragem"
ctx = engine.process(ctx, ThemeMentioned(theme="fé"))
ctx = engine.process(ctx, ThemeMentioned(theme="coragem"))
# → recent_themes=("coragem", "fé")

# 5. "Agora vamos para Lucas 15, a parábola do filho pródigo"
ctx = engine.process(ctx, BookChanged(book="Lucas", book_id=42))
ctx = engine.process(ctx, ChapterChanged(chapter=15))
ctx = engine.process(ctx, ReferenceResolved(
    reference=BibleReference(BibleBook.LUCAS, 15, 11, 32)))
# → book="Lucas", chapter=15, last_reference="Lucas 15:11-32"
# → recent_books=("Lucas", "João"), recent_references=("Lucas 15:11-32", "João 3:16")
# → "Pedro" ainda em recent_characters, "fé" e "coragem" ainda em recent_themes

# 6. Fim do sermão
ctx = engine.process(ctx, ContextReset(reason="fim do sermão"))
# → is_empty=True, update_count=0
```

### Exemplo 2: Expiração natural

```python
config = ContextWindowConfig(book_expiry=5)
engine = SermonContextEngine(config=config)
ctx = engine.reset()

ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
# → book="João", last_book_update=1

# 6 eventos sem mencionar o livro
for i in range(6):
    ctx = engine.process(ctx, ThemeMentioned(theme=f"tema_{i}"))
# → update_count=7, updates_since_book=6 > book_expiry=5
# → book=None, book_id=None, last_reference=None (expirados)
# → recent_themes preservado, recent_books preservado
```

### Exemplo 3: Renovação

```python
config = ContextWindowConfig(book_expiry=5)
engine = SermonContextEngine(config=config)
ctx = engine.reset()

ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
# 3 eventos
for i in range(3):
    ctx = engine.process(ctx, ThemeMentioned(theme=f"t{i}"))
# Renovar menção ao livro
ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
# Mais 3 eventos
for i in range(3):
    ctx = engine.process(ctx, ThemeMentioned(theme=f"t2_{i}"))
# → book="João" ainda ativo (renovado a tempo)
```

### Exemplo 4: Janela de contexto limita histórico

```python
config = ContextWindowConfig(max_references=3)
engine = SermonContextEngine(config=config)
ctx = engine.reset()

for i in range(5):
    ctx = engine.process(ctx, ReferenceResolved(
        reference=BibleReference(BibleBook.JOAO, i+1, 1)))
# → recent_references tem apenas 3 itens (caps 5, 4, 3)
# → caps 1 e 2 foram descartados
```

---

## 10. Confirmação: Nenhum Comportamento Existente foi Alterado

A Fase 8 é **puramente aditiva**. Nenhum arquivo existente foi modificado em seu comportamento.

**Evidências:**

1. **Novo pacote isolado**: `context/` é um módulo novo, não importado por nenhum componente existente.
2. **Única dependência externa**: `busca.bible_reference.BibleReference` (apenas leitura — o engine consome o DTO, não o modifica).
3. **Nenhum import reverso**: nenhum arquivo existente importa `context.*`.
4. **Sem alteração de APIs existentes**: Searcher, Ranking, LLM, Parser, KnowledgeBase, Holyrics, Embeddings — todos intactos.
5. **Testes existentes**: 1376 testes pré-existentes continuam passando sem modificação.

---

## 11. Confirmação: Compatibilidade com o Futuro Streaming Speech Pipeline

A arquitetura foi projetada para suportar o futuro **Streaming Speech Pipeline** (reconhecimento de fala em tempo real durante o sermão).

### Como a compatibilidade é garantida

1. **Eventos de alto nível vs. baixo nível**: O engine atual processa eventos de alto nível (`BookChanged`, `ReferenceResolved`). No futuro, o streaming emitirá eventos de baixo nível (`BOOK_DETECTED`, `CHAPTER_DETECTED`, `VERSE_DETECTED`, `CONCEPT_DETECTED`, `THEME_DETECTED`). A arquitetura suporta duas evoluções:
   - **Opção A**: Agregar eventos de baixo nível em eventos de alto nível antes de chegar ao engine (camada intermediária).
   - **Opção B**: Estender o engine para processar eventos de baixo nível diretamente (novos handlers + novos eventos).

2. **Extensibilidade segura**: Eventos desconhecidos são tratados graciosamente (`else` no dispatch incrementa apenas `update_count`), então adicionar novos eventos não quebra o engine.

3. **Clock injetável**: Permite que o streaming use timestamps reais ou simulados.

4. **Imutabilidade**: Permite que múltiplos consumidores leiam o contexto simultaneamente (ex.: ranking, sugestões, display) sem race conditions.

5. **Sem estado global**: O engine pode ser instanciado por sessão/streaming sem interferência.

6. **`to_dict()`**: Pronto para serialização (persistência, transmissão para UI, log).

### Eventos futuros previstos (não implementados ainda)

| Evento futuro | Mapeia para |
|---------------|-------------|
| `BOOK_DETECTED` | `BookChanged` |
| `CHAPTER_DETECTED` | `ChapterChanged` |
| `VERSE_DETECTED` + contexto ativo | `ReferenceCompleted` |
| `REFERENCE_DETECTED` (completa) | `ReferenceResolved` |
| `THEME_DETECTED` | `ThemeMentioned` |
| `CONCEPT_DETECTED` | `ConceptMentioned` |
| `ENTITY_DETECTED` | `EntityMentioned` |

---

## 12. Confirmação: Todos os Testes Antigos Continuam Passando

**Execução completa da suíte de testes:**

```
$ python -m pytest tests/ -q

1492 passed in 201.47s (0:03:21)
```

| Categoria | Quantidade | Status |
|-----------|-----------|--------|
| Testes pré-existentes | 1376 | ✅ Passando |
| Testes novos (Fase 8) | 116 | ✅ Passando |
| **Total** | **1492** | **✅ Todos passando** |

### Arquivos de teste novos (cada um < 500 linhas)

| Arquivo | Linhas | Testes |
|---------|--------|--------|
| `tests/test_sermon_context_dto.py` | 290 | 40 |
| `tests/test_sermon_context_engine.py` | 464 | 41 |
| `tests/test_sermon_context_expiry.py` | 486 | 35 |

---

## 13. Resumo Executivo

| Aspecto | Valor |
|---------|-------|
| **Fase** | 8 — Sermon Context Engine |
| **Módulos novos** | 1 pacote (`context/`) com 4 arquivos (960 linhas) |
| **DTOs novos** | 1 (`SermonContext`) |
| **Eventos novos** | 10 (todos `frozen dataclass`) |
| **Engine novo** | 1 (`SermonContextEngine`) + `ContextWindowConfig` |
| **Política de expiração** | Baseada em contadores (book=15, chapter=10 updates) |
| **Janela de contexto** | 10 refs, 5 livros, 8 temas, 10 personagens, 8 conceitos, 8 eventos |
| **Testes novos** | 116 (em 3 arquivos, 1240 linhas) |
| **Testes totais** | 1492 (todos passando) |
| **Comportamento alterado** | Nenhum (puramente aditivo) |
| **Compatibilidade futura** | Streaming Speech Pipeline (eventos de baixo nível) |
| **Desacoplamento** | Engine não conhece nenhum outro componente |

---

*Relatório gerado automaticamente pela implementação da Fase 8.*
