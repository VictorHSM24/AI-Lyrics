/**
 * Bootstrap — popula todos os Stores com dados reais do backend
 * imediatamente após a conexão ser estabelecida.
 *
 * Sprint 14: usa Promise.allSettled para resiliência — uma falha
 * parcial não impede o carregamento do restante.
 *
 * Fluxo:
 *   Conexão estabelecida
 *     ↓
 *   bootstrapStores(services, stores)
 *     ↓
 *   9 requisições em paralelo (allSettled)
 *     ↓
 *   Cada resultado → Store.set()
 *     ↓
 *   Hooks re-renderizam com dados reais
 */

import type { PresentationServices } from "@/services";
import type { StoreRegistry } from "@/stores";
import { devLog } from "@/utils";

export interface BootstrapResult {
  /** True se todas as requisições foram bem-sucedidas. */
  allOk: boolean;
  /** Resultados individuais por domínio. */
  results: Record<DomainKey, boolean>;
  /** Erros individuais (se houver). */
  errors: Partial<Record<DomainKey, Error>>;
}

export type DomainKey =
  | "pipelineStatus"
  | "pipelineSession"
  | "pipelineMetrics"
  | "configuration"
  | "diagnostics"
  | "health"
  | "audioDevices"
  | "audioCurrent"
  | "systemInfo"
  | "info";

const DOMAIN_KEYS: DomainKey[] = [
  "pipelineStatus",
  "pipelineSession",
  "pipelineMetrics",
  "configuration",
  "diagnostics",
  "health",
  "audioDevices",
  "audioCurrent",
  "systemInfo",
  "info",
];

interface TaskDef {
  key: DomainKey;
  task: () => Promise<void>;
}

/**
 * Executa o bootstrap — chama todos os Services em paralelo e
 * popula os Stores correspondentes.
 *
 * Usa Promise.allSettled — uma falha parcial não impede o
 * carregamento do restante. Cada Store é atualizado independentemente.
 */
export async function bootstrapStores(
  services: PresentationServices,
  stores: StoreRegistry,
): Promise<BootstrapResult> {
  devLog.bootstrap("Iniciando bootstrap — 10 requisições em paralelo (allSettled)");

  const results: Record<DomainKey, boolean> = {
    pipelineStatus: false,
    pipelineSession: false,
    pipelineMetrics: false,
    configuration: false,
    diagnostics: false,
    health: false,
    audioDevices: false,
    audioCurrent: false,
    systemInfo: false,
    info: false,
  };
  const errors: Partial<Record<DomainKey, Error>> = {};

  const tasks: TaskDef[] = [
    {
      key: "pipelineStatus",
      task: async () => {
        const status = await services.pipeline.getStatus();
        stores.pipeline.update((prev) => ({
          timestamp: Date.now() / 1000,
          status,
          session: prev?.session ?? null as never,
          metrics: prev?.metrics ?? null as never,
          last_event: prev?.last_event ?? null,
        }));
        devLog.bootstrap("pipeline.getStatus OK → stores.pipeline atualizado");
      },
    },
    {
      key: "pipelineSession",
      task: async () => {
        const session = await services.pipeline.getSession();
        stores.session.set(session);
        devLog.bootstrap("pipeline.getSession OK → stores.session atualizado");
      },
    },
    {
      key: "pipelineMetrics",
      task: async () => {
        const metrics = await services.pipeline.getMetrics();
        stores.metrics.set(metrics);
        devLog.bootstrap("pipeline.getMetrics OK → stores.metrics atualizado");
      },
    },
    {
      key: "configuration",
      task: async () => {
        const config = await services.configuration.getConfiguration();
        stores.configuration.set(config);
        devLog.bootstrap("configuration.getConfiguration OK → stores.configuration atualizado");
      },
    },
    {
      key: "diagnostics",
      task: async () => {
        const diags = await services.diagnostics.getDiagnostics();
        stores.diagnostics.set(diags);
        devLog.bootstrap("diagnostics.getDiagnostics OK → stores.diagnostics atualizado");
      },
    },
    {
      key: "health",
      task: async () => {
        const health = await services.health.getHealth();
        stores.health.set(health);
        devLog.bootstrap("health.getHealth OK → stores.health atualizado");
      },
    },
    {
      key: "audioDevices",
      task: async () => {
        const devicesResp = await services.audio.getDevices();
        const prev = stores.audio.current?.data;
        stores.audio.set({
          devices: devicesResp.devices,
          current: prev?.current ?? null,
          levels: prev?.levels ?? null,
          capturing: prev?.capturing ?? false,
          selectedDeviceIndex: prev?.selectedDeviceIndex ?? null,
          sampleRate: prev?.sampleRate ?? 16000,
          channels: prev?.channels ?? 1,
          rms: prev?.rms ?? 0,
          peak: prev?.peak ?? 0,
          lastUpdate: prev?.lastUpdate ?? 0,
          connected: prev?.connected ?? false,
        });
        devLog.bootstrap(`audio.getDevices OK → ${devicesResp.devices.length} dispositivos`);
      },
    },
    {
      key: "audioCurrent",
      task: async () => {
        const current = await services.audio.getCurrentDevice();
        stores.audio.update((prev) => ({
          devices: prev?.devices ?? [],
          current,
          levels: prev?.levels ?? null,
          capturing: prev?.capturing ?? false,
          selectedDeviceIndex: prev?.selectedDeviceIndex ?? null,
          sampleRate: prev?.sampleRate ?? 16000,
          channels: prev?.channels ?? 1,
          rms: prev?.rms ?? 0,
          peak: prev?.peak ?? 0,
          lastUpdate: prev?.lastUpdate ?? 0,
          connected: prev?.connected ?? false,
        }));
        devLog.bootstrap("audio.getCurrent OK → stores.audio.current atualizado");
      },
    },
    {
      key: "systemInfo",
      task: async () => {
        const sysInfo = await services.system.getSystemInfo();
        stores.system.set(sysInfo);
        devLog.bootstrap("system.getSystemInfo OK → stores.system atualizado");
      },
    },
    {
      key: "info",
      task: async () => {
        const info = await services.info.getInfo();
        stores.info.set(info);
        devLog.bootstrap("info.getInfo OK → stores.info atualizado");
      },
    },
  ];

  // Promise.allSettled — uma falha não impede as outras.
  const settled = await Promise.allSettled(tasks.map((t) => t.task()));

  for (let i = 0; i < tasks.length; i += 1) {
    const result = settled[i];
    const key = tasks[i].key;
    if (result.status === "fulfilled") {
      results[key] = true;
    } else {
      results[key] = false;
      errors[key] = result.reason instanceof Error
        ? result.reason
        : new Error(String(result.reason));
      devLog.bootstrap(`${key} FALHOU: ${errors[key]?.message}`);
    }
  }

  const allOk = DOMAIN_KEYS.every((k) => results[k]);
  devLog.bootstrap(
    allOk
      ? "Bootstrap completo — todos os stores populados"
      : `Bootstrap parcial — falhas: ${DOMAIN_KEYS.filter((k) => !results[k]).join(", ")}`,
  );

  return { allOk, results, errors };
}
