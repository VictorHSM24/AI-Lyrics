import { Loader2 } from "lucide-react";
import { cn } from "@/utils";

interface LoadingProps {
  label?: string;
  className?: string;
  size?: "sm" | "md" | "lg";
}

export function Loading({ label = "Carregando…", className, size = "md" }: LoadingProps) {
  const sizeClass = {
    sm: "h-4 w-4",
    md: "h-6 w-6",
    lg: "h-8 w-8",
  }[size];

  return (
    <div
      className={cn("flex items-center justify-center gap-2 py-8", className)}
      data-testid="loading"
      role="status"
      aria-live="polite"
    >
      <Loader2 className={cn("animate-spin text-accent", sizeClass)} />
      <span className="text-sm text-text-muted">{label}</span>
    </div>
  );
}
