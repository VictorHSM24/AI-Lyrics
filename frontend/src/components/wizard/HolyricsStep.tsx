/**
 * HolyricsStep — Etapa 2 do Wizard: Holyrics (Sprint 23.1).
 *
 * Detecta Holyrics na URL padrão da config (reachability sem token),
 * permite informar URL/token manualmente, salva a configuração antes
 * de testar, e testa a conexão usando o token persistido.
 *
 * Sprint 23.1:
 * - Separa detecting (sem token) de testing (com token).
 * - Chama /holyrics/save antes de /holyrics/test para garantir que o
 *   backend use o token persistido (não o estado local stale).
 * - Adiciona validação de URL antes de permitir teste.
 * - Estados de loading separados para detect e test.
 * - Mensagens amigáveis mapeadas por error_type.
 */

import { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  Loader2,
  PlayCircle,
  XCircle,
} from "lucide-react";
import {
  apiGet,
  apiPost,
  type HolyricsTestResult,
} from "./types";

function mapHolyricsError(r: HolyricsTestResult): string {
  switch (r.error_type) {
    case "auth":
      return "Token inválido. Verifique o token configurado no Holyrics em Configurações > API.";
    case "connection":
      return "Holyrics não encontrado. Verifique se está em execução e se a URL está correta.";
    case "timeout":
      return "Tempo limite. O Holyrics demorou muito para responder.";
    case "import":
      return "Módulo de integração com Holyrics não disponível no backend.";
    default:
      return r.message;
  }
}

export function HolyricsStep({ onBusyChange }: { onBusyChange?: (busy: boolean) => void }) {
  const [baseUrl, setBaseUrl] = useState("http://127.0.0.1:8091/api");
  const [token, setToken] = useState("");
  const [result, setResult] = useState<HolyricsTestResult | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [testing, setTesting] = useState(false);
  const [saved, setSaved] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  const busy = detecting || testing;

  useEffect(() => {
    if (onBusyChange) onBusyChange(busy);
  }, [busy, onBusyChange]);

  const detect = useCallback(async () => {
    setDetecting(true);
    setResult(null);
    try {
      const r = await apiGet<HolyricsTestResult>("/holyrics/detect");
      setResult(r);
      if (r.base_url) setBaseUrl(r.base_url);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setResult({
        ok: false,
        message: msg,
        base_url: "",
        latency_ms: 0,
        error_type: "generic",
      });
    } finally {
      setDetecting(false);
    }
  }, []);

  useEffect(() => {
    detect();
  }, [detect]);

  const validateInputs = (): boolean => {
    setValidationError(null);
    if (!baseUrl.trim()) {
      setValidationError("Informe a URL base do Holyrics.");
      return false;
    }
    try {
      // eslint-disable-next-line no-new
      new URL(baseUrl);
    } catch {
      setValidationError("URL inválida. Use o formato http://IP:porta/api");
      return false;
    }
    return true;
  };

  const test = async () => {
    if (!validateInputs()) return;
    setTesting(true);
    setResult(null);
    try {
      // Sprint 23.1: salvar antes de testar para garantir que o backend
      // use o token persistido (não estado local stale) e para que o
      // HolyricsClient do CompositionRoot seja recarregado.
      await apiPost("/holyrics/save", { base_url: baseUrl, token });
      setSaved(true);
      const r = await apiPost<HolyricsTestResult>("/holyrics/test", {
        base_url: baseUrl,
        token,
        timeout_ms: 2000,
      });
      setResult(r);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setResult({
        ok: false,
        message: msg,
        base_url: baseUrl,
        latency_ms: 0,
        error_type: "generic",
      });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Etapa 2 de 5: Holyrics</h2>
      <p className="text-sm text-text-muted">
        O AI Lyrics apresenta versículos no Holyrics. Verifique se ele está
        em execução, informe a URL e o token de API, e teste a conexão.
      </p>

      <div className="grid grid-cols-1 gap-3">
        <label className="text-sm">
          <span className="text-text-muted">URL base</span>
          <input
            type="text"
            value={baseUrl}
            onChange={(e) => { setBaseUrl(e.target.value); setSaved(false); }}
            disabled={busy}
            placeholder="http://127.0.0.1:8091/api"
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-surface text-text disabled:opacity-50"
          />
        </label>
        <label className="text-sm">
          <span className="text-text-muted">Token</span>
          <input
            type="password"
            value={token}
            onChange={(e) => { setToken(e.target.value); setSaved(false); }}
            disabled={busy}
            placeholder="Token configurado no Holyrics (Configurações > API)"
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-surface text-text disabled:opacity-50"
          />
        </label>
      </div>

      {validationError && (
        <div className="flex items-center gap-2 text-sm text-amber-700">
          <XCircle className="h-4 w-4" /> {validationError}
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          onClick={test}
          disabled={busy}
          className="inline-flex items-center gap-2 px-4 py-2 bg-accent text-white rounded hover:opacity-90 disabled:opacity-50"
        >
          {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
          Testar conexão
        </button>
        <button
          onClick={detect}
          disabled={busy}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm text-text-muted hover:text-text disabled:opacity-50"
        >
          {detecting ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
          Detectar novamente
        </button>
        {saved && (
          <span className="text-xs text-green-700 flex items-center gap-1">
            <CheckCircle2 className="h-3 w-3" /> Configuração salva
          </span>
        )}
      </div>

      {result && (
        <div
          className={`flex items-start gap-3 p-4 border rounded ${
            result.ok ? "border-green-300 bg-green-50" : "border-red-300 bg-red-50"
          }`}
        >
          {result.ok ? (
            <CheckCircle2 className="h-5 w-5 text-green-600 flex-shrink-0" />
          ) : (
            <XCircle className="h-5 w-5 text-red-600 flex-shrink-0" />
          )}
          <div className="flex-1">
            <div className="text-sm font-medium">
              {result.ok ? result.message : mapHolyricsError(result)}
            </div>
            <div className="text-xs text-text-muted mt-1">
              URL: {result.base_url} · Latência: {result.latency_ms} ms
              {result.status_code ? ` · HTTP ${result.status_code}` : ""}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
