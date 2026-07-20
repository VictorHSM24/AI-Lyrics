/**
 * PipelineControl — botões de Iniciar/Parar Pipeline (Sprint 17.1).
 *
 * Controla toda a cadeia:
 *   AudioCaptureService → SpeechPipeline → SpeechWorker → EventBus
 *
 * Estados:
 *   Parado, Inicializando, Escutando, Processando, Erro
 *
 * O botão chama pipeline.startPipeline() / pipeline.stopPipeline()
 * via Services. O estado real é refletido pelo usePipeline() hook
 * que consome eventos do EventStream.
 */

import { useState, useCallback } from "react";
import { Play, Square, Loader2, AlertCircle } from "lucide-react";
import { usePipeline, useServices } from "@/hooks";
import { cn } from "@/utils";

type PipelinePhase =
  | "stopped"
  | "starting"
  | "listening"
  | "processing"
  | "error";

function derivePhase(
  running: boolean | undefined,
  processing: boolean | undefined,
  error: string | null,
  transitioning: boolean,
): PipelinePhase {
  if (error) return "error";
  if (transitioning) return "starting";
  if (!running) return "stopped";
  if (processing) return "processing";
  return "listening";
}

const PHASE_CONFIG: Record<PipelinePhase, { label: string; color: string; dotClass: string }> = {
  stopped: { label: "Parado", color: "text-text-muted", dotClass: "bg-text-muted" },
  starting: { label: "Inicializando", color: "text-status-warning", dotClass: "bg-status-warning" },
  listening: { label: "Escutando", color: "text-status-healthy", dotClass: "bg-status-healthy" },
  processing: { label: "Processando", color: "text-primary", dotClass: "bg-primary" },
  error: { label: "Erro", color: "text-status-error", dotClass: "bg-status-error" },
};

export function PipelineControl({ className }: { className?: string }) {
  const { status } = usePipeline();
  const services = useServices();
  const [transitioning, setTransitioning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const running = status?.running ?? false;
  const processing = status?.is_processing ?? false;
  const phase = derivePhase(running, processing, error, transitioning);
  const config = PHASE_CONFIG[phase];

  const handleStart = useCallback(async () => {
    setTransitioning(true);
    setError(null);
    try {
      await services.pipeline.startPipeline();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao iniciar pipeline");
    } finally {
      setTransitioning(false);
    }
  }, [services]);

  const handleStop = useCallback(async () => {
    setTransitioning(true);
    setError(null);
    try {
      await services.pipeline.stopPipeline();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao parar pipeline");
    } finally {
      setTransitioning(false);
    }
  }, [services]);

  const isBusy = transitioning;

  return (
    <div
      className={cn(
        "flex items-center gap-3 rounded-lg border border-border bg-surface px-4 py-3",
        className,
      )}
      data-testid="pipeline-control"
    >
      {/* Status indicator */}
      <div className="flex items-center gap-2" data-testid="pipeline-phase">
        <span
          className={cn(
            "h-2.5 w-2.5 rounded-full transition-colors",
            config.dotClass,
            phase === "listening" && "animate-pulse",
          )}
          aria-hidden="true"
        />
        <span className={cn("text-sm font-semibold", config.color)}>
          {config.label}
        </span>
      </div>

      {/* Error message */}
      {error && (
        <div
          className="flex items-center gap-1.5 text-xs text-status-error"
          data-testid="pipeline-error"
        >
          <AlertCircle className="h-3.5 w-3.5" />
          <span className="truncate max-w-[200px]">{error}</span>
        </div>
      )}

      {/* Buttons */}
      <div className="ml-auto flex items-center gap-2">
        {!running && !transitioning ? (
          <button
            type="button"
            onClick={handleStart}
            disabled={isBusy}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
              "bg-status-healthy text-white hover:bg-status-healthy/90",
              "disabled:opacity-50 disabled:cursor-not-allowed",
            )}
            data-testid="pipeline-start-btn"
          >
            <Play className="h-4 w-4" />
            Iniciar Pipeline
          </button>
        ) : running && !transitioning ? (
          <button
            type="button"
            onClick={handleStop}
            disabled={isBusy}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
              "bg-status-error text-white hover:bg-status-error/90",
              "disabled:opacity-50 disabled:cursor-not-allowed",
            )}
            data-testid="pipeline-stop-btn"
          >
            <Square className="h-4 w-4" />
            Parar Pipeline
          </button>
        ) : null}

        {transitioning && (
          <div className="flex items-center gap-1.5 text-sm text-text-muted">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>{running ? "Parando..." : "Iniciando..."}</span>
          </div>
        )}
      </div>
    </div>
  );
}
