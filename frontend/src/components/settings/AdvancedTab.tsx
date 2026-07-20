/**
 * AdvancedTab — Configurações > Avançado.
 *
 * Apenas expõe configurações existentes do backend (ConfigurationDTO).
 * NÃO cria novas configurações.
 */

import { useConfiguration } from "@/hooks";
import { Card, PropertyGrid, EmptyState } from "@/components";
import { Settings } from "lucide-react";

export function AdvancedTab() {
  const { configuration, loading } = useConfiguration();

  if (loading) {
    return (
      <Card title="Avançado">
        <p className="text-sm text-text-muted">Carregando configuração do backend…</p>
      </Card>
    );
  }

  if (!configuration) {
    return (
      <Card title="Avançado">
        <EmptyState
          title="Sem configuração do backend"
          description="Conecte ao backend para visualizar configurações avançadas."
          icon={<Settings className="h-12 w-12" />}
        />
      </Card>
    );
  }

  // Expõe APENAS as configurações existentes — não cria novas.
  const flatProps: Array<{ label: string; value: string | number | boolean | null }> = [];
  flatProps.push({ label: "mode", value: configuration.mode });

  const flatten = (obj: Record<string, unknown>, prefix: string) => {
    for (const [key, value] of Object.entries(obj)) {
      const fullKey = `${prefix}.${key}`;
      if (value && typeof value === "object" && !Array.isArray(value)) {
        flatten(value as Record<string, unknown>, fullKey);
      } else {
        flatProps.push({
          label: fullKey,
          value: value as string | number | boolean | null,
        });
      }
    }
  };

  // Sprint 17.5.1 — Expõe TODOS os grupos da ConfigurationDTO, não apenas
  // holyrics e stt. Cada grupo é flattado recursivamente para exibir
  // every.key.path = value.
  if (configuration.holyrics) {
    flatten(configuration.holyrics as Record<string, unknown>, "holyrics");
  }
  if (configuration.stt) {
    flatten(configuration.stt as Record<string, unknown>, "stt");
  }
  if (configuration.llm) {
    flatten(configuration.llm as Record<string, unknown>, "llm");
  }
  if (configuration.search) {
    flatten(configuration.search as Record<string, unknown>, "search");
  }
  if (configuration.state) {
    flatten(configuration.state as Record<string, unknown>, "state");
  }
  if (configuration.cache) {
    flatten(configuration.cache as Record<string, unknown>, "cache");
  }
  if (configuration.confidence) {
    flatten(configuration.confidence as Record<string, unknown>, "confidence");
  }
  if (configuration.log) {
    flatten(configuration.log as Record<string, unknown>, "log");
  }
  if (configuration.audio) {
    flatten(configuration.audio as Record<string, unknown>, "audio");
  }
  if (configuration.pipeline_policy) {
    flatten(configuration.pipeline_policy as Record<string, unknown>, "pipeline_policy");
  }

  return (
    <div className="flex flex-col gap-4" data-testid="advanced-tab">
      <Card
        title="Configuração do Backend"
        description="Configurações expostas pelo backend (somente leitura)."
      >
        <PropertyGrid properties={flatProps} columns={1} />
      </Card>
    </div>
  );
}
