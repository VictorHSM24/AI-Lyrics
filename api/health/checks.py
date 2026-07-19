"""Health checks da própria API (não do sistema)."""

from __future__ import annotations

import time


def check_api_health() -> dict:
    """Verifica saúde básica da própria API (não do sistema).

    Retorna sempre healthy — a API em si não tem dependências
    externas além do CompositionRoot.
    """
    return {
        "status": "healthy",
        "component": "api",
        "message": "API operational",
        "timestamp": time.time(),
    }
