"""
Quota Guard & Preemptive Evacuation Orchestrator
================================================
Monitors AI provider quotas and rate limits, detects imminent exhaustion,
and automatically generates a self-contained Context Capsule right before
the session stops, enabling another agent, provider, or machine to take over seamlessly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_comms.capsule.packager import CapsulePackager
from agent_comms.capsule.store import CapsuleStore
from agent_comms.models.capsule import (
    ContextCapsule,
    EpistemicLearning,
    LearningCategory,
    TaskStep,
)
from agent_comms.quota.models import EvacuationResult, QuotaStatus
from agent_comms.quota.tracker import QuotaTracker, quota_tracker

logger = logging.getLogger("agent_comms.quota.guard")


class QuotaGuard:
    """
    Guards active agent sessions against unexpected mid-task rate limits and quota lockouts.
    Preemptively checkpoints workspace state and handoff context into a capsule.
    """

    def __init__(
        self,
        workspace_path: Optional[Path] = None,
        tracker: Optional[QuotaTracker] = None,
        store: Optional[CapsuleStore] = None,
    ):
        self.workspace_path = (workspace_path or Path.cwd()).resolve()
        self.tracker = tracker or quota_tracker
        self.store = store or CapsuleStore()
        self.packager = CapsulePackager(workspace_path=self.workspace_path, store=self.store)

    def check_quota(self, provider: str) -> QuotaStatus:
        """Inspects current quota health for an AI provider."""
        return self.tracker.get_status(provider)

    def record_interaction(
        self,
        provider: str,
        tokens_used: int = 0,
        requests_used: int = 1,
        headers: Optional[Dict[str, Any]] = None,
        status_code: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> QuotaStatus:
        """
        Records an API call outcome (tokens, headers, status) and returns updated health.
        """
        if headers:
            self.tracker.record_headers(provider, headers)
        if tokens_used or requests_used:
            self.tracker.record_usage(provider, tokens=tokens_used, requests=requests_used)
        if status_code and (status_code == 429 or status_code >= 400 and error_message):
            self.tracker.record_error(provider, status_code, error_message or "")
        return self.tracker.get_status(provider)

    def evacuate_if_needed(
        self,
        task_id: str,
        provider: str,
        summary: Optional[str] = None,
        title: Optional[str] = None,
        next_action: Optional[str] = None,
        target_provider: Optional[str] = None,
        auto_push_cloud: bool = False,
        cloud_provider: Optional[str] = None,
    ) -> EvacuationResult:
        """
        Checks quota; if rate limit is imminent, preemptively freezes the session,
        packages code changes and epistemic context into a handoff capsule,
        and saves/pushes it so another agent or machine can resume instantly.
        """
        status = self.check_quota(provider)

        if not status.recommend_evacuation:
            return EvacuationResult(
                evacuated=False,
                task_id=task_id,
                provider=provider,
                target_provider=target_provider,
                quota_status=status,
            )

        logger.warning(
            "Preemptive quota evacuation triggered for provider '%s': %s",
            provider,
            status.reason,
        )

        return self.force_evacuate(
            task_id=task_id,
            provider=provider,
            status=status,
            summary=summary or f"Preemptive evacuation: {provider} quota threshold reached",
            title=title,
            next_action=next_action,
            target_provider=target_provider,
            auto_push_cloud=auto_push_cloud,
            cloud_provider=cloud_provider,
        )

    def force_evacuate(
        self,
        task_id: str,
        provider: str,
        summary: str,
        title: Optional[str] = None,
        next_action: Optional[str] = None,
        target_provider: Optional[str] = None,
        status: Optional[QuotaStatus] = None,
        auto_push_cloud: bool = False,
        cloud_provider: Optional[str] = None,
    ) -> EvacuationResult:
        """
        Forces an immediate checkpoint and handoff capsule generation
        before the current agent session terminates.
        """
        status = status or self.check_quota(provider)
        res_next = next_action or f"Resume execution using alternative provider/account ({target_provider or 'pending allocation'})"

        # Epistemic learnings capturing the quota constraint
        learnings = [
            EpistemicLearning(
                category=LearningCategory.ENVIRONMENT,
                summary=f"Preemptive Quota Evacuation: {provider} rate limit approaching",
                details=(
                    f"Session frozen gracefully to prevent 429 mid-execution. "
                    f"Reason: {status.reason or 'Quota limit threshold reached'}. "
                    f"Requests used: {status.requests_used}/{status.max_requests or 'untracked'}, "
                    f"Tokens used: {status.tokens_used}/{status.max_tokens or 'untracked'}. "
                    f"Reset time: {status.reset_at or 'unknown'}."
                ),
            ),
            EpistemicLearning(
                category=LearningCategory.GOTCHA,
                summary=f"Avoid sending further requests to {provider} until quota reset",
                details=f"Provider quota resets at {status.reset_at or 'the start of the next cycle'}.",
            ),
        ]

        target_info = f" Recommended successor provider: '{target_provider}'." if target_provider else ""
        resumption_prompt = (
            f"You are resuming task '{task_id}': {title or task_id}. "
            f"The previous agent was using AI provider '{provider}' and was preemptively evacuated "
            f"right before its rate limit was reached to preserve workspace consistency.{target_info} "
            f"All staged and unstaged code changes, untracked files, and progress have been restored. "
            f"Immediate next step: {res_next}"
        )

        capsule = self.packager.package(
            task_id=task_id,
            title=title or f"{task_id} (Preemptive Quota Evacuation)",
            executive_summary=summary,
            goal=f"Complete task '{task_id}' seamlessly after rate limit handoff",
            next_action=res_next,
            epistemic_learnings=learnings,
            agent_name=f"QuotaGuard[{provider}]",
            target_agent=target_provider or "successor-agent",
            resumption_prompt=resumption_prompt,
        )

        saved_path = self.store.save(capsule)
        cloud_loc = None

        if auto_push_cloud:
            try:
                cloud_loc = self.store.push_to_cloud(capsule, provider_name=cloud_provider)
                logger.info("Evacuation capsule pushed to cloud: %s", cloud_loc)
            except Exception as ex:
                logger.warning("Could not push evacuation capsule to cloud: %s", ex)

        return EvacuationResult(
            evacuated=True,
            task_id=task_id,
            capsule_id=capsule.capsule_id,
            provider=provider,
            target_provider=target_provider,
            quota_status=status,
            saved_path=str(saved_path),
            cloud_location=cloud_loc,
            briefing=capsule.to_briefing_markdown(),
            resumption_prompt=resumption_prompt,
        )
