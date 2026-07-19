import { AlertCircle } from "lucide-react";

interface ErrorPageProps {
  error?: Error;
  reset?: () => void;
}

export function ErrorPage({ error, reset }: ErrorPageProps) {
  return (
    <div
      className="flex flex-col items-center justify-center gap-4 py-20 text-center"
      data-testid="error-page"
      role="alert"
    >
      <AlertCircle className="h-12 w-12 text-status-error" />
      <div className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold text-text">
          Algo deu errado
        </h1>
        <p className="text-sm text-text-muted">
          {error?.message ?? "Ocorreu um erro inesperado."}
        </p>
      </div>
      {reset && (
        <button
          onClick={reset}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover"
        >
          Tentar novamente
        </button>
      )}
    </div>
  );
}
