import type { ReactNode } from "react";
import { PageLayout } from "@/app/layout";
import { EmptyState } from "@/components";
import { ConnectionIndicator } from "@/components/feedback/ConnectionIndicator";

interface DevelopmentPageProps {
  title: string;
  description: string;
  toolbar?: ReactNode;
}

/**
 * Página padrão para módulos ainda em desenvolvimento.
 *
 * Todas as páginas seguem o mesmo padrão visual:
 * Título → Descrição → Toolbar → Conteúdo.
 *
 * Mostra indicadores reais de infraestrutura (conexão com backend)
 * mas nenhuma funcionalidade de negócio.
 */
export function DevelopmentPage({
  title,
  description,
  toolbar,
}: DevelopmentPageProps) {
  return (
    <PageLayout title={title} description={description} toolbar={toolbar}>
      <div className="mb-4">
        <ConnectionIndicator />
      </div>
      <EmptyState
        title="Em desenvolvimento"
        description="Esta página faz parte da infraestrutura preparatória. Funcionalidades serão adicionadas em fases futuras."
      />
    </PageLayout>
  );
}
