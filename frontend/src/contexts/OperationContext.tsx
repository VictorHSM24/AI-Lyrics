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
import { usePipeline, useHealth } from "@/hooks";

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
    url: "http://localhost:8080",
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
  }, [connStatus, pipelineStatus, health, operation, operationStore]);

  // ============================================================
  // Startup sequence.
  // ============================================================

  const startupRunning = useRef(false);

  const startStartup = useRef(() => {
    if (startupRunning.current) return;
    startupRunning.current = true;

    // Reset steps.
    setStartupSteps(STARTUP_STEPS.map((s) => ({ ...s, state: "pending" })));

    // Set operation to starting.
    operationStore.update(() => ({
      state: "starting",
      since: Date.now() / 1000,
      message: "Inicializando...",
    }));

    // Simulate startup sequence with delays.
    // In a real system, each step would check the actual service.
    const steps = [...STARTUP_STEPS];
    let idx = 0;

    const runNext = () => {
      if (idx >= steps.length) {
        // All done.
        operationStore.update(() => ({
          state: "ready",
          since: Date.now() / 1000,
          message: "Sistema pronto.",
        }));
        startupRunning.current = false;
        return;
      }

      const step = steps[idx];
      const startMs = Date.now();

      // Mark as running.
      setStartupSteps((prev) =>
        prev.map((s) => (s.id === step.id ? { ...s, state: "running" } : s)),
      );

      // Simulate step execution (50-150ms per step).
      const delay = 50 + Math.random() * 100;
      setTimeout(() => {
        const durationMs = Date.now() - startMs;
        // All steps succeed in this phase (no real backend to check).
        // Holyrics may warn if not configured.
        const state: StartupStepState =
          step.id === "holyrics" ? "warning" : "success";

        setStartupSteps((prev) =>
          prev.map((s) =>
            s.id === step.id
              ? { ...s, state, durationMs, message: state === "warning" ? "Não configurado" : undefined }
              : s,
          ),
        );

        idx += 1;
        runNext();
      }, delay);
    };

    runNext();
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
