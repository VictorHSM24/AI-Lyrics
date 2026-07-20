/**
 * BootstrapCoordinator — orquestra o bootstrap de cada recurso do backend
 * de forma independente, com retry exponencial e estado por recurso.
 *
 * Sprint 17.5.1 — Correção arquitetural para as causas raiz R1-R4:
 *
 * - R1: RestTransport.open() marca "connected" sem verificar o backend.
 *   → O coordinator verifica cada endpoint individualmente e faz retry.
 *
 * - R2: useBootstrap marcava bootstrapped=true mesmo quando todas as tasks
 *   falhavam (Promise.allSettled nunca rejeita).
 *   → O coordinator mantém estado por recurso (idle/loading/loaded/failed)
 *     e só marca "loaded" quando o endpoint retorna dados com sucesso.
 *
 * - R3: useBootstrap não re-disparava após reconexão WS (status
 *   "reconnecting" não resetava bootstrapped).
 *   → O coordinator pode ser re-disparado a qualquer momento via
 *     retryFailed() ou ensureLoaded(). Cada recurso decide independentemente
 *     se precisa re-tentar.
 *
 * - R4: System/Info/Audio/Configuration/Session/Metrics/Diagnostics sem
 *   polling ou retry.
 *   → O coordinator faz retry exponencial para recursos que falharam,
 *     sem depender de refresh manual.
 *
 * Princípios:
 * - Cada recurso tem estado próprio: idle | loading | loaded | failed.
 * - Um recurso falhando NÃO impede os demais.
 * - Recursos falhados tentam novamente com backoff exponencial.
 * - O coordinator é idempotente: chamar ensureLoaded() múltiplas vezes
 *   para um recurso já carregado é no-op.
 * - Não usa setTimeout() para mascarar problemas — o retry é explícito e
 *   logado.
 * - Cancelável: cada round pode ser cancelado via AbortController.
 */

import type { PresentationServices } from "@/services";
import type { StoreRegistry } from "@/stores";
import { devLog } from "@/utils";

// ============================================================
// ResourceState — estado de cada recurso individual.
// ============================================================

export type ResourceState = "idle" | "loading" | "loaded" | "failed";

export interface ResourceStatus {
  state: ResourceState;
  /** Timestamp da última transição bem-sucedida (loaded). */
  lastSuccess: number;
  /** Timestamp da última falha. */
  lastError: number;
  /** Mensagem do último erro. */
  errorMessage: string;
  /** Número de tentativas desde o último sucesso. */
  attempts: number;
}

// ============================================================
// Config — parâmetros do coordinator.
// ============================================================

export interface BootstrapCoordinatorConfig {
  /** Atraso base para retry exponencial (ms). Default: 1000. */
  retryBaseMs?: number;
  /** Atraso máximo para retry (ms). Default: 30000. */
  retryMaxMs?: number;
  /** Número máximo de tentativas antes de desistir. Default: 10. */
  maxAttempts?: number;
}

// ============================================================
// ResourceTask — definição de uma task de bootstrap.
// ============================================================

interface ResourceTask {
  key: string;
  /** Função que chama o service e atualiza o store. Lança em caso de erro. */
  run: (services: PresentationServices, stores: StoreRegistry) => Promise<void>;
}

// ============================================================
// Definição das tasks — uma por recurso.
// ============================================================

const TASKS: ResourceTask[] = [
  {
    key: "pipelineStatus",
    run: async (services, stores) => {
      const status = await services.pipeline.getStatus();
      stores.pipeline.update((prev) => ({
        timestamp: Date.now() / 1000,
        status,
        session: prev?.session ?? null as never,
        metrics: prev?.metrics ?? null as never,
        last_event: prev?.last_event ?? null,
      }));
    },
  },
  {
    key: "pipelineSession",
    run: async (services, stores) => {
      const session = await services.pipeline.getSession();
      stores.session.set(session);
    },
  },
  {
    key: "pipelineMetrics",
    run: async (services, stores) => {
      const metrics = await services.pipeline.getMetrics();
      stores.metrics.set(metrics);
    },
  },
  {
    key: "configuration",
    run: async (services, stores) => {
      const config = await services.configuration.getConfiguration();
      stores.configuration.set(config);
    },
  },
  {
    key: "diagnostics",
    run: async (services, stores) => {
      const diags = await services.diagnostics.getDiagnostics();
      stores.diagnostics.set(diags);
    },
  },
  {
    key: "health",
    run: async (services, stores) => {
      const health = await services.health.getHealth();
      stores.health.set(health);
    },
  },
  {
    key: "audioDevices",
    run: async (services, stores) => {
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
    },
  },
  {
    key: "audioCurrent",
    run: async (services, stores) => {
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
    },
  },
  {
    key: "systemInfo",
    run: async (services, stores) => {
      const sysInfo = await services.system.getSystemInfo();
      stores.system.set(sysInfo);
    },
  },
  {
    key: "info",
    run: async (services, stores) => {
      const info = await services.info.getInfo();
      stores.info.set(info);
    },
  },
];

// ============================================================
// BootstrapCoordinator
// ============================================================

export class BootstrapCoordinator {
  private readonly services: PresentationServices;
  private readonly stores: StoreRegistry;
  private readonly retryBaseMs: number;
  private readonly retryMaxMs: number;
  private readonly maxAttempts: number;

  /** Estado por recurso. */
  private readonly status: Map<string, ResourceStatus> = new Map();

  /** Timers de retry pendentes por recurso. */
  private readonly retryTimers: Map<string, ReturnType<typeof setTimeout>> = new Map();

  /** True se o coordinator foi disposed. */
  private disposed = false;

  constructor(
    services: PresentationServices,
    stores: StoreRegistry,
    config: BootstrapCoordinatorConfig = {},
  ) {
    this.services = services;
    this.stores = stores;
    this.retryBaseMs = config.retryBaseMs ?? 1000;
    this.retryMaxMs = config.retryMaxMs ?? 30000;
    this.maxAttempts = config.maxAttempts ?? 10;

    for (const task of TASKS) {
      this.status.set(task.key, {
        state: "idle",
        lastSuccess: 0,
        lastError: 0,
        errorMessage: "",
        attempts: 0,
      });
    }
  }

  // ============================================================
  // API pública
  // ============================================================

  /**
   * Carrega TODOS os recursos em paralelo. Recursos já carregados
   * (state === "loaded") são pulados. Recursos falhados ou idle
   * são (re)tentados.
   *
   * Retorna um snapshot do estado de todos os recursos.
   */
  async loadAll(): Promise<Record<string, ResourceStatus>> {
    if (this.disposed) return this.snapshot();
    devLog.bootstrap("BootstrapCoordinator.loadAll() — disparando todos os recursos");

    const promises = TASKS.map((task) => this.loadOne(task));
    await Promise.allSettled(promises);
    return this.snapshot();
  }

  /**
   * Carrega um recurso específico se ainda não foi carregado.
   * Idempotente: se já está loaded, retorna imediatamente.
   */
  async ensureLoaded(key: string): Promise<void> {
    if (this.disposed) return;
    const task = TASKS.find((t) => t.key === key);
    if (!task) return;
    const st = this.status.get(key);
    if (st?.state === "loaded") return;
    await this.loadOne(task);
  }

  /**
   * Re-tenta apenas recursos que falharam ou estão idle.
   * Útil para chamar após reconexão WS.
   */
  async retryFailed(): Promise<Record<string, ResourceStatus>> {
    if (this.disposed) return this.snapshot();
    devLog.bootstrap("BootstrapCoordinator.retryFailed() — re-tentando recursos falhados");

    const failed = TASKS.filter((t) => {
      const st = this.status.get(t.key);
      return st?.state === "failed" || st?.state === "idle";
    });

    // Reseta attempts para falhados (dando uma nova janela de tentativas).
    for (const task of failed) {
      const st = this.status.get(task.key);
      if (st && st.state === "failed") {
        st.attempts = 0;
        st.errorMessage = "";
      }
    }

    const promises = failed.map((task) => this.loadOne(task));
    await Promise.allSettled(promises);
    return this.snapshot();
  }

  /**
   * Retorna um snapshot imutável do estado de todos os recursos.
   */
  snapshot(): Record<string, ResourceStatus> {
    const result: Record<string, ResourceStatus> = {};
    for (const [key, st] of this.status.entries()) {
      result[key] = { ...st };
    }
    return result;
  }

  /**
   * True se TODOS os recursos estão carregados com sucesso.
   */
  get allLoaded(): boolean {
    for (const st of this.status.values()) {
      if (st.state !== "loaded") return false;
    }
    return true;
  }

  /**
   * True se ALGUM recurso falhou (após esgotar tentativas).
   */
  get hasFailures(): boolean {
    for (const st of this.status.values()) {
      if (st.state === "failed") return true;
    }
    return false;
  }

  /**
   * Libera recursos — cancela timers pendentes.
   */
  dispose(): void {
    this.disposed = true;
    for (const timer of this.retryTimers.values()) {
      clearTimeout(timer);
    }
    this.retryTimers.clear();
  }

  // ============================================================
  // Internos
  // ============================================================

  /**
   * Carrega UM recurso: chama o service, atualiza o store, e em caso
   * de erro agenda retry exponencial.
   */
  private async loadOne(task: ResourceTask): Promise<void> {
    if (this.disposed) return;
    const st = this.status.get(task.key);
    if (!st) return;

    // Já carregado — pula.
    if (st.state === "loaded") return;

    // Cancela retry pendente (vamos tentar agora).
    const pendingTimer = this.retryTimers.get(task.key);
    if (pendingTimer) {
      clearTimeout(pendingTimer);
      this.retryTimers.delete(task.key);
    }

    st.state = "loading";
    const startMs = Date.now();
    devLog.bootstrap(`[${task.key}] carregando... (tentativa ${st.attempts + 1})`);

    try {
      await task.run(this.services, this.stores);
      st.state = "loaded";
      st.lastSuccess = Date.now() / 1000;
      st.attempts = 0;
      st.errorMessage = "";
      const elapsed = Date.now() - startMs;
      devLog.bootstrap(`[${task.key}] OK (${elapsed}ms)`);
    } catch (e) {
      const elapsed = Date.now() - startMs;
      st.lastError = Date.now() / 1000;
      st.attempts += 1;
      st.errorMessage = e instanceof Error ? e.message : String(e);
      devLog.bootstrap(`[${task.key}] FALHOU (${elapsed}ms): ${st.errorMessage}`);

      if (st.attempts >= this.maxAttempts) {
        st.state = "failed";
        devLog.bootstrap(`[${task.key}] desistiu após ${st.attempts} tentativas`);
      } else {
        st.state = "failed";
        this.scheduleRetry(task);
      }
    }
  }

  /**
   * Agenda um retry com backoff exponencial + jitter.
   */
  private scheduleRetry(task: ResourceTask): void {
    if (this.disposed) return;
    const st = this.status.get(task.key);
    if (!st) return;

    const base = this.retryBaseMs * Math.pow(2, st.attempts - 1);
    const capped = Math.min(base, this.retryMaxMs);
    const jitter = Math.random() * 250;
    const delay = capped + jitter;

    devLog.bootstrap(`[${task.key}] retry em ${Math.round(delay)}ms (tentativa ${st.attempts + 1}/${this.maxAttempts})`);

    const timer = setTimeout(() => {
      this.retryTimers.delete(task.key);
      if (this.disposed) return;
      // Re-tenta apenas este recurso.
      this.loadOne(task).catch(() => {
        // Erro já tratado em loadOne.
      });
    }, delay);

    this.retryTimers.set(task.key, timer);
  }
}

// ============================================================
// Factory
// ============================================================

export function createBootstrapCoordinator(
  services: PresentationServices,
  stores: StoreRegistry,
  config?: BootstrapCoordinatorConfig,
): BootstrapCoordinator {
  return new BootstrapCoordinator(services, stores, config);
}
