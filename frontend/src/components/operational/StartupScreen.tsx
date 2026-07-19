/**
 * StartupScreen — tela de inicialização.
 *
 * Mostra todas as etapas executadas pelo sistema.
 * A inicialização ocorre automaticamente via OperationProvider.
 * Quando completa, exibe "Sistema pronto." e botão para continuar.
 */

import { CheckCircle2, RotateCcw, ArrowRight } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useOperationState } from "@/contexts/OperationContext";
import { useApplication } from "@/contexts/ApplicationContext";
import { StartupStepRow } from "./StartupStepRow";
import { OperationStatusBadge } from "./OperationStatusBadge";
import { cn } from "@/utils";

interface StartupScreenProps {
  /** Rota para onde ir após inicialização. Default: "/console". */
  continueTo?: string;
}

export function StartupScreen({ continueTo = "/console" }: StartupScreenProps) {
  const { info } = useApplication();
  const { startupSteps, operation, startStartup } = useOperationState();
  const navigate = useNavigate();

  const opState = operation?.data.state ?? "stopped";
  const opMessage = operation?.data.message ?? "";
  const opSince = operation?.data.since ?? 0;

  const allDone = startupSteps.every(
    (s) => s.state === "success" || s.state === "warning",
  );
  const hasError = startupSteps.some((s) => s.state === "error");
  const isReady = opState === "ready" || opState === "running";

  const handleContinue = () => navigate(continueTo);
  const handleRetry = () => startStartup();

  return (
    <div
      className="flex min-h-screen flex-col items-center justify-center gap-8 bg-background p-6"
      data-testid="startup-screen"
    >
      {/* Logo + nome */}
      <div className="flex flex-col items-center gap-2">
        <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-accent text-white">
          <span className="text-2xl font-bold">AL</span>
        </div>
        <h1 className="text-2xl font-bold text-text">{info.name}</h1>
        <p className="text-sm text-text-muted">v{info.version}</p>
      </div>

      {/* Estado operacional */}
      <OperationStatusBadge
        state={opState}
        message={opMessage}
        since={opSince}
      />

      {/* Etapas */}
      <div
        className="w-full max-w-md rounded-lg border border-border bg-surface p-4"
        data-testid="startup-steps"
      >
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text">Inicializando…</h2>
          {allDone && !hasError && (
            <CheckCircle2 className="h-4 w-4 text-status-success" />
          )}
        </div>
        <div className="flex flex-col divide-y divide-border/50">
          {startupSteps.map((step) => (
            <StartupStepRow key={step.id} step={step} />
          ))}
        </div>
      </div>

      {/* Mensagem de status */}
      <p
        className={cn(
          "text-sm text-center",
          hasError ? "text-status-error" : isReady ? "text-status-success" : "text-text-muted",
        )}
        data-testid="startup-message"
      >
        {hasError
          ? "Falha na inicialização."
          : isReady
            ? "Sistema pronto."
            : opMessage || "Inicializando…"}
      </p>

      {/* Ações */}
      <div className="flex items-center gap-3">
        {(hasError || allDone) && (
          <button
            onClick={handleRetry}
            className="inline-flex items-center gap-2 rounded-md border border-border px-4 py-2 text-sm font-medium text-text hover:bg-surface-hover"
            data-testid="startup-retry"
          >
            <RotateCcw className="h-4 w-4" />
            Reiniciar
          </button>
        )}
        {isReady && (
          <button
            onClick={handleContinue}
            className="inline-flex items-center gap-2 rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover"
            data-testid="startup-continue"
            autoFocus
          >
            Continuar
            <ArrowRight className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  );
}
