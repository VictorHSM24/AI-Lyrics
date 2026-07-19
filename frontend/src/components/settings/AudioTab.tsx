/**
 * AudioTab — Configurações > Áudio.
 *
 * Lista dispositivos disponíveis (mock quando não há backend).
 * Permite: selecionar, atualizar lista, testar dispositivo.
 * Mostra nível do áudio em tempo real (AudioLevelMeter).
 */

import { useState } from "react";
import { RefreshCw, Mic, Volume2 } from "lucide-react";
import { useOperationState } from "@/contexts/OperationContext";
import { Card, EmptyState, PropertyGrid } from "@/components";
import { AudioLevelMeter } from "@/components/operational";
import { Button, SelectField, NumberField } from "./FormControls";

interface AudioDevice {
  id: string;
  name: string;
  type: "input" | "output";
  sampleRate: number;
  channels: number;
}

// Mock devices — em produção viria do backend via Services.
const MOCK_DEVICES: AudioDevice[] = [
  { id: "default", name: "Dispositivo padrão", type: "input", sampleRate: 48000, channels: 2 },
  { id: "mic-1", name: "Microfone USB", type: "input", sampleRate: 16000, channels: 1 },
  { id: "mic-2", name: "Microfone Interno", type: "input", sampleRate: 44100, channels: 1 },
];

export function AudioTab() {
  const { settings, updateSettings } = useOperationState();
  const [devices, setDevices] = useState<AudioDevice[]>(MOCK_DEVICES);
  const [refreshing, setRefreshing] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testLevel, setTestLevel] = useState(0);

  const audio = settings?.data.audio;
  const selected = devices.find((d) => d.id === audio?.selectedDeviceId);
  const noDevice = !audio?.selectedDeviceId;

  const handleRefresh = () => {
    setRefreshing(true);
    setTimeout(() => {
      setDevices([...MOCK_DEVICES]);
      setRefreshing(false);
    }, 500);
  };

  const handleTest = () => {
    if (noDevice) return;
    setTesting(true);
    // Simulate audio test with varying levels.
    const start = Date.now();
    const tick = () => {
      const elapsed = Date.now() - start;
      if (elapsed > 3000) {
        setTesting(false);
        setTestLevel(0);
        return;
      }
      setTestLevel(0.3 + Math.random() * 0.5);
      requestAnimationFrame(tick);
    };
    tick();
  };

  if (!audio) {
    return (
      <Card title="Áudio">
        <p className="text-sm text-text-muted">Carregando configurações…</p>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4" data-testid="audio-tab">
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
              value={audio.selectedDeviceId}
              options={[
                { value: "", label: "— Selecionar —" },
                ...devices.map((d) => ({
                  value: d.id,
                  label: `${d.name} (${d.sampleRate / 1000}kHz, ${d.channels === 1 ? "mono" : "stereo"})`,
                })),
              ]}
              onChange={(value) =>
                updateSettings((prev) => ({
                  ...prev,
                  audio: { ...prev.audio, selectedDeviceId: value },
                }))
              }
            />

            {selected && (
              <PropertyGrid
                properties={[
                  { label: "Nome", value: selected.name },
                  { label: "Tipo", value: selected.type === "input" ? "Entrada" : "Saída" },
                  { label: "Taxa de amostragem", value: `${selected.sampleRate} Hz` },
                  { label: "Canais", value: selected.channels === 1 ? "Mono" : "Stereo" },
                ]}
              />
            )}
          </div>
        )}
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
            value={audio.sampleRate}
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
            value={audio.channels}
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

      <Card
        title="Teste de áudio"
        description="Teste o nível de captura do dispositivo selecionado."
        actions={
          <Button
            onClick={handleTest}
            loading={testing}
            disabled={noDevice}
            icon={<Volume2 className="h-4 w-4" />}
          >
            Testar
          </Button>
        }
      >
        {noDevice ? (
          <EmptyState
            title="Nenhum dispositivo selecionado"
            description="Selecione um dispositivo para testar."
            icon={<Mic className="h-12 w-12" />}
          />
        ) : (
          <AudioLevelMeter
            level={testing ? testLevel : 0}
            deviceName={selected?.name}
            lastActivityAt={testing ? Date.now() / 1000 : 0}
          />
        )}
      </Card>
    </div>
  );
}
