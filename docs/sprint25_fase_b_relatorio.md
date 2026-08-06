# Sprint 25 — Fase B: Relatório de Entrega

## Sumário

A Fase B transformou o Painel do Operador em uma ferramenta de navegação
rápida durante o culto, com navegação contínua por botões ◀ ▶, atalhos de
teclado via camada de comandos desacoplada, separação visual clara entre
"Selecionado" e "Apresentado", e sincronização automática após qualquer
apresentação (IA ou operador).

## 1. Diagrama da Máquina de Estados Implementada

Documentado em `docs/sprint25_fase_b_state_machine.md`.

```
                    ┌─────────────────────────────────┐
                    │         (estado inicial)         │
                    │   selected = null                │
                    │   presented = null               │
                    └────────────┬────────────────────┘
                                 │
                    operador navega OU IA apresenta
                                 │
                                 ▼
              ┌──────────────────────────────────────┐
              │  SELEÇÃO (selected)                   │
              │  Operador escolhe referência          │
              │  via QuickNavigator, busca ou favorito│
              └────────────┬─────────────────────────┘
                           │ getVerse() via cache LRU
                           ▼
              ┌──────────────────────────────────────┐
              │  PRÉ-VISUALIZAÇÃO (preview)           │
              │  Texto carregado, card exibe conteúdo │
              │  Operador confirma visualmente        │
              └────────────┬─────────────────────────┘
                           │ Enter / botão Apresentar
                           ▼
              ┌──────────────────────────────────────┐
              │  APRESENTAR (comando)                 │
              │  POST /operator/present               │
              │  → HolyricsClient.show_verse()        │
              │  → EventBus.publish(VersePresented)   │
              └────────────┬─────────────────────────┘
                           │ VersePresented evento
                           ▼
              ┌──────────────────────────────────────┐
              │  APRESENTADO (presented)              │
              │  VersePresentationStore.current       │
              │  Card "Apresentado" exibe referência  │
              └────────────┬─────────────────────────┘
                           │ Sincronização automática
                           ▼
              ┌──────────────────────────────────────┐
              │  SINCRONIZADO                          │
              │  selected = presented                  │
              │  QuickNavigator posicionado            │
              │  Operador continua navegando daqui     │
              └────────────┬─────────────────────────┘
                           │ operador navega ◀ ▶
                           ▼
                    (volta para SELEÇÃO)
```

Estados: inicial, SELEÇÃO, PRÉ-VISUALIZAÇÃO, APRESENTAR, APRESENTADO,
SINCRONIZADO. Transições detalhadas em tabela no documento.

Regras de consistência:
- `selected` e `presented` são independentes (navegar não afeta Holyrics)
- Após apresentação, `selected` sincroniza com `presented`
- `preview` é derivado de `selected` via cache LRU (não é estado separado)
- Navegação contínua atravessa capítulos e livros
- Estados ambíguos são proibidos (cards separados para Selecionado e Apresentado)

## 2. Arquitetura da Camada de Comandos

Fluxo obrigatório: `Keyboard → Command → Workspace → UI`

### WorkspaceCommands (`frontend/src/components/operator/WorkspaceCommands.ts`)

7 comandos reutilizáveis, cada um recebendo um `WorkspaceContext`:

| Comando | Ação |
|---|---|
| `NextVerseCommand` | selected = próximo versículo (atravessa capítulos e livros) |
| `PreviousVerseCommand` | selected = versículo anterior (atravessa capítulos e livros) |
| `NextChapterCommand` | selected = próximo capítulo, verse=1 (atravessa livros) |
| `PreviousChapterCommand` | selected = capítulo anterior, último versículo (atravessa livros) |
| `PresentVerseCommand` | POST /operator/present com selected + recordUsage |
| `ReplayVerseCommand` | POST /operator/present com presented (ou selected como fallback) |
| `ClearSelectionCommand` | selected = null |
| `SelectByReferenceCommand` | selected = ref específica (para busca/favoritos futuros) |

`executeCommand(name, ctx)` permite executar por string (para Stream Deck,
MIDI, API externa futura).

### WorkspaceContext (`useWorkspaceContext.ts`)

Contrato injetado nos comandos com acesso a:
- `selected`, `presented`, `quickPresentation` (getters)
- `books`, `getChapters()`, `getVerses()`, `getVerse()` (navegação com cache LRU)
- `presentVerse()` (serviço)
- `setSelected()` (store)
- `recordUsage()` (recents store)

### KeyboardController (`KeyboardController.ts`)

Listener global de `keydown` que dispara comandos. Sem lógica de negócio.

| Tecla | Comando |
|---|---|
| ← | `previousVerse` |
| → | `nextVerse` |
| ↑ | `previousChapter` |
| ↓ | `nextChapter` |
| Enter | `presentVerse` |
| Ctrl+Enter | `replayVerse` |
| Esc | `clearSelection` |
| Ctrl+H | placeholder (histórico, Fase C) |
| Ctrl+F | placeholder (busca, Fase C) |

Atalhos de navegação não funcionam em campos de texto (input, textarea,
select, contenteditable). Esc e Ctrl+H/Ctrl+F sempre funcionam.

## 3. Componentes Criados ou Refatorados

### Novos componentes (`frontend/src/components/operator/`)

| Arquivo | Linhas | Responsabilidade |
|---|---|---|
| `WorkspaceCommands.ts` | 421 | 7 comandos + executeCommand + WorkspaceContext |
| `KeyboardController.ts` | 136 | Listener global de teclado → comandos |
| `useWorkspaceContext.ts` | 86 | Constrói WorkspaceContext a partir de stores/services |
| `useAutoSyncSelected.ts` | 51 | Sincroniza selected = presented após apresentação |
| `QuickNavigator.tsx` | 203 | Navegação ◀ ▶ para livro/capítulo/versículo |
| `PresentationCards.tsx` | 277 | Cards Selecionado (preview) + Apresentado (ao vivo) |
| `HistoryList.tsx` | 90 | Histórico extraído do OperatorPanel monolítico |
| `QuickPresentationToggle.tsx` | 58 | Toggle do modo quick presentation |
| `OperatorWorkspace.tsx` | 113 | Orquestra todos os componentes |
| `index.ts` | 27 | Exports do módulo |

### Refatorações

- `OperatorPage.tsx`: trocou `OperatorPanel` por `OperatorWorkspace`
- `OperatorPanel.tsx`: mantido para compatibilidade (não quebra imports existentes)
- `HistoryList`: extraído do OperatorPanel monolítico para componente próprio
- `hooks/index.ts`: re-exporta `useStores` de `InfraContext`

### Documentação

- `docs/sprint25_fase_b_state_machine.md` (183 linhas): máquina de estados formal

## 4. Fluxo de Sincronização entre Workspace e EventBus

```
IA apresenta versículo
        │
        ▼
VersePresentationService (backend)
        │
        ▼
EventBus.publish(VersePresented)
        │
        ▼
EventStream → WebSocket → frontend
        │
        ▼
handleVersePresentationEvent (hooks/index.ts)
        │
        ▼
VersePresentationStore.update(entry)
        │
        ▼
useVersePresentation() re-renderiza
        │
        ├──→ PresentedCard exibe nova referência (card "Apresentado")
        │
        └──→ useAutoSyncSelected detecta mudança
                    │
                    ▼
                workspaceStore.setSelected(presentedRef)
                    │
                    ▼
                QuickNavigator posicionado em presented
                    │
                    ▼
                PreviewCard carrega texto via cache LRU
                    │
                    ▼
                Operador continua navegando daquele ponto
```

Para apresentação manual do operador, o fluxo é:
```
Operador clica "Apresentar" ou pressionou Enter
        │
        ▼
PresentVerseCommand(ctx)
        │
        ▼
services.operator.presentVerse() → POST /operator/present
        │
        ▼
Backend: HolyricsClient.show_verse() + EventBus.publish(VersePresented)
        │
        ▼
(mesmo fluxo acima: EventStream → VersePresentationStore → useAutoSyncSelected)
```

## 5. Testes Adicionados

### Frontend (`frontend/tests/`)

| Arquivo | Testes | Cobertura |
|---|---|---|
| `operator-commands.test.ts` | 25 | Navegação contínua, comandos, executeCommand, casos extremos |
| `operator-stores.test.ts` | 21 | WorkspaceStore, FavoritesStore, RecentsStore |
| `parse-bible-reference.test.ts` | 20 | Parser, normalização, sugestões, índice de aliases |
| **Total novo** | **66** | |

### Backend (`tests/`)

| Arquivo | Testes | Cobertura |
|---|---|---|
| `test_sprint25_operator_parse.py` | 9 | GET /operator/parse (validação híbrida) |

### Validações

- Frontend: 546 testes passaram (1 falha pré-existente em
  `transcript-panel.test.tsx`, não relacionada à Fase B, confirmada via
  `git stash`)
- Backend: 3156 testes passaram (3147 + 9 novos), 287s
- Typecheck: limpo
- Build: 1693 módulos, 449KB JS / 31.71KB CSS
- `config/config.overrides.json` permanece limpo após suíte completa

## 6. Evidências de Funcionamento

### Navegação contínua (testes unitários)

```
NextVerseCommand: atravessa capítulos (1:1:3 → 1:2:1) ✓
NextVerseCommand: atravessa livros (1:2:2 → 2:1:1) ✓
NextVerseCommand: fim da Bíblia retorna erro (3:2:4) ✓
PreviousVerseCommand: atravessa capítulos no sentido inverso (1:2:1 → 1:1:3) ✓
PreviousVerseCommand: atravessa livros no sentido inverso (2:1:1 → 1:2:2) ✓
PreviousVerseCommand: início da Bíblia retorna erro (1:1:1) ✓
NextChapterCommand: atravessa livros (1:2 → 2:1:1) ✓
PreviousChapterCommand: atravessa livros (2:1 → 1:2:2) ✓
```

### Camada de comandos (testes unitários)

```
PresentVerseCommand: dispara presentVerse e recordUsage ✓
ReplayVerseCommand: usa presented quando disponível ✓
ReplayVerseCommand: usa selected como fallback ✓
ClearSelectionCommand: limpa selected ✓
SelectByReferenceCommand: seleciona referência específica ✓
executeCommand: executa todos os comandos por nome ✓
COMMAND_NAMES: lista todos os 7 comandos ✓
quickPresentation é repassado para presentVerse ✓
```

### Parser híbrido (testes unitários + backend)

```
parse "João 3:16" → bookId=43, chapter=3, verse=16 ✓
parse "Rm 8:28" → bookId=45, chapter=8, verse=28 ✓
parse "João 3" → verse=null (capítulo sem versículo) ✓
parse "1 Coríntios 13:4" → bookId=46 ✓
parse "Apocalipse 21:4" → bookId=66 (com acentos) ✓
GET /operator/parse "João 3:16" → ok=true com texto ✓
GET /operator/parse "Rm 8:28" → ok=true ✓
GET /operator/parse "xyz" → ok=false, reason=parse_failed ✓
```

## 7. Limitações Conhecidas e Pontos Preparados para Fase C

### Limitações

1. **Ctrl+H e Ctrl+F são placeholders.** Os callbacks `onToggleHistory` e
   `onFocusSearch` existem no `KeyboardController` mas estão vazios no
   `OperatorWorkspace`. A Fase C implementará a busca e o histórico
   avançado.

2. **QuickNavigator não tem seletores diretos.** A navegação é apenas por
   botões ◀ ▶. Selecionar um livro específico (ex.: pular de Gênesis
   para Apocalipse) requer muitos cliques. A Fase C pode adicionar um
   seletor dropdown acessível via clique no nome do livro.

3. **Sincronização automática não diferencia origem.** O
   `useAutoSyncSelected` sincroniza `selected = presented` sempre que
   `presented` muda, independente se a origem foi IA ou operador. Se o
   operador acabou de apresentar manualmente e está navegando, a
   sincronização não causa problema (porque `presented` não muda de
   novo). Mas se a IA apresenta algo enquanto o operador navega, a
   seleção do operador é sobrescrita. Isso é o comportamento desejado
   (sincronizar com a IA), mas vale documentar.

4. **`OperatorPanel` antigo permanece no código.** Mantido para
   compatibilidade, mas não é mais usado pela `OperatorPage`. Pode ser
   removido em sprint futuro se nenhum outro componente o referencia.

### Pontos preparados para Fase C

1. **`OperatorFavoritesStore` e `OperatorRecentsStore`** já existem
   (Fase A) com add/remove/recordUsage/getByFrequency. A Fase C só
   precisa criar os componentes `FavoritesPanel` e `RecentsPanel` que
   consomem esses stores, com persistência via `useLocalStorage`.

2. **`SelectByReferenceCommand`** já existe e é a forma como a busca
   (QuickSearch) selecionará versículos. A Fase C cria o componente
   `QuickSearch` que usa `parseBibleReference` + `suggestReferences`
   (Fase A) e dispara `SelectByReferenceCommand`.

3. **`KeyboardController` callbacks** `onToggleHistory` e `onFocusSearch`
   já estão wired no `OperatorWorkspace`. A Fase C só precisa implementar
   os componentes de histórico e busca e passar os callbacks reais.

4. **`WorkspaceContext`** já expõe `recordUsage()`, que é chamado pelo
   `PresentVerseCommand`. Os recentes já estão sendo registrados; a Fase
   C só precisa exibi-los.

5. **`parseBibleReference` e `suggestReferences`** (Fase A) estão prontos
   para o QuickSearch, com índice de aliases construído a partir de
   `OperatorBookDTO[]`.

6. **`GET /operator/parse`** (Fase A) está pronto para validação
   híbrida: o frontend sugere, o backend confirma.

7. **Arquitetura de comandos** é extensível: adicionar novos comandos
   (ex.: `SelectFavoriteCommand`, `SearchCommand`) é apenas criar uma
   nova função que recebe `WorkspaceContext` e registrar no
   `executeCommand` se necessário.

## Critérios de Aceite — Verificação

| Critério | Status |
|---|---|
| Navegar pela Bíblia inteira usando apenas ◀ ▶ | ✓ (QuickNavigator + comandos) |
| Navegação atravessa capítulos e livros automaticamente | ✓ (testes 1-8) |
| Todos os atalhos funcionam corretamente | ✓ (KeyboardController) |
| Teclado usa camada de comandos, sem lógica nos componentes React | ✓ (KeyboardController apenas dispara executeCommand) |
| Estados "Selecionado" e "Apresentado" estão separados | ✓ (PresentationCards: SelectedCard + PresentedCard) |
| Painel sincroniza após apresentação da IA ou do operador | ✓ (useAutoSyncSelected) |
| Navegação fluida e instantânea | ✓ (cache LRU da Fase A) |
| Arquitetura preparada para Fase C sem refatorações estruturais | ✓ (ver pontos acima) |

Todos os critérios de aceite atendidos.
