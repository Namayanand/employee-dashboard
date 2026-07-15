"""Domain-specific exceptions so the UI layer can catch and message cleanly."""
from __future__ import annotations


class EmployeeServiceError(Exception):
    """Base class for all service-layer errors."""


class EmployeeNotFound(EmployeeServiceError):
    """No employee matched the given identifier."""


class InvalidColumn(EmployeeServiceError):
    """A dynamic column reference wasn't in the known-columns whitelist."""


class TooManyGroups(EmployeeServiceError):
    """A split would produce more files than the configured safety limit."""


class UnsupportedFormat(EmployeeServiceError):
    """Requested an export format the exporter doesn't support."""
