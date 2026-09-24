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

import { ChevronLeft, ChevronRight, BookOpen, FileText, Hash, Languages, Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useServices, useWorkspaceSnapshot, useOperatorNavigation } from "@/hooks";
import type { OperatorVerseDTO } from "@/types";
import { cn, formatVersionKey } from "@/utils";
import {
  NextVerseCommand,
  PreviousVerseCommand,
  NextChapterCommand,
  PreviousChapterCommand,
  PresentVerseCommand,
  type CommandResult,
  type WorkspaceContext,
} from "./WorkspaceCommands";

// Mapa key Holyrics (pt_*) → versão presente na base FTS5 local.
// Versões fora deste mapa não têm texto local para preview — o
// Holyrics resolve o texto na apresentação.
const LOCAL_VERSION_MAP: Record<string, string> = {
  pt_acf: "ACF",
  pt_ra: "ARA",
  pt_arc: "ARC",
  pt_a21: "AS21",
  pt_jfaa: "JFAA",
  pt_naa: "NAA",
  pt_nbv: "NBV",
  pt_ntlh: "NTLH",
  pt_nvi: "NVI",
  pt_nvt: "NVT",
};
const LOCAL_VERSION_SET = new Set(Object.values(LOCAL_VERSION_MAP));

function toLocalVersion(version: string): string | undefined {
  if (!version) return undefined;
  if (LOCAL_VERSION_MAP[version]) return LOCAL_VERSION_MAP[version];
  const upper = version.toUpperCase();
  if (LOCAL_VERSION_SET.has(upper)) return upper;
  return undefined;
}

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

  // Versão apresentada — lista vem do Holyrics (keys pt_*), a ativa
  // vem do backend (/operator/version).
  const services = useServices();
  const [versions, setVersions] = useState<string[]>([]);
  const [version, setVersion] = useState<string>("");
  const [versionBusy, setVersionBusy] = useState(false);

  // Carregar books na montagem (para resolver bookId → nome).
  useEffect(() => {
    if (nav.books.length === 0) {
      void nav.loadBooks();
    }
  }, [nav]);

  // Carregar versões do Holyrics + versão ativa na montagem.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const vs = await services.operator.getVersions();
        if (cancelled) return;
        setVersions(vs.versions);
        try {
          const cur = await services.operator.getVersion();
          if (cancelled) return;
          // Backend retorna nome local ("ACF") — casar com a key pt_*.
          const match = vs.versions.find(
            (v) => v === cur.version || formatVersionKey(v) === cur.version.toUpperCase(),
          );
          setVersion(match ?? cur.version ?? vs.versions[0] ?? "");
        } catch {
          if (!cancelled && vs.versions.length > 0) setVersion(vs.versions[0]);
        }
      } catch {
        // Holyrics offline — seletor fica desabilitado.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [services]);

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

    // Carregar texto do versículo via cache LRU (na versão local
    // equivalente, se existir — versões fora da base local não têm
    // texto para preview, mas o Holyrics resolve na apresentação).
    if (version !== "" && toLocalVersion(version) === undefined) {
      setPreview(null);
      setPreviewLoading(false);
      return;
    }
    let cancelled = false;
    setPreviewLoading(true);
    void ctx
      .getVerse(selected.bookId, selected.chapter, selected.verse, toLocalVersion(version))
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
  }, [selected, nav.books, ctx, version]);

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

  // Trocar a versão: persiste no backend e re-apresenta o versículo
  // atualmente apresentado na nova tradução (se houver um).
  const onVersionChange = useCallback(
    (v: string) => {
      setVersion(v);
      setVersionBusy(true);
      void (async () => {
        try {
          await services.operator.setVersion(v);
        } catch {
          // Backend indisponível — ainda tenta reapresentar.
        }
        const ref = ctx.presented;
        if (ref) {
          try {
            await ctx.presentVerse({
              book_id: ref.bookId,
              chapter: ref.chapter,
              verse: ref.verse,
              version: v,
              quick: ctx.quickPresentation,
            });
          } catch {
            // Falha de apresentação aparece no histórico/painel.
          }
        }
        setVersionBusy(false);
      })();
    },
    [ctx, services],
  );

  const hasSelection = selected !== null;
  const localVersionMissing = version !== "" && toLocalVersion(version) === undefined;

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

      {/* Linha 4: Versão — troca a tradução do versículo apresentado. */}
      <div className="flex items-center gap-2" data-testid="operator-version-row">
        <span className="flex items-center gap-1 text-[10px] font-medium text-text-muted uppercase tracking-wide w-16 shrink-0">
          <Languages className="h-3.5 w-3.5 text-text-muted" />
          Versão
        </span>
        <select
          value={version}
          onChange={(e) => onVersionChange(e.target.value)}
          disabled={versions.length === 0 || versionBusy}
          title="Tradução apresentada no Holyrics — trocar re-apresenta o versículo atual"
          className="flex-1 rounded-md border border-border bg-surface-elevated px-2.5 py-2 text-sm font-semibold text-text focus:border-primary focus:outline-none disabled:opacity-50"
          data-testid="operator-version-select"
        >
          {versions.length === 0 ? (
            <option value="">{version ? formatVersionKey(version) : "—"}</option>
          ) : (
            versions.map((v) => (
              <option key={v} value={v}>
                {formatVersionKey(v)}
              </option>
            ))
          )}
          {version !== "" && !versions.includes(version) && (
            <option value={version}>{formatVersionKey(version)}</option>
          )}
        </select>
        {versionBusy && <Loader2 className="h-3.5 w-3.5 animate-spin text-text-muted" />}
      </div>

      {!hasSelection && (
        <div className="flex flex-col items-center gap-2 py-3 rounded-md border border-dashed border-border-subtle bg-surface-hover/30">
          <BookOpen className="h-6 w-6 text-text-subtle" />
          <p className="text-xs text-text-muted text-center max-w-[200px]">
            Nenhum versículo selecionado.
          </p>
          <p className="text-[10px] text-text-subtle text-center max-w-[220px]">
            Use <kbd className="px-1 py-0.5 rounded border border-border bg-surface text-[9px]">Ctrl+F</kbd> ou
            digite uma referência acima.
          </p>
        </div>
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
              <span className="text-[10px] text-text-subtle">
                {formatVersionKey(preview.version)}
              </span>
            </>
          ) : (
            <p className="text-xs text-text-muted italic py-1">
              {localVersionMissing
                ? "Texto indisponível nesta versão — o Holyrics resolve na apresentação."
                : "Versículo não disponível."}
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
