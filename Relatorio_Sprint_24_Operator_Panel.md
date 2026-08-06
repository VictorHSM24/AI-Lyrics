# Relatório Sprint 24 — Painel do Operador

## Visão Geral

A Sprint 24 implementou o **Painel do Operador**, uma interface dedicada para o operador de cultos navegar pela Bíblia e apresentar versículos no Holyrics manualmente, sem precisar abrir o Holyrics diretamente. O painel se integra ao mesmo fluxo de eventos do pipeline automático, garantindo que toda apresentação (manual ou automática) apareça no histórico em tempo real.

## Objetivos

1. Expor navegação bíblica estruturada (livro → capítulo → versículo) via API REST.
2. Permitir apresentação manual de versículos no Holyrics via a mesma camada oficial (`HolyricsClient.show_verse()`).
3. Publicar `VersePresented` no EventBus para que o painel e todos os componentes atualizem automaticamente.
4. Criar UI dedicada com seletores, card do versículo, controles e histórico em tempo real.
5. Dedup consecutivo no histórico para evitar poluição com o mesmo versículo apresentado múltiplas vezes seguidas.

## Arquitetura

### Princípio de Design

O Painel do Operador foi construído sobre a infraestrutura existente, sem criar paralelismos:

- **Apresentação**: usa `HolyricsClient.show_verse()` (mesma camada do pipeline automático), garantindo consistência de token, timeout e retries.
- **Eventos**: publica `VersePresented` e `VersePresentationFailed` no `PipelineEventBus`, para que o `EventStore`, o `EventPublisher` (WebSocket) e todos os componentes reajam automaticamente.
- **Navegação**: usa `Searcher` (mesma base SQLite do pipeline de IA), garantindo que os versículos exibidos sejam os mesmos que o pipeline reconhece.
- **Histórico**: consome `VersePresentationStore` via `useVersePresentation()` (hook existente), atualizado em tempo real pelo `EventStreamBridge`.

### Fluxo de Apresentação Manual

```
Operador (UI) → POST /operator/present
  → Searcher.get_verse_by_id() resolve texto e referência
  → HolyricsClient.show_verse() apresenta no Holyrics
  → EventBus.publish(VersePresented) com origin="OperatorPanel"
    → EventStore armazena
    → EventPublisher transmite via WebSocket
    → Frontend EventStreamBridge atualiza VersePresentationStore
    → useVersePresentation() re-renderiza OperatorPanel + ConsolePage
```

### Fluxo de Navegação

```
Operador seleciona livro → GET /operator/books/{id}/chapters
  → Searcher.get_chapters(book_id) consulta SQLite
  → Retorna lista de capítulos

Operador seleciona capítulo → GET /operator/books/{id}/chapters/{c}/verses
  → Searcher.get_verse_numbers(book_id, chapter) consulta SQLite
  → Retorna lista de versículos

Operador seleciona versículo → GET /operator/verse
  → Searcher.get_verse_by_id() consulta SQLite
  → Retorna texto, referência formatada e versão
```

## Mudanças

### Backend

#### Novos endpoints (`api/routers/operator.py`, 473 linhas)

| Endpoint | Método | Descrição |
|---|---|---|
| `/operator/books` | GET | Lista os 66 livros com aliases |
| `/operator/books/{book_id}/chapters` | GET | Capítulos disponíveis por livro |
| `/operator/books/{book_id}/chapters/{chapter}/verses` | GET | Versículos por capítulo |
| `/operator/verse` | GET | Texto de um versículo específico |
| `/operator/present` | POST | Apresenta versículo no Holyrics + publica evento |
| `/operator/history` | GET | Histórico de apresentações (do EventStore) |
| `/operator/current` | GET | Último versículo apresentado |

#### Novos métodos no Searcher (`busca/searcher.py`)

- `get_chapters(book_id, version)` — lista capítulos via `SELECT DISTINCT chapter`.
- `get_verse_numbers(book_id, chapter, version)` — lista versículos via `SELECT verse`.
- `get_verse_by_id(book_id, chapter, verse, version)` — busca versículo por IDs numéricos (sem precisar do nome do livro, ao contrário de `search_by_reference`).

#### Registro do router

- `api/routers/__init__.py` — adicionado `operator_router` ao `ALL_ROUTERS`.
- `api/app.py` — adicionado `"operador"` às `SPA_ROUTES` e `"operator"` ao catch-all de paths API.

#### Publicação de eventos

O endpoint `POST /operator/present` publica `VersePresented` com `origin="OperatorPanel"` (distinto do `origin="VersePresentationService"` do pipeline automático), permitindo distinguir apresentações manuais das automáticas no histórico. Em caso de falha no Holyrics, publica `VersePresentationFailed` com `error_type="operator_manual"`.

### Frontend

#### Novo serviço (`frontend/src/services/index.ts`)

`OperatorService` com 7 métodos:
- `getBooks()`, `getChapters(bookId, version?)`, `getVerses(bookId, chapter, version?)`
- `getVerse(bookId, chapter, verse, version?)`
- `presentVerse(req)`, `getHistory(limit?)`, `getCurrent()`

Adicionado ao `PresentationServices` e ao `createStubServices()`.

#### Mapeamento REST (`frontend/src/sdk/transports/rest.ts`)

Adicionados 7 mapeamentos de método SDK → endpoint REST:
- `operator.getBooks` → `/operator/books`
- `operator.getChapters` → `/operator/books/{book_id}/chapters`
- `operator.getVerses` → `/operator/books/{book_id}/chapters/{chapter}/verses`
- `operator.getVerse` → `/operator/verse`
- `operator.present` → `/operator/present` (POST)
- `operator.getHistory` → `/operator/history`
- `operator.getCurrent` → `/operator/current`

**Melhoria na infraestrutura**: `buildUrl()` agora suporta path params (`{key}`), substituindo placeholders pelos valores correspondentes e removendo-os dos query params. Isso beneficia qualquer endpoint futuro que use path params.

#### Novo hook (`frontend/src/hooks/index.ts`)

`useOperator()` — gerencia estado de navegação (books, chapters, verses, currentVerse), apresentação (presenting, lastPresentResult) e histórico (entries do `VersePresentationStore` em tempo real). Expõe ações `loadBooks`, `loadChapters`, `loadVerses`, `loadVerse`, `presentVerse`.

#### Dedup consecutivo (`frontend/src/stream/handlers.ts`)

Ao receber `VersePresented`, se o versículo for o mesmo do `current` (mesmo `bookId`, `chapter`, `verse`), substitui a entrada no topo do histórico em vez de adicionar nova. Evita poluição quando o operador apresenta o mesmo versículo múltiplas vezes seguidas (ou quando o pipeline automático re-deteta a mesma referência).

#### Novos tipos (`frontend/src/types/index.ts`)

8 novos DTOs: `OperatorBookDTO`, `OperatorBooksResponseDTO`, `OperatorChapterListDTO`, `OperatorVerseListDTO`, `OperatorVerseDTO`, `OperatorPresentRequest`, `OperatorPresentResultDTO`, `OperatorHistoryEntryDTO`, `OperatorHistoryDTO`, `OperatorCurrentDTO`.

#### Novos componentes (`frontend/src/components/operator/`)

`OperatorPanel.tsx` (468 linhas) — painel completo com 4 sub-componentes:
1. **VerseNavigator** — seletores de livro/capítulo/versículo em cascata.
2. **CurrentVerseCard** — card com referência, texto e versão do versículo selecionado.
3. **PresentationControls** — toggle de quick presentation + botão Apresentar + último resultado.
4. **HistoryList** — histórico em tempo real com indicador "ao vivo" e ícones de status.

#### Nova página e rota

- `frontend/src/pages/OperatorPage.tsx` — página com `PageLayout` + `ConnectionIndicator` + `OperatorPanel`.
- `frontend/src/router/index.tsx` — rota `/operador` com `AppLayout`.
- `frontend/src/app/layout/Sidebar.tsx` — item "Operador" com ícone `BookOpen`, posicionado após Console.

## Testes

### Backend (`tests/test_sprint24_operator_panel.py`, 354 linhas, 23 testes)

8 classes de teste cobrindo todos os endpoints e métodos:

| Classe | Testes | Cobertura |
|---|---|---|
| `TestOperatorBooks` | 3 | Lista 66 livros, schema versioned, campos |
| `TestOperatorChapters` | 3 | Capítulos de João, book_id inválido, zero |
| `TestOperatorVerses` | 2 | Versículos de João 3, chapter inválido |
| `TestOperatorVerse` | 2 | João 3:16 com texto, 404 se não encontrado |
| `TestOperatorPresent` | 5 | Chamada Holyrics, publicação evento, quick, falha, 404 |
| `TestOperatorHistory` | 2 | Lista, limit |
| `TestOperatorCurrent` | 2 | Schema, entry após present |
| `TestSearcherNavigation` | 4 | get_chapters, get_verse_numbers, get_verse_by_id, not_found |

Fixtures usam `FakeSearcher` e `FakeBookTable` mockados, injetados no `CompositionRoot` via `set_root()`, permitindo testes isolados sem depender da base bíblica real.

### Frontend

- `npm run typecheck` — passou sem erros.
- `npm run build` — passou, 1680 módulos transformados, 434KB JS / 30KB CSS.

### Suíte completa

3147 testes passaram (3124 existentes + 23 novos), 11 subtests, em 214s.

## Arquivos Modificados

### Backend
- `api/routers/operator.py` (novo, 473 linhas)
- `api/routers/__init__.py` (adicionado operator_router)
- `api/app.py` (SPA_ROUTES + catch-all)
- `busca/searcher.py` (3 novos métodos: get_chapters, get_verse_numbers, get_verse_by_id)
- `tests/test_sprint24_operator_panel.py` (novo, 354 linhas, 23 testes)

### Frontend
- `frontend/src/types/index.ts` (8 novos DTOs)
- `frontend/src/services/index.ts` (OperatorService + PresentationServices + stub)
- `frontend/src/sdk/transports/rest.ts` (7 mapeamentos + path params + POST_METHODS)
- `frontend/src/api/client.ts` (operator no stub)
- `frontend/src/hooks/index.ts` (useOperator + imports)
- `frontend/src/stream/handlers.ts` (dedup consecutivo)
- `frontend/src/components/operator/OperatorPanel.tsx` (novo, 468 linhas)
- `frontend/src/components/operator/index.ts` (novo)
- `frontend/src/pages/OperatorPage.tsx` (novo)
- `frontend/src/pages/index.ts` (export OperatorPage)
- `frontend/src/router/index.tsx` (rota /operador)
- `frontend/src/app/layout/Sidebar.tsx` (item Operador)

## Decisões de Design

### 1. Por que publicar VersePresented no endpoint manual?

O endpoint `POST /operator/present` poderia apenas chamar `HolyricsClient.show_verse()` e retornar o resultado. Em vez disso, publica `VersePresented` no EventBus. Isso garante que:
- O histórico no painel do operador atualiza automaticamente.
- O ConsolePage (que usa `VersePresentationPanel`) também reflete a apresentação manual.
- O EventStore persiste a apresentação para auditoria.
- O WebSocket transmite para todos os clientes conectados.

### 2. Por que origin="OperatorPanel"?

Distingue apresentações manuais das automáticas (`origin="VersePresentationService"`) no histórico e na auditoria, sem precisar de campo extra no evento.

### 3. Por que dedup consecutivo em vez de dedup total?

O operador pode apresentar o mesmo versículo em momentos diferentes (ex: antes e depois do sermão). O dedup consecutivo apenas colapsa apresentações imediatamente seguidas do mesmo versículo, preservando o histórico de apresentações em momentos distintos.

### 4. Por que path params no buildUrl?

O `RestTransport.buildUrl()` não suportava path params. Adicionar suporte a `{key}` beneficia não apenas o operador, mas qualquer endpoint futuro que use path params (ex: `/sessions/{id}/events`).

## Estado Final

O Painel do Operador está completo e funcional, com navegação bíblica estruturada, apresentação manual integrada ao mesmo fluxo de eventos do pipeline automático, histórico em tempo real e dedup consecutivo. Todos os 3147 testes passam, typecheck e build do frontend limpos.
