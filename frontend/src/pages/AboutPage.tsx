import { PageLayout } from "@/app/layout";
import { Card, PropertyGrid } from "@/components";
import { useApplication } from "@/contexts/ApplicationContext";

export function AboutPage() {
  const { info } = useApplication();

  return (
    <PageLayout
      title="Sobre"
      description="Informações sobre o AI Lyrics."
    >
      <Card title="Aplicação">
        <PropertyGrid
          properties={[
            { label: "Nome", value: info.name },
            { label: "Versão", value: info.version },
            { label: "Descrição", value: info.description },
          ]}
        />
      </Card>
      <Card title="Arquitetura">
        <p className="text-sm text-text-muted">
          A interface web do AI Lyrics é completamente desacoplada do Core.
          Toda comunicação ocorre exclusivamente através da Presentation Layer,
          que expõe DTOs imutáveis via Services e Adapters.
        </p>
      </Card>
    </PageLayout>
  );
}
