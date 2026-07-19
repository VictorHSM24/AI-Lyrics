import type { ReactNode } from "react";
import { cn } from "@/utils";

interface CardProps {
  children: ReactNode;
  className?: string;
  title?: string;
  description?: string;
  actions?: ReactNode;
}

export function Card({ children, className, title, description, actions }: CardProps) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-surface-raised p-4",
        className,
      )}
      data-testid="card"
    >
      {(title || actions) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          <div className="flex flex-col gap-0.5">
            {title && (
              <h3 className="text-sm font-semibold text-text">{title}</h3>
            )}
            {description && (
              <p className="text-xs text-text-muted">{description}</p>
            )}
          </div>
          {actions && <div className="flex items-center gap-1">{actions}</div>}
        </div>
      )}
      {children}
    </div>
  );
}
