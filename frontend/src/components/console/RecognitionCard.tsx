/**
 * RecognitionCard — mostra a última fala reconhecida.
 *
 * Mostra:
 * - Texto reconhecido
 * - Idioma
 * - Confiança
 * - Tempo de processamento
 * - Modelo utilizado
 *
 * Dados vêm do EventStore (último evento SpeechRecognized).
 */

import { AudioLines, Globe, Gauge, Cpu } from "lucide-react";
import { useEvents } from "@/hooks";
import { Card } from "@/components";
import { cn } from "@/utils";

interface RecognitionCardProps {
  className?: string;
}

function findLastSpeechRecognized(events: { event_type: string; payload: Record<string, unknown> }[]) {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].event_type === "SpeechRecognized") {
      return events[i];
    }
  }
  return null;
}

export function RecognitionCard({ className }: RecognitionCardProps) {
  const { events } = useEvents();
  const last = findLastSpeechRecognized(events);

  const text = (last?.payload["text"] as string) ?? null;
  const language = (last?.payload["language"] as string) ?? "pt-BR";
  const confidence = last?.payload["confidence"] as number | undefined;
  const latencyMs = last?.payload["latency_ms"] as number | undefined;
  const model = (last?.payload["model"] as string) ?? "whisper-base";

  return (
    <Card
      title="Reconhecimento"
      description="Última fala reconhecida"
      className={cn(className)}
      data-testid="recognition-card"
    >
      {!text ? (
        <div className="py-6 text-center text-sm text-text-muted">
          Aguardando reconhecimento...
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {/* Texto reconhecido */}
          <div className="rounded-md bg-surface p-3">
            <div className="mb-1 flex items-center gap-1.5 text-xs text-text-muted">
              <AudioLines className="h-3.5 w-3.5" aria-hidden="true" />
              Fala
            </div>
            <p className="text-sm font-medium text-text" data-testid="recognition-text">
              "{text}"
            </p>
          </div>

          {/* Metadados */}
          <div className="grid grid-cols-2 gap-2">
            <div className="flex items-center gap-1.5 text-xs" title={`Idioma: ${language}`}>
              <Globe className="h-3.5 w-3.5 text-text-muted" aria-hidden="true" />
              <span className="text-text-muted">Idioma:</span>
              <span className="font-medium text-text">{language}</span>
            </div>

            <div className="flex items-center gap-1.5 text-xs" title={`Confiança: ${confidence != null ? `${Math.round(confidence * 100)}%` : "—"}`}>
              <Gauge className="h-3.5 w-3.5 text-text-muted" aria-hidden="true" />
              <span className="text-text-muted">Confiança:</span>
              <span className="font-medium text-text" data-testid="recognition-confidence">
                {confidence != null ? `${Math.round(confidence * 100)}%` : "—"}
              </span>
            </div>

            <div className="flex items-center gap-1.5 text-xs" title={`Latência: ${latencyMs != null ? `${Math.round(latencyMs)} ms` : "—"}`}>
              <Gauge className="h-3.5 w-3.5 text-text-muted" aria-hidden="true" />
              <span className="text-text-muted">Latência:</span>
              <span className="font-medium text-text" data-testid="recognition-latency">
                {latencyMs != null ? `${Math.round(latencyMs)} ms` : "—"}
              </span>
            </div>

            <div className="flex items-center gap-1.5 text-xs" title={`Modelo: ${model}`}>
              <Cpu className="h-3.5 w-3.5 text-text-muted" aria-hidden="true" />
              <span className="text-text-muted">Modelo:</span>
              <span className="font-medium text-text">{model}</span>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
