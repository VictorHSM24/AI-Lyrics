import { Link } from "react-router-dom";
import { Home } from "lucide-react";

export function NotFoundPage() {
  return (
    <div
      className="flex flex-col items-center justify-center gap-4 py-20 text-center"
      data-testid="not-found-page"
    >
      <span className="text-6xl font-bold text-text-subtle">404</span>
      <div className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold text-text">Página não encontrada</h1>
        <p className="text-sm text-text-muted">
          A página que você procura não existe ou foi movida.
        </p>
      </div>
      <Link
        to="/"
        className="flex items-center gap-2 rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover"
      >
        <Home className="h-4 w-4" />
        Voltar ao Dashboard
      </Link>
    </div>
  );
}
