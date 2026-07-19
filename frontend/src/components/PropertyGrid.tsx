import { cn } from "@/utils";

interface Property {
  label: string;
  value: string | number | boolean | null | undefined;
}

interface PropertyGridProps {
  properties: Property[];
  columns?: 1 | 2 | 3;
  className?: string;
}

export function PropertyGrid({
  properties,
  columns = 2,
  className,
}: PropertyGridProps) {
  const colClass = {
    1: "grid-cols-1",
    2: "grid-cols-2",
    3: "grid-cols-3",
  }[columns];

  return (
    <div
      className={cn("grid gap-3", colClass, className)}
      data-testid="property-grid"
    >
      {properties.map((prop, i) => (
        <div
          key={i}
          className="flex flex-col gap-0.5 border-b border-border/50 pb-2"
        >
          <span className="text-xs text-text-muted">{prop.label}</span>
          <span className="text-sm text-text">
            {prop.value === null || prop.value === undefined
              ? "—"
              : String(prop.value)}
          </span>
        </div>
      ))}
    </div>
  );
}
