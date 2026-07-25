/**
 * Tipos e helpers compartilhados entre as etapas do Wizard (Sprint 23.1).
 *
 * Centraliza os tipos das respostas dos endpoints /wizard/* e os helpers
 * de API e visual, para que cada etapa seja um módulo independente.
 *
 * Sprint 23.1:
 * - apiGet/apiPost agora têm timeout (10s) via AbortController.
 * - Tratamento de erro extrai mensagem do corpo da resposta.
 * - Novos tipos para endpoints de save (SaveResult).
 * - BibleValidation.bible_retriever_stats agora inclui sources_dir e error.
 * - TestResult.components agora é tipado (ComponentStatus).
 */

import { CheckCircle2, XCircle } from "lucide-react";
import type React from "react";

// ============================================================
// Tipos das respostas da API /wizard/*
// ============================================================

export interface WizardStatus {
  completed: boolean;
  flag_path: string;
}

export interface AudioDevice {
  index: number;
  name: string;
  hostapi: string;
  channels: number;
  is_input: boolean;
  is_default: boolean;
}

export interface AudioDevicesResponse {
  devices: AudioDevice[];
  count: number;
  error?: string;
}

export interface AudioLevels {
  rms: number;
  peak: number;
  capturing: boolean;
  error?: string;
}

export interface HolyricsTestResult {
  ok: boolean;
  message: string;
  base_url: string;
  latency_ms: number;
  status_code?: number;
  error_type?: string;
}

export interface SaveResult {
  ok: boolean;
  message: string;
  base_url?: string;
  model?: string;
}

export interface OllamaDetect {
  installed: boolean;
  executable: string | null;
  version: string | null;
  message: string;
}

export interface OllamaApi {
  ok: boolean;
  api_url: string;
  latency_ms: number;
  models_installed?: string[];
  models_count?: number;
  error?: string;
  error_type?: string;
}

export interface OllamaModel {
  configured_model: string;
  installed: boolean;
  message: string;
  all_models?: string[];
  error_type?: string;
}

export interface PullStatus {
  running: boolean;
  completed: boolean;
  failed: boolean;
  progress: string;
  error: string;
  elapsed_s: number;
}

export interface BibleRetrieverStats {
  total_versions: number;
  total_verses: number;
  unique_verses: number;
  versions_discovered: string[];
  init_time_ms: number;
  sources_dir?: string;
  error?: string;
}

export interface BibleValidation {
  sources_dir: string;
  versions_found: string[];
  versions_count: number;
  sqlite_files: string[];
  bible_retriever_ready: boolean;
  bible_retriever_ok: boolean;
  bible_retriever_stats?: BibleRetrieverStats;
  fts5_db_exists: boolean;
  fts5_db_path: string;
  embeddings_npy_exists: boolean;
  embeddings_npy_path: string;
  ok: boolean;
}

export interface ComponentStatus {
  ok?: boolean;
  bible_retriever_ok?: boolean;
  message?: string;
  [key: string]: unknown;
}

export interface TestResult {
  components: Record<string, ComponentStatus>;
  all_ok: boolean;
  message: string;
}

export type Step = "audio" | "holyrics" | "ollama" | "bible" | "test" | "done";

export const STEPS: Step[] = ["audio", "holyrics", "ollama", "bible", "test"];

// ============================================================
// Helpers de API compartilhados
// ============================================================

const API_TIMEOUT_MS = 10000;

/**
 * Extrai mensagem amigável do erro de fetch.
 * Tenta ler o corpo da resposta JSON; se não conseguir, usa o status HTTP.
 */
async function extractErrorMessage(resp: Response): Promise<string> {
  try {
    const body = await resp.json();
    if (body?.payload?.message) return body.payload.message;
    if (body?.message) return body.message;
    if (body?.detail) return body.detail;
    return `HTTP ${resp.status}`;
  } catch {
    return `HTTP ${resp.status}`;
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  try {
    const resp = await fetch(`/wizard${path}`, { signal: controller.signal });
    if (!resp.ok) throw new Error(await extractErrorMessage(resp));
    const json = await resp.json();
    return json.payload as T;
  } catch (e: unknown) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error("Tempo limite excedido. Tente novamente.");
    }
    throw e;
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  try {
    const resp = await fetch(`/wizard${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
    if (!resp.ok) throw new Error(await extractErrorMessage(resp));
    const json = await resp.json();
    return json.payload as T;
  } catch (e: unknown) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error("Tempo limite excedido. Tente novamente.");
    }
    throw e;
  } finally {
    clearTimeout(timeoutId);
  }
}

// ============================================================
// Helper visual compartilhado
// ============================================================

export function StatusRow({
  ok,
  label,
  value,
}: {
  ok: boolean;
  label: string;
  value: string;
}): React.ReactElement {
  return (
    <div className="flex items-start gap-3 p-3 border border-border rounded">
      {ok ? (
        <CheckCircle2 className="h-5 w-5 text-green-600 flex-shrink-0" />
      ) : (
        <XCircle className="h-5 w-5 text-amber-600 flex-shrink-0" />
      )}
      <div className="flex-1">
        <div className="text-sm font-medium">{label}</div>
        <div className="text-xs text-text-muted mt-0.5">{value}</div>
      </div>
    </div>
  );
}
