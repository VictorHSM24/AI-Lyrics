// Sprint 24 — OperatorPanel original (mantido para compatibilidade).
export { OperatorPanel } from "./OperatorPanel";

// Sprint 25 Fase B — componentes de navegação e comandos.
export { OperatorWorkspace } from "./OperatorWorkspace";
export { QuickNavigator } from "./QuickNavigator";
export { PresentationCards } from "./PresentationCards";
export { HistoryList } from "./HistoryList";
export { QuickPresentationToggle } from "./QuickPresentationToggle";
export { useWorkspaceContext } from "./useWorkspaceContext";
export { useAutoSyncSelected } from "./useAutoSyncSelected";
export { useKeyboardController } from "./KeyboardController";
export {
  NextVerseCommand,
  PreviousVerseCommand,
  NextChapterCommand,
  PreviousChapterCommand,
  PresentVerseCommand,
  ReplayVerseCommand,
  ClearSelectionCommand,
  SelectByReferenceCommand,
  executeCommand,
  COMMAND_NAMES,
  type WorkspaceContext,
  type CommandResult,
  type CommandName,
} from "./WorkspaceCommands";

// Sprint 25 Fase C — busca, histórico, favoritos, mais usados.
export { QuickSearch, type QuickSearchHandle } from "./QuickSearch";
export { SuggestionList } from "./SuggestionList";
export { useSearchController, type UseSearchControllerResult, type HighlightedParts, type ConfirmResult } from "./SearchController";
export { HistoryPanel } from "./HistoryPanel";
export { FavoritesPanel } from "./FavoritesPanel";
export { MostUsedPanel } from "./MostUsedPanel";

// Sprint 26 — Command Palette Bíblica (Zero Mouse).
export { CommandPalette, type CommandPaletteHandle } from "./CommandPalette";
export { useCommandPalette, type UseCommandPaletteResult, type CommandPaletteState, type ConfirmOutcome } from "./useCommandPalette";
export { SearchHistoryController, type SearchHistoryState } from "./SearchHistoryController";
