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

import { ChevronLeft, ChevronRight, BookOpen, FileText, Hash, Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useWorkspaceSnapshot, useOperatorNavigation } from "@/hooks";
import type { OperatorVerseDTO } from "@/types";
import { cn } from "@/utils";
import {
  NextVerseCommand,
  PreviousVerseCommand,
  NextChapterCommand,
  PreviousChapterCommand,
  PresentVerseCommand,
  type CommandResult,
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

  // Preview do versículo selecionado (carregado via cache LRU do ctx).
  const [preview, setPreview] = useState<OperatorVerseDTO | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Carregar books na montagem (para resolver bookId → nome).
  useEffect(() => {
    if (nav.books.length === 0) {
      void nav.loadBooks();
    }
  }, [nav]);

  // Quando selected muda, atualizar display e carregar preview.
  useEffect(() => {
    if (!selected) {
      setBookName("");
      setChapter(null);
      setVerse(null);
      setPreview(null);
      return;
    }
    const book = nav.books.find((b) => b.id === selected.bookId);
    setBookName(book?.canonical ?? `Livro ${selected.bookId}`);
    setChapter(selected.chapter);
    setVerse(selected.verse);

    // Carregar texto do versículo via cache LRU.
    let cancelled = false;
    setPreviewLoading(true);
    void ctx
      .getVerse(selected.bookId, selected.chapter, selected.verse)
      .then((v) => {
        if (!cancelled) setPreview(v);
      })
      .catch(() => {
        if (!cancelled) setPreview(null);
      })
      .finally(() => {
        if (!cancelled) setPreviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected, nav.books, ctx]);

  // Navegar e apresentar automaticamente: após o comando de navegação
  // atualizar `selected` no store, dispara PresentVerseCommand para o novo
  // versículo. ctx.selected é um getter que lê do store sincronamente,
  // então após selectAndLoad o valor já é o novo ref.
  const navigateAndPresent = useCallback(
    async (navCmd: () => Promise<CommandResult>) => {
      const result = await navCmd();
      if (result.ok && result.ref) {
        await PresentVerseCommand(ctx);
      }
    },
    [ctx],
  );

  const onNextVerse = useCallback(
    () => void navigateAndPresent(() => NextVerseCommand(ctx)),
    [ctx, navigateAndPresent],
  );
  const onPrevVerse = useCallback(
    () => void navigateAndPresent(() => PreviousVerseCommand(ctx)),
    [ctx, navigateAndPresent],
  );
  const onNextChapter = useCallback(
    () => void navigateAndPresent(() => NextChapterCommand(ctx)),
    [ctx, navigateAndPresent],
  );
  const onPrevChapter = useCallback(
    () => void navigateAndPresent(() => PreviousChapterCommand(ctx)),
    [ctx, navigateAndPresent],
  );

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

      {/* Preview do versículo selecionado */}
      {hasSelection && (
        <div
          className="flex flex-col gap-1.5 rounded-md border border-primary/30 bg-primary/5 p-3"
          data-testid="selected-verse-preview"
        >
          {previewLoading ? (
            <div className="flex items-center gap-2 py-2 text-text-muted">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              <span className="text-xs">Carregando...</span>
            </div>
          ) : preview ? (
            <>
              <span className="text-base font-bold text-text">
                {preview.reference}
              </span>
              <p className="text-sm text-text italic border-l-2 border-primary/30 pl-3 leading-relaxed">
                "{preview.text}"
              </p>
              <span className="text-[10px] text-text-subtle">{preview.version}</span>
            </>
          ) : (
            <p className="text-xs text-text-muted italic py-1">
              Versículo não disponível.
            </p>
          )}
        </div>
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
