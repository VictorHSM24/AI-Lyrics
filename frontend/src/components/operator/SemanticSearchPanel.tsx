/**
 * SemanticSearchPanel (Sprint 28 Fase 9) — Busca semântica de versículos.
 *
 * Painel do operador para buscar versículos por texto livre (palavras-chave,
 * paráfrases, temas). Combina FTS5 (BibleRetriever) + Ollama (re-ranqueamento).
 *
 * Fluxo:
 *   Operador digita texto → Enter → busca → lista de candidatos →
 *   ↑↓ navega → Enter apresenta no Holyrics (ou clique no botão ▶).
 *
 * Layout:
 *   ┌─────────────────────────────────────────────┐
 *   │ [input: "verso sobre amor de Deus"] [Buscar] │
 *   ├─────────────────────────────────────────────┤
 *   │ ● João 3:16                    [ACF ▼] [▶]  │
 *   │   "Porque Deus amou o mundo..."             │
 *   │   score: 0.95                               │
 *   ├─────────────────────────────────────────────┤
 *   │ ○ Romanos 5:8                 [ACF ▼] [▶]  │
 *   │   "Mas Deus prova o seu amor..."            │
 *   └─────────────────────────────────────────────┘
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Loader2,
  X,
  CornerDownLeft,
  Play,
  AlertTriangle,
  Zap,
  ZapOff,
  Sparkles,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { useSemanticSearch, useOperator, useStores } from "@/hooks";
import { cn, formatVersionKey } from "@/utils";
import type { SemanticSearchResultDTO, OperatorPresentResultDTO } from "@/types";

interface SemanticSearchPanelProps {
  className?: string;
}

export function SemanticSearchPanel({ className }: SemanticSearchPanelProps) {
  const sem = useSemanticSearch();
  const op = useOperator();
  const workspaceStore = useStores().workspace;
  const inputRef = useRef<HTMLInputElement>(null);
  const [presentingId, setPresentingId] = useState<string | null>(null);
  const [presentError, setPresentError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(true);
  // Mapa de versão selecionada por referência (ex.: "João 3:16" → "ACF").
  // Persiste entre re-renders e permite que Enter apresente com a versão
  // escolhida no dropdown do candidato selecionado.
  const [versionOverrides, setVersionOverrides] = useState<Record<string, string>>({});

  // Expandir automaticamente quando há resultados ou query.
  useEffect(() => {
    if (sem.results.length > 0 || sem.query.trim().length > 0) {
      setCollapsed(false);
    }
  }, [sem.results.length, sem.query]);

  // Resetar overrides de versão quando uma nova busca é realizada.
  useEffect(() => {
    setVersionOverrides({});
  }, [sem.lastSearchedQuery]);

  // Apresentar versículo candidato no Holyrics.
  const presentCandidate = useCallback(
    async (result: SemanticSearchResultDTO, version?: string) => {
      setPresentingId(result.reference);
      setPresentError(null);
      // Sincroniza o workspace store para que PresentationCards não tente
      // carregar book_id=0 (que causava 404 no /operator/verse).
      workspaceStore.setSelected({
        bookId: result.book_id,
        chapter: result.chapter,
        verse: result.verse,
      });
      try {
        const req = {
          book_id: result.book_id,
          chapter: result.chapter,
          verse: result.verse,
          ...(version ? { version } : {}),
        };
        const res: OperatorPresentResultDTO = await op.presentVerse(req);
        if (!res.ok) {
          setPresentError(res.message);
        }
      } catch (e) {
        setPresentError(e instanceof Error ? e.message : String(e));
      } finally {
        setPresentingId(null);
      }
    },
    [op, workspaceStore],
  );

  // Handler de teclado no input.
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      switch (e.key) {
        case "Enter":
          e.preventDefault();
          if (sem.results.length > 0 && sem.selectedResult && !sem.queryChanged) {
            // Query não mudou desde a última busca: Enter apresenta o selecionado
            // com a versão escolhida no dropdown (ou best_version se não trocou).
            const sel = sem.selectedResult;
            const ver = versionOverrides[sel.reference] ?? sel.best_version;
            void presentCandidate(sel, ver);
          } else {
            // Query mudou ou não há resultados: Enter dispara busca.
            void sem.search();
          }
          break;
        case "ArrowDown":
          if (sem.results.length > 0) {
            e.preventDefault();
            sem.selectNext();
          }
          break;
        case "ArrowUp":
          if (sem.results.length > 0) {
            e.preventDefault();
            sem.selectPrev();
          }
          break;
        case "Escape":
          e.preventDefault();
          sem.clear();
          inputRef.current?.blur();
          break;
      }
    },
    [sem, presentCandidate],
  );

  const hasQuery = sem.query.trim().length > 0;

  return (
    <div
      className={cn(
        "rounded-lg border transition-colors",
        collapsed
          ? "border-border-subtle bg-surface/50"
          : "border-accent/30 bg-surface",
        className,
      )}
      data-testid="semantic-search-panel"
    >
      {/* Header — sempre visível, clicável para expandir/colapsar */}
      <div
        className="px-3 py-2 cursor-pointer select-none"
        onClick={() => setCollapsed(!collapsed)}
        role="button"
        aria-expanded={!collapsed}
        data-testid="semantic-search-toggle"
      >
        <div className="flex items-center gap-2">
          <Sparkles className="h-3.5 w-3.5 text-accent shrink-0" />
          <span className="text-xs font-medium text-text">Busca Semântica</span>
          <span className="text-[10px] text-text-subtle">
            {sem.useOllama ? "Ollama + FTS5" : "Apenas FTS5"}
          </span>
          <button
            onClick={(e) => {
              e.stopPropagation();
              sem.setUseOllama(!sem.useOllama);
            }}
            className={cn(
              "ml-auto flex items-center gap-1 text-[10px] px-2 py-1 rounded-md border transition-colors",
              sem.useOllama
                ? "border-primary/40 bg-primary/10 text-primary hover:bg-primary/20"
                : "border-border bg-surface-hover text-text-muted hover:bg-surface-elevated",
            )}
            aria-label={sem.useOllama ? "Desligar Ollama" : "Ligar Ollama"}
            title={sem.useOllama ? "Ollama ativo (re-ranqueio semântico)" : "Ollama desligado (apenas FTS5/BM25)"}
            data-testid="ollama-toggle"
          >
            {sem.useOllama ? (
              <>
                <Zap className="h-3 w-3" />
                Ollama
              </>
            ) : (
              <>
                <ZapOff className="h-3 w-3" />
                FTS5
              </>
            )}
          </button>
          {collapsed ? (
            <ChevronDown className="h-3.5 w-3.5 text-text-subtle shrink-0" />
          ) : (
            <ChevronUp className="h-3.5 w-3.5 text-text-subtle shrink-0" />
          )}
        </div>
      </div>

      {/* Conteúdo — visível apenas quando expandido */}
      {!collapsed && (
        <>
          {/* Input */}
          <div className="px-3 pb-3">
        <div
          className={cn(
            "flex items-center gap-2 rounded-md border bg-surface px-3 py-2 transition-colors min-h-[40px]",
            sem.searching
              ? "border-accent/50"
              : "border-border focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/20",
          )}
        >
          {sem.searching ? (
            <Loader2 className="h-4 w-4 text-accent animate-spin shrink-0" />
          ) : (
            <Sparkles className="h-4 w-4 text-accent shrink-0" />
          )}
          <input
            ref={inputRef}
            type="text"
            value={sem.query}
            onChange={(e) => sem.setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Buscar por tema, palavras-chave... (ex.: amor de Deus, fé, bom pastor)"
            className="flex-1 bg-transparent text-sm text-text placeholder:text-text-muted outline-none"
            aria-label="Busca semântica de versículos"
            data-testid="semantic-search-input"
            spellCheck={false}
            autoComplete="off"
          />
          {hasQuery && !sem.searching && (
            <button
              onClick={() => sem.clear()}
              className="text-text-muted hover:text-text transition-colors p-1 rounded shrink-0"
              aria-label="Limpar"
              data-testid="semantic-search-clear"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
          {!sem.searching && (
            <button
              onClick={() => void sem.search()}
              disabled={!hasQuery}
              className={cn(
                "text-xs px-2 py-1 rounded transition-colors shrink-0",
                hasQuery
                  ? "bg-primary/10 text-primary hover:bg-primary/20"
                  : "bg-border text-text-muted cursor-not-allowed",
              )}
              data-testid="semantic-search-button"
            >
              Buscar
            </button>
          )}
        </div>

        {/* Dica de uso (estado vazio) */}
        {!hasQuery && !sem.searching && sem.results.length === 0 && (
          <div className="mt-2 text-[11px] text-text-subtle">
            Digite palavras-chave ou descreva o versículo que procura. Ex.: "amor de Deus", "versículo sobre fé", "bom pastor".
          </div>
        )}

        {/* Banner de fallback (Ollama não usado) */}
        {sem.fallback && sem.results.length > 0 && (
          <div className="mt-2 flex items-center gap-1.5 text-[11px] text-warning bg-warning/10 rounded-md px-2 py-1 border border-warning/30">
            <AlertTriangle className="h-3 w-3 shrink-0" />
            <span>
              {sem.useOllama
                ? "Ollama indisponível ou pipeline ativo — resultados do FTS5 sem re-ranqueio."
                : "Ollama desligado — resultados do FTS5/BM25 (busca instantânea)."}
            </span>
          </div>
        )}

        {/* Erro de busca */}
        {sem.error && (
          <div className="mt-2 text-xs text-status-error bg-status-error/10 rounded-md px-2 py-1.5 border border-status-error/30">
            {sem.error}
          </div>
        )}

        {/* Erro de apresentação */}
        {presentError && (
          <div className="mt-2 text-xs text-status-error bg-status-error/10 rounded-md px-2 py-1.5 border border-status-error/30">
            {presentError}
          </div>
        )}

        {/* Latência (discreto) */}
        {sem.results.length > 0 && sem.latencyMs > 0 && (
          <div className="mt-1 text-[10px] text-text-subtle">
            {sem.results.length} candidatos · {sem.latencyMs}ms
            {sem.fallback ? " (fallback)" : " (Ollama)"}
          </div>
        )}
      </div>
      </>
      )}

      {/* Lista de candidatos — fora do collapse para ocupar largura total */}
      {sem.results.length > 0 && (
        <div
          className="border-t border-border-subtle max-h-[400px] overflow-y-auto"
          role="listbox"
          aria-label="Candidatos da busca semântica"
          data-testid="semantic-search-results"
        >
          {sem.results.map((result, index) => (
            <CandidateCard
              key={`${result.book_id}-${result.chapter}-${result.verse}`}
              result={result}
              index={index}
              selected={index === sem.selectedIndex}
              selectedVersion={versionOverrides[result.reference] ?? result.best_version}
              onVersionChange={(v) =>
                setVersionOverrides((prev) => ({ ...prev, [result.reference]: v }))
              }
              onSelect={() => sem.setSelectedIndex(index)}
              onPresent={(version) => presentCandidate(result, version)}
              presenting={presentingId === result.reference}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================
// CandidateCard — card de um versículo candidato
// ============================================================

interface CandidateCardProps {
  result: SemanticSearchResultDTO;
  index: number;
  selected: boolean;
  selectedVersion: string;
  onVersionChange: (v: string) => void;
  onSelect: () => void;
  onPresent: (version?: string) => void;
  presenting: boolean;
}

function CandidateCard({
  result,
  index,
  selected,
  selectedVersion,
  onVersionChange,
  onSelect,
  onPresent,
  presenting,
}: CandidateCardProps) {
  const [showVersions, setShowVersions] = useState(false);

  return (
    <div
      role="option"
      aria-selected={selected}
      className={cn(
        "px-3 py-2.5 border-b border-border-subtle cursor-pointer transition-colors",
        selected ? "bg-primary/10" : "hover:bg-surface-hover",
      )}
      onClick={onSelect}
      data-testid={`candidate-card-${index}`}
    >
      <div className="flex items-start gap-2">
        {/* Score badge */}
        <div className="shrink-0 mt-0.5">
          <ScoreBadge score={result.semantic_score} rank={index + 1} />
        </div>

        {/* Conteúdo principal */}
        <div className="flex-1 min-w-0">
          {/* Referência + versão + apresentar */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-text">
              {result.reference}
            </span>
            {/* Seletor de versão */}
            <VersionSelector
              versions={result.versions}
              selectedVersion={selectedVersion}
              onChange={onVersionChange}
              onToggle={() => setShowVersions((v) => !v)}
              expanded={showVersions}
            />
            <button
              onClick={(e) => {
                e.stopPropagation();
                onPresent(selectedVersion);
              }}
              disabled={presenting}
              className={cn(
                "ml-auto flex items-center gap-1 text-[11px] px-2 py-1 rounded transition-colors shrink-0",
                presenting
                  ? "bg-primary/20 text-primary/60"
                  : "bg-primary/10 text-primary hover:bg-primary/20",
              )}
              aria-label={`Apresentar ${result.reference}`}
              data-testid={`present-candidate-${index}`}
            >
              {presenting ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Play className="h-3 w-3" />
              )}
              <span>Apresentar</span>
            </button>
          </div>

          {/* Texto do versículo (versão selecionada) */}
          <p className="mt-1 text-xs text-text-muted leading-relaxed">
            {getVersionText(result, selectedVersion)}
          </p>

          {/* Versões expandidas */}
          {showVersions && (
            <div className="mt-2 space-y-1.5 pl-2 border-l-2 border-border-subtle">
              {result.versions.map((v) => (
                <div key={v.version} className="text-[11px]">
                  <span className="font-medium text-text-subtle">{formatVersionKey(v.version)}: </span>
                  <span className="text-text-muted">{v.text}</span>
                </div>
              ))}
            </div>
          )}

          {/* Indicador de selecionado + atalho */}
          {selected && (
            <div className="mt-1.5 flex items-center gap-1 text-[10px] text-text-subtle">
              <CornerDownLeft className="h-2.5 w-2.5" />
              <span>Enter para apresentar</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ============================================================
// ScoreBadge — badge de score semântico
// ============================================================

function ScoreBadge({ score, rank }: { score: number; rank: number }) {
  const percent = Math.round(score * 100);
  const color =
    percent >= 80 ? "text-status-success" :
    percent >= 50 ? "text-warning" :
    "text-text-subtle";

  return (
    <div className="flex flex-col items-center gap-0.5">
      <div className={cn("text-[10px] font-bold", color)}>{percent}%</div>
      <div className="text-[9px] text-text-subtle">#{rank}</div>
    </div>
  );
}

// ============================================================
// VersionSelector — seletor de versão do candidato
// ============================================================

interface VersionSelectorProps {
  versions: Array<{ version: string; text: string; score: number }>;
  selectedVersion: string;
  onChange: (v: string) => void;
  onToggle: () => void;
  expanded: boolean;
}

function VersionSelector({
  versions,
  selectedVersion,
  onChange,
  onToggle,
  expanded,
}: VersionSelectorProps) {
  if (versions.length === 0) return null;

  return (
    <div className="flex items-center gap-1">
      <select
        value={selectedVersion}
        onChange={(e) => {
          e.stopPropagation();
          onChange(e.target.value);
        }}
        onClick={(e) => e.stopPropagation()}
        className="text-[10px] bg-surface-hover border border-border rounded px-1 py-0.5 text-text outline-none cursor-pointer"
        aria-label="Selecionar versão"
        data-testid="version-selector"
      >
        {versions.map((v) => (
          <option key={v.version} value={v.version}>
            {formatVersionKey(v.version)}
          </option>
        ))}
      </select>
      {versions.length > 1 && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onToggle();
          }}
          className="text-[10px] text-text-subtle hover:text-text transition-colors"
          aria-label="Ver todas as versões"
        >
          {expanded ? "▲" : `+${versions.length - 1}`}
        </button>
      )}
    </div>
  );
}

// ============================================================
// Helpers
// ============================================================

function getVersionText(
  result: SemanticSearchResultDTO,
  version: string,
): string {
  const match = result.versions.find((v) => v.version === version);
  return match?.text ?? result.best_text;
}
