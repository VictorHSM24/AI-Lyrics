import { Inbox } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/utils";

interface EmptyStateProps {
  title?: string;
  description?: string;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({
  title = "Nada por aqui",
  description = "Não há dados para exibir no momento.",
  icon,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 py-12 text-center",
        className,
      )}
      data-testid="empty-state"
    >
      <span className="text-text-subtle">
        {icon ?? <Inbox className="h-12 w-12" />}
      </span>
      <div className="flex flex-col gap-1">
        <h3 className="text-sm font-semibold text-text">{title}</h3>
        <p className="text-sm text-text-muted">{description}</p>
      </div>
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
