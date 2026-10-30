"""
Live Relay Server
=================
FastAPI + WebSocket hub enabling in-session agent-to-agent pub/sub,
point-to-point messaging, remote procedure calls (RPC), and disk-persisted
unified storage for Context Capsules across fleet machines.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException, Query, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from agent_comms.capsule.server import CapsuleStorageServer
from agent_comms.models.capsule import ContextCapsule
from agent_comms.models.protocol import AgentDescriptor, FrameType, RelayFrame

logger = logging.getLogger("agent_comms.relay.server")


class RelayHub:
    def __init__(self, storage_dir: Optional[Path] = None):
        # agent_id -> WebSocket
        self.connections: Dict[str, WebSocket] = {}
        # agent_id -> AgentDescriptor
        self.peers: Dict[str, AgentDescriptor] = {}
        # topic -> Set[agent_id]
        self.topic_subscribers: Dict[str, Set[str]] = {}
        # Disk-persisted unified capsule storage engine
        self.storage = CapsuleStorageServer(storage_dir=storage_dir)
        self._lock = asyncio.Lock()

    @property
    def capsules(self) -> Dict[str, Dict[str, Any]]:
        """Backwards compatibility for direct dictionary access."""
        return self.storage._index

    async def register_client(self, websocket: WebSocket, descriptor: AgentDescriptor):
        async with self._lock:
            self.connections[descriptor.agent_id] = websocket
            self.peers[descriptor.agent_id] = descriptor
            for topic in descriptor.topics:
                self.topic_subscribers.setdefault(topic, set()).add(descriptor.agent_id)
        logger.info(f"Registered agent: {descriptor.agent_id} on {descriptor.machine_id}")

    async def unregister_client(self, agent_id: str):
        async with self._lock:
            self.connections.pop(agent_id, None)
            self.peers.pop(agent_id, None)
            for subscribers in self.topic_subscribers.values():
                subscribers.discard(agent_id)
        logger.info(f"Unregistered agent: {agent_id}")

    async def subscribe(self, agent_id: str, topic: str):
        async with self._lock:
            self.topic_subscribers.setdefault(topic, set()).add(agent_id)
            if agent_id in self.peers:
                if topic not in self.peers[agent_id].topics:
                    self.peers[agent_id].topics.append(topic)

    async def unsubscribe(self, agent_id: str, topic: str):
        async with self._lock:
            if topic in self.topic_subscribers:
                self.topic_subscribers[topic].discard(agent_id)
            if agent_id in self.peers:
                if topic in self.peers[agent_id].topics:
                    self.peers[agent_id].topics.remove(topic)

    async def send_to_agent(self, target_id: str, frame: RelayFrame) -> bool:
        ws = self.connections.get(target_id)
        if ws:
            try:
                await ws.send_text(frame.model_dump_json())
                return True
            except Exception as e:
                logger.warning(f"Error sending frame to {target_id}: {e}")
                return False
        return False

    async def publish_to_topic(self, topic: str, frame: RelayFrame):
        subscribers = list(self.topic_subscribers.get(topic, set()))
        for sub_id in subscribers:
            if sub_id != frame.sender_id:
                await self.send_to_agent(sub_id, frame)

    def get_peer_descriptors(self) -> List[AgentDescriptor]:
        return list(self.peers.values())


def create_app(
    hub: Optional[RelayHub] = None,
    storage_dir: Optional[Path] = None,
) -> FastAPI:
    app = FastAPI(
        title="Agent Handover & Relay Protocol (AHRP) Hub",
        version="1.1.0",
        description="Real-time message broker and disk-persisted Context Capsule unified storage for AI agents",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if hub is None:
        hub = RelayHub(storage_dir=storage_dir)
    app.state.hub = hub

    @app.get("/health")
    async def health():
        status = hub.storage.get_status()
        return {
            "status": "healthy",
            "active_agents": len(hub.peers),
            "topics": list(hub.topic_subscribers.keys()),
            "total_capsules": status["total_capsules"],
            "storage_dir": status["storage_dir"],
        }

    @app.get("/storage/status")
    async def storage_status():
        return hub.storage.get_status()

    @app.get("/peers", response_model=List[AgentDescriptor])
    async def list_peers():
        return hub.get_peer_descriptors()

    @app.get("/capsules")
    async def list_capsules(
        q: Optional[str] = Query(None, description="Search filter across capsules"),
        task_id: Optional[str] = Query(None, description="Filter by task_id"),
        target_agent: Optional[str] = Query(None, description="Filter by target agent name"),
        limit: int = Query(100, ge=1, le=500),
    ):
        return hub.storage.list_capsules(query=q, task_id=task_id, target_agent=target_agent, limit=limit)

    @app.post("/capsules")
    async def upload_capsule(capsule: Dict[str, Any]):
        cid = capsule.get("capsule_id")
        if not cid:
            raise HTTPException(status_code=400, detail="Missing capsule_id")
        try:
            rec = hub.storage.store_capsule(capsule)
            return {
                "status": "stored",
                "capsule_id": rec["capsule_id"],
                "task_id": rec["task_id"],
                "location": f"/capsules/{rec['capsule_id']}",
            }
        except Exception as e:
            logger.error(f"Error persisting capsule: {e}")
            raise HTTPException(status_code=400, detail=f"Failed to store capsule: {e}")

    @app.get("/capsules/{capsule_id}")
    async def get_capsule(capsule_id: str):
        data = hub.storage.get_capsule(capsule_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"Capsule '{capsule_id}' not found")
        return data

    @app.get("/capsules/{capsule_id}/briefing")
    async def get_briefing(capsule_id: str):
        briefing = hub.storage.get_briefing(capsule_id)
        if briefing is None:
            raise HTTPException(status_code=404, detail=f"Briefing for '{capsule_id}' not found")
        return Response(content=briefing, media_type="text/markdown")

    @app.delete("/capsules/{capsule_id}")
    async def delete_capsule(capsule_id: str):
        success = hub.storage.delete_capsule(capsule_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Capsule '{capsule_id}' not found")
        return {"status": "deleted", "capsule_id": capsule_id}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        registered_agent_id: Optional[str] = None

        try:
            # First frame must be REGISTER
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            init_frame = RelayFrame.model_validate(data)

            if init_frame.type != FrameType.REGISTER:
                await websocket.send_text(
                    RelayFrame(
                        type=FrameType.ERROR,
                        sender_id="server",
                        error="First message must be REGISTER",
                    ).model_dump_json()
                )
                await websocket.close()
                return

            descriptor = AgentDescriptor.model_validate(init_frame.payload)
            registered_agent_id = descriptor.agent_id
            await hub.register_client(websocket, descriptor)

            # Send ACK
            await websocket.send_text(
                RelayFrame(
                    type=FrameType.REGISTER_ACK,
                    sender_id="server",
                    target_id=registered_agent_id,
                    payload={"message": "Connected to AHRP Hub", "agent_id": registered_agent_id},
                ).model_dump_json()
            )

            # Event Loop for this connection
            while True:
                msg = await websocket.receive_text()
                frame_dict = json.loads(msg)
                frame = RelayFrame.model_validate(frame_dict)

                if frame.type == FrameType.SUBSCRIBE and frame.topic:
                    await hub.subscribe(registered_agent_id, frame.topic)

                elif frame.type == FrameType.UNSUBSCRIBE and frame.topic:
                    await hub.unsubscribe(registered_agent_id, frame.topic)

                elif frame.type == FrameType.PUBLISH and frame.topic:
                    await hub.publish_to_topic(frame.topic, frame)

                elif frame.type in (
                    FrameType.MESSAGE,
                    FrameType.RPC_REQUEST,
                    FrameType.RPC_RESPONSE,
                    FrameType.STREAM_CHUNK,
                    FrameType.STREAM_END,
                    FrameType.ACTIVATE_SESSION,
                    FrameType.SESSION_ACTIVATED,
                    FrameType.CAPSULE_TRANSFER,
                ):
                    if frame.target_id:
                        delivered = await hub.send_to_agent(frame.target_id, frame)
                        if not delivered and frame.type == FrameType.RPC_REQUEST:
                            await websocket.send_text(
                                RelayFrame(
                                    type=FrameType.ERROR,
                                    sender_id="server",
                                    target_id=registered_agent_id,
                                    request_id=frame.request_id,
                                    error=f"Target agent '{frame.target_id}' is offline.",
                                ).model_dump_json()
                            )
                    else:
                        for target_id in list(hub.connections.keys()):
                            if target_id != registered_agent_id:
                                await hub.send_to_agent(target_id, frame)

                elif frame.type == FrameType.PEER_LIST_REQ:
                    peers = [p.model_dump() for p in hub.get_peer_descriptors()]
                    await websocket.send_text(
                        RelayFrame(
                            type=FrameType.PEER_LIST_RESP,
                            sender_id="server",
                            target_id=registered_agent_id,
                            request_id=frame.request_id,
                            payload={"peers": peers},
                        ).model_dump_json()
                    )

                elif frame.type == FrameType.HEARTBEAT:
                    await websocket.send_text(
                        RelayFrame(
                            type=FrameType.PONG,
                            sender_id="server",
                            target_id=registered_agent_id,
                        ).model_dump_json()
                    )

        except (WebSocketDisconnect, asyncio.CancelledError):
            if registered_agent_id:
                await hub.unregister_client(registered_agent_id)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            if registered_agent_id:
                await hub.unregister_client(registered_agent_id)

    return app
