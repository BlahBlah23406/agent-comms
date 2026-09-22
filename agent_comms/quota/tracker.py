"""
AI Provider Quota & Usage Tracker
=================================
Tracks rolling-window API request and token consumption, parses vendor rate-limit
HTTP headers (Anthropic, OpenAI, Gemini, generic), and evaluates quota health.
Persists state to ~/.agent-comms/quotas.json.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_comms.quota.models import AIProvider, QuotaBudget, QuotaStatus, QuotaWindow

logger = logging.getLogger("agent_comms.quota.tracker")


class QuotaTracker:
    """Monitors usage, parses vendor rate-limit headers, and tracks quota exhaustion."""

    DEFAULT_BUDGETS: Dict[str, QuotaBudget] = {
        "anthropic": QuotaBudget(
            provider="anthropic",
            window=QuotaWindow.HOUR,
            max_requests=50,
            max_tokens=200000,
            warning_threshold_ratio=0.80,
            critical_threshold_ratio=0.90,
            min_safe_requests_remaining=3,
            min_safe_tokens_remaining=10000,
        ),
        "openai": QuotaBudget(
            provider="openai",
            window=QuotaWindow.HOUR,
            max_requests=60,
            max_tokens=300000,
            warning_threshold_ratio=0.80,
            critical_threshold_ratio=0.90,
            min_safe_requests_remaining=3,
            min_safe_tokens_remaining=10000,
        ),
        "gemini": QuotaBudget(
            provider="gemini",
            window=QuotaWindow.DAY,
            max_requests=1500,
            max_tokens=1000000,
            warning_threshold_ratio=0.85,
            critical_threshold_ratio=0.95,
            min_safe_requests_remaining=10,
            min_safe_tokens_remaining=25000,
        ),
        "cursor": QuotaBudget(
            provider="cursor",
            window=QuotaWindow.MONTH,
            max_requests=500,
            warning_threshold_ratio=0.85,
            critical_threshold_ratio=0.95,
            min_safe_requests_remaining=5,
        ),
    }

    def __init__(self, data_path: Optional[Path] = None):
        self.data_dir = (data_path or (Path.home() / ".agent-comms")).resolve()
        self.data_file = self.data_dir / "quotas.json"
        self._budgets: Dict[str, QuotaBudget] = dict(self.DEFAULT_BUDGETS)
        # provider -> list of {"timestamp": iso, "tokens": int, "requests": int}
        self._usage_events: Dict[str, List[Dict[str, Any]]] = {}
        # provider -> header overrides {"remaining_requests": int, "reset_at": iso, ...}
        self._header_states: Dict[str, Dict[str, Any]] = {}
        self.load()

    def load(self):
        """Loads budgets and usage state from disk."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.data_file.exists():
            try:
                raw = json.loads(self.data_file.read_text(encoding="utf-8"))
                for p_name, b_dict in raw.get("budgets", {}).items():
                    self._budgets[p_name.lower()] = QuotaBudget.model_validate(b_dict)
                self._usage_events = raw.get("usage_events", {})
                self._header_states = raw.get("header_states", {})
            except Exception as e:
                logger.warning("Error loading quotas.json: %s", e)

    def save(self):
        """Persists current state to disk."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "budgets": {k: v.model_dump() for k, v in self._budgets.items()},
            "usage_events": self._usage_events,
            "header_states": self._header_states,
        }
        self.data_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def set_budget(self, budget: QuotaBudget):
        """Registers or updates a provider budget."""
        self._budgets[budget.provider.lower()] = budget
        self.save()

    def get_budget(self, provider: str) -> QuotaBudget:
        p = provider.lower()
        if p in self._budgets:
            return self._budgets[p]
        # Return generic default
        return QuotaBudget(provider=p, window=QuotaWindow.HOUR)

    def record_usage(self, provider: str, tokens: int = 0, requests: int = 1):
        """Logs consumption event for client-side window tracking."""
        p = provider.lower()
        events = self._usage_events.setdefault(p, [])
        events.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tokens": max(0, tokens),
            "requests": max(0, requests),
        })
        self._prune_events(p)
        self.save()

    def record_headers(self, provider: str, headers: Dict[str, Any]):
        """
        Parses vendor rate-limit headers (Anthropic, OpenAI, Gemini, generic)
        and caches real-time server-reported quota state.
        """
        p = provider.lower()
        norm_headers = {str(k).lower(): str(v) for k, v in headers.items()}
        state = self._header_states.setdefault(p, {})
        now = datetime.now(timezone.utc)

        # 1. Anthropic Rate Limits
        if "anthropic-ratelimit-requests-remaining" in norm_headers:
            state["remaining_requests"] = int(norm_headers["anthropic-ratelimit-requests-remaining"])
        if "anthropic-ratelimit-requests-limit" in norm_headers:
            state["max_requests"] = int(norm_headers["anthropic-ratelimit-requests-limit"])
        if "anthropic-ratelimit-requests-reset" in norm_headers:
            state["reset_at"] = norm_headers["anthropic-ratelimit-requests-reset"]
        if "anthropic-ratelimit-tokens-remaining" in norm_headers:
            state["remaining_tokens"] = int(norm_headers["anthropic-ratelimit-tokens-remaining"])
        if "anthropic-ratelimit-tokens-limit" in norm_headers:
            state["max_tokens"] = int(norm_headers["anthropic-ratelimit-tokens-limit"])
        if "anthropic-ratelimit-tokens-reset" in norm_headers:
            state["reset_at"] = norm_headers["anthropic-ratelimit-tokens-reset"]

        # 2. OpenAI Rate Limits
        if "x-ratelimit-remaining-requests" in norm_headers:
            state["remaining_requests"] = int(norm_headers["x-ratelimit-remaining-requests"])
        if "x-ratelimit-limit-requests" in norm_headers:
            state["max_requests"] = int(norm_headers["x-ratelimit-limit-requests"])
        if "x-ratelimit-remaining-tokens" in norm_headers:
            state["remaining_tokens"] = int(norm_headers["x-ratelimit-remaining-tokens"])
        if "x-ratelimit-limit-tokens" in norm_headers:
            state["max_tokens"] = int(norm_headers["x-ratelimit-limit-tokens"])
        if "x-ratelimit-reset-requests" in norm_headers:
            state["reset_at"] = norm_headers["x-ratelimit-reset-requests"]

        # 3. Google Gemini Rate Limits
        if "x-goog-ratelimit-remaining-requests" in norm_headers:
            state["remaining_requests"] = int(norm_headers["x-goog-ratelimit-remaining-requests"])
        if "x-goog-ratelimit-remaining-tokens" in norm_headers:
            state["remaining_tokens"] = int(norm_headers["x-goog-ratelimit-remaining-tokens"])

        # 4. Generic Headers / Retry-After
        if "retry-after" in norm_headers:
            try:
                sec = float(norm_headers["retry-after"])
                state["retry_after_seconds"] = sec
                state["reset_at"] = (now + timedelta(seconds=sec)).isoformat()
                state["is_rate_limited"] = True
            except ValueError:
                state["reset_at"] = norm_headers["retry-after"]
                state["is_rate_limited"] = True

        state["last_updated"] = now.isoformat()
        self.save()

    def record_error(self, provider: str, status_code: int, error_message: str = ""):
        """Records a 429 or quota exhaustion error event."""
        p = provider.lower()
        state = self._header_states.setdefault(p, {})
        if status_code == 429 or "rate" in error_message.lower() or "quota" in error_message.lower():
            state["is_rate_limited"] = True
            state["last_error"] = error_message
            state["last_error_time"] = datetime.now(timezone.utc).isoformat()
            self.save()

    def get_status(self, provider: str) -> QuotaStatus:
        """
        Evaluates current quota health, combining real-time server headers and client tracking.
        Determines whether preemptive evacuation is recommended.
        """
        p = provider.lower()
        budget = self.get_budget(p)
        self._prune_events(p)

        # Aggregate client usage over window
        events = self._usage_events.get(p, [])
        client_requests = sum(e.get("requests", 0) for e in events)
        client_tokens = sum(e.get("tokens", 0) for e in events)

        header_state = self._header_states.get(p, {})
        now = datetime.now(timezone.utc)

        # Merge max limits
        max_req = header_state.get("max_requests") or budget.max_requests
        max_tok = header_state.get("max_tokens") or budget.max_tokens

        # Merge remaining counts
        rem_req = header_state.get("remaining_requests")
        if rem_req is None and max_req is not None:
            rem_req = max(0, max_req - client_requests)

        rem_tok = header_state.get("remaining_tokens")
        if rem_tok is None and max_tok is not None:
            rem_tok = max(0, max_tok - client_tokens)

        # Calculate utilization
        req_util = 0.0
        if max_req and max_req > 0:
            if rem_req is not None:
                req_util = max(0.0, min(1.0, (max_req - rem_req) / max_req))
            else:
                req_util = max(0.0, min(1.0, client_requests / max_req))

        tok_util = 0.0
        if max_tok and max_tok > 0:
            if rem_tok is not None:
                tok_util = max(0.0, min(1.0, (max_tok - rem_tok) / max_tok))
            else:
                tok_util = max(0.0, min(1.0, client_tokens / max_tok))

        # Check rate limited state
        is_rate_limited = header_state.get("is_rate_limited", False)
        reset_at = header_state.get("reset_at")
        if reset_at:
            try:
                reset_dt = datetime.fromisoformat(reset_at)
                if reset_dt < now:
                    is_rate_limited = False
                    header_state["is_rate_limited"] = False
            except Exception:
                pass

        # Check warning and critical thresholds
        is_warning = (
            req_util >= budget.warning_threshold_ratio
            or tok_util >= budget.warning_threshold_ratio
            or (rem_req is not None and rem_req <= budget.min_safe_requests_remaining * 2)
        )

        is_critical = (
            req_util >= budget.critical_threshold_ratio
            or tok_util >= budget.critical_threshold_ratio
            or (rem_req is not None and rem_req <= budget.min_safe_requests_remaining)
            or (rem_tok is not None and rem_tok <= budget.min_safe_tokens_remaining)
        )

        recommend_evac = is_rate_limited or is_critical
        reason = None
        if is_rate_limited:
            reason = f"Provider '{p}' has hit rate limit (429 / quota exceeded). Reset at {reset_at or 'unknown'}."
        elif is_critical:
            if rem_req is not None and rem_req <= budget.min_safe_requests_remaining:
                reason = f"Critical request threshold reached for '{p}': only {rem_req} request(s) remaining."
            elif rem_tok is not None and rem_tok <= budget.min_safe_tokens_remaining:
                reason = f"Critical token threshold reached for '{p}': only {rem_tok} token(s) remaining."
            elif req_util >= budget.critical_threshold_ratio:
                reason = f"Request utilization at {req_util * 100:.1f}% (critical threshold: {budget.critical_threshold_ratio * 100:.0f}%)."
            elif tok_util >= budget.critical_threshold_ratio:
                reason = f"Token utilization at {tok_util * 100:.1f}% (critical threshold: {budget.critical_threshold_ratio * 100:.0f}%)."
        elif is_warning:
            reason = f"Warning: Provider '{p}' quota utilization high ({max(req_util, tok_util) * 100:.1f}%)."

        return QuotaStatus(
            provider=p,
            window=budget.window,
            requests_used=client_requests,
            tokens_used=client_tokens,
            max_requests=max_req,
            max_tokens=max_tok,
            remaining_requests=rem_req,
            remaining_tokens=rem_tok,
            reset_at=reset_at,
            retry_after_seconds=header_state.get("retry_after_seconds"),
            request_utilization=round(req_util, 3),
            token_utilization=round(tok_util, 3),
            is_warning=is_warning,
            is_critical=is_critical,
            is_rate_limited=is_rate_limited,
            recommend_evacuation=recommend_evac,
            reason=reason,
        )

    def _prune_events(self, provider: str):
        """Removes usage events that fall outside the configured rolling window."""
        budget = self.get_budget(provider)
        delta_map = {
            QuotaWindow.MINUTE: timedelta(minutes=1),
            QuotaWindow.HOUR: timedelta(hours=1),
            QuotaWindow.DAY: timedelta(days=1),
            QuotaWindow.WEEK: timedelta(weeks=1),
            QuotaWindow.MONTH: timedelta(days=30),
        }
        window_delta = delta_map.get(budget.window, timedelta(hours=1))
        cutoff = datetime.now(timezone.utc) - window_delta

        events = self._usage_events.get(provider, [])
        valid_events = []
        for e in events:
            try:
                dt = datetime.fromisoformat(e["timestamp"])
                if dt >= cutoff:
                    valid_events.append(e)
            except Exception:
                continue
        self._usage_events[provider] = valid_events


# Global singleton instance
quota_tracker = QuotaTracker()
