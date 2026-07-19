/**
 * TabNav — navegação por abas.
 *
 * Componente genérico e acessível (ARIA tabs).
 * Usado pela página de Configurações.
 */

import type { ReactNode } from "react";
import { cn } from "@/utils";

export interface TabDef {
  id: string;
  label: string;
  icon?: ReactNode;
  content: ReactNode;
}

interface TabNavProps {
  tabs: TabDef[];
  activeTab: string;
  onChange: (tabId: string) => void;
  className?: string;
}

export function TabNav({ tabs, activeTab, onChange, className }: TabNavProps) {
  const active = tabs.find((t) => t.id === activeTab) ?? tabs[0];

  return (
    <div className={cn("flex flex-col gap-4", className)} data-testid="tab-nav">
      <div
        className="flex flex-wrap gap-1 border-b border-border"
        role="tablist"
        aria-label="Abas"
      >
        {tabs.map((tab) => {
          const isActive = tab.id === active.id;
          return (
            <button
              key={tab.id}
              role="tab"
              id={`tab-${tab.id}`}
              aria-selected={isActive}
              aria-controls={`tabpanel-${tab.id}`}
              tabIndex={isActive ? 0 : -1}
              onClick={() => onChange(tab.id)}
              className={cn(
                "inline-flex items-center gap-2 border-b-2 px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "border-accent text-accent"
                  : "border-transparent text-text-muted hover:text-text",
              )}
              data-testid={`tab-button-${tab.id}`}
              data-active={isActive}
            >
              {tab.icon}
              {tab.label}
            </button>
          );
        })}
      </div>
      <div
        role="tabpanel"
        id={`tabpanel-${active.id}`}
        aria-labelledby={`tab-${active.id}`}
        data-testid={`tabpanel-${active.id}`}
      >
        {active.content}
      </div>
    </div>
  );
}
