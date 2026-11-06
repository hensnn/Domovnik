"""Doménové chyby. API vrstva je mapuje na HTTP (RFC 9457 problem+json)."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    status = 400
    code = "domain_error"

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.message = message
        self.extra = extra


class NotFound(DomainError):
    status = 404
    code = "not_found"


class Conflict(DomainError):
    status = 409
    code = "conflict"


class ValidationFailed(DomainError):
    status = 422
    code = "validation_failed"


class PayloadTooLarge(DomainError):
    status = 413
    code = "payload_too_large"


class Forbidden(DomainError):
    status = 403
    code = "forbidden"


class Unauthorized(DomainError):
    status = 401
    code = "unauthorized"
