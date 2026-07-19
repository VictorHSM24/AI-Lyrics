import type { ReactNode } from "react";
import { PageContainer } from "@/components";
import { Toolbar } from "@/components";

interface PageHeaderProps {
  title: string;
  description?: string;
  toolbar?: ReactNode;
}

export function PageHeader({ title, description, toolbar }: PageHeaderProps) {
  return (
    <div className="flex flex-col gap-3" data-testid="page-header">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold text-text">{title}</h1>
        {description && (
          <p className="text-sm text-text-muted">{description}</p>
        )}
      </div>
      {toolbar && <Toolbar>{toolbar}</Toolbar>}
    </div>
  );
}

interface PageLayoutProps {
  title: string;
  description?: string;
  toolbar?: ReactNode;
  children: ReactNode;
}

/**
 * Layout padrão que toda página deve seguir.
 *
 * Estrutura: Título → Descrição → Toolbar → Conteúdo.
 */
export function PageLayout({
  title,
  description,
  toolbar,
  children,
}: PageLayoutProps) {
  return (
    <PageContainer>
      <PageHeader title={title} description={description} toolbar={toolbar} />
      <div className="flex flex-col gap-6" data-testid="page-content">
        {children}
      </div>
    </PageContainer>
  );
}
