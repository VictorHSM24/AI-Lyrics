# Sprint 25 — Fase B: Máquina de Estados do Operador

## Conceitos

### Versículo Selecionado (`selected`)

Aquilo que o operador está navegando no painel. Existe apenas no estado
do `OperatorWorkspaceStore`. Não tem relação com o Holyrics.

Pode ser alterado por:
- Navegação manual (QuickNavigator ◀ ▶)
- Busca (Fase C, futura)
- Favoritos (Fase C, futura)
- Histórico (Fase C, futura)
- Sincronização automática após apresentação

### Versículo Apresentado (`presented`)

Aquilo que está sendo exibido no Holyrics neste momento. Vem do
`VersePresentationStore.current` (atualizado em tempo real via
EventStream → EventBus → WebSocket).

Pode ser alterado por:
- Apresentação manual do operador (POST /operator/present)
- Apresentação automática da IA (VersePresentationService)
- Reapresentação (Fase C, via histórico/favoritos)

O `OperatorWorkspaceStore` NÃO é dono deste estado. Ele apenas lê do
`VersePresentationStore` para fins de sincronização.

### Versículo Pré-visualizado (`preview`)

Texto do versículo selecionado, carregado para confirmação visual
antes de enviar ao Holyrics. Derivado de `selected` via
`useOperatorNavigation.getVerse()` (com cache LRU da Fase A).

Não é um estado separado — é uma projeção de `selected` + cache.

### Navegação

Ato de alterar `selected` sem apresentar. Pode ser:
- Manual (operador clica ◀ ▶ ou usa teclado)
- Automática (sincronização após apresentação)

### Seleção por Busca (futura — Fase C)

Seleção via QuickSearch (parser de referências). Dispara comando
`SelectByReferenceCommand` que atualiza `selected`.

### Seleção Manual

Seleção via QuickNavigator ou seletores de livro/capítulo/versículo.
Dispara comandos `NextVerseCommand`, `PreviousVerseCommand`, etc.

### Seleção Automática (IA)

Quando a IA apresenta um versículo, o painel sincroniza `selected`
para a mesma referência, permitindo que o operador continue navegando
daquele ponto.

## Diagrama de Estados

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
                           │
                           │ getVerse() via cache LRU
                           ▼
              ┌──────────────────────────────────────┐
              │  PRÉ-VISUALIZAÇÃO (preview)           │
              │  Texto carregado, card exibe conteúdo │
              │  Operador confirma visualmente        │
              └────────────┬─────────────────────────┘
                           │
                           │ Enter / botão Apresentar
                           ▼
              ┌──────────────────────────────────────┐
              │  APRESENTAR (comando)                 │
              │  POST /operator/present               │
              │  → HolyricsClient.show_verse()        │
              │  → EventBus.publish(VersePresented)   │
              └────────────┬─────────────────────────┘
                           │
                           │ VersePresented evento
                           ▼
              ┌──────────────────────────────────────┐
              │  APRESENTADO (presented)              │
              │  VersePresentationStore.current       │
              │  Card "Apresentado" exibe referência  │
              └────────────┬─────────────────────────┘
                           │
                           │ Sincronização automática
                           ▼
              ┌──────────────────────────────────────┐
              │  SINCRONIZADO                          │
              │  selected = presented                  │
              │  QuickNavigator posicionado            │
              │  Operador continua navegando daqui     │
              └────────────┬─────────────────────────┘
                           │
                           │ operador navega ◀ ▶
                           ▼
                    (volta para SELEÇÃO)
```

## Transições Possíveis

| Estado Atual | Evento | Próximo Estado | Ação |
|---|---|---|---|
| inicial | operador navega | SELEÇÃO | `selected` = ref |
| inicial | IA apresenta | APRESENTADO | `presented` = ref |
| inicial | operador apresenta via busca | APRESENTADO | POST /present |
| SELEÇÃO | texto carregado | PRÉ-VISUALIZAÇÃO | `preview` = texto |
| PRÉ-VISUALIZAÇÃO | Enter / Apresentar | APRESENTAR | POST /present |
| PRÉ-VISUALIZAÇÃO | operador navega | SELEÇÃO | `selected` = nova ref |
| PRÉ-VISUALIZAÇÃO | Esc | inicial | `selected` = null |
| APRESENTAR | sucesso | APRESENTADO | `presented` = ref |
| APRESENTAR | falha | PRÉ-VISUALIZAÇÃO | erro exibido, `selected` mantido |
| APRESENTADO | sincronização | SINCRONIZADO | `selected` = `presented` |
| SINCRONIZADO | operador navega | SELEÇÃO | `selected` = nova ref |
| SINCRONIZADO | IA apresenta novo | APRESENTADO | `presented` = novo ref |
| qualquer | Ctrl+Enter (reapresentar) | APRESENTAR | POST /present com `selected` |

## Regras de Consistência

1. **`selected` e `presented` são independentes.** O operador pode
   navegar livremente sem afetar o Holyrics. Só `Apresentar` afeta
   `presented`.

2. **Após apresentação, `selected` sincroniza com `presented`.** Isso
   permite que o operador continue navegando daquele ponto sem precisar
   localizar manualmente.

3. **`preview` é derivado de `selected`.** Não é estado independente.
   Sempre que `selected` muda, `preview` é recalculado via cache LRU.

4. **Navegação contínua atravessa capítulos e livros.** João 3:36 →
   próximo → João 4:1. Malaquias 4:6 → próximo → Mateus 1:1.

5. **Atalhos de teclado disparam comandos, não lógica de UI.** O
   fluxo é: Keyboard → Command → Workspace → UI reage.

6. **Estados ambíguos são proibidos.** Se `selected` = Romanos 8:30 e
   `presented` = Romanos 8:28, os dois cards devem exibir valores
   diferentes simultaneamente. Nunca um card único misturando os dois.

## Camada de Comandos

Os comandos são a única forma de alterar `selected` e disparar
apresentações. Eles encapsulam toda a regra de negócio:

```
NextVerseCommand       — selected = próximo versículo (atravessa capítulos)
PreviousVerseCommand   — selected = versículo anterior (atravessa capítulos)
NextChapterCommand     — selected = próximo capítulo (atravessa livros)
PreviousChapterCommand — selected = capítulo anterior (atravessa livros)
PresentVerseCommand    — POST /operator/present com selected
ReplayVerseCommand     — POST /operator/present com presented (reapresenta atual)
ClearSelectionCommand  — selected = null
SelectByReferenceCommand — selected = ref específica (para busca/favoritos)
```

Cada comando recebe um `WorkspaceContext` com acesso a:
- `workspace` (OperatorWorkspaceStore)
- `navigation` (useOperatorNavigation — cache LRU)
- `services.operator` (para apresentar)
- `versePresentation` (para sincronizar e reapresentar)

Comandos são reutilizáveis por: KeyboardController, QuickNavigator
(botões), QuickSearch (Fase C), FavoritesPanel (Fase C), HistoryPanel
(Fase C), e futuramente Stream Deck / MIDI / API externa.
