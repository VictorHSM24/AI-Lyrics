import { AlertCircle } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/utils";

interface ErrorStateProps {
  title?: string;
  message?: string;
  action?: ReactNode;
  className?: string;
}

export function ErrorState({
  title = "Erro",
  message = "Ocorreu um erro ao carregar os dados.",
  action,
  className,
}: ErrorStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 py-12 text-center",
        className,
      )}
      data-testid="error-state"
      role="alert"
    >
      <AlertCircle className="h-12 w-12 text-status-error" />
      <div className="flex flex-col gap-1">
        <h3 className="text-sm font-semibold text-text">{title}</h3>
        <p className="text-sm text-text-muted">{message}</p>
      </div>
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
