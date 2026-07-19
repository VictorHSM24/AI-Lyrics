"""Health package — healthcheck da própria API."""

from api.health.checks import check_api_health

__all__ = ["check_api_health"]
