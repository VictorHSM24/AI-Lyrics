/**
 * EventCard — cartão individual de um evento na timeline.
 *
 * Mostra:
 * - Horário
 * - Tipo
 * - Categoria (com cor própria)
 * - Descrição
 * - Severity
 * - Correlation ID (quando existir)
 *
 * Nunca depende apenas de cor — sempre tem ícone + texto.
 */

import {
  Mic, AudioLines, Workflow, Search, Send, Server, AlertCircle,
  type LucideIcon,
} from "lucide-react";
import type { EventDTO } from "@/types";
import {
  eventToCategory,
  eventToSeverity,
  categoryToConfig,
  type EventCategory,
} from "./event-categories";
import { SeverityBadge } from "./SeverityBadge";
import { cn } from "@/utils";

interface EventCardProps {
  event: EventDTO;
  className?: string;
}

const CATEGORY_ICONS: Record<EventCategory, LucideIcon> = {
  audio: Mic,
  stt: AudioLines,
  pipeline: Workflow,
  search: Search,
  holyrics: Send,
  system: Server,
  error: AlertCircle,
};

function formatTime(timestamp: number): string {
  const d = new Date(timestamp * 1000);
  return d.toLocaleTimeString("pt-BR", { hour12: false });
}

function describeEvent(event: EventDTO): string {
  const p = event.payload as Record<string, unknown>;
  // Tenta extrair uma descrição útil do payload.
  if (typeof p["text"] === "string") return p.text as string;
  if (typeof p["query"] === "string") return p.query as string;
  if (typeof p["message"] === "string") return p.message as string;
  if (typeof p["verse"] === "string") return p.verse as string;
  if (typeof p["reference"] === "string") return p.reference as string;
  if (typeof p["book"] === "string" && typeof p["chapter"] === "number") {
    return `${p.book} ${p.chapter}:${p.verse ?? ""}`;
  }
  // Fallback: tipo do evento em formato legível.
  return event.event_type.replace(/([A-Z])/g, " $1").trim().toLowerCase();
}

export function EventCard({ event, className }: EventCardProps) {
  const category = eventToCategory(event.event_type);
  const config = categoryToConfig(category);
  const severity = eventToSeverity(event.event_type);
  const Icon = CATEGORY_ICONS[category];

  const correlationId = event.meta.correlation_id || null;
  const time = formatTime(event.meta.timestamp);

  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-md border px-3 py-2",
        config.bgClass,
        config.borderClass,
        className,
      )}
      data-testid="event-card"
      data-category={category}
      data-event-type={event.event_type}
    >
      {/* Ícone da categoria */}
      <Icon
        className={cn("mt-0.5 h-4 w-4 shrink-0", config.colorClass)}
        aria-hidden="true"
      />

      {/* Conteúdo */}
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-semibold text-text">
            {event.event_type}
          </span>
          <span className="text-xs text-text-subtle tabular-nums" title={time}>
            {time}
          </span>
        </div>

        <span className="truncate text-sm text-text-muted" title={describeEvent(event)}>
          {describeEvent(event)}
        </span>

        <div className="flex items-center gap-3">
          {/* Categoria */}
          <span
            className={cn("text-xs font-medium", config.colorClass)}
            title={`Categoria: ${config.label}`}
          >
            {config.label}
          </span>

          {/* Severity */}
          <SeverityBadge severity={severity} />

          {/* Correlation ID */}
          {correlationId && (
            <span
              className="text-xs text-text-subtle"
              title={`Correlation: ${correlationId}`}
            >
              #{correlationId.slice(0, 8)}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
