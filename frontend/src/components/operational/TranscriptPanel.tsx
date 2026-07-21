/**
 * TranscriptPanel — área de transcrição em tempo real (Sprint 16 + Sprint 19).
 *
 * Sprint 16:
 * - 🎤 Escutando (quando VAD detecta fala)
 * - ⏳ Transcrevendo... (quando Whisper está processando)
 * - Histórico de transcrições (cada segmento completo)
 *
 * Sprint 19 — Streaming Speech Pipeline:
 * - Área "Parcial": transcrição em tempo real (SpeechPartial / SpeechPartialUpdated).
 *   Atualiza continuamente enquanto o pregador fala. Pode mudar.
 * - Área "Confirmada": histórico de transcrições consolidadas (SpeechTranscribed).
 *   Nunca muda após publicada.
 */

import { Mic, Loader2, MessageSquare, Radio } from "lucide-react";
import { useTranscript } from "@/hooks";
import { cn } from "@/utils";

interface TranscriptPanelProps {
  className?: string;
}

export function TranscriptPanel({ className }: TranscriptPanelProps) {
  const { entries, listening, transcribing, partialText, loading } = useTranscript();

  return (
    <div
      className={cn("flex flex-col gap-3 rounded-lg border border-border bg-surface p-4", className)}
      data-testid="transcript-panel"
    >
      {/* Header */}
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-text">Transcrição</h3>
        <StatusBadge listening={listening} transcribing={transcribing} hasPartial={!!partialText} />
      </div>

      {/* Status bar */}
      <div className="flex items-center gap-2 text-xs">
        {listening && (
          <span className="inline-flex items-center gap-1.5 text-status-processing animate-pulse">
            <Mic className="h-3.5 w-3.5" />
            Escutando...
          </span>
        )}
        {transcribing && (
          <span className="inline-flex items-center gap-1.5 text-status-warning">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Transcrevendo...
          </span>
        )}
        {!listening && !transcribing && entries.length === 0 && !partialText && !loading && (
          <span className="text-text-muted">
            Aguardando fala...
          </span>
        )}
        {loading && (
          <span className="text-text-muted">Carregando...</span>
        )}
      </div>

      {/* Sprint 19 — Área Parcial (transcrição em tempo real) */}
      {partialText && (
        <div
          className="flex flex-col gap-1 rounded-md border border-status-processing/30 bg-status-processing/5 px-3 py-2"
          data-testid="transcript-partial"
        >
          <div className="flex items-center gap-1.5 text-[10px] font-medium text-status-processing">
            <Radio className="h-3 w-3 animate-pulse" />
            PARCIAL
          </div>
          <p className="text-sm text-text leading-relaxed italic">
            {partialText}
            <span className="inline-block w-1.5 h-3.5 ml-0.5 bg-status-processing/60 animate-pulse align-middle" />
          </p>
        </div>
      )}

      {/* Área Confirmada — histórico de transcrições consolidadas */}
      <div className="flex items-center gap-1.5 text-[10px] font-medium text-text-muted">
        <MessageSquare className="h-3 w-3" />
        CONFIRMADAS
      </div>
      <div
        className="flex flex-col gap-2 max-h-96 overflow-y-auto"
        data-testid="transcript-history"
      >
        {entries.length === 0 ? (
          <p className="text-xs text-text-muted italic py-4 text-center">
            Nenhuma transcrição confirmada ainda.
          </p>
        ) : (
          entries.map((entry) => (
            <div
              key={entry.id}
              className="flex flex-col gap-1 rounded-md border border-border-subtle bg-surface-elevated px-3 py-2"
              data-testid="transcript-entry"
            >
              <div className="flex items-start gap-2">
                <MessageSquare className="h-4 w-4 shrink-0 text-text-muted mt-0.5" />
                <p className="text-sm text-text leading-relaxed flex-1">
                  {entry.text || "(sem texto reconhecido)"}
                </p>
              </div>
              <div className="flex items-center gap-3 text-[10px] text-text-subtle ml-6">
                <span>{(entry.confidence * 100).toFixed(0)}% conf.</span>
                <span>{entry.latencyMs}ms</span>
                <span>{(entry.durationMs / 1000).toFixed(1)}s áudio</span>
                <span className="ml-auto">
                  {new Date(entry.timestamp * 1000).toLocaleTimeString()}
                </span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function StatusBadge({
  listening,
  transcribing,
  hasPartial,
}: {
  listening: boolean;
  transcribing: boolean;
  hasPartial: boolean;
}) {
  let label = "Inativo";
  let color = "text-text-muted bg-surface-elevated border-border-subtle";

  if (transcribing) {
    label = "Transcrevendo";
    color = "text-status-warning bg-status-warning/10 border-status-warning/30";
  } else if (hasPartial) {
    label = "Streaming";
    color = "text-status-processing bg-status-processing/10 border-status-processing/30";
  } else if (listening) {
    label = "Escutando";
    color = "text-status-processing bg-status-processing/10 border-status-processing/30";
  }

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
        color,
      )}
    >
      {label}
    </span>
  );
}
