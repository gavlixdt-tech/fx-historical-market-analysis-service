"""Shared types for upstream service clients."""

from __future__ import annotations

from enum import StrEnum


class UpstreamState(StrEnum):
    """Connection state of an upstream integration.

    The vocabulary is intentionally explicit so the dashboard never has to
    guess, and so an *unconfigured* service is never presented as *connected*.
    """

    UNCONFIGURED = "unconfigured"
    UNVERIFIED = "unverified"
    CONNECTED = "connected"
    UNAVAILABLE = "unavailable"
    AUTH_FAILED = "auth_failed"


class UpstreamContractStatus(StrEnum):
    """Verification status of the upstream contract this client targets."""

    VERIFIED = "verified"
    PROPOSED_NOT_YET_VERIFIED = "proposed-not-yet-verified"


class UpstreamCheckResult:
    """Outcome of a single upstream connectivity check."""

    __slots__ = ("state", "message", "latency_ms", "checked_at", "contract_status")

    def __init__(
        self,
        state: UpstreamState,
        message: str,
        latency_ms: float | None = None,
        checked_at: str | None = None,
        contract_status: UpstreamContractStatus = UpstreamContractStatus.VERIFIED,
    ) -> None:
        self.state = state
        self.message = message
        self.latency_ms = latency_ms
        self.checked_at = checked_at
        self.contract_status = contract_status
