import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Terminal,
  History,
  RotateCcw,
  ScrollText,
  Settings,
  Stethoscope,
  Info,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/utils";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/console", label: "Console", icon: Terminal },
  { to: "/sessoes", label: "Sessões", icon: History },
  { to: "/replay", label: "Replay", icon: RotateCcw },
  { to: "/logs", label: "Logs", icon: ScrollText },
  { to: "/configuracoes", label: "Configurações", icon: Settings },
  { to: "/diagnostico", label: "Diagnóstico", icon: Stethoscope },
  { to: "/sobre", label: "Sobre", icon: Info },
];

interface SidebarProps {
  open?: boolean;
  onClose?: () => void;
}

export function Sidebar({ open = true, onClose }: SidebarProps) {
  return (
    <>
      {/* Overlay em mobile */}
      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
          onClick={onClose}
          data-testid="sidebar-overlay"
          aria-hidden="true"
        />
      )}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r border-border bg-surface transition-transform lg:static lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
        data-testid="sidebar"
      >
        <nav className="flex flex-1 flex-col gap-1 p-3" aria-label="Navegação principal">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              onClick={onClose}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-accent-muted text-accent"
                    : "text-text-muted hover:bg-surface-hover hover:text-text",
                )
              }
            >
              <Icon className="h-4 w-4 flex-shrink-0" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
      </aside>
    </>
  );
}
