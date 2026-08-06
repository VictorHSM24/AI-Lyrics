/**
 * OperatorPanel — Painel do Operador (Sprint 24).
 *
 * Permite navegação bíblica estruturada (livro → capítulo → versículo)
 * e apresentação manual de versículos no Holyrics, sem precisar abrir
 * o Holyrics diretamente.
 *
 * Layout:
 *   1. Navegação (seletores de livro/capítulo/versículo)
 *   2. Card do versículo atual (texto + referência)
 *   3. Controles de apresentação (botão Apresentar + quick)
 *   4. Histórico de apresentações (tempo real via VersePresentationStore)
 *
 * Atualização do histórico é em tempo real via EventStream →
 * VersePresentationStore → useVersePresentation (hook).
 */

import {
  BookOpen,
  Send,
  ChevronRight,
  History,
  CheckCircle2,
  XCircle,
  Loader2,
  Zap,
  AlertCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useOperator } from "@/hooks";
import { useVersePresentation } from "@/hooks";
import { cn } from "@/utils";

interface OperatorPanelProps {
  className?: string;
}

export function OperatorPanel({ className }: OperatorPanelProps) {
  const op = useOperator();
  const { current: liveCurrent } = useVersePresentation();

  // Seleção local de navegação.
  const [selectedBookId, setSelectedBookId] = useState<number | null>(null);
  const [selectedChapter, setSelectedChapter] = useState<number | null>(null);
  const [selectedVerse, setSelectedVerse] = useState<number | null>(null);
  const [quick, setQuick] = useState(false);

  // Carregar livros na montagem.
  useEffect(() => {
    op.loadBooks();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Quando livro muda, carregar capítulos.
  const onBookChange = useCallback(
    (bookId: number) => {
      setSelectedBookId(bookId);
      setSelectedChapter(null);
      setSelectedVerse(null);
      op.loadChapters(bookId);
    },
    [op],
  );

  // Quando capítulo muda, carregar versículos.
  const onChapterChange = useCallback(
    (chapter: number) => {
      setSelectedChapter(chapter);
      setSelectedVerse(null);
      if (selectedBookId !== null) {
        op.loadVerses(selectedBookId, chapter);
      }
    },
    [op, selectedBookId],
  );

  // Quando versículo muda, carregar texto.
  const onVerseChange = useCallback(
    (verse: number) => {
      setSelectedVerse(verse);
      if (selectedBookId !== null && selectedChapter !== null) {
        op.loadVerse(selectedBookId, selectedChapter, verse);
      }
    },
    [op, selectedBookId, selectedChapter],
  );

  // Apresentar versículo.
  const onPresent = useCallback(async () => {
    if (selectedBookId === null || selectedChapter === null || selectedVerse === null) return;
    try {
      await op.presentVerse({
        book_id: selectedBookId,
        chapter: selectedChapter,
        verse: selectedVerse,
        quick,
      });
    } catch {
      // erro já tratado no hook (op.error)
    }
  }, [op, selectedBookId, selectedChapter, selectedVerse, quick]);

  const canPresent = selectedBookId !== null && selectedChapter !== null && selectedVerse !== null && !op.presenting;

  return (
    <div
      className={cn("flex flex-col gap-4", className)}
      data-testid="operator-panel"
    >
      {/* Erro global */}
      {op.error && (
        <div
          className="flex items-start gap-2 rounded-md border border-status-error/30 bg-status-error/10 px-3 py-2"
          data-testid="operator-error"
        >
          <AlertCircle className="h-4 w-4 shrink-0 text-status-error mt-0.5" />
          <p className="text-xs text-status-error">{op.error}</p>
        </div>
      )}

      {/* Grid: navegação + card atual | controles + histórico */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Coluna esquerda: navegação + card do versículo */}
        <div className="flex flex-col gap-4">
          <VerseNavigator
            books={op.books}
            booksLoading={op.booksLoading}
            chapters={op.chapters}
            verses={op.verses}
            selectedBookId={selectedBookId}
            selectedChapter={selectedChapter}
            selectedVerse={selectedVerse}
            onBookChange={onBookChange}
            onChapterChange={onChapterChange}
            onVerseChange={onVerseChange}
          />
          <CurrentVerseCard verse={op.currentVerse} />
        </div>

        {/* Coluna direita: controles + histórico */}
        <div className="flex flex-col gap-4">
          <PresentationControls
            canPresent={canPresent}
            presenting={op.presenting}
            quick={quick}
            onQuickChange={setQuick}
            onPresent={onPresent}
            lastResult={op.lastPresentResult}
          />
          <HistoryList entries={op.history} liveCurrent={liveCurrent} />
        </div>
      </div>
    </div>
  );
}

// ============================================================
// VerseNavigator — seletores de livro/capítulo/versículo.
// ============================================================

interface VerseNavigatorProps {
  books: { id: number; canonical: string; aliases: string[] }[];
  booksLoading: boolean;
  chapters: number[];
  verses: number[];
  selectedBookId: number | null;
  selectedChapter: number | null;
  selectedVerse: number | null;
  onBookChange: (bookId: number) => void;
  onChapterChange: (chapter: number) => void;
  onVerseChange: (verse: number) => void;
}

function VerseNavigator({
  books,
  booksLoading,
  chapters,
  verses,
  selectedBookId,
  selectedChapter,
  selectedVerse,
  onBookChange,
  onChapterChange,
  onVerseChange,
}: VerseNavigatorProps) {
  return (
    <div
      className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4"
      data-testid="verse-navigator"
    >
      <div className="flex items-center gap-2">
        <BookOpen className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-semibold text-text">Navegação Bíblica</h3>
      </div>

      {/* Seletor de livro */}
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-medium text-text-muted uppercase tracking-wide">
          Livro
        </label>
        <select
          value={selectedBookId ?? ""}
          onChange={(e) => onBookChange(Number(e.target.value))}
          disabled={booksLoading}
          className="rounded-md border border-border bg-surface-elevated px-3 py-2 text-sm text-text focus:border-primary focus:outline-none"
          data-testid="operator-book-select"
        >
          <option value="" disabled>
            {booksLoading ? "Carregando..." : "Selecione um livro"}
          </option>
          {books.map((b) => (
            <option key={b.id} value={b.id}>
              {b.id}. {b.canonical}
            </option>
          ))}
        </select>
      </div>

      {/* Seletor de capítulo */}
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-medium text-text-muted uppercase tracking-wide">
          Capítulo
        </label>
        <select
          value={selectedChapter ?? ""}
          onChange={(e) => onChapterChange(Number(e.target.value))}
          disabled={chapters.length === 0}
          className="rounded-md border border-border bg-surface-elevated px-3 py-2 text-sm text-text focus:border-primary focus:outline-none disabled:opacity-50"
          data-testid="operator-chapter-select"
        >
          <option value="" disabled>
            {chapters.length === 0 ? "Selecione um livro primeiro" : "Selecione"}
          </option>
          {chapters.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      {/* Seletor de versículo */}
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-medium text-text-muted uppercase tracking-wide">
          Versículo
        </label>
        <select
          value={selectedVerse ?? ""}
          onChange={(e) => onVerseChange(Number(e.target.value))}
          disabled={verses.length === 0}
          className="rounded-md border border-border bg-surface-elevated px-3 py-2 text-sm text-text focus:border-primary focus:outline-none disabled:opacity-50"
          data-testid="operator-verse-select"
        >
          <option value="" disabled>
            {verses.length === 0 ? "Selecione um capítulo primeiro" : "Selecione"}
          </option>
          {verses.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

// ============================================================
// CurrentVerseCard — card com texto do versículo selecionado.
// ============================================================

interface CurrentVerseCardProps {
  verse: { book: string; chapter: number; verse: number; reference: string; text: string; version: string } | null;
}

function CurrentVerseCard({ verse }: CurrentVerseCardProps) {
  return (
    <div
      className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-4"
      data-testid="current-verse-card"
    >
      <div className="flex items-center gap-2">
        <BookOpen className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-semibold text-text">Versículo Selecionado</h3>
      </div>
      {verse ? (
        <div className="flex flex-col gap-2">
          <span className="text-lg font-bold text-text">{verse.reference}</span>
          <p className="text-sm text-text italic border-l-2 border-primary/30 pl-3">
            "{verse.text}"
          </p>
          <span className="text-[10px] text-text-subtle">{verse.version}</span>
        </div>
      ) : (
        <p className="text-xs text-text-muted italic">
          Nenhum versículo selecionado. Use os seletores acima.
        </p>
      )}
    </div>
  );
}

// ============================================================
// PresentationControls — botão Apresentar + quick toggle.
// ============================================================

interface PresentationControlsProps {
  canPresent: boolean;
  presenting: boolean;
  quick: boolean;
  onQuickChange: (v: boolean) => void;
  onPresent: () => void;
  lastResult: { ok: boolean; message: string; reference: string; holyrics_status: string; latency_ms: number } | null;
}

function PresentationControls({
  canPresent,
  presenting,
  quick,
  onQuickChange,
  onPresent,
  lastResult,
}: PresentationControlsProps) {
  return (
    <div
      className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4"
      data-testid="presentation-controls"
    >
      <div className="flex items-center gap-2">
        <Send className="h-4 w-4 text-emerald-400" />
        <h3 className="text-sm font-semibold text-text">Apresentação</h3>
      </div>

      {/* Quick toggle */}
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={quick}
          onChange={(e) => onQuickChange(e.target.checked)}
          className="rounded border-border"
          data-testid="operator-quick-toggle"
        />
        <span className="flex items-center gap-1 text-xs text-text">
          <Zap className="h-3 w-3 text-status-warning" />
          Quick Presentation (popup sem encerrar apresentação atual)
        </span>
      </label>

      {/* Botão Apresentar */}
      <button
        onClick={onPresent}
        disabled={!canPresent}
        className={cn(
          "flex items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm font-medium transition-colors",
          canPresent
            ? "bg-emerald-600 text-white hover:bg-emerald-700"
            : "bg-surface-hover text-text-muted cursor-not-allowed",
        )}
        data-testid="operator-present-btn"
      >
        {presenting ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Apresentando...
          </>
        ) : (
          <>
            <Send className="h-4 w-4" />
            Apresentar no Holyrics
          </>
        )}
      </button>

      {/* Último resultado */}
      {lastResult && (
        <div
          className={cn(
            "flex items-start gap-2 rounded-md border px-2.5 py-1.5",
            lastResult.ok
              ? "border-status-success/30 bg-status-success/10"
              : "border-status-error/30 bg-status-error/10",
          )}
          data-testid="operator-last-result"
        >
          {lastResult.ok ? (
            <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-status-success mt-0.5" />
          ) : (
            <XCircle className="h-3.5 w-3.5 shrink-0 text-status-error mt-0.5" />
          )}
          <div className="flex flex-col gap-0.5">
            <span className="text-xs font-medium text-text">
              {lastResult.reference} · {lastResult.latency_ms}ms
            </span>
            <span className="text-[10px] text-text-muted">{lastResult.message}</span>
          </div>
        </div>
      )}
    </div>
  );
}

// ============================================================
// HistoryList — histórico de apresentações (tempo real).
// ============================================================

interface HistoryListProps {
  entries: { id: string; reference: string; status: string; totalLatencyMs: number; timestamp: number; book: string; chapter: number; verse: number }[];
  liveCurrent: { id: string; reference: string; status: string; totalLatencyMs: number; timestamp: number } | null;
}

function HistoryList({ entries, liveCurrent }: HistoryListProps) {
  const sorted = useMemo(
    () => [...entries].sort((a, b) => b.timestamp - a.timestamp),
    [entries],
  );

  return (
    <div
      className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-4"
      data-testid="operator-history"
    >
      <div className="flex items-center gap-2">
        <History className="h-4 w-4 text-text-muted" />
        <h3 className="text-sm font-semibold text-text">Histórico</h3>
        {liveCurrent && (
          <span className="ml-auto text-[10px] text-status-success flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-status-success animate-pulse" />
            ao vivo
          </span>
        )}
      </div>

      {sorted.length === 0 ? (
        <p className="text-xs text-text-muted italic py-4 text-center">
          Nenhuma apresentação ainda.
        </p>
      ) : (
        <div className="flex flex-col gap-1.5 max-h-72 overflow-y-auto">
          {sorted.map((entry) => (
            <HistoryRow key={entry.id} entry={entry} />
          ))}
        </div>
      )}
    </div>
  );
}

function HistoryRow({ entry }: { entry: { id: string; reference: string; status: string; totalLatencyMs: number; timestamp: number } }) {
  const Icon = entry.status === "presented" ? CheckCircle2 : entry.status === "failed" ? XCircle : Loader2;
  const colorClass =
    entry.status === "presented" ? "text-status-success" :
    entry.status === "failed" ? "text-status-error" :
    "text-status-warning";

  return (
    <div
      className="flex items-center gap-2 rounded-md border border-border-subtle bg-surface-elevated px-2.5 py-1.5"
      data-testid="operator-history-row"
    >
      <Icon className={cn("h-3 w-3 shrink-0", colorClass, entry.status === "presenting" && "animate-spin")} />
      <span className="text-xs font-medium text-text flex-1">{entry.reference}</span>
      <ChevronRight className="h-3 w-3 text-text-subtle" />
      <span className="text-[10px] text-text-subtle">
        {entry.totalLatencyMs > 0 ? `${entry.totalLatencyMs}ms` : "—"}
      </span>
    </div>
  );
}
