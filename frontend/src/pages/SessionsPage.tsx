/**
 * SessionsPage — Gravação de auditoria do pipeline.
 *
 * Tela para iniciar/parar a gravação do resultado do pipeline em
 * arquivos locais (detalhados o suficiente para auditoria completa,
 * inclusive de erros):
 *
 *   <output_dir>/gravacao_<timestamp>/
 *     events.jsonl    — todos os eventos operacionais do EventBus
 *     errors.jsonl    — eventos de erro + registros de log ERROR+
 *     telemetry.jsonl — eventos de telemetria (alta frequência)
 *     summary.json    — índice da auditoria (duração, contagens, erros)
 *
 * O diretório de saída é personalizável e persistido no backend
 * (default: ~/Documents/AI-Lyrics/gravacoes).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Circle,
  Square,
  FolderOpen,
  History,
  AlertTriangle,
  FileText,
} from "lucide-react";
import { PageLayout } from "@/app/layout";
import { Card, PropertyGrid } from "@/components";
import { ConnectionIndicator } from "@/components/feedback/ConnectionIndicator";
import { Button } from "@/components/settings/FormControls";
import { useServices } from "@/contexts/InfraContext";
import type {
  RecordingEntryDTO,
  RecordingStatusDTO,
} from "@/types";

function formatElapsed(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(ss)}` : `${pad(m)}:${pad(ss)}`;
}

function formatStartedAt(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("pt-BR");
}

const POLL_MS = 2000;

export function SessionsPage() {
  const services = useServices();
  const [status, setStatus] = useState<RecordingStatusDTO | null>(null);
  const [recordings, setRecordings] = useState<RecordingEntryDTO[]>([]);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const mountedRef = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const [st, list] = await Promise.all([
        services.recording.getStatus(),
        services.recording.list(20),
      ]);
      if (!mountedRef.current) return;
      setStatus(st);
      setRecordings(list.recordings);
    } catch (e) {
      if (!mountedRef.current) return;
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [services]);

  // Carga inicial + polling enquanto grava.
  useEffect(() => {
    mountedRef.current = true;
    refresh();
    return () => {
      mountedRef.current = false;
    };
  }, [refresh]);

  useEffect(() => {
    if (!status?.recording) return;
    const t = setInterval(refresh, POLL_MS);
    return () => clearInterval(t);
  }, [status?.recording, refresh]);

  const handleStart = async () => {
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      const st = await services.recording.start({ label: label.trim() });
      setStatus(st);
      setNotice(`Gravando em ${st.session_dir}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleStop = async () => {
    setBusy(true);
    setError(null);
    try {
      const st = await services.recording.stop();
      setStatus(st);
      const summary = st.last_summary as { session_dir?: string } | null;
      setNotice(
        summary?.session_dir
          ? `Gravação salva em ${summary.session_dir}`
          : "Gravação finalizada.",
      );
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleBrowseDir = async () => {
    setBrowsing(true);
    setError(null);
    setNotice("");
    try {
      // Seletor nativo do Windows aberto pelo backend — o caminho
      // escolhido já é aplicado e persistido em seguida.
      const res = await services.recording.browse();
      if (res.cancelled || !res.path) return;
      const st = await services.recording.setOutputDir(res.path);
      setStatus(st);
      setNotice(`Pasta de gravação definida: ${st.output_dir}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBrowsing(false);
    }
  };

  const recording = status?.recording ?? false;

  return (
    <PageLayout
      title="Sessões"
      description="Gravação do resultado do pipeline para auditoria completa, inclusive de erros."
    >
      <div className="mb-4">
        <ConnectionIndicator />
      </div>

      {error && (
        <div
          className="mb-4 flex items-center gap-2 rounded-md border border-status-error/40 bg-status-error/10 px-3 py-2 text-sm text-status-error"
          role="alert"
        >
          <AlertTriangle className="h-4 w-4 flex-shrink-0" />
          {error}
        </div>
      )}
      {notice && !error && (
        <p className="mb-4 text-xs text-status-success">{notice}</p>
      )}

      <div className="flex flex-col gap-4">
        <Card
          title="Gravação do pipeline"
          description="Registra todos os eventos do pipeline (transcrição, detecção de referências, apresentações e erros) em arquivos JSONL para auditoria."
        >
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3">
              <span
                className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold ${
                  recording
                    ? "bg-status-error/15 text-status-error"
                    : "bg-surface-hover text-text-muted"
                }`}
                data-testid="recording-status-badge"
              >
                <Circle
                  className={`h-2.5 w-2.5 ${recording ? "fill-status-error animate-pulse" : ""}`}
                />
                {recording ? "GRAVANDO" : "PARADO"}
              </span>
              {recording && (
                <span className="font-mono text-lg text-text" data-testid="recording-elapsed">
                  {formatElapsed(status?.elapsed_s ?? 0)}
                </span>
              )}
            </div>

            <PropertyGrid
              properties={[
                {
                  label: "Eventos gravados",
                  value: String(status?.events_count ?? 0),
                },
                {
                  label: "Eventos de telemetria",
                  value: String(status?.telemetry_count ?? 0),
                },
                {
                  label: "Erros capturados",
                  value: String(status?.errors_count ?? 0),
                },
                {
                  label: "Pasta da gravação",
                  value: status?.session_dir ?? "—",
                },
              ]}
            />

            {status?.last_error && (
              <p className="rounded-md bg-status-error/10 px-3 py-2 text-xs text-status-error">
                Último erro: {status.last_error}
              </p>
            )}

            <div className="flex flex-col gap-2">
              <label htmlFor="recording-label" className="text-xs text-text-muted">
                Rótulo da gravação (opcional — ex.: "culto de domingo")
              </label>
              <input
                id="recording-label"
                type="text"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                disabled={recording}
                placeholder="Sem rótulo"
                className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-text placeholder:text-text-subtle focus:border-accent focus:outline-none disabled:opacity-50"
              />
            </div>

            <div className="flex flex-wrap gap-2">
              {!recording ? (
                <Button
                  onClick={handleStart}
                  loading={busy}
                  icon={<Circle className="h-4 w-4 fill-current" />}
                  variant="primary"
                  data-testid="recording-start-btn"
                >
                  Iniciar gravação
                </Button>
              ) : (
                <Button
                  onClick={handleStop}
                  loading={busy}
                  icon={<Square className="h-4 w-4 fill-current" />}
                  variant="danger"
                  data-testid="recording-stop-btn"
                >
                  Parar e salvar
                </Button>
              )}
            </div>
          </div>
        </Card>

        <Card
          title="Pasta de destino"
          description="Onde as gravações são salvas. O padrão é a pasta Documents do usuário."
        >
          <div className="flex flex-col gap-3">
            <PropertyGrid
              properties={[
                { label: "Pasta atual", value: status?.output_dir ?? "—" },
                { label: "Pasta padrão", value: status?.default_dir ?? "—" },
              ]}
            />
            <div className="flex flex-wrap items-center gap-2">
              <Button
                onClick={handleBrowseDir}
                loading={browsing}
                disabled={recording}
                icon={<FolderOpen className="h-4 w-4" />}
                data-testid="recording-browse-dir-btn"
              >
                Selecionar pasta…
              </Button>
            </div>
            {recording && (
              <p className="text-xs text-text-muted">
                A pasta não pode ser alterada durante uma gravação.
              </p>
            )}
          </div>
        </Card>

        <Card
          title="Gravações anteriores"
          description="Sessões de auditoria salvas (mais recentes primeiro)."
          actions={<History className="h-4 w-4 text-text-subtle" />}
        >
          {recordings.length === 0 ? (
            <p className="text-sm text-text-muted">
              Nenhuma gravação encontrada na pasta de destino.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-border text-xs text-text-muted">
                    <th className="pb-2 pr-4 font-medium">Sessão</th>
                    <th className="pb-2 pr-4 font-medium">Início</th>
                    <th className="pb-2 pr-4 font-medium">Duração</th>
                    <th className="pb-2 pr-4 font-medium">Eventos</th>
                    <th className="pb-2 pr-4 font-medium">Erros</th>
                    <th className="pb-2 font-medium">Arquivos</th>
                  </tr>
                </thead>
                <tbody>
                  {recordings.map((r) => (
                    <tr
                      key={r.name}
                      className="border-b border-border/50 last:border-0"
                    >
                      <td className="py-2 pr-4">
                        <div className="flex flex-col">
                          <span className="font-medium text-text">
                            {r.label || r.name}
                          </span>
                          {r.label && (
                            <span className="text-xs text-text-subtle">{r.name}</span>
                          )}
                        </div>
                      </td>
                      <td className="py-2 pr-4 text-text-muted">
                        {formatStartedAt(r.started_at)}
                      </td>
                      <td className="py-2 pr-4 text-text-muted">
                        {formatElapsed(r.duration_s)}
                      </td>
                      <td className="py-2 pr-4 text-text-muted">{r.events_count}</td>
                      <td
                        className={`py-2 pr-4 ${
                          r.errors_count > 0 ? "text-status-error" : "text-text-muted"
                        }`}
                      >
                        {r.errors_count}
                      </td>
                      <td className="py-2 text-text-muted">
                        <span
                          className="inline-flex items-center gap-1 text-xs"
                          title={r.path}
                        >
                          <FileText className="h-3.5 w-3.5" />
                          {r.has_summary ? "summary.json" : "incompleta"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </PageLayout>
  );
}
