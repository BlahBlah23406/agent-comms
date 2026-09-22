"""
AI Provider Quota & Rate Limit Models
=====================================
Defines schemas for rate limit monitoring, usage windows, threshold rules,
and preemptive handoff recommendations across AI providers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AIProvider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GEMINI = "gemini"
    CURSOR = "cursor"
    CUSTOM = "custom"


class QuotaWindow(str, Enum):
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class QuotaBudget(BaseModel):
    """Configured rate-limit/quota budget for a given AI provider."""
    provider: str
    window: QuotaWindow = QuotaWindow.HOUR
    max_requests: Optional[int] = Field(None, description="Maximum requests allowed in window")
    max_tokens: Optional[int] = Field(None, description="Maximum tokens allowed in window")
    warning_threshold_ratio: float = Field(0.80, description="Ratio (0.0 - 1.0) to trigger warnings")
    critical_threshold_ratio: float = Field(0.92, description="Ratio (0.0 - 1.0) to trigger preemptive evacuation")
    min_safe_requests_remaining: int = Field(3, description="Minimum safe remaining requests before evacuation")
    min_safe_tokens_remaining: int = Field(5000, description="Minimum safe remaining tokens before evacuation")


class QuotaStatus(BaseModel):
    """Current quota consumption and rate-limit state for a provider."""
    provider: str
    window: QuotaWindow = QuotaWindow.HOUR
    requests_used: int = 0
    tokens_used: int = 0
    max_requests: Optional[int] = None
    max_tokens: Optional[int] = None
    remaining_requests: Optional[int] = None
    remaining_tokens: Optional[int] = None
    reset_at: Optional[str] = None
    retry_after_seconds: Optional[float] = None
    request_utilization: float = 0.0
    token_utilization: float = 0.0
    is_warning: bool = False
    is_critical: bool = False
    is_rate_limited: bool = False
    recommend_evacuation: bool = False
    reason: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EvacuationResult(BaseModel):
    """Result of a preemptive quota evacuation handoff."""
    evacuated: bool
    task_id: str
    capsule_id: Optional[str] = None
    provider: str
    target_provider: Optional[str] = None
    quota_status: Optional[QuotaStatus] = None
    saved_path: Optional[str] = None
    cloud_location: Optional[str] = None
    briefing: Optional[str] = None
    resumption_prompt: Optional[str] = None
