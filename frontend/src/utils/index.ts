/**
 * Utilitários gerais do frontend.
 */

/**
 * Formata timestamp (segundos desde epoch) para string legível.
 */
export function formatTimestamp(ts: number): string {
  if (ts <= 0) return "—";
  return new Date(ts * 1000).toLocaleString("pt-BR");
}

/**
 * Formata duração em segundos para string legível.
 */
export function formatDuration(seconds: number): string {
  if (seconds <= 0) return "0s";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const parts: string[] = [];
  if (h > 0) parts.push(`${h}h`);
  if (m > 0) parts.push(`${m}m`);
  if (s > 0 || parts.length === 0) parts.push(`${s}s`);
  return parts.join(" ");
}

/**
 * Formata número com separadores de milhar.
 */
export function formatNumber(n: number): string {
  return n.toLocaleString("pt-BR");
}

/**
 * Formata percentual (0.0–1.0) como string.
 */
export function formatPercent(value: number, decimals = 1): string {
  if (value <= 0) return "0%";
  return `${(value * 100).toFixed(decimals)}%`;
}

/**
 * Formata latência em ms.
 */
export function formatLatency(ms: number): string {
  if (ms <= 0) return "—";
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

/**
 * Trunca string com reticências.
 */
export function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen - 1) + "…";
}

/**
 * Gera ID único para uso em DOM (para aria, etc.).
 */
let _idCounter = 0;
export function generateId(prefix = "id"): string {
  _idCounter += 1;
  return `${prefix}-${_idCounter}`;
}

/**
 * Classes condicionais (cn utility).
 */
export function cn(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}
