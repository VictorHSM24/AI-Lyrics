/**
 * AudioStep — Etapa 1 do Wizard: dispositivo de áudio (Sprint 23.0).
 *
 * Lista dispositivos, permite selecionar, mostra medidor RMS em tempo
 * real (polling de /wizard/audio/levels a cada 250ms).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  Loader2,
  RefreshCw,
  XCircle,
} from "lucide-react";
import {
  apiGet,
  apiPost,
  type AudioDevice,
  type AudioDevicesResponse,
  type AudioLevels,
} from "./types";

export function AudioStep({ onBusyChange }: { onBusyChange?: (busy: boolean) => void }) {
  const [devices, setDevices] = useState<AudioDevice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [levels, setLevels] = useState<AudioLevels | null>(null);
  const pollRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await apiGet<AudioDevicesResponse>("/audio/devices");
      setDevices(r.devices);
      setSelected(r.devices.find((d) => d.is_default)?.index ?? null);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (onBusyChange) onBusyChange(loading);
  }, [loading, onBusyChange]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    let mounted = true;
    let intervalId: number | null = null;
    let inFlight = false;

    const poll = async () => {
      if (!mounted || inFlight) return;
      inFlight = true;
      try {
        const l = await apiGet<AudioLevels>("/audio/levels");
        if (mounted) setLevels(l);
      } catch {
        /* silencioso — medidor não é crítico */
      } finally {
        inFlight = false;
      }
    };

    poll();
    intervalId = window.setInterval(poll, 250);

    return () => {
      mounted = false;
      if (intervalId) window.clearInterval(intervalId);
      pollRef.current = null;
    };
  }, []);

  const selectDevice = async (idx: number) => {
    try {
      await apiPost("/audio/select", { device_index: idx });
      setSelected(idx);
    } catch (e: any) {
      setError(e.message ?? String(e));
    }
  };

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Etapa 1 de 5: Dispositivo de áudio</h2>
      <p className="text-sm text-text-muted">
        Selecione o microfone que será usado para capturar a fala do pregador.
      </p>

      {loading && (
        <div className="flex items-center gap-2 text-sm text-text-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> Carregando dispositivos...
        </div>
      )}
      {error && (
        <div className="flex items-center gap-2 text-sm text-red-600">
          <XCircle className="h-4 w-4" /> {error}
        </div>
      )}
      {!loading && devices.length === 0 && (
        <div className="flex items-center gap-2 text-sm text-amber-600">
          <XCircle className="h-4 w-4" /> Nenhum dispositivo de entrada encontrado.
        </div>
      )}

      {devices.length > 0 && (
        <div className="space-y-2">
          {devices.map((d) => (
            <label
              key={d.index}
              className={`flex items-center gap-3 p-3 border rounded cursor-pointer ${
                selected === d.index
                  ? "border-accent bg-accent/5"
                  : "border-border hover:border-accent/50"
              }`}
            >
              <input
                type="radio"
                name="audio-device"
                checked={selected === d.index}
                onChange={() => selectDevice(d.index)}
                className="accent-accent"
              />
              <div className="flex-1">
                <div className="text-sm font-medium">{d.name}</div>
                <div className="text-xs text-text-muted">
                  {d.hostapi} · {d.channels} canal(is) {d.is_default && "· padrão"}
                </div>
              </div>
              {selected === d.index && <CheckCircle2 className="h-5 w-5 text-accent" />}
            </label>
          ))}
        </div>
      )}

      <div className="border border-border rounded p-4">
        <div className="text-xs text-text-muted mb-2">Nível de áudio (RMS)</div>
        <div className="h-3 bg-surface rounded overflow-hidden">
          <div
            className="h-full bg-green-500 transition-all duration-100"
            style={{ width: `${Math.min(100, (levels?.rms ?? 0) * 200)}%` }}
          />
        </div>
        <div className="text-xs text-text-muted mt-1">
          RMS: {(levels?.rms ?? 0).toFixed(4)} · Peak: {(levels?.peak ?? 0).toFixed(4)}
        </div>
      </div>

      <button
        onClick={load}
        className="inline-flex items-center gap-2 text-sm text-text-muted hover:text-text"
      >
        <RefreshCw className="h-4 w-4" /> Atualizar lista
      </button>
    </div>
  );
}
