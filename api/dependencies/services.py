"""Dependencies — injeção de Presentation Services nos routers.

Estas funções são usadas pelo FastAPI via Depends(). Elas expõem
APENAS Presentation Services — nunca o Core.
"""

from __future__ import annotations

from fastapi import Depends

from api.startup import CompositionRoot, get_root
from presentation import (
    ConfigurationPresentationService,
    DiagnosticPresentationService,
    EventPresentationService,
    HealthPresentationService,
    MetricsPresentationService,
    PipelinePresentationService,
    SessionPresentationService,
)


def get_composition_root() -> CompositionRoot:
    """Retorna o CompositionRoot singleton."""
    return get_root()


def get_pipeline_service(
    root: CompositionRoot = Depends(get_composition_root),
) -> PipelinePresentationService:
    return root.pipeline_service


def get_session_service(
    root: CompositionRoot = Depends(get_composition_root),
) -> SessionPresentationService:
    return root.session_service


def get_metrics_service(
    root: CompositionRoot = Depends(get_composition_root),
) -> MetricsPresentationService:
    return root.metrics_service


def get_configuration_service(
    root: CompositionRoot = Depends(get_composition_root),
) -> ConfigurationPresentationService:
    return root.configuration_service


def get_health_service(
    root: CompositionRoot = Depends(get_composition_root),
) -> HealthPresentationService:
    return root.health_service


def get_diagnostic_service(
    root: CompositionRoot = Depends(get_composition_root),
) -> DiagnosticPresentationService:
    return root.diagnostic_service


def get_event_service(
    root: CompositionRoot = Depends(get_composition_root),
) -> EventPresentationService:
    return root.event_service
