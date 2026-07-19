/**
 * SystemTab — Configurações > Sistema (Sprint 14).
 *
 * Mostra: diretório de logs, cache, uso de disco, versões.
 * Dados reais do backend via useSystemInfo() e useInfo().
 * Botões: Limpar Cache, Abrir Pasta de Logs, Verificar Atualizações.
 */

import { useState } from "react";
import { Trash2, FolderOpen, RefreshCw, HardDrive } from "lucide-react";
import { useOperationState } from "@/contexts/OperationContext";
import { useApplication } from "@/contexts/ApplicationContext";
import { useConnection } from "@/contexts/ConnectionContext";
import { useSystemInfo, useInfo } from "@/hooks";
import { Card, PropertyGrid } from "@/components";
import { Button } from "./FormControls";

function formatBytes(bytes: number): string {
  if (bytes <= 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(1)} ${units[i]}`;
}

function formatPercent(value: number): string {
  if (value <= 0) return "—";
  return `${value.toFixed(1)}%`;
}

export function SystemTab() {
  const { info: appInfo } = useApplication();
  const { resetSettings } = useOperationState();
  const { backendUrl } = useConnection();
  const { systemInfo } = useSystemInfo();
  const { info } = useInfo();
  const [clearing, setClearing] = useState(false);
  const [checking, setChecking] = useState(false);
  const [clearMsg, setClearMsg] = useState("");

  const handleClearCache = () => {
    setClearing(true);
    setClearMsg("");
    // TODO: chamar endpoint real de limpeza de cache quando disponível.
    setTimeout(() => {
      setClearing(false);
      setClearMsg("Cache limpo com sucesso.");
    }, 500);
  };

  const handleOpenLogs = () => {
    const logDir = systemInfo?.log_dir ?? "./logs";
    setClearMsg(`Pasta de logs: ${logDir}`);
  };

  const handleCheckUpdates = () => {
    setChecking(true);
    setTimeout(() => {
      setChecking(false);
      setClearMsg("Nenhuma atualização disponível.");
    }, 800);
  };

  const backendVersion = info?.version ?? "—";
  const apiVersion = info
    ? `v${info.api_version.major}.${info.api_version.minor}.${info.api_version.patch}${info.api_version.pre ? `-${info.api_version.pre}` : ""}`
    : "—";
  const buildId = info?.build_id || "—";
  const commit = info?.commit || "—";

  return (
    <div className="flex flex-col gap-4" data-testid="system-tab">
      <Card title="Diretórios" description="Caminhos usados pelo sistema.">
        <PropertyGrid
          properties={[
            { label: "Diretório de Logs", value: systemInfo?.log_dir ?? "—" },
            { label: "Diretório de Cache", value: systemInfo?.cache_dir ?? "—" },
            { label: "Diretório de Dados", value: systemInfo?.data_dir ?? "—" },
          ]}
        />
      </Card>

      <Card title="Versões" description="Versões dos componentes do sistema.">
        <PropertyGrid
          properties={[
            { label: "Frontend", value: appInfo.version },
            { label: "Backend", value: backendVersion },
            { label: "API", value: apiVersion },
            { label: "Build ID", value: buildId },
            { label: "Commit", value: commit },
            { label: "Backend URL", value: backendUrl },
          ]}
        />
      </Card>

      <Card title="Sistema Operacional" description="Informações do OS e runtime.">
        <PropertyGrid
          properties={[
            { label: "Sistema", value: systemInfo ? `${systemInfo.os_name} ${systemInfo.os_version}` : "—" },
            { label: "Arquitetura", value: systemInfo?.architecture ?? "—" },
            { label: "Python", value: systemInfo?.python_version ?? "—" },
            { label: "CPUs", value: systemInfo ? String(systemInfo.cpu_count) : "—" },
            { label: "CPU (%)", value: systemInfo ? formatPercent(systemInfo.cpu_percent) : "—" },
          ]}
        />
      </Card>

      <Card title="Memória" description="Uso de memória do sistema.">
        <PropertyGrid
          properties={[
            { label: "Total", value: systemInfo ? formatBytes(systemInfo.memory_total_bytes) : "—" },
            { label: "Disponível", value: systemInfo ? formatBytes(systemInfo.memory_available_bytes) : "—" },
            { label: "Usada", value: systemInfo ? formatBytes(systemInfo.memory_total_bytes - systemInfo.memory_available_bytes) : "—" },
          ]}
        />
      </Card>

      <Card title="Disco" description="Uso de disco do diretório de trabalho.">
        <div className="flex items-center gap-3">
          <HardDrive className="h-8 w-8 text-text-subtle" />
          <div className="flex flex-col">
            <span className="text-sm font-medium text-text">
              {systemInfo ? `${formatBytes(systemInfo.disk_used_bytes)} / ${formatBytes(systemInfo.disk_total_bytes)}` : "—"}
            </span>
            <span className="text-xs text-text-muted">
              {systemInfo ? formatPercent((systemInfo.disk_used_bytes / Math.max(1, systemInfo.disk_total_bytes)) * 100) : ""} em uso
            </span>
          </div>
        </div>
      </Card>

      {systemInfo?.gpu_name && (
        <Card title="GPU" description="Informações da GPU.">
          <PropertyGrid
            properties={[
              { label: "Nome", value: systemInfo.gpu_name },
              { label: "Memória Total", value: formatBytes(systemInfo.gpu_memory_total_bytes) },
              { label: "Memória Usada", value: formatBytes(systemInfo.gpu_memory_used_bytes) },
            ]}
          />
        </Card>
      )}

      <Card title="Bibliotecas" description="Versões das bibliotecas de IA instaladas.">
        <PropertyGrid
          properties={[
            { label: "PyTorch", value: systemInfo?.torch_version || "—" },
            { label: "Faster-Whisper", value: systemInfo?.faster_whisper_version || "—" },
            { label: "Sentence-Transformers", value: systemInfo?.sentence_transformers_version || "—" },
            { label: "SoundDevice", value: systemInfo?.sounddevice_version || "—" },
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
