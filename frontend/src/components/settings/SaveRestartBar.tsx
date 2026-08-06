/**
 * SaveRestartBar — barra global "Salvar e Reiniciar Backend".
 *
 * Sprint 27 — Substitui o botão "Aplicar no Backend" que ficava dentro
 * do AITab. Agora é um componente GLOBAL na ConfigurationPage, fixo no
 * rodapé, para que o usuário entenda que TODAS as configurações de
 * TODAS as abas serão salvas de uma só vez antes de reiniciar.
 *
 * Fluxo:
 * 1. Calcula divergências entre localStorage (AppSettings) e backend
 *    (ConfigurationDTO) para STT, Holyrics e Áudio.
 * 2. Mostra contador de alterações pendentes na barra inferior.
 * 3. Ao clicar, abre modal listando TODAS as divergências com aviso
 *    de que o backend será reiniciado.
 * 4. Ao confirmar: PUT /configuration (persistir) + POST /system/restart.
 * 5. Overlay "Reiniciando..." com polling até o backend voltar.
 */

import { useState, useCallback, useRef, useEffect } from "react";
import { AlertTriangle, Save, RotateCw, X, CheckCircle2, Loader2 } from "lucide-react";
import { useOperationState, type AppSettings } from "@/contexts/OperationContext";
import { useConfiguration, useServices } from "@/hooks";
import type { ConfigurationDTO } from "@/types";

// ============================================================
// Mapeamento AppSettings (UI) → overrides do backend.
// ============================================================

function uiModelToBackend(uiModel: string): string {
  const map: Record<string, string> = {
    "whisper-tiny": "tiny",
    "whisper-base": "base",
    "whisper-small": "small",
    "whisper-medium": "medium",
    "whisper-large-v3": "large-v3",
    "large-v3-turbo": "large-v3-turbo",
  };
  return map[uiModel] ?? uiModel;
}

function uiDeviceToBackend(uiDevice: string): string {
  if (uiDevice === "gpu") return "cuda";
  return uiDevice;
}

interface PendingChange {
  group: string;
  field: string;
  uiValue: string;
  backendValue: string;
}

/**
 * Compara AppSettings (localStorage) com ConfigurationDTO (backend)
 * e retorna lista de divergências + o payload de overrides para enviar.
 */
function computePendingChanges(
  settings: AppSettings,
  backend: ConfigurationDTO | null,
): { changes: PendingChange[]; overrides: Record<string, unknown> } {
  const changes: PendingChange[] = [];
  const overrides: Record<string, unknown> = {};

  if (!backend) return { changes, overrides };

  const fmt = (v: unknown): string => String(v ?? "—");

  // --- STT ---
  const beStt = backend.stt as Record<string, unknown> | undefined;
  if (beStt) {
    const sttOverrides: Record<string, unknown> = {};
    const uiModel = uiModelToBackend(settings.ai.whisperModel);
    if (fmt(beStt.model) !== fmt(uiModel)) {
      changes.push({ group: "IA", field: "Modelo", uiValue: settings.ai.whisperModel, backendValue: fmt(beStt.model) });
      sttOverrides["model"] = uiModel;
    }
    if (fmt(beStt.backend) !== fmt(settings.ai.backend)) {
      changes.push({ group: "IA", field: "Backend", uiValue: settings.ai.backend, backendValue: fmt(beStt.backend) });
      sttOverrides["backend"] = settings.ai.backend;
    }
    const uiDevice = uiDeviceToBackend(settings.ai.device);
    if (fmt(beStt.device) !== fmt(uiDevice)) {
      changes.push({ group: "IA", field: "Dispositivo", uiValue: settings.ai.device, backendValue: fmt(beStt.device) });
      sttOverrides["device"] = uiDevice;
    }
    if (fmt(beStt.compute_type) !== fmt(settings.ai.computeType)) {
      changes.push({ group: "IA", field: "Compute Type", uiValue: settings.ai.computeType, backendValue: fmt(beStt.compute_type) });
      sttOverrides["compute_type"] = settings.ai.computeType;
    }
    const uiLang = settings.ai.language === "pt-BR" ? "pt" : settings.ai.language;
    if (fmt(beStt.language) !== fmt(uiLang)) {
      changes.push({ group: "IA", field: "Idioma", uiValue: settings.ai.language, backendValue: fmt(beStt.language) });
      sttOverrides["language"] = uiLang;
    }
    if (Number(beStt.cpu_threads ?? 0) !== settings.ai.threads) {
      changes.push({ group: "IA", field: "Threads", uiValue: String(settings.ai.threads), backendValue: fmt(beStt.cpu_threads) });
      sttOverrides["cpu_threads"] = settings.ai.threads;
    }
    if (Object.keys(sttOverrides).length > 0) overrides["stt"] = sttOverrides;
  }

  // --- Holyrics ---
  const beHolyrics = backend.holyrics as Record<string, unknown> | undefined;
  if (beHolyrics) {
    const holyricsOverrides: Record<string, unknown> = {};
    if (fmt(beHolyrics.base_url) !== fmt(settings.holyrics.url)) {
      changes.push({ group: "Holyrics", field: "URL", uiValue: settings.holyrics.url || "(vazio)", backendValue: fmt(beHolyrics.base_url) });
      holyricsOverrides["base_url"] = settings.holyrics.url;
    }
    if (fmt(beHolyrics.token) !== fmt(settings.holyrics.token)) {
      changes.push({ group: "Holyrics", field: "Token", uiValue: settings.holyrics.token ? "***" : "(vazio)", backendValue: beHolyrics.token ? "***" : "(vazio)" });
      holyricsOverrides["token"] = settings.holyrics.token;
    }
    if (Object.keys(holyricsOverrides).length > 0) overrides["holyrics"] = holyricsOverrides;
  }

  // --- Audio ---
  const beAudio = backend.audio as Record<string, unknown> | undefined;
  if (beAudio) {
    const audioOverrides: Record<string, unknown> = {};
    if (Number(beAudio.sample_rate ?? 0) !== settings.audio.sampleRate) {
      changes.push({ group: "Áudio", field: "Taxa de amostragem", uiValue: `${settings.audio.sampleRate} Hz`, backendValue: fmt(beAudio.sample_rate) });
      audioOverrides["sample_rate"] = settings.audio.sampleRate;
    }
    if (Number(beAudio.channels ?? 0) !== settings.audio.channels) {
      changes.push({ group: "Áudio", field: "Canais", uiValue: String(settings.audio.channels), backendValue: fmt(beAudio.channels) });
      audioOverrides["channels"] = settings.audio.channels;
    }
    if (Object.keys(audioOverrides).length > 0) overrides["audio"] = audioOverrides;
  }

  return { changes, overrides };
}

// ============================================================
// Estados do overlay de reinicialização.
// ============================================================

type RestartPhase = "idle" | "saving" | "restarting" | "polling" | "success" | "error";

// ============================================================
// Componente principal.
// ============================================================

export function SaveRestartBar() {
  const { settings } = useOperationState();
  const { configuration } = useConfiguration();
  const services = useServices();

  const [showModal, setShowModal] = useState(false);
  const [phase, setPhase] = useState<RestartPhase>("idle");
  const [restartError, setRestartError] = useState<string | null>(null);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const pending = settings?.data && configuration
    ? computePendingChanges(settings.data, configuration)
    : { changes: [], overrides: {} };

  const hasPending = pending.changes.length > 0;

  // Limpar timer ao desmontar.
  useEffect(() => {
    return () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, []);

  /**
   * Faz polling em GET /system até o backend voltar a responder.
   * Timeout de 30s.
   */
  const pollBackend = useCallback(async () => {
    const deadline = Date.now() + 30_000;
    const attempt = async () => {
      if (Date.now() > deadline) {
        setPhase("error");
        setRestartError("Timeout: o backend não voltou em 30 segundos.");
        return;
      }
      try {
        await services.system.getSystemInfo();
        setPhase("success");
        // Recarrega a configuração do backend para limpar divergências.
        setTimeout(() => window.location.reload(), 1500);
      } catch {
        // Backend ainda não voltou — tentar novamente em 1s.
        pollTimer.current = setTimeout(attempt, 1000);
      }
    };
    // Pequeno delay inicial para dar tempo do shutdown acontecer.
    pollTimer.current = setTimeout(attempt, 2000);
  }, [services]);

  /**
   * Executa o fluxo completo: salvar overrides + reiniciar backend.
   */
  const handleSaveAndRestart = useCallback(async () => {
    if (!hasPending) return;
    setShowModal(false);
    setPhase("saving");
    setRestartError(null);

    try {
      // 1. Persistir overrides no backend.
      await services.configuration.updateConfiguration(pending.overrides);
      setPhase("restarting");

      // 2. Solicitar reinício do backend.
      await services.system.restart();
      setPhase("polling");

      // 3. Polling até o backend voltar.
      pollBackend();
    } catch (e) {
      setPhase("error");
      setRestartError(e instanceof Error ? e.message : String(e));
    }
  }, [hasPending, pending.overrides, services, pollBackend]);

  // ============================================================
  // Render — Overlay de reinicialização (cobre toda a tela).
  // ============================================================

  if (phase !== "idle") {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
        <div className="flex flex-col items-center gap-4 rounded-xl border border-border bg-surface p-8 shadow-2xl">
          {phase === "saving" && (
            <>
              <Loader2 className="h-10 w-10 animate-spin text-status-processing" />
              <p className="text-sm font-medium text-text">Salvando configurações…</p>
            </>
          )}
          {phase === "restarting" && (
            <>
              <RotateCw className="h-10 w-10 animate-spin text-status-processing" />
              <p className="text-sm font-medium text-text">Reiniciando backend…</p>
              <p className="text-xs text-text-muted">O servidor está recarregando a configuração.</p>
            </>
          )}
          {phase === "polling" && (
            <>
              <Loader2 className="h-10 w-10 animate-spin text-status-processing" />
              <p className="text-sm font-medium text-text">Aguardando backend voltar…</p>
              <p className="text-xs text-text-muted">Isso pode levar alguns segundos.</p>
            </>
          )}
          {phase === "success" && (
            <>
              <CheckCircle2 className="h-10 w-10 text-status-success" />
              <p className="text-sm font-medium text-text">Backend reiniciado com sucesso!</p>
              <p className="text-xs text-text-muted">Recarregando página…</p>
            </>
          )}
          {phase === "error" && (
            <>
              <AlertTriangle className="h-10 w-10 text-status-error" />
              <p className="text-sm font-medium text-text">Erro ao reiniciar</p>
              <p className="max-w-md text-xs text-text-muted">{restartError}</p>
              <button
                type="button"
                onClick={() => { setPhase("idle"); setRestartError(null); }}
                className="mt-2 rounded-md border border-border bg-surface px-4 py-2 text-sm text-text hover:bg-surface-hover"
              >
                Fechar
              </button>
            </>
          )}
        </div>
      </div>
    );
  }

  // ============================================================
  // Render — Modal de confirmação.
  // ============================================================

  if (showModal) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
        <div className="flex max-h-[80vh] w-full max-w-lg flex-col rounded-xl border border-border bg-surface shadow-2xl">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-border px-6 py-4">
            <h2 className="text-base font-semibold text-text">Salvar e Reiniciar Backend</h2>
            <button
              type="button"
              onClick={() => setShowModal(false)}
              className="text-text-muted hover:text-text"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto px-6 py-4">
            <div className="mb-4 flex items-start gap-2 rounded-md bg-warning/10 p-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warning" />
              <div className="text-sm text-text">
                <p className="font-medium">As seguintes configurações serão aplicadas:</p>
                <p className="mt-1 text-xs text-text-muted">
                  O backend será reiniciado imediatamente após salvar.
                  Transcrições em andamento serão interrompidas.
                </p>
              </div>
            </div>

            <div className="flex flex-col gap-2">
              {pending.changes.map((c, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between rounded-md border border-border bg-bg px-3 py-2 text-sm"
                >
                  <div className="flex flex-col">
                    <span className="text-xs font-medium text-text-muted">{c.group} · {c.field}</span>
                    <span className="text-text">
                      <span className="text-status-processing">{c.uiValue}</span>
                      {" → substitui → "}
                      <span className="text-text-muted line-through">{c.backendValue}</span>
                    </span>
                  </div>
                </div>
              ))}
            </div>

            <p className="mt-4 rounded-md bg-surface-hover p-3 text-xs text-text-muted">
              Dica: você pode revisar configurações em outras abas antes de confirmar.
              Todas as alterações de todas as abas serão salvas de uma vez.
            </p>
          </div>

          {/* Footer */}
          <div className="flex justify-end gap-2 border-t border-border px-6 py-4">
            <button
              type="button"
              onClick={() => setShowModal(false)}
              className="rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-text hover:bg-surface-hover"
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={handleSaveAndRestart}
              className="inline-flex items-center gap-2 rounded-md bg-status-processing px-4 py-2 text-sm font-medium text-white hover:opacity-90"
            >
              <RotateCw className="h-4 w-4" />
              Salvar e Reiniciar
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ============================================================
  // Render — Barra inferior fixa.
  // ============================================================

  if (!settings?.data) return null;

  return (
    <div
      className="sticky bottom-0 z-30 mt-4 flex items-center justify-between rounded-lg border border-border bg-surface/95 px-4 py-3 shadow-lg backdrop-blur"
      data-testid="save-restart-bar"
    >
      <div className="flex items-center gap-2 text-sm">
        {hasPending ? (
          <>
            <AlertTriangle className="h-4 w-4 text-warning" />
            <span className="text-text">
              <strong>{pending.changes.length}</strong> alteraç{pending.changes.length !== 1 ? "ões" : ""} não aplicada{pending.changes.length !== 1 ? "s" : ""} ao backend
            </span>
          </>
        ) : (
          <>
            <CheckCircle2 className="h-4 w-4 text-status-success" />
            <span className="text-text-muted">Todas as configurações estão em dia com o backend</span>
          </>
        )}
      </div>

      <button
        type="button"
        onClick={() => setShowModal(true)}
        disabled={!hasPending}
        className="inline-flex items-center gap-2 rounded-md bg-status-processing px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        data-testid="save-restart-btn"
      >
        <Save className="h-4 w-4" />
        Salvar e Reiniciar Backend
      </button>
    </div>
  );
}
