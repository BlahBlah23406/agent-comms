"""
Cloud Storage Provider Base
===========================
Abstract interface and metadata schema for cloud-based capsule repositories.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from agent_comms.models.capsule import ContextCapsule


class CloudCapsuleRecord(BaseModel):
    """Metadata describing a capsule stored in a cloud provider."""
    capsule_id: str
    task_id: str
    created_at: str
    title: Optional[str] = None
    summary: Optional[str] = None
    provider: str
    location: str  # URL, S3 URI, Gist ID, or path
    size_bytes: Optional[int] = None


class BaseCloudProvider(ABC):
    """Abstract base class for cloud capsule storage backends."""

    name: str = "base"

    @abstractmethod
    def upload(self, capsule: ContextCapsule) -> str:
        """
        Uploads a ContextCapsule to cloud storage.
        Returns a persistent reference URI or locator string.
        """
        pass

    @abstractmethod
    def download(self, capsule_id_or_uri: str) -> ContextCapsule:
        """
        Downloads and validates a ContextCapsule from cloud storage.
        """
        pass

    @abstractmethod
    def list_capsules(self) -> List[CloudCapsuleRecord]:
        """
        Lists all available capsules stored under this provider.
        """
        pass

    @abstractmethod
    def delete(self, capsule_id_or_uri: str) -> bool:
        """
        Deletes a capsule from cloud storage.
        """
        pass
