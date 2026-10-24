"""Single error model for the API: every failure is ``{"error": <code>, "detail": ...}``.

Domain errors carry their own ``code``; this module is the one place that decides the
HTTP status for each, so views never contain try/except ladders (ADR-0009).
"""

import logging

from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from fuel_route.domain.errors import (
    DomainError,
    LocationNotFoundError,
    NoFeasiblePlanError,
    ProviderUnavailableError,
    UnknownStrategyError,
)

log = logging.getLogger(__name__)

STATUS_BY_ERROR: dict[type[DomainError], int] = {
    LocationNotFoundError: status.HTTP_400_BAD_REQUEST,
    UnknownStrategyError: status.HTTP_400_BAD_REQUEST,
    NoFeasiblePlanError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ProviderUnavailableError: status.HTTP_502_BAD_GATEWAY,
}


def error_body(exc: DomainError) -> tuple[dict, int]:
    code = next((c for t, c in STATUS_BY_ERROR.items() if isinstance(exc, t)), status.HTTP_400_BAD_REQUEST)
    if code >= 500:
        log.warning("upstream failure: %s", exc)
    return {"error": exc.code, "detail": str(exc)}, code


def exception_handler(exc, context):
    if isinstance(exc, DomainError):
        body, code = error_body(exc)
        return Response(body, status=code)
    if isinstance(exc, ValidationError):
        return Response({"error": "invalid_request", "detail": exc.detail}, status=status.HTTP_400_BAD_REQUEST)
    return drf_exception_handler(exc, context)
