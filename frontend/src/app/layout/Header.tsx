import { Mic, Sun, Moon, Monitor, Wifi, WifiOff, CircleDashed } from "lucide-react";
import { useApplication } from "@/contexts/ApplicationContext";
import { useTheme, type ThemeMode } from "@/contexts/ThemeContext";
import { useConnection, type ConnectionStatus } from "@/contexts/ConnectionContext";
import { cn } from "@/utils";

const CONNECTION_CONFIG: Record<ConnectionStatus, { icon: typeof Wifi; label: string; color: string }> = {
  connected: { icon: Wifi, label: "Conectado", color: "text-status-success" },
  disconnected: { icon: WifiOff, label: "Desconectado", color: "text-status-error" },
  connecting: { icon: CircleDashed, label: "Conectando…", color: "text-status-warning" },
  unknown: { icon: CircleDashed, label: "Sem backend", color: "text-text-subtle" },
};

const THEME_OPTIONS: Array<{ mode: ThemeMode; icon: typeof Sun; label: string }> = [
  { mode: "light", icon: Sun, label: "Claro" },
  { mode: "dark", icon: Moon, label: "Escuro" },
  { mode: "system", icon: Monitor, label: "Sistema" },
];

export function Header() {
  const { info } = useApplication();
  const { mode, setMode } = useTheme();
  const { status } = useConnection();

  const connConfig = CONNECTION_CONFIG[status];
  const ConnIcon = connConfig.icon;

  return (
    <header
      className="flex h-14 items-center justify-between border-b border-border bg-surface px-4"
      data-testid="header"
    >
      {/* Logo + nome + versão */}
      <div className="flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-accent text-white">
          <Mic className="h-5 w-5" />
        </div>
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-bold text-text">{info.name}</span>
          <span className="text-xs text-text-subtle">v{info.version}</span>
        </div>
      </div>

      {/* Status da conexão + Pipeline indicator + Tema */}
      <div className="flex items-center gap-4">
        {/* Pipeline indicator (placeholder) */}
        <div className="hidden items-center gap-1.5 sm:flex">
          <span className="h-2 w-2 rounded-full bg-text-subtle" aria-hidden="true" />
          <span className="text-xs text-text-muted">Pipeline: —</span>
        </div>

        {/* Status da conexão */}
        <div className="flex items-center gap-1.5">
          <ConnIcon className={cn("h-4 w-4", connConfig.color)} />
          <span className={cn("text-xs", connConfig.color)}>{connConfig.label}</span>
        </div>

        {/* Tema claro/escuro/sistema */}
        <div className="flex items-center gap-0.5 rounded-md border border-border p-0.5">
          {THEME_OPTIONS.map(({ mode: m, icon: Icon, label }) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={cn(
                "rounded p-1.5 transition-colors",
                mode === m
                  ? "bg-accent text-white"
                  : "text-text-muted hover:bg-surface-hover hover:text-text",
              )}
              aria-label={`Tema ${label}`}
              aria-pressed={mode === m}
            >
              <Icon className="h-4 w-4" />
            </button>
          ))}
        </div>
      </div>
    </header>
  );
}
