/**
 * AudioTab — Configurações > Áudio (Sprint 15.1).
 *
 * Captura de áudio REAL via backend.
 * Nenhum mock. Nenhuma animação fake.
 *
 * Fluxo:
 *   Backend (AudioCaptureService) → WebSocket → Bridge → AudioStore → useAudio → AudioTab
 *
 * Controles:
 * - Selecionar dispositivo (POST /audio/select)
 * - Iniciar captura (POST /audio/start)
 * - Parar captura (POST /audio/stop)
 * - Medidor RMS real (via WebSocket audio.level)
 * - Medidor Peak real (via WebSocket audio.level)
 */

import { useState } from "react";
import { RefreshCw, Mic, Play, Square } from "lucide-react";
import { useOperationState } from "@/contexts/OperationContext";
import { useAudio } from "@/hooks";
import { useServices } from "@/contexts/InfraContext";
import { Card, EmptyState, PropertyGrid } from "@/components";
import { AudioLevelMeter } from "@/components/operational";
import { Button, SelectField, NumberField } from "./FormControls";

export function AudioTab() {
  const { settings, updateSettings } = useOperationState();
  const {
    devices,
    current,
    capturing,
    rms,
    peak,
    lastUpdate,
    connected,
  } = useAudio();
  const services = useServices();
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const audio = settings?.data.audio;
  const selectedDeviceId = audio?.selectedDeviceId ?? (current ? String(current.index) : "");
  const selected = devices.find((d) => String(d.index) === selectedDeviceId) ?? current ?? null;
  const noDevice = !selected;

  const handleRefresh = async () => {
    setRefreshing(true);
    setError(null);
    try {
      const resp = await services.audio.getDevices();
      // O store será atualizado via bootstrap, mas podemos forçar refresh.
      void resp;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao listar dispositivos");
    } finally {
      setRefreshing(false);
    }
  };

  const handleStart = async () => {
    setBusy(true);
    setError(null);
    try {
      await services.audio.startCapture();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao iniciar captura");
    } finally {
      setBusy(false);
    }
  };

  const handleStop = async () => {
    setBusy(true);
    setError(null);
    try {
      await services.audio.stopCapture();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao parar captura");
    } finally {
      setBusy(false);
    }
  };

  const handleSelectDevice = async (value: string) => {
    // Atualiza o estado local primeiro.
    updateSettings((prev) => ({
      ...prev,
      audio: { ...prev.audio, selectedDeviceId: value },
    }));

    if (!value) return;

    const deviceIndex = parseInt(value, 10);
    if (isNaN(deviceIndex)) return;

    setBusy(true);
    setError(null);
    try {
      // POST /audio/select — backend troca dispositivo e reinicia se estava ativo.
      await services.audio.selectDevice(deviceIndex);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao selecionar dispositivo");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-4" data-testid="audio-tab">
      {error && (
        <div className="rounded-md bg-status-error/10 p-3 text-sm text-status-error">
          {error}
        </div>
      )}

      <Card
        title="Dispositivos"
        description="Selecione o microfone usado pelo reconhecimento."
        actions={
          <Button
            onClick={handleRefresh}
            loading={refreshing}
            icon={<RefreshCw className="h-4 w-4" />}
          >
            Atualizar
          </Button>
        }
      >
        {devices.length === 0 ? (
          <EmptyState
            title="Nenhum dispositivo disponível"
            description="Conecte um microfone e clique em Atualizar."
            icon={<Mic className="h-12 w-12" />}
            action={
              <Button onClick={handleRefresh} loading={refreshing}>
                Atualizar lista
              </Button>
            }
          />
        ) : (
          <div className="flex flex-col gap-4">
            <SelectField
              label="Dispositivo de entrada"
              description="Microfone usado para captura de áudio."
              tooltip="Recomendado: microfone dedicado com sample rate 16kHz mono."
              value={selectedDeviceId}
              options={[
                { value: "", label: "— Selecionar —" },
                ...devices.map((d) => ({
                  value: String(d.index),
                  label: `${d.name} (${d.sample_rate / 1000}kHz, ${d.channels === 1 ? "mono" : "stereo"})${d.is_default ? " (padrão)" : ""}`,
                })),
              ]}
              onChange={handleSelectDevice}
            />

            {selected && (
              <PropertyGrid
                properties={[
                  { label: "Nome", value: selected.name },
                  { label: "Índice", value: String(selected.index) },
                  { label: "Canais", value: selected.channels === 1 ? "Mono" : "Stereo" },
                  { label: "Taxa de amostragem", value: `${selected.sample_rate} Hz` },
                  { label: "Padrão do sistema", value: selected.is_default ? "Sim" : "Não" },
                ]}
              />
            )}
          </div>
        )}
      </Card>

      <Card
        title="Captura"
        description="Controle de captura de áudio em tempo real."
        actions={
          <div className="flex gap-2">
            <Button
              onClick={handleStart}
              loading={busy}
              disabled={capturing || noDevice}
              icon={<Play className="h-4 w-4" />}
              variant="primary"
            >
              Iniciar
            </Button>
            <Button
              onClick={handleStop}
              loading={busy}
              disabled={!capturing}
              icon={<Square className="h-4 w-4" />}
              variant="danger"
            >
              Parar
            </Button>
          </div>
        }
      >
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${
                capturing
                  ? "bg-status-success/15 text-status-success"
                  : "bg-border text-text-muted"
              }`}
              data-testid="audio-capture-status"
            >
              <span
                className={`h-2 w-2 rounded-full ${
                  capturing ? "bg-status-success animate-pulse" : "bg-text-subtle"
                }`}
              />
              {capturing ? "Capturando" : "Parado"}
            </span>
            {connected && (
              <span className="text-xs text-text-subtle">
                Conectado via WebSocket
              </span>
            )}
          </div>

          {noDevice ? (
            <EmptyState
              title="Nenhum dispositivo selecionado"
              description="Selecione um dispositivo para capturar."
              icon={<Mic className="h-12 w-12" />}
            />
          ) : (
            <div className="flex flex-col gap-3">
              <div>
                <div className="mb-1 text-xs font-medium text-text-muted">
                  Nível RMS (tempo real)
                </div>
                <AudioLevelMeter
                  level={capturing ? rms : 0}
                  deviceName={selected?.name}
                  lastActivityAt={lastUpdate}
                  data-testid="rms-meter"
                />
              </div>
              <div>
                <div className="mb-1 text-xs font-medium text-text-muted">
                  Nível Peak (tempo real)
                </div>
                <AudioLevelMeter
                  level={capturing ? peak : 0}
                  deviceName={selected?.name}
                  lastActivityAt={lastUpdate}
                  compact
                  data-testid="peak-meter"
                />
              </div>
            </div>
          )}
        </div>
      </Card>

      <Card
        title="Configuração de captura"
        description="Parâmetros de captura de áudio."
      >
        <div className="flex flex-col gap-4">
          <NumberField
            label="Taxa de amostragem"
            description="Frequência de amostragem em Hz."
            tooltip="Whisper funciona melhor com 16kHz."
            value={audio?.sampleRate ?? 16000}
            min={8000}
            max={48000}
            step={1000}
            onChange={(value) =>
              updateSettings((prev) => ({
                ...prev,
                audio: { ...prev.audio, sampleRate: value },
              }))
            }
          />
          <NumberField
            label="Canais"
            description="Número de canais (1 = mono, 2 = stereo)."
            value={audio?.channels ?? 1}
            min={1}
            max={2}
            onChange={(value) =>
              updateSettings((prev) => ({
                ...prev,
                audio: { ...prev.audio, channels: value },
              }))
            }
          />
        </div>
      </Card>
    </div>
  );
}
