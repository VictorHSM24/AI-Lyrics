/**
 * TimelinePanel — painel principal da linha do tempo de eventos.
 *
 * Recursos de UX:
 * - Auto-scroll configurável
 * - Pausar atualização
 * - Limpar console
 * - Filtrar eventos (por texto, categoria, severity)
 * - Buscar texto
 *
 * Toda informação vem exclusivamente do EventStore via useEvents().
 * Nenhum polling. Nenhum acesso direto a WebSocket/Transport.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Pause, Play, Trash2, Filter, ChevronDown } from "lucide-react";
import { useEvents } from "@/hooks";
import { Panel, SearchBox, EmptyState } from "@/components";
import { EventCard } from "./EventCard";
import {
  ALL_CATEGORIES,
  ALL_SEVERITIES,
  eventToCategory,
  eventToSeverity,
  type EventCategory,
  type EventSeverity,
} from "./event-categories";
import { cn } from "@/utils";

// ============================================================
// Filtros
// ============================================================

interface Filters {
  text: string;
  categories: Set<EventCategory>;
  severities: Set<EventSeverity>;
}

const NO_FILTERS: Filters = {
  text: "",
  categories: new Set(ALL_CATEGORIES),
  severities: new Set(ALL_SEVERITIES),
};

function matchesFilters(
  event: { event_type: string; payload: Record<string, unknown>; meta: { correlation_id: string } },
  filters: Filters,
): boolean {
  // Filtro de texto.
  if (filters.text) {
    const q = filters.text.toLowerCase();
    const haystack = `${event.event_type} ${JSON.stringify(event.payload)} ${event.meta.correlation_id}`.toLowerCase();
    if (!haystack.includes(q)) return false;
  }
  // Filtro de categoria.
  const cat = eventToCategory(event.event_type);
  if (!filters.categories.has(cat)) return false;
  // Filtro de severity.
  const sev = eventToSeverity(event.event_type);
  if (!filters.severities.has(sev)) return false;
  return true;
}

// ============================================================
// Componente principal
// ============================================================

export function TimelinePanel() {
  const { events } = useEvents();
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [paused, setPaused] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [showFilters, setShowFilters] = useState(false);

  // Eventos "congelados" quando pausado.
  const [frozenEvents, setFrozenEvents] = useState<typeof events | null>(null);
  // Offset de eventos limpos (clear). Eventos antes do offset são ocultados.
  const [clearedCount, setClearedCount] = useState(0);

  const displayEvents = paused
    ? (frozenEvents ?? [])
    : events.slice(clearedCount);

  const filteredEvents = useMemo(() => {
    return displayEvents.filter((e) => matchesFilters(e, filters));
  }, [displayEvents, filters]);

  // Auto-scroll.
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (autoScroll && !paused && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [filteredEvents, autoScroll, paused]);

  // Quando pausa, congela os eventos atuais.
  function togglePause() {
    setPaused((prev) => {
      if (!prev) {
        // Pausa: congela os eventos atuais (considerando offset de clear).
        setFrozenEvents(events.slice(clearedCount));
      } else {
        // Retoma: descarta eventos congelados.
        setFrozenEvents(null);
      }
      return !prev;
    });
  }

  function clearEvents() {
    // Marca todos os eventos atuais como "limpos" via offset.
    // O EventStore não é modificado — apenas a visualização.
    setClearedCount(events.length);
    setFrozenEvents([]);
  }

  function toggleCategory(cat: EventCategory) {
    setFilters((prev) => {
      const cats = new Set(prev.categories);
      if (cats.has(cat)) cats.delete(cat);
      else cats.add(cat);
      return { ...prev, categories: cats };
    });
  }

  function toggleSeverity(sev: EventSeverity) {
    setFilters((prev) => {
      const sevs = new Set(prev.severities);
      if (sevs.has(sev)) sevs.delete(sev);
      else sevs.add(sev);
      return { ...prev, severities: sevs };
    });
  }

  return (
    <div data-testid="timeline-panel">
    <Panel
      title="Linha do Tempo"
    >
      {/* Toolbar */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {/* Busca */}
        <SearchBox
          value={filters.text}
          onChange={(text) => setFilters((prev) => ({ ...prev, text }))}
          placeholder="Buscar eventos..."
          className="flex-1 min-w-[200px]"
        />

        {/* Pausar */}
        <button
          type="button"
          onClick={togglePause}
          className={cn(
            "flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
            paused
              ? "border-status-warning/30 bg-status-warning/10 text-status-warning"
              : "border-border bg-surface text-text-muted hover:text-text",
          )}
          title={paused ? "Retomar atualização" : "Pausar atualização"}
          data-testid="timeline-pause-btn"
        >
          {paused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
          {paused ? "Retomar" : "Pausar"}
        </button>

        {/* Auto-scroll */}
        <button
          type="button"
          onClick={() => setAutoScroll((prev) => !prev)}
          className={cn(
            "flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
            autoScroll
              ? "border-accent/30 bg-accent/10 text-accent"
              : "border-border bg-surface text-text-muted hover:text-text",
          )}
          title={autoScroll ? "Auto-scroll ativo" : "Auto-scroll inativo"}
          data-testid="timeline-autoscroll-btn"
        >
          <ChevronDown className="h-3.5 w-3.5" />
          Auto-scroll
        </button>

        {/* Filtros */}
        <button
          type="button"
          onClick={() => setShowFilters((prev) => !prev)}
          className={cn(
            "flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
            showFilters
              ? "border-accent/30 bg-accent/10 text-accent"
              : "border-border bg-surface text-text-muted hover:text-text",
          )}
          title="Filtrar eventos"
          data-testid="timeline-filter-btn"
        >
          <Filter className="h-3.5 w-3.5" />
          Filtros
        </button>

        {/* Limpar */}
        <button
          type="button"
          onClick={clearEvents}
          className="flex items-center gap-1.5 rounded-md border border-border bg-surface px-3 py-1.5 text-xs font-medium text-text-muted transition-colors hover:text-status-error"
          title="Limpar console"
          data-testid="timeline-clear-btn"
        >
          <Trash2 className="h-3.5 w-3.5" />
          Limpar
        </button>
      </div>

      {/* Painel de filtros */}
      {showFilters && (
        <div
          className="mb-3 flex flex-col gap-3 rounded-md border border-border bg-surface p-3"
          data-testid="timeline-filters"
        >
          {/* Categorias */}
          <div>
            <span className="mb-1.5 block text-xs font-semibold text-text-muted">Categorias</span>
            <div className="flex flex-wrap gap-1.5">
              {ALL_CATEGORIES.map((cat) => (
                <button
                  key={cat}
                  type="button"
                  onClick={() => toggleCategory(cat)}
                  className={cn(
                    "rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
                    filters.categories.has(cat)
                      ? "border-accent/30 bg-accent/10 text-accent"
                      : "border-border bg-surface text-text-subtle",
                  )}
                  data-testid={`filter-category-${cat}`}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>

          {/* Severities */}
          <div>
            <span className="mb-1.5 block text-xs font-semibold text-text-muted">Severidade</span>
            <div className="flex flex-wrap gap-1.5">
              {ALL_SEVERITIES.map((sev) => (
                <button
                  key={sev}
                  type="button"
                  onClick={() => toggleSeverity(sev)}
                  className={cn(
                    "rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
                    filters.severities.has(sev)
                      ? "border-accent/30 bg-accent/10 text-accent"
                      : "border-border bg-surface text-text-subtle",
                  )}
                  data-testid={`filter-severity-${sev}`}
                >
                  {sev}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Estado pausado */}
      {paused && (
        <div className="mb-2 rounded-md bg-status-warning/10 px-3 py-1.5 text-xs text-status-warning" data-testid="timeline-paused-notice">
          Atualização pausada — {frozenEvents?.length ?? 0} eventos congelados.
        </div>
      )}

      {/* Lista de eventos */}
      <div
        ref={scrollRef}
        className="flex max-h-[500px] flex-col gap-1.5 overflow-y-auto"
        data-testid="timeline-list"
      >
        {filteredEvents.length === 0 ? (
          <EmptyState
            title={events.length === 0 ? "Aguardando início do pipeline..." : "Nenhum evento corresponde aos filtros"}
            description={events.length === 0 ? "Os eventos aparecerão aqui quando o pipeline iniciar." : "Ajuste os filtros para ver mais eventos."}
          />
        ) : (
          filteredEvents.map((event, i) => (
            <EventCard key={`${event.meta.event_id}-${i}`} event={event} />
          ))
        )}
      </div>

      {/* Contador */}
      <div className="mt-2 flex items-center justify-between text-xs text-text-subtle">
        <span data-testid="timeline-count">
          {filteredEvents.length} evento{filteredEvents.length !== 1 ? "s" : ""}
          {filteredEvents.length !== displayEvents.length && ` (de ${displayEvents.length})`}
        </span>
        {paused && <span>PAUSADO</span>}
      </div>
    </Panel>
    </div>
  );
}
