/**
 * StatusBar — indicadores de status do sistema no painel do operador.
 *
 * Mostra em tempo real:
 * - Pipeline (rodando/parado)
 * - Microfone (capturando/parado + nível RMS)
 * - Holyrics (conectado/desconectado)
 */

import { usePipeline, useAudio, useHealth } from "@/hooks";
import { cn } from "@/utils";
import {
  Activity,
  Mic,
  Presentation,
  Loader2,
} from "lucide-react";

interface StatusBarProps {
  className?: string;
}

export function StatusBar({ className }: StatusBarProps) {
  const pipeline = usePipeline();
  const audio = useAudio();
  const health = useHealth();

  const running = pipeline.status?.running ?? false;
  const capturing = audio.capturing;
  const rms = audio.rms;

  // Encontrar componente Holyrics no health.
  const holyrics = health.health?.components.find(
    (c) => c.component === "holyrics",
  );
  const holyricsOk = holyrics?.is_healthy ?? false;
  const holyricsMsg = holyrics?.status ?? "desconhecido";

  // Nível de sinal do microfone para a barra.
  const micLevel = capturing && rms > 0 ? Math.min(rms * 5, 1) : 0;

  return (
    <div
      className={cn(
        "flex items-center gap-4 rounded-lg border border-border-subtle bg-surface px-3 py-2",
        className,
      )}
      data-testid="operator-status-bar"
    >
      {/* Pipeline */}
      <StatusItem
        icon={<Activity className="h-3.5 w-3.5" />}
        label="Pipeline"
        active={running}
        activeText="Rodando"
        inactiveText="Parado"
      />

      {/* Separador */}
      <div className="h-4 w-px bg-border-subtle" />

      {/* Microfone */}
      <StatusItem
        icon={<Mic className="h-3.5 w-3.5" />}
        label="Mic"
        active={capturing}
        activeText="Capturando"
        inactiveText="Parado"
        extra={
          capturing && micLevel > 0 ? (
            <div className="flex items-center gap-0.5">
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className={cn(
                    "w-1 rounded-full transition-all",
                    micLevel > (i + 1) * 0.25
                      ? "bg-status-success h-2.5"
                      : "bg-border h-1.5",
                  )}
                />
              ))}
            </div>
          ) : undefined
        }
      />

      {/* Separador */}
      <div className="h-4 w-px bg-border-subtle" />

      {/* Holyrics */}
      <StatusItem
        icon={<Presentation className="h-3.5 w-3.5" />}
        label="Holyrics"
        active={holyricsOk}
        activeText="Conectado"
        inactiveText={holyricsMsg}
      />

      {/* Indicador de loading quando algo está processando */}
      {pipeline.loading && (
        <div className="ml-auto">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-text-subtle" />
        </div>
      )}
    </div>
  );
}

// ============================================================
// StatusItem — item individual da barra de status
// ============================================================

interface StatusItemProps {
  icon: React.ReactNode;
  label: string;
  active: boolean;
  activeText: string;
  inactiveText: string;
  extra?: React.ReactNode;
}

function StatusItem({
  icon,
  label,
  active,
  activeText,
  inactiveText,
  extra,
}: StatusItemProps) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        className={cn(
          "shrink-0",
          active ? "text-status-success" : "text-text-muted",
        )}
      >
        {icon}
      </span>
      <span className="text-[10px] font-medium text-text-muted uppercase tracking-wide">
        {label}
      </span>
      <span
        className={cn(
          "text-[11px] font-semibold",
          active ? "text-status-success" : "text-text-subtle",
        )}
      >
        {active ? activeText : inactiveText}
      </span>
      {extra}
    </div>
  );
}
