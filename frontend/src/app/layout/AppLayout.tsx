import { useState, type ReactNode } from "react";
import { Menu } from "lucide-react";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";
import { Footer } from "./Footer";

interface AppLayoutProps {
  children: ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="flex h-screen flex-col" data-testid="app-layout">
      <Header />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar
          open={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
        />
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Botão de menu mobile */}
          <button
            className="flex items-center gap-2 border-b border-border px-4 py-2 text-sm text-text-muted lg:hidden"
            onClick={() => setSidebarOpen(true)}
            aria-label="Abrir menu"
          >
            <Menu className="h-4 w-4" />
            <span>Menu</span>
          </button>
          <main className="flex-1 overflow-y-auto" data-testid="main-content">
            {children}
          </main>
          <Footer />
        </div>
      </div>
    </div>
  );
}
