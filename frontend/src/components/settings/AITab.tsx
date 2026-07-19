/**
 * AITab — Configurações > IA.
 *
 * Mostra: modelo Whisper, backend, CPU/GPU, compute type, idioma, threads, LLM.
 * Todos os campos utilizam a configuração existente (AppSettings).
 * Preparado para futura expansão.
 */

import { Cpu, Mic2, Brain } from "lucide-react";
import { useOperationState } from "@/contexts/OperationContext";
import { useConfiguration } from "@/hooks";
import { Card, PropertyGrid } from "@/components";
import { SelectField, NumberField, TextField } from "./FormControls";

const WHISPER_MODELS = [
  { value: "whisper-tiny", label: "Whisper Tiny (39M)" },
  { value: "whisper-base", label: "Whisper Base (74M)" },
  { value: "whisper-small", label: "Whisper Small (244M)" },
  { value: "whisper-medium", label: "Whisper Medium (769M)" },
  { value: "whisper-large-v3", label: "Whisper Large v3 (1550M)" },
];

const BACKENDS = [
  { value: "whisper", label: "Whisper (OpenAI)" },
  { value: "whisper.cpp", label: "whisper.cpp" },
  { value: "faster-whisper", label: "Faster Whisper" },
];

const DEVICES = [
  { value: "cpu", label: "CPU" },
  { value: "gpu", label: "GPU (CUDA)" },
  { value: "auto", label: "Automático" },
];

const COMPUTE_TYPES = [
  { value: "int8", label: "int8 (mais rápido, menor)" },
  { value: "int8_float16", label: "int8_float16 (balanceado)" },
  { value: "float16", label: "float16 (mais preciso)" },
  { value: "float32", label: "float32 (máxima precisão)" },
];

const STT_LANGUAGES = [
  { value: "pt-BR", label: "Português (Brasil)" },
  { value: "pt", label: "Português" },
  { value: "en", label: "English" },
  { value: "es", label: "Español" },
  { value: "auto", label: "Detecção automática" },
];

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

  // Se houver configuração do backend, mostrar como referência.
  const backendStt = configuration?.stt as Record<string, unknown> | undefined;

  return (
    <div className="flex flex-col gap-4" data-testid="ai-tab">
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
            tooltip="whisper.cpp é mais rápido em CPU. faster-whisper usa CTranslate2."
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
            tooltip="Mais threads = mais rápido, mas usa mais CPU."
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
        <Card title="Configuração do Backend" description="Valores atuais reportados pelo backend.">
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
