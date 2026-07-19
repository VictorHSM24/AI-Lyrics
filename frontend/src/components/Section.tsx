import type { ReactNode } from "react";
import { cn } from "@/utils";

interface SectionProps {
  title?: string;
  description?: string;
  children: ReactNode;
  className?: string;
  actions?: ReactNode;
}

export function Section({
  title,
  description,
  children,
  className,
  actions,
}: SectionProps) {
  return (
    <section
      className={cn("flex flex-col gap-3", className)}
      data-testid="section"
    >
      {(title || actions) && (
        <div className="flex items-center justify-between gap-4">
          <div className="flex flex-col gap-1">
            {title && (
              <h2 className="text-lg font-semibold text-text">{title}</h2>
            )}
            {description && (
              <p className="text-sm text-text-muted">{description}</p>
            )}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}
