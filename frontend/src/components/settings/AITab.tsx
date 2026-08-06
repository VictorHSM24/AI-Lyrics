/**
 * AITab — Configurações > IA.
 *
 * Mostra: modelo Whisper, backend, CPU/GPU, compute type, idioma, threads, LLM.
 * Todos os campos utilizam a configuração existente (AppSettings).
 * Preparado para futura expansão.
 *
 * Sprint 27 — O botão "Aplicar no Backend" foi removido daqui e movido
 * para a barra global SaveRestartBar na ConfigurationPage. Agora o
 * usuário altera todas as abas que quiser e clica em "Salvar e Reiniciar
 * Backend" uma única vez no rodapé.
 */

import { Cpu, Mic2, Brain, AlertTriangle } from "lucide-react";
import { useOperationState } from "@/contexts/OperationContext";
import { useConfiguration } from "@/hooks";
import { Card, PropertyGrid } from "@/components";
import { SelectField, NumberField, TextField } from "./FormControls";

const WHISPER_MODELS = [
  { value: "tiny", label: "Whisper Tiny (39M)" },
  { value: "base", label: "Whisper Base (74M)" },
  { value: "small", label: "Whisper Small (244M)" },
  { value: "medium", label: "Whisper Medium (769M)" },
  { value: "large-v3-turbo", label: "Whisper Large v3 Turbo (809M)" },
];

const BACKENDS = [
  { value: "faster-whisper", label: "Faster Whisper (CTranslate2)" },
];

const DEVICES = [
  { value: "cpu", label: "CPU" },
  { value: "cuda", label: "GPU (CUDA)" },
  { value: "auto", label: "Automático" },
];

const COMPUTE_TYPES = [
  { value: "int8", label: "int8 (mais rápido, menor)" },
  { value: "int8_float16", label: "int8_float16 (balanceado)" },
  { value: "float16", label: "float16 (mais preciso)" },
  { value: "float32", label: "float32 (máxima precisão)" },
];

const STT_LANGUAGES = [
  { value: "pt", label: "Português" },
  { value: "pt-BR", label: "Português (Brasil)" },
  { value: "en", label: "English" },
  { value: "es", label: "Español" },
  { value: "auto", label: "Detecção automática" },
];

/**
 * Mapeia o modelo da UI (alias) para o nome real do faster-whisper.
 */
function uiModelToBackend(uiModel: string): string {
  const map: Record<string, string> = {
    "whisper-tiny": "tiny",
    "whisper-base": "base",
    "whisper-small": "small",
    "whisper-medium": "medium",
    "whisper-large-v3": "large-v3",
    "large-v3-turbo": "large-v3-turbo",
  };
  return map[uiModel] ?? uiModel;
}

/**
 * Mapeia o device da UI para o device do backend.
 */
function uiDeviceToBackend(uiDevice: string): string {
  if (uiDevice === "gpu") return "cuda";
  return uiDevice;
}

export function AITab() {
  const { settings, updateSettings } = useOperationState();
  const { configuration } = useConfiguration();

  const ai = settings?.data.ai;

  if (!ai) {
    return (
      <Card title="IA">
        <p className="text-sm text-text-muted">Carregando configurações…</p>
      </Card>
    );
  }

  // Configuração do backend (config.yaml).
  const backendStt = configuration?.stt as Record<string, unknown> | undefined;

  // Sprint 17.3 — Detectar divergências entre UI e backend.
  const divergences: string[] = [];
  if (backendStt) {
    const beModel = String(backendStt.model ?? "");
    const beBackend = String(backendStt.backend ?? "");
    const beDevice = String(backendStt.device ?? "");
    const beCompute = String(backendStt.compute_type ?? "");
    const beThreads = Number(backendStt.cpu_threads ?? 0);

    if (beModel && beModel !== uiModelToBackend(ai.whisperModel)) {
      divergences.push(
        `Modelo: UI="${ai.whisperModel}" vs Backend="${beModel}"`,
      );
    }
    if (beBackend && beBackend !== ai.backend) {
      divergences.push(
        `Backend: UI="${ai.backend}" vs Backend="${beBackend}"`,
      );
    }
    if (beDevice && beDevice !== uiDeviceToBackend(ai.device)) {
      divergences.push(
        `Device: UI="${ai.device}" vs Backend="${beDevice}"`,
      );
    }
    if (beCompute && beCompute !== ai.computeType) {
      divergences.push(
        `Compute: UI="${ai.computeType}" vs Backend="${beCompute}"`,
      );
    }
    if (beThreads > 0 && beThreads !== ai.threads) {
      divergences.push(
        `Threads: UI=${ai.threads} vs Backend=${beThreads}`,
      );
    }
  }

  return (
    <div className="flex flex-col gap-4" data-testid="ai-tab">
      {divergences.length > 0 && (
        <Card
          title="Divergência Detectada"
          description="A configuração da UI difere do backend."
        >
          <div className="flex flex-col gap-2">
            <div className="flex items-start gap-2 text-sm text-warning">
              <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
              <div>
                <p className="font-medium">
                  {divergences.length} divergência(s) entre UI e backend:
                </p>
                <ul className="mt-1 list-disc list-inside text-xs">
                  {divergences.map((d, i) => (
                    <li key={i}>{d}</li>
                  ))}
                </ul>
                <p className="mt-2 text-xs">
                  A UI mostra valores do localStorage. O backend usa config.yaml.
                  Use o botão "Salvar e Reiniciar Backend" no rodapé para aplicar.
                </p>
              </div>
            </div>
          </div>
        </Card>
      )}

      <Card
        title="Speech-to-Text"
        description="Configuração do modelo de reconhecimento de fala."
      >
        <div className="flex flex-col gap-4">
          <SelectField
            label="Modelo Whisper"
            description="Modelo usado para transcrição."
            tooltip="Modelos maiores são mais precisos mas mais lentos."
            value={ai.whisperModel}
            options={WHISPER_MODELS}
            onChange={(value) =>
              updateSettings((prev) => ({
                ...prev,
                ai: { ...prev.ai, whisperModel: value },
              }))
            }
          />

          <SelectField
            label="Backend"
            description="Implementação do Whisper."
            tooltip="faster-whisper usa CTranslate2 (único backend suportado)."
            value={ai.backend}
            options={BACKENDS}
            onChange={(value) =>
              updateSettings((prev) => ({
                ...prev,
                ai: { ...prev.ai, backend: value },
              }))
            }
          />

          <SelectField
            label="Dispositivo"
            description="CPU ou GPU para inferência."
            tooltip="GPU requer CUDA. Automático seleciona o melhor disponível."
            value={ai.device}
            options={DEVICES}
            onChange={(value) =>
              updateSettings((prev) => ({
                ...prev,
                ai: { ...prev.ai, device: value },
              }))
            }
          />

          <SelectField
            label="Compute Type"
            description="Tipo de quantização."
            tooltip="int8 é mais rápido e usa menos memória. float32 é mais preciso."
            value={ai.computeType}
            options={COMPUTE_TYPES}
            onChange={(value) =>
              updateSettings((prev) => ({
                ...prev,
                ai: { ...prev.ai, computeType: value },
              }))
            }
          />

          <SelectField
            label="Idioma"
            description="Idioma do áudio a ser reconhecido."
            tooltip="Detecção automática adiciona latência. Especificar o idioma é mais rápido."
            value={ai.language}
            options={STT_LANGUAGES}
            onChange={(value) =>
              updateSettings((prev) => ({
                ...prev,
                ai: { ...prev.ai, language: value },
              }))
            }
          />

          <NumberField
            label="Threads"
            description="Número de threads CPU."
            tooltip="Mais threads = mais rápido, mas usa mais CPU. 0 = default do sistema."
            value={ai.threads}
            min={1}
            max={32}
            onChange={(value) =>
              updateSettings((prev) => ({
                ...prev,
                ai: { ...prev.ai, threads: value },
              }))
            }
          />
        </div>
      </Card>

      <Card
        title="LLM"
        description="Modelo de linguagem para processamento adicional (quando existir)."
      >
        <TextField
          label="Modelo LLM"
          description="Nome do modelo LLM usado para pós-processamento."
          tooltip="Preparado para futura expansão. Vazio = desativado."
          value={ai.llmModel}
          placeholder="ex: llama3, gpt-4o-mini"
          onChange={(value) =>
            updateSettings((prev) => ({
              ...prev,
              ai: { ...prev.ai, llmModel: value },
            }))
          }
        />
      </Card>

      {backendStt && (
        <Card
          title="Configuração do Backend (config.yaml)"
          description="Valores atuais carregados pelo backend no startup."
        >
          <PropertyGrid
            properties={Object.entries(backendStt).map(([k, v]) => ({
              label: k,
              value: v as string | number | boolean | null,
            }))}
          />
        </Card>
      )}

      <Card title="Resumo">
        <div className="flex flex-wrap gap-3 text-xs text-text-muted">
          <span className="inline-flex items-center gap-1">
            <Mic2 className="h-3.5 w-3.5" /> {ai.whisperModel}
          </span>
          <span className="inline-flex items-center gap-1">
            <Cpu className="h-3.5 w-3.5" /> {ai.device} · {ai.computeType}
          </span>
          {ai.llmModel && (
            <span className="inline-flex items-center gap-1">
              <Brain className="h-3.5 w-3.5" /> {ai.llmModel}
            </span>
          )}
        </div>
      </Card>
    </div>
  );
}
