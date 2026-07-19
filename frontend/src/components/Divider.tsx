import { cn } from "@/utils";

interface DividerProps {
  className?: string;
  label?: string;
}

export function Divider({ className, label }: DividerProps) {
  if (label) {
    return (
      <div className={cn("flex items-center gap-3", className)} data-testid="divider">
        <div className="h-px flex-1 bg-border" />
        <span className="text-xs text-text-subtle">{label}</span>
        <div className="h-px flex-1 bg-border" />
      </div>
    );
  }
  return <div className={cn("h-px bg-border", className)} data-testid="divider" />;
}
