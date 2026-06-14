"""Shared request schemas for the cockpit (ARCH-3): the small request primitives the plan and
perception routers both build on -- the build Order and its count cap. Extracted from server.py so
both routers import one source of truth without importing the app module (no cycle)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

_MAX_ORDERS = 1000   # N8 input limit: refuse absurd build queues before they reach the planner


class Order(BaseModel):
    model_config = ConfigDict(extra="allow")
    action: str | None = Field(default=None, max_length=120)
    kind: str | None = Field(default=None, max_length=40)
    x: float = 0.0
    y: float = 0.0
    footprint_m2: float = Field(default=1.0, gt=0, le=1e8)
    depth_m: float = Field(default=0.0, ge=-100.0, le=100.0)
