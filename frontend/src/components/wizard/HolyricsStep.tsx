/**
 * HolyricsStep — Etapa 2 do Wizard: Holyrics (Sprint 23.0).
 *
 * Detecta Holyrics na URL padrão da config, permite informar URL/token
 * manualmente, testa a conexão e exibe resultado com latência.
 */

import { useEffect, useState } from "react";
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

export function HolyricsStep() {
  const [baseUrl, setBaseUrl] = useState("http://127.0.0.1:8091/api");
  const [token, setToken] = useState("");
  const [result, setResult] = useState<HolyricsTestResult | null>(null);
  const [testing, setTesting] = useState(false);

  const detect = async () => {
    setTesting(true);
    setResult(null);
    try {
      const r = await apiGet<HolyricsTestResult>("/holyrics/detect");
      setResult(r);
      if (r.base_url) setBaseUrl(r.base_url);
    } catch (e: any) {
      setResult({ ok: false, message: e.message ?? String(e), base_url: "", latency_ms: 0 });
    } finally {
      setTesting(false);
    }
  };

  const test = async () => {
    setTesting(true);
    setResult(null);
    try {
      const r = await apiPost<HolyricsTestResult>("/holyrics/test", {
        base_url: baseUrl,
        token,
        timeout_ms: 2000,
      });
      setResult(r);
    } catch (e: any) {
      setResult({ ok: false, message: e.message ?? String(e), base_url: baseUrl, latency_ms: 0 });
    } finally {
      setTesting(false);
    }
  };

  useEffect(() => {
    detect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Etapa 2 de 5: Holyrics</h2>
      <p className="text-sm text-text-muted">
        O AI Lyrics apresenta versículos no Holyrics. Verifique se ele está
        em execução e testando a conexão.
      </p>

      <div className="grid grid-cols-1 gap-3">
        <label className="text-sm">
          <span className="text-text-muted">URL base</span>
          <input
            type="text"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-surface text-text"
          />
        </label>
        <label className="text-sm">
          <span className="text-text-muted">Token</span>
          <input
            type="text"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="Token configurado no Holyrics"
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-surface text-text"
          />
        </label>
      </div>

      <button
        onClick={test}
        disabled={testing}
        className="inline-flex items-center gap-2 px-4 py-2 bg-accent text-white rounded hover:opacity-90 disabled:opacity-50"
      >
        {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
        Testar conexão
      </button>

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
            <div className="text-sm font-medium">{result.message}</div>
            <div className="text-xs text-text-muted mt-1">
              URL: {result.base_url} · Latência: {result.latency_ms} ms
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
