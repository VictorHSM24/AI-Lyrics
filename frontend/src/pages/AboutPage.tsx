/**
 * AboutPage — tela Sobre.
 *
 * Mostra: nome, versão, build, commit, frontend, backend, API,
 * arquitetura, sistema operacional, modelo STT, modelo LLM,
 * licença, links úteis, status geral.
 */

import { Github, Globe, Heart } from "lucide-react";
import { PageLayout } from "@/app/layout";
import { Card, PropertyGrid } from "@/components";
import { HealthPanel, OperationStatusBadge } from "@/components/operational";
import { useApplication } from "@/contexts/ApplicationContext";
import { useOperationState } from "@/contexts/OperationContext";

export function AboutPage() {
  const { info } = useApplication();
  const { operation, settings } = useOperationState();
  const opState = operation?.data.state ?? "stopped";
  const opMessage = operation?.data.message ?? "";

  const ai = settings?.data.ai;
  const sttModel = ai?.whisperModel ?? "—";
  const llmModel = ai?.llmModel || "—";

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
            { label: "Nome", value: info.name },
            { label: "Versão", value: info.version },
            { label: "Build", value: "—" },
            { label: "Commit", value: "—" },
            { label: "Descrição", value: info.description },
          ]}
        />
      </Card>

      <Card title="Componentes">
        <PropertyGrid
          properties={[
            { label: "Frontend", value: info.version },
            { label: "Backend", value: "—" },
            { label: "API", value: "v1" },
            { label: "Arquitetura", value: "Presentation Layer + Event Sourcing" },
            { label: "Sistema Operacional", value: navigator.platform || "—" },
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
