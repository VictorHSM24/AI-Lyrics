"""Entry point do AI Lyrics para empacotamento PyInstaller.

Este módulo é o ponto de entrada usado pelo ai-lyrics.spec para gerar
ai-lyrics.exe. Faz duas coisas:

1. Verifica se o wizard de primeira execução já foi concluído. Se não,
   marca um flag que o frontend lê para redirecionar para /wizard.
2. Inicia o servidor uvicorn embutido com a aplicação FastAPI
   (api.app:app).

O wizard em si é implementado em api/wizard.py (endpoints REST) e
frontend/src/pages/Wizard.tsx (UI). Este main.py apenas orquestra o
startup do servidor.

Para desenvolvimento (sem PyInstaller), continue usando:
    uvicorn api.app:app --reload --port 8000
"""
from __future__ import annotations

import logging
import os
import sys
import webbrowser
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


# Flag file criada quando o wizard é concluído. Persiste entre execuções.
WIZARD_FLAG_FILENAME = ".wizard_completed"


def _app_data_dir() -> Path:
    """Diretório base para dados persistentes do app.

    Em PyInstaller (frozen), usa %APPDATA%/AI Lyrics Assistant.
    Em desenvolvimento, usa o diretório do projeto.
    """
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA", str(Path.home()))
        return Path(base) / "AI Lyrics Assistant"
    return Path(__file__).resolve().parent


def wizard_completed() -> bool:
    """Retorna True se o wizard de primeira execução já foi concluído."""
    flag = _app_data_dir() / WIZARD_FLAG_FILENAME
    return flag.exists()


def mark_wizard_completed() -> None:
    """Marca o wizard como concluído (chamado pelo endpoint /wizard/complete)."""
    base = _app_data_dir()
    base.mkdir(parents=True, exist_ok=True)
    flag = base / WIZARD_FLAG_FILENAME
    flag.write_text("completed\n", encoding="utf-8")
    logger.info("Wizard marcado como concluído em %s", flag)


def _resolve_host_port() -> tuple[str, int]:
    """Host e porta do servidor. Padrão 127.0.0.1:8000."""
    host = os.environ.get("AI_LYRICS_HOST", "127.0.0.1")
    port = int(os.environ.get("AI_LYRICS_PORT", "8000"))
    return host, port


def _open_wizard_in_browser(host: str, port: int) -> None:
    """Abre o wizard no browser padrão do usuário."""
    url = f"http://{host}:{port}/wizard"
    try:
        webbrowser.open(url)
        logger.info("Wizard aberto em %s", url)
    except Exception as e:
        logger.warning("Não foi possível abrir o browser automaticamente: %s", e)
        logger.info("Abra manualmente: %s", url)


def main() -> int:
    """Ponto de entrada principal do AI Lyrics."""
    host, port = _resolve_host_port()
    needs_wizard = not wizard_completed()

    if needs_wizard:
        logger.info("Primeira execução detectada — wizard será aberto.")
    else:
        logger.info("Wizard já concluído — iniciando em modo normal.")

    # Atraso mínimo para o uvicorn estar escutando antes de abrir o browser.
    if needs_wizard:
        import threading

        def _open_after_delay() -> None:
            import time
            time.sleep(2.0)
            _open_wizard_in_browser(host, port)

        threading.Thread(target=_open_after_delay, daemon=True).start()

    # Importa a app FastAPI explicitamente (não por string) para garantir
    # que o PyInstaller resolva o módulo api.app no bundle em tempo de
    # import, evitando o erro "Could not import module api.app" que
    # ocorre quando uvicorn tenta importlib em runtime.
    try:
        from api.app import app  # noqa: E402
    except ImportError as e:
        logger.error(
            "Não foi possível importar api.app: %s. "
            "Verifique se o bundle PyInstaller inclui o pacote api.",
            e,
        )
        return 1

    # Importa uvicorn após a app (garante que api.app está resolvível).
    try:
        import uvicorn
    except ImportError:
        logger.error("uvicorn não está instalado. Instale com: pip install uvicorn")
        return 1

    logger.info("Iniciando AI Lyrics em http://%s:%d", host, port)
    # Passa o objeto app diretamente (não a string "api.app:app") para
    # evitar import dinâmico em runtime no bundle PyInstaller.
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
