import type { ReactNode } from "react";
import { cn } from "@/utils";

interface PageContainerProps {
  children: ReactNode;
  className?: string;
}

export function PageContainer({ children, className }: PageContainerProps) {
  return (
    <div
      className={cn("flex flex-col gap-6 p-6 lg:p-8", className)}
      data-testid="page-container"
    >
      {children}
    </div>
  );
}
