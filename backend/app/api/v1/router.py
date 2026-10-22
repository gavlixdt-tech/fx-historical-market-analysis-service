"""Versioned API router.

Aggregates the v1 route modules. The router is mounted by the application
factory at the configured API prefix (`/api/v1` by default).
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.v1.routes import health, status, version

router = APIRouter()
router.include_router(health.router, prefix="/health", tags=["health"])
router.include_router(status.router, prefix="", tags=["status"])
router.include_router(version.router, prefix="", tags=["version"])
