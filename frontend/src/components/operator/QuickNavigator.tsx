/**
 * QuickNavigator (Sprint 25 Fase B) — navegação rápida ◀ ▶.
 *
 * Substitui a navegação baseada apenas em selects por botões grandes
 * que disparam comandos (NextVerse, PreviousVerse, etc.).
 *
 * Navegação contínua: atravessa capítulos e livros automaticamente.
 * João 3:36 → próximo → João 4:1. Malaquias 4:6 → próximo → Mateus 1:1.
 *
 * Cada clique dispara um comando que:
 * 1. Atualiza `selected` no WorkspaceStore
 * 2. Carrega o versículo via cache LRU (instantâneo se já cached)
 * 3. O PreviewCard reage automaticamente
 *
 * Não contém lógica de negócio — apenas dispara comandos.
 */

import { ChevronLeft, ChevronRight, BookOpen, FileText, Hash } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useWorkspaceSnapshot, useOperatorNavigation } from "@/hooks";
import { cn } from "@/utils";
import {
  NextVerseCommand,
  PreviousVerseCommand,
  NextChapterCommand,
  PreviousChapterCommand,
  type WorkspaceContext,
} from "./WorkspaceCommands";

interface QuickNavigatorProps {
  /** Contexto do workspace (construído via useWorkspaceContext). */
  ctx: WorkspaceContext;
  className?: string;
}

export function QuickNavigator({ ctx, className }: QuickNavigatorProps) {
  // Assinar o workspace store reativamente para re-renderizar quando
  // `selected` muda via comandos de navegação (não apenas via eventos
  // de apresentação que causam re-render do parent).
  const workspaceSnap = useWorkspaceSnapshot();
  const selected = workspaceSnap?.data.selected ?? null;
  const nav = useOperatorNavigation();

  // Estado local para exibir nome do livro, capítulo e versículo.
  // Derivado de `selected` + cache de books.
  const [bookName, setBookName] = useState<string>("");
  const [chapter, setChapter] = useState<number | null>(null);
  const [verse, setVerse] = useState<number | null>(null);

  // Carregar books na montagem (para resolver bookId → nome).
  useEffect(() => {
    if (nav.books.length === 0) {
      void nav.loadBooks();
    }
  }, [nav]);

  // Quando selected muda, atualizar display.
  useEffect(() => {
    if (!selected) {
      setBookName("");
      setChapter(null);
      setVerse(null);
      return;
    }
    const book = nav.books.find((b) => b.id === selected.bookId);
    setBookName(book?.canonical ?? `Livro ${selected.bookId}`);
    setChapter(selected.chapter);
    setVerse(selected.verse);
  }, [selected, nav.books]);

  const onNextVerse = useCallback(() => void NextVerseCommand(ctx), [ctx]);
  const onPrevVerse = useCallback(() => void PreviousVerseCommand(ctx), [ctx]);
  const onNextChapter = useCallback(() => void NextChapterCommand(ctx), [ctx]);
  const onPrevChapter = useCallback(() => void PreviousChapterCommand(ctx), [ctx]);

  const hasSelection = selected !== null;

  return (
    <div
      className={cn("flex flex-col gap-3 rounded-lg border border-border bg-surface p-4", className)}
      data-testid="quick-navigator"
    >
      <div className="flex items-center gap-2">
        <BookOpen className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-semibold text-text">Navegação Rápida</h3>
      </div>

      {/* Linha 1: Livro (◀ ▶) — navegação entre livros via NextChapter/PreviousChapter
          quando no último/primeiro capítulo, ou via seletores. Por simplicidade,
          a navegação de livro usa os mesmos comandos de capítulo que atravessam
          livros automaticamente. */}
      <NavigatorRow
        icon={<BookOpen className="h-3.5 w-3.5 text-text-muted" />}
        label="Livro"
        value={bookName || "—"}
        onPrev={onPrevChapter}
        onNext={onNextChapter}
        disabled={!hasSelection}
        prevTitle="Capítulo anterior (atravessa livros)"
        nextTitle="Próximo capítulo (atravessa livros)"
        testIdPrefix="operator-book"
      />

      {/* Linha 2: Capítulo */}
      <NavigatorRow
        icon={<FileText className="h-3.5 w-3.5 text-text-muted" />}
        label="Capítulo"
        value={chapter !== null ? String(chapter) : "—"}
        onPrev={onPrevChapter}
        onNext={onNextChapter}
        disabled={!hasSelection}
        testIdPrefix="operator-chapter"
      />

      {/* Linha 3: Versículo */}
      <NavigatorRow
        icon={<Hash className="h-3.5 w-3.5 text-text-muted" />}
        label="Versículo"
        value={verse !== null ? String(verse) : "—"}
        onPrev={onPrevVerse}
        onNext={onNextVerse}
        disabled={!hasSelection}
        testIdPrefix="operator-verse"
      />

      {!hasSelection && (
        <p className="text-xs text-text-muted italic text-center py-1">
          Use os atalhos de teclado ou comece a navegar para selecionar.
        </p>
      )}
    </div>
  );
}

// ============================================================
// NavigatorRow — linha individual com ◀ value ▶
// ============================================================

interface NavigatorRowProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  onPrev: () => void;
  onNext: () => void;
  disabled: boolean;
  prevTitle?: string;
  nextTitle?: string;
  testIdPrefix: string;
}

function NavigatorRow({
  icon,
  label,
  value,
  onPrev,
  onNext,
  disabled,
  prevTitle,
  nextTitle,
  testIdPrefix,
}: NavigatorRowProps) {
  return (
    <div className="flex items-center gap-2" data-testid={`${testIdPrefix}-row`}>
      <span className="flex items-center gap-1 text-[10px] font-medium text-text-muted uppercase tracking-wide w-16 shrink-0">
        {icon}
        {label}
      </span>
      <button
        onClick={onPrev}
        disabled={disabled}
        title={prevTitle ?? `${label} anterior`}
        aria-label={`${label} anterior`}
        className={cn(
          "flex items-center justify-center rounded-md border border-border bg-surface-elevated h-9 w-9 transition-colors",
          disabled
            ? "text-text-muted opacity-50 cursor-not-allowed"
            : "text-text hover:bg-surface-hover hover:border-primary focus-visible:ring-2 focus-visible:ring-primary",
        )}
        data-testid={`${testIdPrefix}-prev`}
      >
        <ChevronLeft className="h-4 w-4" />
      </button>
      <span
        className="flex-1 text-center text-sm font-semibold text-text truncate px-2"
        data-testid={`${testIdPrefix}-value`}
      >
        {value}
      </span>
      <button
        onClick={onNext}
        disabled={disabled}
        title={nextTitle ?? `Próximo ${label.toLowerCase()}`}
        aria-label={`Próximo ${label.toLowerCase()}`}
        className={cn(
          "flex items-center justify-center rounded-md border border-border bg-surface-elevated h-9 w-9 transition-colors",
          disabled
            ? "text-text-muted opacity-50 cursor-not-allowed"
            : "text-text hover:bg-surface-hover hover:border-primary focus-visible:ring-2 focus-visible:ring-primary",
        )}
        data-testid={`${testIdPrefix}-next`}
      >
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  );
}
