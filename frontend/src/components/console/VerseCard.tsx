/**
 * VerseCard — mostra o versículo encontrado e enviado ao Holyrics.
 *
 * Mostra:
 * - Versículo encontrado (livro, capítulo, versículo, versão)
 * - Resultado enviado ao Holyrics
 * - Status
 * - Tempo total
 *
 * Dados vêm do EventStore (últimos eventos VerseFound / HolyricsSuccess).
 */

import { BookOpen, Send, CheckCircle, XCircle, Clock } from "lucide-react";
import { useEvents } from "@/hooks";
import { Card } from "@/components";
import { cn } from "@/utils";

interface VerseCardProps {
  className?: string;
}

function findLast(events: { event_type: string; payload: Record<string, unknown> }[], type: string) {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].event_type === type) return events[i];
  }
  return null;
}

export function VerseCard({ className }: VerseCardProps) {
  const { events } = useEvents();

  const verse = findLast(events, "VerseFound");
  const holyrics = findLast(events, "HolyricsSuccess");
  const holyricsFail = findLast(events, "HolyricsFailure");

  const book = (verse?.payload["book"] as string) ?? null;
  const chapter = verse?.payload["chapter"] as number | undefined;
  const verseNum = verse?.payload["verse"] as number | undefined;
  const version = (verse?.payload["version"] as string) ?? "ACF";
  const verseText = (verse?.payload["text"] as string) ?? null;
  const totalTimeMs = (holyrics?.payload["total_time_ms"] as number | undefined) ?? (verse?.payload["latency_ms"] as number | undefined);

  const holyricsStatus: "success" | "failure" | "pending" | "idle" =
    holyrics ? "success" :
    holyricsFail ? "failure" :
    verse ? "pending" :
    "idle";

  const hasVerse = book != null && chapter != null;

  return (
    <Card
      title="Resultado"
      description="Versículo encontrado e envio ao Holyrics"
      className={cn(className)}
      data-testid="verse-card"
    >
      {!hasVerse ? (
        <div className="py-6 text-center text-sm text-text-muted">
          Aguardando resultado...
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {/* Referência */}
          <div className="rounded-md bg-surface p-3">
            <div className="mb-1 flex items-center gap-1.5 text-xs text-text-muted">
              <BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
              Referência
            </div>
            <p className="text-sm font-semibold text-text" data-testid="verse-reference">
              {book} {chapter}:{verseNum ?? ""}
            </p>
            <p className="text-xs text-text-muted">Versão: {version}</p>
          </div>

          {/* Texto do versículo */}
          {verseText && (
            <div className="rounded-md bg-surface p-3">
              <p className="text-sm italic text-text-muted" data-testid="verse-text">
                "{verseText}"
              </p>
            </div>
          )}

          {/* Status Holyrics */}
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5 text-xs" title={`Holyrics: ${holyricsStatus}`}>
              {holyricsStatus === "success" && <CheckCircle className="h-4 w-4 text-status-healthy" aria-hidden="true" />}
              {holyricsStatus === "failure" && <XCircle className="h-4 w-4 text-status-error" aria-hidden="true" />}
              {holyricsStatus === "pending" && <Send className="h-4 w-4 text-status-warning" aria-hidden="true" />}
              {holyricsStatus === "idle" && <Send className="h-4 w-4 text-text-subtle" aria-hidden="true" />}
              <span className="text-text-muted">Holyrics:</span>
              <span
                className={cn(
                  "font-medium",
                  holyricsStatus === "success" && "text-status-healthy",
                  holyricsStatus === "failure" && "text-status-error",
                  holyricsStatus === "pending" && "text-status-warning",
                  holyricsStatus === "idle" && "text-text-subtle",
                )}
                data-testid="holyrics-status"
              >
                {holyricsStatus === "success" ? "Enviado" :
                 holyricsStatus === "failure" ? "Falhou" :
                 holyricsStatus === "pending" ? "Pendente" :
                 "Aguardando"}
              </span>
            </div>

            {/* Tempo total */}
            <div className="flex items-center gap-1.5 text-xs" title={`Tempo total: ${totalTimeMs != null ? `${Math.round(totalTimeMs)} ms` : "—"}`}>
              <Clock className="h-3.5 w-3.5 text-text-muted" aria-hidden="true" />
              <span className="text-text-muted">Tempo:</span>
              <span className="font-medium text-text" data-testid="verse-total-time">
                {totalTimeMs != null ? `${Math.round(totalTimeMs)} ms` : "—"}
              </span>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
