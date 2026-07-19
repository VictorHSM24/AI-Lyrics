/**
 * AboutPage — tela Sobre (Sprint 14).
 *
 * Mostra: nome, versão, build, commit, frontend, backend, API,
 * arquitetura, sistema operacional, modelo STT, modelo LLM,
 * licença, links úteis, status geral.
 *
 * Dados reais do backend via useInfo() e useSystemInfo().
 */

import { Github, Globe, Heart } from "lucide-react";
import { PageLayout } from "@/app/layout";
import { Card, PropertyGrid } from "@/components";
import { HealthPanel, OperationStatusBadge } from "@/components/operational";
import { useApplication } from "@/contexts/ApplicationContext";
import { useOperationState } from "@/contexts/OperationContext";
import { useInfo, useSystemInfo } from "@/hooks";

export function AboutPage() {
  const { info: appInfo } = useApplication();
  const { operation, settings } = useOperationState();
  const { info } = useInfo();
  const { systemInfo } = useSystemInfo();
  const opState = operation?.data.state ?? "stopped";
  const opMessage = operation?.data.message ?? "";

  const ai = settings?.data.ai;
  const sttModel = ai?.whisperModel ?? "—";
  const llmModel = ai?.llmModel || "—";

  const backendVersion = info?.version ?? "—";
  const apiVersion = info
    ? `v${info.api_version.major}.${info.api_version.minor}.${info.api_version.patch}${info.api_version.pre ? `-${info.api_version.pre}` : ""}`
    : "—";
  const buildId = info?.build_id || "—";
  const commit = info?.commit || "—";
  const osName = systemInfo ? `${systemInfo.os_name} ${systemInfo.os_version}` : "—";
  const arch = systemInfo?.architecture ?? "—";
  const pythonVer = systemInfo?.python_version ?? "—";

  return (
    <PageLayout
      title="Sobre"
      description="Informações sobre o AI Lyrics."
      toolbar={
        <OperationStatusBadge state={opState} message={opMessage} />
      }
    >
      <Card title="Aplicação">
        <PropertyGrid
          properties={[
            { label: "Nome", value: appInfo.name },
            { label: "Versão", value: appInfo.version },
            { label: "Build", value: buildId },
            { label: "Commit", value: commit },
            { label: "Descrição", value: appInfo.description },
          ]}
        />
      </Card>

      <Card title="Componentes">
        <PropertyGrid
          properties={[
            { label: "Frontend", value: appInfo.version },
            { label: "Backend", value: backendVersion },
            { label: "API", value: apiVersion },
            { label: "Arquitetura", value: "Presentation Layer + Event Sourcing" },
            { label: "Sistema Operacional", value: osName },
            { label: "Arquitetura CPU", value: arch },
            { label: "Python", value: pythonVer },
          ]}
        />
      </Card>

      <Card title="Modelos de IA">
        <PropertyGrid
          properties={[
            { label: "Modelo STT", value: sttModel },
            { label: "Modelo LLM", value: llmModel },
          ]}
        />
      </Card>

      {systemInfo?.gpu_name && (
        <Card title="GPU">
          <PropertyGrid
            properties={[
              { label: "Nome", value: systemInfo.gpu_name },
              { label: "PyTorch", value: systemInfo.torch_version || "—" },
            ]}
          />
        </Card>
      )}

      <Card title="Licença">
        <p className="text-sm text-text-muted">
          Software proprietário. Todos os direitos reservados.
        </p>
      </Card>

      <Card title="Links úteis">
        <div className="flex flex-wrap gap-3">
          <a
            href="#"
            className="inline-flex items-center gap-2 text-sm text-accent hover:underline"
            onClick={(e) => e.preventDefault()}
          >
            <Github className="h-4 w-4" /> Repositório
          </a>
          <a
            href="#"
            className="inline-flex items-center gap-2 text-sm text-accent hover:underline"
            onClick={(e) => e.preventDefault()}
          >
            <Globe className="h-4 w-4" /> Documentação
          </a>
          <a
            href="#"
            className="inline-flex items-center gap-2 text-sm text-accent hover:underline"
            onClick={(e) => e.preventDefault()}
          >
            <Heart className="h-4 w-4" /> Suporte
          </a>
        </div>
      </Card>

      <Card title="Status geral" description="Saúde dos componentes do sistema.">
        <HealthPanel />
      </Card>
    </PageLayout>
  );
}
