/**
 * ReadingFollowPanel — Sprint 23.2.
 *
 * Painel do modo de acompanhamento de leitura.
 * Permite ao operador:
 * - Ativar/desativar o modo manualmente.
 * - Avançar versículos manualmente.
 * - Ver o progresso (versículo atual / total).
 * - Mudar a versão bíblica ativa.
 * - Habilitar/desabilitar mudança automática de versão por voz.
 */

import {
  BookOpen,
  Play,
  Square,
  ChevronRight,
  Loader2,
  AlertCircle,
  Mic,
  MicOff,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useReadingFollow, useOperator } from "@/hooks";
import { cn } from "@/utils";

interface ReadingFollowPanelProps {
  className?: string;
}

export function ReadingFollowPanel({ className }: ReadingFollowPanelProps) {
  const follow = useReadingFollow();
  const op = useOperator();

  const [selBookId, setSelBookId] = useState<number | null>(null);
  const [selChapter, setSelChapter] = useState<number | null>(null);
  const [selVerseStart, setSelVerseStart] = useState<number | null>(null);
  const [selVerseEnd, setSelVerseEnd] = useState<number | null>(null);

  useEffect(() => {
    follow.refreshState();
    follow.loadVersions();
    if (op.books.length === 0) {
      op.loadBooks();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onBookChange = (bookId: number) => {
    setSelBookId(bookId);
    setSelChapter(null);
    setSelVerseStart(null);
    setSelVerseEnd(null);
    op.loadChapters(bookId);
  };

  const onChapterChange = (chapter: number) => {
    setSelChapter(chapter);
    setSelVerseStart(null);
    setSelVerseEnd(null);
    if (selBookId !== null) {
      op.loadVerses(selBookId, chapter);
    }
  };

  const canStart =
    selBookId !== null &&
    selChapter !== null &&
    selVerseStart !== null &&
    selVerseEnd !== null &&
    selVerseEnd > selVerseStart &&
    !follow.state?.active;

  const handleStart = () => {
    if (!canStart || selBookId === null || selChapter === null) return;
    const book = op.books.find((b) => b.id === selBookId);
    if (!book) return;
    follow.start({
      book_id: selBookId,
      book_name: book.canonical,
      chapter: selChapter,
      verse_start: selVerseStart!,
      verse_end: selVerseEnd!,
    });
  };

  const handleStop = () => {
    follow.stop();
  };

  const handleAdvance = () => {
    follow.advance();
  };

  const handleVersionChange = (version: string) => {
    follow.setVersion(version);
  };

  const handleAutoVersionToggle = () => {
    follow.setAutoVersion(!follow.autoVersionEnabled);
  };

  const progress =
    follow.state && follow.state.total_verses > 0
      ? Math.round((follow.state.verses_read / follow.state.total_verses) * 100)
      : 0;

  return (
    <div
      className={cn("flex flex-col gap-3 rounded-lg border border-border-subtle bg-bg-surface p-4", className)}
      data-testid="reading-follow-panel"
    >
      {/* Header */}
      <div className="flex items-center gap-2">
        <BookOpen className="h-4 w-4 text-text-secondary" />
        <h3 className="text-sm font-semibold text-text-primary">
          Acompanhamento de Leitura
        </h3>
        {follow.state?.active && (
          <span className="ml-auto flex items-center gap-1 rounded-full bg-status-success/10 px-2 py-0.5 text-[10px] font-medium text-status-success">
            <span className="h-1.5 w-1.5 rounded-full bg-status-success animate-pulse" />
            Ativo
          </span>
        )}
      </div>

      {/* Error */}
      {follow.error && (
        <div className="flex items-start gap-2 rounded-md border border-status-error/30 bg-status-error/10 px-3 py-2">
          <AlertCircle className="h-3.5 w-3.5 shrink-0 text-status-error mt-0.5" />
          <p className="text-xs text-status-error">{follow.error}</p>
        </div>
      )}

      {/* Active state display */}
      {follow.state?.active ? (
        <div className="flex flex-col gap-2 rounded-md border border-border-default bg-bg-base p-3">
          <div className="flex items-baseline justify-between">
            <span className="text-sm font-medium text-text-primary">
              {follow.state.book} {follow.state.chapter}:{follow.state.current_verse}
            </span>
            <span className="text-xs text-text-subtle">
              {follow.state.verses_read} / {follow.state.total_verses} versículos
            </span>
          </div>
          {/* Progress bar */}
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-bg-base">
            <div
              className="h-full rounded-full bg-accent-primary transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
          {/* Verse range */}
          <div className="text-[10px] text-text-subtle">
            Intervalo: {follow.state.verse_start} ao {follow.state.verse_end}
          </div>
          {/* Controls */}
          <div className="flex gap-2 mt-1">
            <button
              onClick={handleAdvance}
              disabled={follow.loading}
              className="flex items-center gap-1 rounded-md border border-border-default bg-bg-surface px-3 py-1.5 text-xs font-medium text-text-primary hover:bg-bg-hover transition-colors disabled:opacity-50"
            >
              <ChevronRight className="h-3.5 w-3.5" />
              Avançar
            </button>
            <button
              onClick={handleStop}
              disabled={follow.loading}
              className="flex items-center gap-1 rounded-md border border-status-error/30 bg-status-error/10 px-3 py-1.5 text-xs font-medium text-status-error hover:bg-status-error/20 transition-colors disabled:opacity-50"
            >
              <Square className="h-3.5 w-3.5" />
              Parar
            </button>
            {follow.loading && (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-text-subtle self-center" />
            )}
          </div>
        </div>
      ) : (
        /* Inactive: manual activation form */
        <div className="flex flex-col gap-2">
          {/* Book selector */}
          <select
            value={selBookId ?? ""}
            onChange={(e) => onBookChange(Number(e.target.value))}
            className="rounded-md border border-border-default bg-bg-base px-3 py-1.5 text-xs text-text-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
          >
            <option value="">Selecione o livro...</option>
            {op.books.map((b) => (
              <option key={b.id} value={b.id}>
                {b.canonical}
              </option>
            ))}
          </select>

          {/* Chapter selector */}
          <select
            value={selChapter ?? ""}
            onChange={(e) => onChapterChange(Number(e.target.value))}
            disabled={op.chapters.length === 0}
            className="rounded-md border border-border-default bg-bg-base px-3 py-1.5 text-xs text-text-primary focus:outline-none focus:ring-1 focus:ring-accent-primary disabled:opacity-50"
          >
            <option value="">Capítulo...</option>
            {op.chapters.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>

          {/* Verse range */}
          <div className="flex items-center gap-2">
            <select
              value={selVerseStart ?? ""}
              onChange={(e) => setSelVerseStart(Number(e.target.value))}
              disabled={op.verses.length === 0}
              className="flex-1 rounded-md border border-border-default bg-bg-base px-3 py-1.5 text-xs text-text-primary focus:outline-none focus:ring-1 focus:ring-accent-primary disabled:opacity-50"
            >
              <option value="">Versículo inicial...</option>
              {op.verses.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
            <span className="text-xs text-text-subtle">ao</span>
            <select
              value={selVerseEnd ?? ""}
              onChange={(e) => setSelVerseEnd(Number(e.target.value))}
              disabled={op.verses.length === 0 || selVerseStart === null}
              className="flex-1 rounded-md border border-border-default bg-bg-base px-3 py-1.5 text-xs text-text-primary focus:outline-none focus:ring-1 focus:ring-accent-primary disabled:opacity-50"
            >
              <option value="">Versículo final...</option>
              {op.verses
                .filter((v) => selVerseStart === null || v > selVerseStart)
                .map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
            </select>
          </div>

          {/* Start button */}
          <button
            onClick={handleStart}
            disabled={!canStart || follow.loading}
            className="flex items-center justify-center gap-1.5 rounded-md bg-accent-primary px-3 py-2 text-xs font-medium text-white hover:bg-accent-primary-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {follow.loading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
            Iniciar Acompanhamento
          </button>
        </div>
      )}

      {/* Version management */}
      <div className="border-t border-border-subtle pt-3">
        <div className="flex items-center justify-between gap-2">
          <label className="text-xs font-medium text-text-secondary">
            Versão:
          </label>
          <select
            value={follow.currentVersion}
            onChange={(e) => handleVersionChange(e.target.value)}
            disabled={follow.versions.length === 0}
            className="rounded-md border border-border-default bg-bg-base px-2 py-1 text-xs text-text-primary focus:outline-none focus:ring-1 focus:ring-accent-primary disabled:opacity-50"
          >
            {follow.versions.length > 0 ? (
              follow.versions.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))
            ) : (
              <option value={follow.currentVersion}>{follow.currentVersion}</option>
            )}
          </select>
        </div>

        {/* Auto version toggle */}
        <button
          onClick={handleAutoVersionToggle}
          className={cn(
            "mt-2 flex w-full items-center justify-between rounded-md border px-3 py-1.5 text-xs transition-colors",
            follow.autoVersionEnabled
              ? "border-status-success/30 bg-status-success/10 text-status-success"
              : "border-border-default bg-bg-base text-text-subtle",
          )}
        >
          <span className="flex items-center gap-1.5">
            {follow.autoVersionEnabled ? (
              <Mic className="h-3.5 w-3.5" />
            ) : (
              <MicOff className="h-3.5 w-3.5" />
            )}
            Mudança automática por voz
          </span>
          <span className="font-medium">
            {follow.autoVersionEnabled ? "ON" : "OFF"}
          </span>
        </button>
      </div>
    </div>
  );
}
