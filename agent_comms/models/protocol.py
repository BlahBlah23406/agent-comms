"""
Live Relay Protocol Frame Models
================================
Defines the wire protocol frames for real-time agent-to-agent communication,
topic pub/sub, direct messaging, streaming, and remote procedure calls (RPC).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class FrameType(str, Enum):
    REGISTER = "register"
    REGISTER_ACK = "register_ack"
    PEER_LIST_REQ = "peer_list_req"
    PEER_LIST_RESP = "peer_list_resp"
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    PUBLISH = "publish"
    MESSAGE = "message"
    RPC_REQUEST = "rpc_request"
    RPC_RESPONSE = "rpc_response"
    STREAM_CHUNK = "stream_chunk"
    STREAM_END = "stream_end"
    HEARTBEAT = "heartbeat"
    PONG = "pong"
    ERROR = "error"


class AgentDescriptor(BaseModel):
    agent_id: str = Field(..., description="Unique agent identifier e.g. laptop-antigravity")
    machine_id: str = Field(..., description="Machine/Host identifier")
    framework: str = Field("custom", description="e.g. Antigravity, Claude, AutoGen")
    capabilities: List[str] = Field(default_factory=list, description="Supported operations e.g. [code_exec, gpu, git]")
    topics: List[str] = Field(default_factory=list, description="Subscribed topics")
    connected_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RelayFrame(BaseModel):
    frame_id: str = Field(default_factory=lambda: f"frm-{uuid.uuid4().hex[:12]}")
    type: FrameType
    sender_id: str
    machine_id: str = "unknown"
    target_id: Optional[str] = None     # Specific agent ID (for direct/RPC) or None
    topic: Optional[str] = None         # Topic name (for publish/subscribe)
    request_id: Optional[str] = None    # Correlates RPC response with request
    payload: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
