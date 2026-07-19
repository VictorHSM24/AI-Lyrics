/**
 * HolyricsTab — Configurações > Holyrics.
 *
 * Permite configurar: URL, Token, Versão, Quick Presentation.
 * Botão: Testar conexão (chamada real ao backend).
 * Exibe: Conectado, Desconectado, Erro, Tempo de resposta.
 */

import { useState } from "react";
import { Church, Plug, CheckCircle2, XCircle, Clock } from "lucide-react";
import { useOperationState } from "@/contexts/OperationContext";
import { useServicesHook } from "@/hooks";
import { Card } from "@/components";
import { TextField, Toggle, Button } from "./FormControls";
import { cn } from "@/utils";

type TestState = "idle" | "testing" | "connected" | "error";

interface TestResult {
  state: TestState;
  message: string;
  responseTimeMs?: number;
}

export function HolyricsTab() {
  const { settings, updateSettings } = useOperationState();
  const services = useServicesHook();
  const [test, setTest] = useState<TestResult>({ state: "idle", message: "" });

  const holyrics = settings?.data.holyrics;

  const handleTest = async () => {
    if (!holyrics?.url) {
      setTest({ state: "error", message: "URL não configurada." });
      return;
    }
    setTest({ state: "testing", message: "Testando…" });
    const start = Date.now();
    try {
      // Chamada real ao backend — POST /health/holyrics/test
      // O backend faz uma chamada real à API Holyrics com timeout 2s.
      const result = await services.health.testHolyrics({
        base_url: holyrics.url,
        token: holyrics.token || "",
      });
      const elapsed = Date.now() - start;
      if (result.ok) {
        setTest({
          state: "connected",
          message: result.message || "Conexão bem-sucedida.",
          responseTimeMs: elapsed,
        });
      } else {
        setTest({
          state: "error",
          message: result.message || "Falha na conexão.",
          responseTimeMs: elapsed,
        });
      }
    } catch (err) {
      const elapsed = Date.now() - start;
      setTest({
        state: "error",
        message: err instanceof Error ? err.message : "Falha na conexão.",
        responseTimeMs: elapsed,
      });
    }
  };

  if (!holyrics) {
    return (
      <Card title="Holyrics">
        <p className="text-sm text-text-muted">Carregando configurações…</p>
      </Card>
    );
  }

  const testColor =
    test.state === "connected"
      ? "text-status-success"
      : test.state === "error"
        ? "text-status-error"
        : test.state === "testing"
          ? "text-status-processing"
          : "text-text-muted";

  return (
    <div className="flex flex-col gap-4" data-testid="holyrics-tab">
      <Card
        title="Conexão"
        description="Configuração da integração com Holyrics."
        actions={
          <Button
            onClick={handleTest}
            loading={test.state === "testing"}
            icon={<Plug className="h-4 w-4" />}
          >
            Testar conexão
          </Button>
        }
      >
        <div className="flex flex-col gap-4">
          <TextField
            label="URL"
            description="Endereço do servidor Holyrics."
            tooltip="Inclua o protocolo (http:// ou https://) e a porta."
            value={holyrics.url}
            placeholder="http://localhost:8091/api"
            onChange={(value) =>
              updateSettings((prev) => ({
                ...prev,
                holyrics: { ...prev.holyrics, url: value },
              }))
            }
          />

          <TextField
            label="Token"
            description="Token de autenticação (se necessário)."
            tooltip="Token gerado pelo Holyrics. Deixe vazio se não usar autenticação."
            type="password"
            value={holyrics.token}
            placeholder="—"
            onChange={(value) =>
              updateSettings((prev) => ({
                ...prev,
                holyrics: { ...prev.holyrics, token: value },
              }))
            }
          />

          <TextField
            label="Versão"
            description="Versão do Holyrics (preenchida automaticamente após conectar)."
            value={holyrics.version}
            placeholder="—"
            onChange={(value) =>
              updateSettings((prev) => ({
                ...prev,
                holyrics: { ...prev.holyrics, version: value },
              }))
            }
          />

          <Toggle
            label="Quick Presentation"
            description="Apresentar versículos imediatamente ao encontrar."
            tooltip="Quando ativado, o versículo é enviado para a projeção sem confirmação."
            checked={holyrics.quickPresentation}
            onChange={(checked) =>
              updateSettings((prev) => ({
                ...prev,
                holyrics: { ...prev.holyrics, quickPresentation: checked },
              }))
            }
          />
        </div>
      </Card>

      <Card title="Status da conexão">
        {test.state === "idle" ? (
          <p className="text-sm text-text-muted">
            Clique em "Testar conexão" para verificar.
          </p>
        ) : (
          <div className="flex flex-col gap-2" data-testid="holyrics-test-result">
            <div className={cn("flex items-center gap-2", testColor)}>
              {test.state === "connected" && <CheckCircle2 className="h-4 w-4" />}
              {test.state === "error" && <XCircle className="h-4 w-4" />}
              {test.state === "testing" && <Clock className="h-4 w-4 animate-pulse" />}
              <span className="text-sm font-medium">
                {test.state === "connected"
                  ? "Conectado"
                  : test.state === "error"
                    ? "Erro"
                    : test.state === "testing"
                      ? "Testando…"
                      : "Desconectado"}
              </span>
            </div>
            <p className="text-xs text-text-muted">{test.message}</p>
            {test.responseTimeMs !== undefined && (
              <p className="text-xs text-text-subtle">
                Tempo de resposta: {test.responseTimeMs}ms
              </p>
            )}
          </div>
        )}
      </Card>

      <Card title="Resumo">
        <div className="flex flex-wrap gap-3 text-xs text-text-muted">
          <span className="inline-flex items-center gap-1">
            <Church className="h-3.5 w-3.5" /> {holyrics.url || "Não configurado"}
          </span>
          <span>Quick: {holyrics.quickPresentation ? "Sim" : "Não"}</span>
        </div>
      </Card>
    </div>
  );
}
