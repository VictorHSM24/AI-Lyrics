/**
 * Versionamento — preparação para evoluir DTOs, eventos e API
 * sem quebrar clientes antigos.
 *
 * Nenhum versionamento real é implementado. Apenas a estrutura
 * para que futuras versões possam coexistir.
 */

// ============================================================
// ApiVersion
// ============================================================

export interface ApiVersion {
  /** Versão major (breaking changes). */
  readonly major: number;
  /** Versão minor (features adicionadas). */
  readonly minor: number;
  /** Versão patch (correções). */
  readonly patch: number;
  /** Label de pré-lançamento (ex: "beta.1") ou null. */
  readonly pre: string | null;
}

export const CURRENT_API_VERSION: ApiVersion = {
  major: 0,
  minor: 1,
  patch: 0,
  pre: "foundation",
};

export function apiVersionToString(v: ApiVersion): string {
  const base = `${v.major}.${v.minor}.${v.patch}`;
  return v.pre ? `${base}-${v.pre}` : base;
}

export function parseApiVersion(s: string): ApiVersion | null {
  const m = /^(\d+)\.(\d+)\.(\d+)(?:-(.+))?$/.exec(s);
  if (!m) return null;
  return {
    major: Number(m[1]),
    minor: Number(m[2]),
    patch: Number(m[3]),
    pre: m[4] ?? null,
  };
}

/**
 * Compara duas versões. Retorna:
 * - negativo se a < b
 * - 0 se a == b
 * - positivo se a > b
 */
export function compareApiVersion(a: ApiVersion, b: ApiVersion): number {
  if (a.major !== b.major) return a.major - b.major;
  if (a.minor !== b.minor) return a.minor - b.minor;
  if (a.patch !== b.patch) return a.patch - b.patch;
  if (a.pre === null && b.pre === null) return 0;
  if (a.pre === null) return 1; // release > pre-release
  if (b.pre === null) return -1;
  return a.pre < b.pre ? -1 : a.pre > b.pre ? 1 : 0;
}

// ============================================================
// Versioned<T> — envelope para qualquer payload versionado.
// ============================================================

export interface Versioned<T> {
  readonly api: ApiVersion;
  readonly payload: T;
}

export function versioned<T>(payload: T, api?: ApiVersion): Versioned<T> {
  return { api: api ?? CURRENT_API_VERSION, payload };
}

/**
 * Verifica compatibilidade major entre a versão do payload e a atual.
 */
export function isCompatible<T>(v: Versioned<T>, current: ApiVersion = CURRENT_API_VERSION): boolean {
  return v.api.major === current.major;
}
