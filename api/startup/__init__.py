"""Startup package — composition root e inicialização."""

from api.startup.composition import (
    CompositionRoot,
    create_composition_root,
    get_root,
    reset_root,
)

__all__ = [
    "CompositionRoot",
    "create_composition_root",
    "get_root",
    "reset_root",
]
