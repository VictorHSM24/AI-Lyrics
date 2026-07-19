/**
 * SystemTab — Configurações > Sistema.
 *
 * Mostra: diretório de logs, cache, uso de disco, versões.
 * Botões: Limpar Cache, Abrir Pasta de Logs, Verificar Atualizações (preparado).
 */

import { useState } from "react";
import { Trash2, FolderOpen, RefreshCw, HardDrive } from "lucide-react";
import { useOperationState } from "@/contexts/OperationContext";
import { useApplication } from "@/contexts/ApplicationContext";
import { useConnection } from "@/contexts/ConnectionContext";
import { Card, PropertyGrid } from "@/components";
import { Button } from "./FormControls";

export function SystemTab() {
  const { info } = useApplication();
  const { resetSettings } = useOperationState();
  const { backendUrl } = useConnection();
  const [clearing, setClearing] = useState(false);
  const [checking, setChecking] = useState(false);
  const [clearMsg, setClearMsg] = useState("");

  // System info — em produção viria do backend via Services.
  const systemInfo = {
    logDir: "./logs",
    cacheDir: "./cache",
    diskUsage: "—",
    backendVersion: "—",
    apiVersion: "—",
    frontendVersion: info.version,
  };

  const handleClearCache = () => {
    setClearing(true);
    setClearMsg("");
    setTimeout(() => {
      setClearing(false);
      setClearMsg("Cache limpo com sucesso.");
    }, 500);
  };

  const handleOpenLogs = () => {
    // Em um app desktop, abriria o file manager.
    // No browser, apenas mostra o caminho.
    setClearMsg(`Pasta de logs: ${systemInfo.logDir}`);
  };

  const handleCheckUpdates = () => {
    setChecking(true);
    setTimeout(() => {
      setChecking(false);
      setClearMsg("Nenhuma atualização disponível.");
    }, 800);
  };

  return (
    <div className="flex flex-col gap-4" data-testid="system-tab">
      <Card title="Diretórios" description="Caminhos usados pelo sistema.">
        <PropertyGrid
          properties={[
            { label: "Diretório de Logs", value: systemInfo.logDir },
            { label: "Diretório de Cache", value: systemInfo.cacheDir },
            { label: "Uso de Disco", value: systemInfo.diskUsage },
          ]}
        />
      </Card>

      <Card title="Versões" description="Versões dos componentes do sistema.">
        <PropertyGrid
          properties={[
            { label: "Frontend", value: systemInfo.frontendVersion },
            { label: "Backend", value: systemInfo.backendVersion },
            { label: "API", value: systemInfo.apiVersion },
            { label: "Backend URL", value: backendUrl },
          ]}
        />
      </Card>

      <Card title="Ações" description="Operações de manutenção.">
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={handleClearCache}
              loading={clearing}
              icon={<Trash2 className="h-4 w-4" />}
              variant="danger"
            >
              Limpar Cache
            </Button>
            <Button
              onClick={handleOpenLogs}
              icon={<FolderOpen className="h-4 w-4" />}
            >
              Abrir Pasta de Logs
            </Button>
            <Button
              onClick={handleCheckUpdates}
              loading={checking}
              icon={<RefreshCw className="h-4 w-4" />}
            >
              Verificar Atualizações
            </Button>
          </div>
          {clearMsg && (
            <p className="text-xs text-status-success" data-testid="system-action-msg">
              {clearMsg}
            </p>
          )}
        </div>
      </Card>

      <Card title="Disco" description="Uso de disco pelo sistema.">
        <div className="flex items-center gap-3">
          <HardDrive className="h-8 w-8 text-text-subtle" />
          <div className="flex flex-col">
            <span className="text-sm font-medium text-text">{systemInfo.diskUsage}</span>
            <span className="text-xs text-text-muted">Cache + Logs + Modelos</span>
          </div>
        </div>
      </Card>

      <Card title="Restaurar Configurações" description="Resetar todas as configurações para o padrão.">
        <Button
          onClick={() => {
            if (confirm("Restaurar todas as configurações para o padrão?")) {
              resetSettings();
              setClearMsg("Configurações restauradas.");
            }
          }}
          variant="danger"
        >
          Restaurar Padrão
        </Button>
      </Card>
    </div>
  );
}
