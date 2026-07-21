/**
 * SermonMemoryPanel — painel da memória contínua da pregação (Sprint 21).
 *
 * Mostra em tempo real:
 * - Livro atual do sermão
 * - Capítulo atual
 * - Tema provável
 * - Entidades reconhecidas (com peso visual)
 * - Histórico recente de referências
 * - Confiança do contexto
 * - Tempo desde última atualização
 * - Eventos de mudança (livro/capítulo/tema)
 * - Métricas operacionais (atualizações/min, mudanças, expirações)
 *
 * Atualização em tempo real via EventStream → SermonStore → useSermon.
 *
 * Eventos que alimentam este painel:
 *   SermonContextUpdated  → atualiza contexto atual
 *   SermonBookChanged     → adiciona mudança de livro
 *   SermonChapterChanged  → adiciona mudança de capítulo
 *   SermonTopicChanged    → adiciona mudança de tema
 */

import {
  Brain,
  BookOpen,
  Hash,
  Lightbulb,
  Users,
  History,
  Activity,
  Clock,
  TrendingUp,
  AlertCircle,
} from "lucide-react";
import { useSermon } from "@/hooks";
import type {
  SermonContextEntry,
  SermonEntityEntry,
  SermonTopicEntry,
  SermonReferenceEntry,
  SermonChangeEvent,
} from "@/stores";
import { cn } from "@/utils";

interface SermonMemoryPanelProps {
  className?: string;
}

export function SermonMemoryPanel({ className }: SermonMemoryPanelProps) {
  const { current, changes, metrics, loading } = useSermon();

  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-lg border border-border bg-surface p-4",
        className,
      )}
      data-testid="sermon-memory-panel"
    >
      {/* Header */}
      <div className="flex items-center gap-2">
        <Brain className="h-4 w-4 text-indigo-400" />
        <h3 className="text-sm font-semibold text-text">
          Sermon Memory
        </h3>
        <span className="ml-auto text-[10px] text-text-muted">
          Sprint 21
        </span>
      </div>

      {loading ? (
        <p className="text-xs text-text-muted">Carregando...</p>
      ) : !current || current.isEmpty ? (
        <p className="text-xs text-text-muted italic">
          Nenhuma memória de sermão construída ainda.
        </p>
      ) : (
        <>
          <CurrentContext context={current} />
          <EntitiesList entities={current.entities} />
          <TopicsList topics={current.recentTopics} />
          <ReferencesList references={current.recentReferences} />
          <ChangesHistory changes={changes} />
          {metrics && <MetricsBlock metrics={metrics} />}
        </>
      )}
    </div>
  );
}

// ============================================================
// Sub-componentes
// ============================================================

function CurrentContext({ context }: { context: SermonContextEntry }) {
  const confidencePct = Math.round(context.confidence * 100);
  const ageSeconds = context.updatedAt
    ? Math.max(0, (Date.now() - new Date(context.updatedAt).getTime()) / 1000)
    : 0;

  return (
    <div
      className="flex flex-col gap-2 rounded-md border border-border bg-surface-2 p-3"
      data-testid="sermon-current-context"
    >
      {/* Livro + Capítulo */}
      <div className="flex flex-wrap items-center gap-3">
        {context.currentBook && (
          <span className="flex items-center gap-1.5 text-sm text-text">
            <BookOpen className="h-4 w-4 text-indigo-400" />
            <span className="font-mono font-semibold">
              {context.currentBook}
            </span>
          </span>
        )}
        {context.currentChapter != null && context.currentChapter > 0 && (
          <span className="flex items-center gap-1 text-sm text-text">
            <Hash className="h-3.5 w-3.5 text-text-muted" />
            <span className="font-mono">{context.currentChapter}</span>
          </span>
        )}
        {!context.currentBook && (
          <span className="text-xs text-text-muted italic">
            Livro ainda não identificado
          </span>
        )}
      </div>

      {/* Tema provável */}
      {context.probableTheme && (
        <div className="flex items-center gap-1.5">
          <Lightbulb className="h-3.5 w-3.5 text-yellow-400" />
          <span className="text-xs text-text">{context.probableTheme}</span>
        </div>
      )}

      {/* Confiança + idade */}
      <div className="flex flex-wrap items-center gap-3 text-[10px] text-text-muted">
        <span className="flex items-center gap-1">
          <TrendingUp className="h-3 w-3" />
          confiança: <span className="text-text font-mono">{confidencePct}%</span>
        </span>
        <span className="flex items-center gap-1">
          <Clock className="h-3 w-3" />
          atualizado há <span className="text-text font-mono">{ageSeconds.toFixed(0)}s</span>
        </span>
        <span>
          updates: <span className="text-text font-mono">{context.totalUpdates}</span>
        </span>
      </div>

      {/* Barra de confiança */}
      <div className="h-1.5 w-full rounded-full bg-border overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            confidencePct >= 70
              ? "bg-emerald-500"
              : confidencePct >= 40
                ? "bg-yellow-500"
                : "bg-red-500",
          )}
          style={{ width: `${confidencePct}%` }}
        />
      </div>
    </div>
  );
}

function EntitiesList({ entities }: { entities: SermonEntityEntry[] }) {
  if (entities.length === 0) return null;
  const top = entities.slice(0, 8);
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5 text-[10px] font-medium text-text-muted uppercase tracking-wide">
        <Users className="h-3 w-3" />
        Entidades ({entities.length})
      </div>
      <div className="flex flex-wrap gap-1.5" data-testid="sermon-entities">
        {top.map((e) => {
          const pct = Math.round(e.weight * 100);
          return (
            <span
              key={e.name}
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-mono",
                pct >= 70
                  ? "bg-emerald-900/30 text-emerald-300 border border-emerald-700/40"
                  : pct >= 40
                    ? "bg-yellow-900/30 text-yellow-300 border border-yellow-700/40"
                    : "bg-surface-2 text-text-muted border border-border",
              )}
              title={`menções: ${e.mentionCount}`}
            >
              {e.name}
              <span className="opacity-60">{pct}%</span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

function TopicsList({ topics }: { topics: SermonTopicEntry[] }) {
  if (topics.length === 0) return null;
  const top = topics.slice(0, 5);
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5 text-[10px] font-medium text-text-muted uppercase tracking-wide">
        <Lightbulb className="h-3 w-3" />
        Temas ({topics.length})
      </div>
      <div className="flex flex-col gap-1" data-testid="sermon-topics">
        {top.map((t) => {
          const pct = Math.round(t.weight * 100);
          return (
            <div key={t.name} className="flex items-center gap-2">
              <span className="text-xs text-text font-mono flex-1 truncate">
                {t.name}
              </span>
              <div className="h-1 w-16 rounded-full bg-border overflow-hidden">
                <div
                  className={cn(
                    "h-full rounded-full",
                    pct >= 70 ? "bg-emerald-500" : pct >= 40 ? "bg-yellow-500" : "bg-red-500",
                  )}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="text-[10px] text-text-muted w-8 text-right">
                {pct}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ReferencesList({ references }: { references: SermonReferenceEntry[] }) {
  if (references.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5 text-[10px] font-medium text-text-muted uppercase tracking-wide">
        <History className="h-3 w-3" />
        Referências Recentes ({references.length})
      </div>
      <div
        className="flex flex-col gap-1 max-h-32 overflow-y-auto"
        data-testid="sermon-references"
      >
        {references.slice(0, 8).map((r, i) => (
          <div
            key={`${r.referenceStr}-${i}`}
            className="flex items-center gap-2 text-[10px]"
          >
            <span className="font-mono text-text flex-1 truncate">
              {r.referenceStr}
            </span>
            <span
              className={cn(
                "px-1.5 py-0.5 rounded text-[9px] uppercase",
                r.source === "semantic"
                  ? "bg-purple-900/30 text-purple-300"
                  : "bg-blue-900/30 text-blue-300",
              )}
            >
              {r.source}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ChangesHistory({ changes }: { changes: SermonChangeEvent[] }) {
  if (changes.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5 text-[10px] font-medium text-text-muted uppercase tracking-wide">
        <Activity className="h-3 w-3" />
        Mudanças ({changes.length})
      </div>
      <div
        className="flex flex-col gap-1 max-h-32 overflow-y-auto"
        data-testid="sermon-changes"
      >
        {changes.slice(0, 10).map((c, i) => (
          <div key={i} className="flex items-center gap-2 text-[10px] text-text-muted">
            <span
              className={cn(
                "px-1.5 py-0.5 rounded uppercase font-medium",
                c.type === "book" && "bg-indigo-900/30 text-indigo-300",
                c.type === "chapter" && "bg-cyan-900/30 text-cyan-300",
                c.type === "topic" && "bg-yellow-900/30 text-yellow-300",
              )}
            >
              {c.type === "book" ? "livro" : c.type === "chapter" ? "cap." : "tema"}
            </span>
            <span className="font-mono truncate flex-1">
              {c.previous || "—"} → {c.next || "—"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

type MetricsLike = NonNullable<ReturnType<typeof useSermon>["metrics"]>;

function MetricsBlock({ metrics }: { metrics: MetricsLike }) {
  return (
    <div
      className="flex flex-col gap-1.5 rounded-md border border-border bg-surface-2 p-2"
      data-testid="sermon-metrics"
    >
      <div className="flex items-center gap-1.5 text-[10px] font-medium text-text-muted uppercase tracking-wide">
        <Activity className="h-3 w-3" />
        Métricas
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[10px] text-text-muted">
        <MetricItem label="updates/min" value={metrics.updatesPerMinute.toFixed(1)} />
        <MetricItem label="uptime" value={`${metrics.uptimeSeconds.toFixed(0)}s`} />
        <MetricItem label="mudanças livro" value={String(metrics.bookChanges)} />
        <MetricItem label="mudanças cap." value={String(metrics.chapterChanges)} />
        <MetricItem label="mudanças tema" value={String(metrics.topicChanges)} />
        <MetricItem label="duração sermão" value={`${metrics.sermonDurationSeconds.toFixed(0)}s`} />
        <MetricItem label="exp. entidades" value={String(metrics.entityExpirations)} />
        <MetricItem label="exp. temas" value={String(metrics.topicExpirations)} />
        <MetricItem label="exp. referências" value={String(metrics.referenceExpirations)} />
        <MetricItem label="idade contexto" value={`${metrics.contextAgeSeconds.toFixed(0)}s`} />
      </div>
    </div>
  );
}

function MetricItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-1">
      <span className="truncate">{label}</span>
      <span className="text-text font-mono">{value}</span>
    </div>
  );
}
