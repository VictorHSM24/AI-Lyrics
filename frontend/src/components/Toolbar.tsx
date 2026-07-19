import type { ReactNode } from "react";
import { cn } from "@/utils";

interface ToolbarProps {
  children: ReactNode;
  className?: string;
}

export function Toolbar({ children, className }: ToolbarProps) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-2 border-b border-border pb-3",
        className,
      )}
      data-testid="toolbar"
    >
      {children}
    </div>
  );
}
