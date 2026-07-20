/**
 * AITab — Configurações > IA.
 *
 * Mostra: modelo Whisper, backend, CPU/GPU, compute type, idioma, threads, LLM.
 * Todos os campos utilizam a configuração existente (AppSettings).
 * Preparado para futura expansão.
 *
 * Sprint 17.3 — Auditoria do Runtime do STT:
 * - Mostra divergência entre UI (localStorage) e backend (config.yaml).
 * - Botão "Aplicar no Backend" envia via PUT /configuration.
 * - Aviso se alteração só vale após reiniciar backend.
 */

import { useState } from "react";
import { Cpu, Mic2, Brain, AlertTriangle, Send } from "lucide-react";
import { useOperationState } from "@/contexts/OperationContext";
import { useConfiguration } from "@/hooks";
import { useServices } from "@/hooks";
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
  const services = useServices();
  const [applying, setApplying] = useState(false);
  const [applyResult, setApplyResult] = useState<string | null>(null);

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

  /**
   * Sprint 17.5.2 — Valida valores críticos ANTES de enviar ao backend.
   * Espelha a validação de config/loader.py para falhar cedo na UI
   * com mensagem amigável, em vez de persistir valor inválido e
   * quebrar o restart do backend.
   */
  const VALID_BACKENDS = new Set(["faster-whisper"]);
  const VALID_DEVICES = new Set(["cpu", "cuda", "auto"]);
  const VALID_COMPUTE_TYPES = new Set(["int8", "int8_float16", "float16", "float32"]);

  function validateSttOverrides(overrides: Record<string, unknown>): string[] {
    const errs: string[] = [];
    const backend = overrides.backend as string | undefined;
    const device = overrides.device as string | undefined;
    const computeType = overrides.compute_type as string | undefined;
    const threads = overrides.cpu_threads as number | undefined;
    if (backend && !VALID_BACKENDS.has(backend)) {
      errs.push(`Backend inválido: "${backend}". Válidos: faster-whisper.`);
    }
    if (device && !VALID_DEVICES.has(device)) {
      errs.push(`Device inválido: "${device}". Válidos: cpu, cuda, auto.`);
    }
    if (computeType && !VALID_COMPUTE_TYPES.has(computeType)) {
      errs.push(`Compute type inválido: "${computeType}". Válidos: int8, int8_float16, float16, float32.`);
    }
    if (threads !== undefined && (!Number.isInteger(threads) || threads < 0 || threads > 128)) {
      errs.push(`CPU threads inválido: ${threads}. Deve ser inteiro entre 0 e 128.`);
    }
    return errs;
  }

  /**
   * Sprint 17.3 — Envia configurações de STT para o backend via PUT /configuration.
   * As alterações só passam a valer após reiniciar o backend (o modelo STT
   * é carregado uma vez no startup).
   *
   * Sprint 17.5.2 — Valida antes de enviar. Se houver valores inválidos,
   * mostra erro amigável e NÃO envia ao backend.
   */
  async function applyToBackend() {
    if (!services || !ai) return;
    setApplying(true);
    setApplyResult(null);
    try {
      const sttOverrides: Record<string, unknown> = {
        model: uiModelToBackend(ai.whisperModel),
        backend: ai.backend,
        device: uiDeviceToBackend(ai.device),
        compute_type: ai.computeType,
        language: ai.language === "pt-BR" ? "pt" : ai.language,
        cpu_threads: ai.threads,
      };
      const validationErrors = validateSttOverrides(sttOverrides);
      if (validationErrors.length > 0) {
        setApplyResult(
          `Não enviado — valores inválidos detectados:\n${validationErrors.map((e) => `  • ${e}`).join("\n")}`,
        );
        return;
      }
      const overrides = { stt: sttOverrides };
      await services.configuration.updateConfiguration(overrides);
      setApplyResult(
        "Configuração enviada ao backend. REINICIE o backend para aplicar (o modelo STT é carregado no startup).",
      );
    } catch (e) {
      setApplyResult(`Erro ao aplicar: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setApplying(false);
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
                  Use "Aplicar no Backend" para sincronizar.
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

          <button
            type="button"
            onClick={applyToBackend}
            disabled={applying}
            className="inline-flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 text-sm font-medium text-text hover:bg-surface-hover disabled:opacity-50"
            data-testid="apply-stt-to-backend"
          >
            <Send className="h-4 w-4" />
            {applying ? "Aplicando..." : "Aplicar no Backend"}
          </button>

          {applyResult && (
            <p
              className="text-xs"
              data-testid="apply-result"
            >
              {applyResult}
            </p>
          )}
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
