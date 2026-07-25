/**
 * Tipos e helpers compartilhados entre as etapas do Wizard (Sprint 23.0).
 *
 * Centraliza os tipos das respostas dos endpoints /wizard/* e os helpers
 * de API e visual, para que cada etapa seja um módulo independente.
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
}

export interface HolyricsTestResult {
  ok: boolean;
  message: string;
  base_url: string;
  latency_ms: number;
  status_code?: number;
  error_type?: string;
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
}

export interface OllamaModel {
  configured_model: string;
  installed: boolean;
  message: string;
  all_models?: string[];
}

export interface PullStatus {
  running: boolean;
  completed: boolean;
  failed: boolean;
  progress: string;
  error: string;
  elapsed_s: number;
}

export interface BibleValidation {
  sources_dir: string;
  versions_found: string[];
  versions_count: number;
  sqlite_files: string[];
  bible_retriever_ready: boolean;
  bible_retriever_ok: boolean;
  bible_retriever_stats?: {
    total_versions: number;
    total_verses: number;
    unique_verses: number;
    versions_discovered: string[];
    init_time_ms: number;
  };
  fts5_db_exists: boolean;
  fts5_db_path: string;
  embeddings_npy_exists: boolean;
  embeddings_npy_path: string;
  ok: boolean;
}

export interface TestResult {
  components: Record<string, any>;
  all_ok: boolean;
  message: string;
}

export type Step = "audio" | "holyrics" | "ollama" | "bible" | "test" | "done";

export const STEPS: Step[] = ["audio", "holyrics", "ollama", "bible", "test"];

// ============================================================
// Helpers de API compartilhados
// ============================================================

export async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(`/wizard${path}`);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const json = await resp.json();
  return json.payload as T;
}

export async function apiPost<T>(path: string, body?: any): Promise<T> {
  const resp = await fetch(`/wizard${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const json = await resp.json();
  return json.payload as T;
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
