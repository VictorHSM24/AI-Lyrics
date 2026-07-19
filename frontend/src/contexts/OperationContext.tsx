/**
 * OperationContext — estado operacional global + persistência de settings.
 *
 * Este context CRIA novos stores usando o factory existente
 * `createSnapshotStore<T>()` — NÃO modifica SnapshotStore nem
 * StoreRegistry. Apenas cria instâncias adicionais e as provê
 * via um context separado.
 *
 * Stores criados:
 * - OperationStore: estado operacional global (Stopped, Starting, Ready, etc.)
 * - SettingsStore: configurações persistentes (localStorage)
 *
 * Hooks expostos:
 * - useOperationState(): estado operacional atual
 * - useSettings(): configurações persistentes
 * - useStartupSteps(): etapas da inicialização
 */

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createSnapshotStore, type Snapshot } from "@/stores";
import { useConnection } from "@/contexts/ConnectionContext";
import { usePipeline, useHealth, useConfiguration } from "@/hooks";
import { useInfrastructure } from "@/contexts/InfraContext";
import type { Client } from "@/sdk";
import type { PresentationServices } from "@/services";
import type { StoreRegistry } from "@/stores";
import type { EventStream } from "@/stream";
import { devLog } from "@/utils";

// ============================================================
// Operation State — estado operacional global.
// ============================================================

export type OperationState =
  | "stopped"
  | "starting"
  | "ready"
  | "running"
  | "paused"
  | "degraded"
  | "error"
  | "stopping";

export interface OperationSnapshot {
  state: OperationState;
  /** Timestamp da última transição. */
  since: number;
  /** Mensagem opcional (ex: motivo de erro). */
  message: string;
}

// ============================================================
// Startup Step — etapa de inicialização.
// ============================================================

export type StartupStepState = "pending" | "running" | "success" | "warning" | "error";

export interface StartupStep {
  id: string;
  label: string;
  state: StartupStepState;
  /** Tempo de execução em ms. */
  durationMs?: number;
  /** Mensagem opcional. */
  message?: string;
}

// ============================================================
// Settings — configurações persistentes.
// ============================================================

export interface GeneralSettings {
  language: string;
  theme: "light" | "dark" | "system";
  autoStart: boolean;
  autoConnect: boolean;
}

export interface AudioSettings {
  selectedDeviceId: string;
  sampleRate: number;
  channels: number;
}

export interface HolyricsSettings {
  url: string;
  token: string;
  version: string;
  quickPresentation: boolean;
}

export interface AISettings {
  whisperModel: string;
  backend: string;
  device: string;
  computeType: string;
  language: string;
  threads: number;
  llmModel: string;
}

export interface SystemInfo {
  logDir: string;
  cacheDir: string;
  diskUsage: string;
  backendVersion: string;
  apiVersion: string;
  frontendVersion: string;
}

export interface AppSettings {
  general: GeneralSettings;
  audio: AudioSettings;
  holyrics: HolyricsSettings;
  ai: AISettings;
}

// ============================================================
// Defaults.
// ============================================================

const DEFAULT_SETTINGS: AppSettings = {
  general: {
    language: "pt-BR",
    theme: "system",
    autoStart: false,
    autoConnect: true,
  },
  audio: {
    selectedDeviceId: "",
    sampleRate: 16000,
    channels: 1,
  },
  holyrics: {
    url: "",
    token: "",
    version: "",
    quickPresentation: true,
  },
  ai: {
    whisperModel: "whisper-base",
    backend: "whisper",
    device: "cpu",
    computeType: "int8",
    language: "pt-BR",
    threads: 4,
    llmModel: "",
  },
};

const DEFAULT_OPERATION: OperationSnapshot = {
  state: "stopped",
  since: 0,
  message: "",
};

const STARTUP_STEPS: StartupStep[] = [
  { id: "backend", label: "Backend", state: "pending" },
  { id: "eventstream", label: "EventStream", state: "pending" },
  { id: "websocket", label: "WebSocket", state: "pending" },
  { id: "presentation", label: "Presentation", state: "pending" },
  { id: "stt", label: "STT", state: "pending" },
  { id: "holyrics", label: "Holyrics", state: "pending" },
  { id: "config", label: "Configuração", state: "pending" },
  { id: "pipeline", label: "Pipeline", state: "pending" },
];

// ============================================================
// Persistence — localStorage.
// ============================================================

const SETTINGS_KEY = "ai-lyrics:settings";

function loadSettings(): AppSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const parsed = JSON.parse(raw) as Partial<AppSettings>;
    return {
      general: { ...DEFAULT_SETTINGS.general, ...parsed.general },
      audio: { ...DEFAULT_SETTINGS.audio, ...parsed.audio },
      holyrics: { ...DEFAULT_SETTINGS.holyrics, ...parsed.holyrics },
      ai: { ...DEFAULT_SETTINGS.ai, ...parsed.ai },
    };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

function saveSettings(settings: AppSettings): void {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    // Silently fail — não bloqueia a UI.
  }
}

// ============================================================
// Startup step checker — verifica o estado real de cada etapa.
// ============================================================

interface StepCheckResult {
  ok: boolean;
  /** True se a falha é apenas um warning (ex: Holyrics não configurado). */
  warning?: boolean;
  message?: string;
}

/**
 * Verifica o estado real de uma etapa do startup.
 *
 * Cada etapa verifica uma condição real:
 * - backend: client.status === "connected"
 * - eventstream: stream não está fechado
 * - websocket: client.status === "connected" (mesmo transporte)
 * - presentation: health store populado (bootstrap completou)
 * - stt: componente STT no HealthSnapshot
 * - holyrics: componente Holyrics no HealthSnapshot
 * - config: configuration store populado
 * - pipeline: pipeline store populado
 *
 * Para etapas que dependem do bootstrap, disporta o bootstrap se
 * a conexão já estiver estabelecida.
 */
async function checkStartupStep(
  stepId: string,
  services: PresentationServices,
  stores: StoreRegistry,
  client: Client,
  stream: EventStream,
): Promise<StepCheckResult> {
  switch (stepId) {
    case "backend": {
      const status = client.status as string;
      if (status === "connected") {
        return { ok: true };
      }
      // Tenta conectar.
      try {
        await client.connect();
        const postStatus = client.status as string;
        return postStatus === "connected"
          ? { ok: true }
          : { ok: false, message: "Backend não respondeu" };
      } catch {
        return { ok: false, message: "Falha ao conectar ao backend" };
      }
    }

    case "eventstream": {
      if (stream.closed) {
        return { ok: false, message: "EventStream fechado" };
      }
      return { ok: true };
    }

    case "websocket": {
      // WebSocket usa o mesmo client — se conectou, WS também conectou.
      const wsStatus = client.status as string;
      if (wsStatus === "connected") {
        return { ok: true };
      }
      return { ok: false, message: "WebSocket não conectado" };
    }

    case "presentation": {
      // Dispara bootstrap se ainda não foi feito.
      if (!stores.health.hasSnapshot) {
        try {
          const health = await services.health.getHealth();
          stores.health.set(health);
        } catch {
          return { ok: false, message: "HealthSnapshot indisponível" };
        }
      }
      const health = stores.health.current?.data;
      if (!health) {
        return { ok: false, message: "HealthSnapshot vazio" };
      }
      return { ok: true };
    }

    case "stt": {
      // Garante que o health store tem dados.
      if (!stores.health.hasSnapshot) {
        try {
          const health = await services.health.getHealth();
          stores.health.set(health);
        } catch {
          return { ok: false, message: "Health indisponível" };
        }
      }
      const health = stores.health.current?.data;
      const stt = health?.components.find((c) => c.component === "stt");
      if (!stt) {
        return { ok: false, message: "Componente STT não encontrado" };
      }
      if (stt.status === "healthy") return { ok: true };
      if (stt.status === "degraded") return { ok: true, message: "STT degradado" };
      return { ok: false, message: `STT ${stt.status}` };
    }

    case "holyrics": {
      // Garante que o health store tem dados.
      if (!stores.health.hasSnapshot) {
        try {
          const health = await services.health.getHealth();
          stores.health.set(health);
        } catch {
          return { ok: false, warning: true, message: "Health indisponível" };
        }
      }
      const health = stores.health.current?.data;
      const holyrics = health?.components.find((c) => c.component === "holyrics");
      if (!holyrics) {
        // Holyrics não encontrado no health — pode ser que não esteja configurado.
        return { ok: false, warning: true, message: "Não configurado" };
      }
      if (holyrics.status === "healthy") return { ok: true };
      if (holyrics.status === "degraded") return { ok: true, message: "Holyrics degradado" };
      return { ok: false, warning: true, message: `Holyrics ${holyrics.status}` };
    }

    case "config": {
      if (!stores.configuration.hasSnapshot) {
        try {
          const config = await services.configuration.getConfiguration();
          stores.configuration.set(config);
        } catch {
          return { ok: false, message: "Configuration indisponível" };
        }
      }
      if (!stores.configuration.current?.data) {
        return { ok: false, message: "Configuration vazio" };
      }
      return { ok: true };
    }

    case "pipeline": {
      if (!stores.pipeline.hasSnapshot) {
        try {
          const status = await services.pipeline.getStatus();
          stores.pipeline.update((prev) => ({
            timestamp: Date.now() / 1000,
            status,
            session: prev?.session ?? null as never,
            metrics: prev?.metrics ?? null as never,
            last_event: prev?.last_event ?? null,
          }));
        } catch {
          return { ok: false, message: "Pipeline status indisponível" };
        }
      }
      if (!stores.pipeline.current?.data) {
        return { ok: false, message: "Pipeline vazio" };
      }
      return { ok: true };
    }

    default:
      return { ok: false, message: `Etapa desconhecida: ${stepId}` };
  }
}

// ============================================================
// OperationContext — provê stores e hooks.
// ============================================================

export interface OperationContextValue {
  operation: Snapshot<OperationSnapshot> | null;
  settings: Snapshot<AppSettings> | null;
  startupSteps: StartupStep[];
  /** Inicia a sequência de startup. */
  startStartup: () => void;
  /** Atualiza settings (auto-persiste). */
  updateSettings: (updater: (prev: AppSettings) => AppSettings) => void;
  /** Reseta settings para o padrão. */
  resetSettings: () => void;
  /** Define o estado operacional explicitamente. */
  setOperationState: (state: OperationState, message?: string) => void;
}

const OperationContext = createContext<OperationContextValue | null>(null);

export interface OperationProviderProps {
  children: ReactNode;
  /** Skip startup (para testes). */
  skipStartup?: boolean;
}

export function OperationProvider({ children, skipStartup = false }: OperationProviderProps) {
  // Stores — criados com o factory existente, sem modificar SnapshotStore.
  const operationStore = useMemo(() => createSnapshotStore<OperationSnapshot>(), []);
  const settingsStore = useMemo(() => createSnapshotStore<AppSettings>(), []);

  // Estado local para re-render.
  const [operation, setOperation] = useState<Snapshot<OperationSnapshot> | null>(null);
  const [settings, setSettings] = useState<Snapshot<AppSettings> | null>(null);
  const [startupSteps, setStartupSteps] = useState<StartupStep[]>(STARTUP_STEPS);

  // Inicializa stores.
  useEffect(() => {
    // Carrega settings persistidos.
    const loaded = loadSettings();
    settingsStore.set(loaded);
    setSettings(settingsStore.current);

    // Estado operacional inicial.
    operationStore.set(DEFAULT_OPERATION);
    setOperation(operationStore.current);

    // Assina mudanças.
    const opSub = operationStore.subscribe((s) => setOperation(s));
    const setSub = settingsStore.subscribe((s) => {
      setSettings(s);
      saveSettings(s.data);
    });

    return () => {
      opSub.unsubscribe();
      setSub.unsubscribe();
    };
  }, [operationStore, settingsStore]);

  // Deriva estado operacional de stores existentes (quando não em startup).
  const { status: connStatus } = useConnection();
  const { status: pipelineStatus } = usePipeline();
  const { health } = useHealth();
  const { configuration } = useConfiguration();
  const infra = useInfrastructure();

  useEffect(() => {
    if (!operation) return;
    const currentState = operation.data.state;
    // Não deriva durante starting/stopping.
    if (currentState === "starting" || currentState === "stopping") return;

    // Deriva de pipeline + connection + health.
    let derived: OperationState = "stopped";
    if (connStatus === "connected") {
      if (pipelineStatus?.running) {
        derived = "running";
      } else if (pipelineStatus?.paused) {
        derived = "paused";
      } else if (health && !health.all_healthy) {
        derived = "degraded";
      } else {
        derived = "ready";
      }
    } else if (connStatus === "connecting") {
      derived = "starting";
    } else if (connStatus === "disconnected") {
      derived = "error";
    }

    if (derived !== currentState) {
      operationStore.update(() => ({
        state: derived,
        since: Date.now() / 1000,
        message: "",
      }));
    }
  }, [connStatus, pipelineStatus, health, operation, operationStore, configuration]);

  // Sincroniza settings.data.holyrics a partir da configuração do backend.
  // O backend (config.yaml) é a única fonte de verdade para URL e token.
  // O frontend apenas espelha esses valores — nunca os define independentemente.
  useEffect(() => {
    if (!configuration) return;
    const backendHolyrics = configuration.holyrics as Record<string, unknown> | undefined;
    if (!backendHolyrics) return;
    const backendUrl = String(backendHolyrics.base_url ?? "");
    const backendToken = String(backendHolyrics.token ?? "");
    if (!backendUrl) return;

    // Só atualiza se os valores diferem (evita loops).
    setSettings((prev) => {
      if (!prev) return prev;
      const current = prev.data.holyrics;
      if (current.url === backendUrl && current.token === backendToken) {
        return prev;
      }
      const updated: AppSettings = {
        ...prev.data,
        holyrics: {
          ...current,
          url: backendUrl,
          token: backendToken,
        },
      };
      settingsStore.set(updated);
      return settingsStore.current;
    });
  }, [configuration]); // eslint-disable-line react-hooks/exhaustive-deps

  // ============================================================
  // Startup sequence — verificações reais do estado do backend.
  // ============================================================

  const startupRunning = useRef(false);

  /**
   * Verifica o estado real de cada etapa do startup.
   * Cada etapa reflete um estado real do backend, NÃO uma simulação.
   *
   * Etapas:
   * - backend: cliente conectado?
   * - eventstream: stream não está fechado?
   * - websocket: cliente conectado (mesmo transporte)?
   * - presentation: HealthSnapshot recebido?
   * - stt: componente STT saudável no HealthSnapshot?
   * - holyrics: componente Holyrics no HealthSnapshot?
   * - config: ConfigurationStore populado?
   * - pipeline: PipelineStore populado?
   */
  const startStartup = useRef(async () => {
    if (startupRunning.current) return;
    startupRunning.current = true;
    devLog.startup("Iniciando sequência de startup com verificações reais");

    // Reset steps.
    setStartupSteps(STARTUP_STEPS.map((s) => ({ ...s, state: "pending" })));

    // Set operation to starting.
    operationStore.update(() => ({
      state: "starting",
      since: Date.now() / 1000,
      message: "Inicializando...",
    }));

    const steps = [...STARTUP_STEPS];

    for (let idx = 0; idx < steps.length; idx += 1) {
      const step = steps[idx];
      const startMs = Date.now();

      // Mark as running.
      setStartupSteps((prev) =>
        prev.map((s) => (s.id === step.id ? { ...s, state: "running" } : s)),
      );
      devLog.startup(`Etapa ${step.id} — verificando...`);

      // Verifica o estado real da etapa.
      const result = await checkStartupStep(step.id, infra.services, infra.stores, infra.client, infra.stream);
      const durationMs = Date.now() - startMs;

      let state: StartupStepState = result.ok ? "success" : "error";
      let message: string | undefined = result.message;

      // Holyrics: warning se não configurado (não é erro).
      if (step.id === "holyrics" && !result.ok && result.warning) {
        state = "warning";
        message = result.message ?? "Não configurado";
      }

      setStartupSteps((prev) =>
        prev.map((s) =>
          s.id === step.id
            ? { ...s, state, durationMs, message }
            : s,
        ),
      );
      devLog.startup(`Etapa ${step.id} → ${state} (${durationMs}ms)${message ? ": " + message : ""}`);
    }

    // All done — set operation to ready (ou error se alguma etapa falhou).
    const finalSteps = STARTUP_STEPS.map((s) => ({ ...s }));
    // Lê o estado atual dos steps (não podemos ler setStartupSteps diretamente,
    // mas podemos inferir do resultado).
    const hasErrors = finalSteps.some((s) => s.state === "error");
    operationStore.update(() => ({
      state: hasErrors ? "error" : "ready",
      since: Date.now() / 1000,
      message: hasErrors ? "Falha na inicialização." : "Sistema pronto.",
    }));
    startupRunning.current = false;
    devLog.startup(hasErrors ? "Startup concluído com erros" : "Startup concluído com sucesso");
  });

  // Auto-start on mount (unless skipped).
  useEffect(() => {
    if (skipStartup) return;
    const timer = setTimeout(() => startStartup.current(), 100);
    return () => clearTimeout(timer);
  }, [skipStartup]);

  // ============================================================
  // Settings updates.
  // ============================================================

  const updateSettings = useRef((updater: (prev: AppSettings) => AppSettings) => {
    settingsStore.update((prev) => updater(prev ?? settingsStore.current?.data ?? DEFAULT_SETTINGS));
  });

  const resetSettings = useRef(() => {
    settingsStore.set(DEFAULT_SETTINGS);
  });

  const setOperationState = useRef((state: OperationState, message?: string) => {
    operationStore.update(() => ({
      state,
      since: Date.now() / 1000,
      message: message ?? "",
    }));
  });

  const value: OperationContextValue = {
    operation,
    settings,
    startupSteps,
    startStartup: () => startStartup.current(),
    updateSettings: (updater) => updateSettings.current(updater),
    resetSettings: () => resetSettings.current(),
    setOperationState: (state, msg) => setOperationState.current(state, msg),
  };

  return (
    <OperationContext.Provider value={value}>
      {children}
    </OperationContext.Provider>
  );
}

// ============================================================
// Hooks.
// ============================================================

export function useOperationState(): OperationContextValue {
  const ctx = useContext(OperationContext);
  if (!ctx) {
    throw new Error("useOperationState deve ser usado dentro de OperationProvider");
  }
  return ctx;
}

// ============================================================
// Operation State → Visual Status mapping.
// ============================================================

export function operationStateToVisual(
  state: OperationState,
): "offline" | "processing" | "healthy" | "warning" | "error" | "paused" | "running" | "unknown" {
  switch (state) {
    case "stopped": return "offline";
    case "starting": return "processing";
    case "ready": return "healthy";
    case "running": return "running";
    case "paused": return "paused";
    case "degraded": return "warning";
    case "error": return "error";
    case "stopping": return "processing";
    default: return "unknown";
  }
}

export function operationStateLabel(state: OperationState): string {
  switch (state) {
    case "stopped": return "Parado";
    case "starting": return "Iniciando";
    case "ready": return "Pronto";
    case "running": return "Executando";
    case "paused": return "Pausado";
    case "degraded": return "Degradado";
    case "error": return "Erro";
    case "stopping": return "Parando";
    default: return "Desconhecido";
  }
}
