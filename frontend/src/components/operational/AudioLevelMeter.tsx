/**
 * AudioLevelMeter — componente reutilizável de nível de áudio.
 *
 * Mostra:
 * - Nível atual (barra animada 0-100%)
 * - dB
 * - Animação suave
 * - Última atividade
 * - Dispositivo atual
 *
 * Preparado para reutilização no Console.
 *
 * Não acessa WebSocket/Transport diretamente.
 * Recebe o nível via props (futuramente via EventStream).
 */

import { useEffect, useRef, useState } from "react";
import { Mic, MicOff } from "lucide-react";
import { cn, formatTimestamp } from "@/utils";

interface AudioLevelMeterProps {
  /** Nível atual 0.0–1.0. */
  level?: number;
  /** Dispositivo atual (nome). */
  deviceName?: string;
  /** Timestamp da última atividade (segundos). */
  lastActivityAt?: number;
  /** Sem dispositivo — mostra estado vazio. */
  noDevice?: boolean;
  className?: string;
  /** Compacto: apenas barra + dB. */
  compact?: boolean;
}

function levelToDb(level: number): number {
  if (level <= 0) return -Infinity;
  return 20 * Math.log10(level);
}

function formatDb(db: number): string {
  if (!isFinite(db)) return "-∞ dB";
  return `${db.toFixed(1)} dB`;
}

export function AudioLevelMeter({
  level = 0,
  deviceName,
  lastActivityAt = 0,
  noDevice = false,
  className,
  compact = false,
}: AudioLevelMeterProps) {
  // Smooth animation via rAF.
  const [displayLevel, setDisplayLevel] = useState(0);
  const targetRef = useRef(level);
  const rafRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    targetRef.current = level;
  }, [level]);

  useEffect(() => {
    const animate = () => {
      setDisplayLevel((prev) => {
        const target = targetRef.current;
        const diff = target - prev;
        // Smooth approach: 20% per frame.
        const next = prev + diff * 0.2;
        if (Math.abs(diff) < 0.001) return target;
        return next;
      });
      rafRef.current = requestAnimationFrame(animate);
    };
    rafRef.current = requestAnimationFrame(animate);
    return () => {
      if (rafRef.current !== undefined) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  const pct = Math.min(100, Math.max(0, displayLevel * 100));
  const db = levelToDb(displayLevel);

  // Bar segments: 10 blocks.
  const filledBlocks = Math.round((displayLevel * 100) / 10);

  if (noDevice) {
    return (
      <div
        className={cn("flex items-center gap-3", className)}
        data-testid="audio-level-meter"
        data-state="no-device"
        role="status"
        aria-label="Nenhum dispositivo de áudio selecionado"
      >
        <MicOff className="h-4 w-4 text-text-subtle" />
        <span className="text-sm text-text-muted">Sem dispositivo</span>
      </div>
    );
  }

  return (
    <div
      className={cn("flex flex-col gap-2", className)}
      data-testid="audio-level-meter"
      data-state="active"
      role="status"
      aria-label={`Nível de áudio: ${pct.toFixed(0)}%, ${formatDb(db)}`}
    >
      {/* Barra de nível */}
      <div className="flex items-center gap-2">
        <Mic className="h-4 w-4 shrink-0 text-text-muted" />
        <div
          className="flex flex-1 gap-0.5"
          role="meter"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Nível de áudio"
        >
          {Array.from({ length: 10 }).map((_, i) => (
            <div
              key={i}
              className={cn(
                "h-3 flex-1 rounded-sm transition-colors",
                i < filledBlocks
                  ? i < 6
                    ? "bg-status-success"
                    : i < 8
                      ? "bg-status-warning"
                      : "bg-status-error"
                  : "bg-border",
              )}
            />
          ))}
        </div>
        <span
          className="w-16 text-right text-xs tabular-nums text-text-muted"
          data-testid="audio-level-db"
        >
          {formatDb(db)}
        </span>
      </div>

      {!compact && (
        <div className="flex items-center justify-between text-xs text-text-subtle">
          <span data-testid="audio-level-device">
            {deviceName ?? "Dispositivo padrão"}
          </span>
          <span data-testid="audio-level-activity">
            {lastActivityAt > 0
              ? `Última atividade: ${formatTimestamp(lastActivityAt)}`
              : "Sem atividade"}
          </span>
        </div>
      )}
    </div>
  );
}
