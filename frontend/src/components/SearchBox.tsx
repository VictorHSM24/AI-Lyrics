import { Search } from "lucide-react";
import { cn } from "@/utils";

interface SearchBoxProps {
  value?: string;
  onChange?: (value: string) => void;
  placeholder?: string;
  className?: string;
}

export function SearchBox({
  value = "",
  onChange,
  placeholder = "Buscar…",
  className,
}: SearchBoxProps) {
  return (
    <div
      className={cn("relative", className)}
      data-testid="search-box"
    >
      <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-text-subtle" />
      <input
        type="text"
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-md border border-border bg-surface py-1.5 pl-8 pr-3 text-sm text-text placeholder:text-text-subtle focus:border-accent"
        aria-label={placeholder}
      />
    </div>
  );
}
