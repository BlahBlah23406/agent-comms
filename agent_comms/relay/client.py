"""
Live Relay Client
=================
Asynchronous WebSocket client allowing any agent to connect to the Relay Hub,
discover peers, publish/subscribe to topics, exchange direct messages,
and issue or handle Remote Procedure Calls (RPC).
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import socket
import uuid
from typing import Any, Callable, Coroutine, Dict, List, Optional
import websockets
from agent_comms.models.protocol import AgentDescriptor, FrameType, RelayFrame

logger = logging.getLogger("agent_comms.relay.client")


class AgentRelayClient:
    def __init__(
        self,
        agent_id: str,
        relay_url: str = "ws://localhost:8765/ws",
        machine_id: Optional[str] = None,
        framework: str = "custom",
        capabilities: Optional[List[str]] = None,
    ):
        self.agent_id = agent_id
        self.relay_url = relay_url
        self.machine_id = machine_id or socket.gethostname()
        self.framework = framework
        self.capabilities = capabilities or ["general"]
        self.ws: Optional[websockets.WebSocketClientProtocol] = None

        # Internal state
        self._connected = False
        self._listen_task: Optional[asyncio.Task] = None
        self._pending_rpc_futures: Dict[str, asyncio.Future] = {}
        self._rpc_handlers: Dict[str, Callable[[Dict[str, Any]], Coroutine[Any, Any, Any]]] = {}
        self._topic_callbacks: Dict[str, List[Callable[[RelayFrame], Coroutine[Any, Any, None]]]] = {}
        self._message_callbacks: List[Callable[[RelayFrame], Coroutine[Any, Any, None]]] = []
        self._activation_callbacks: List[Callable[[RelayFrame], Coroutine[Any, Any, None]]] = []
        self._session_activated_callbacks: List[Callable[[RelayFrame], Coroutine[Any, Any, None]]] = []
        self._capsule_callbacks: List[Callable[[RelayFrame], Coroutine[Any, Any, None]]] = []

    async def connect(self):
        """Connects to the relay hub and performs registration."""
        # Connect with 32MB max frame size for high-fidelity Context Capsules
        self.ws = await websockets.connect(self.relay_url, max_size=32 * 1024 * 1024)
        self._connected = True

        # Send Registration Frame
        descriptor = AgentDescriptor(
            agent_id=self.agent_id,
            machine_id=self.machine_id,
            framework=self.framework,
            capabilities=self.capabilities,
            topics=list(self._topic_callbacks.keys()),
        )
        reg_frame = RelayFrame(
            type=FrameType.REGISTER,
            sender_id=self.agent_id,
            machine_id=self.machine_id,
            payload=descriptor.model_dump(),
        )
        await self.ws.send(reg_frame.model_dump_json())

        # Await ACK
        ack_raw = await self.ws.recv()
        ack = RelayFrame.model_validate(json.loads(ack_raw))
        if ack.type != FrameType.REGISTER_ACK:
            raise ConnectionError(f"Registration failed: {ack}")

        # Start listener loop
        self._listen_task = asyncio.create_task(self._listen_loop())
        logger.info(f"Agent {self.agent_id} successfully connected to {self.relay_url}")

    async def disconnect(self):
        self._connected = False
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self.ws:
            await self.ws.close()
        logger.info(f"Agent {self.agent_id} disconnected.")

    async def _listen_loop(self):
        try:
            while self._connected and self.ws:
                raw_msg = await self.ws.recv()
                frame = RelayFrame.model_validate(json.loads(raw_msg))
                asyncio.create_task(self._dispatch_frame(frame))
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass
        except Exception as e:
            logger.error(f"Error in listener loop: {e}")

    async def _dispatch_frame(self, frame: RelayFrame):
        # 1. Handle RPC Response and Peer List Response
        if frame.type in (FrameType.RPC_RESPONSE, FrameType.ERROR, FrameType.PEER_LIST_RESP):
            req_id = frame.request_id
            if req_id and req_id in self._pending_rpc_futures:
                fut = self._pending_rpc_futures.pop(req_id)
                if not fut.done():
                    if frame.type == FrameType.ERROR:
                        fut.set_exception(RuntimeError(frame.error or "Remote RPC error"))
                    elif frame.type == FrameType.PEER_LIST_RESP:
                        fut.set_result(frame.payload)
                    else:
                        fut.set_result(frame.payload.get("result"))
                return

        # 2. Handle incoming RPC Request
        if frame.type == FrameType.RPC_REQUEST:
            method = frame.payload.get("method")
            params = frame.payload.get("params", {})
            req_id = frame.request_id

            if method in self._rpc_handlers:
                try:
                    result = await self._rpc_handlers[method](params)
                    resp_frame = RelayFrame(
                        type=FrameType.RPC_RESPONSE,
                        sender_id=self.agent_id,
                        machine_id=self.machine_id,
                        target_id=frame.sender_id,
                        request_id=req_id,
                        payload={"result": result},
                    )
                except Exception as ex:
                    resp_frame = RelayFrame(
                        type=FrameType.ERROR,
                        sender_id=self.agent_id,
                        machine_id=self.machine_id,
                        target_id=frame.sender_id,
                        request_id=req_id,
                        error=f"RPC error executing '{method}': {str(ex)}",
                    )
            else:
                resp_frame = RelayFrame(
                    type=FrameType.ERROR,
                    sender_id=self.agent_id,
                    machine_id=self.machine_id,
                    target_id=frame.sender_id,
                    request_id=req_id,
                    error=f"No handler registered for method '{method}'",
                )
            await self._send_frame(resp_frame)
            return

        # 3. Handle Topic Subscriptions
        if frame.topic and frame.topic in self._topic_callbacks:
            for cb in self._topic_callbacks[frame.topic]:
                try:
                    await cb(frame)
                except Exception as e:
                    logger.error(f"Error in topic callback: {e}")

        # 4. Handle Direct Messages
        if frame.type == FrameType.MESSAGE:
            for cb in self._message_callbacks:
                try:
                    await cb(frame)
                except Exception as e:
                    logger.error(f"Error in message callback: {e}")

        # 5. Handle Cross-Session Activation
        if frame.type == FrameType.ACTIVATE_SESSION:
            for cb in self._activation_callbacks:
                try:
                    await cb(frame)
                except Exception as e:
                    logger.error(f"Error in activation callback: {e}")

        # 6. Handle Session Activated confirmation
        if frame.type == FrameType.SESSION_ACTIVATED:
            for cb in self._session_activated_callbacks:
                try:
                    await cb(frame)
                except Exception as e:
                    logger.error(f"Error in session activated callback: {e}")

        # 7. Handle Direct Capsule Transfer
        if frame.type == FrameType.CAPSULE_TRANSFER:
            for cb in self._capsule_callbacks:
                try:
                    await cb(frame)
                except Exception as e:
                    logger.error(f"Error in capsule transfer callback: {e}")

    async def _send_frame(self, frame: RelayFrame):
        if self.ws:
            await self.ws.send(frame.model_dump_json())

    def on_activation(self, callback: Callable[[RelayFrame], Coroutine[Any, Any, None]]):
        """Registers a callback when an activation request is received."""
        self._activation_callbacks.append(callback)

    def on_session_activated(self, callback: Callable[[RelayFrame], Coroutine[Any, Any, None]]):
        """Registers a callback when a peer confirms it has been activated."""
        self._session_activated_callbacks.append(callback)

    def on_capsule_transfer(self, callback: Callable[[RelayFrame], Coroutine[Any, Any, None]]):
        """Registers a callback when a capsule is transferred directly over WebSocket."""
        self._capsule_callbacks.append(callback)

    async def activate_peer(
        self,
        target_id: Optional[str],
        session_id: str,
        relay_url: str,
        capsule_data: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
    ):
        """Sends an ACTIVATE_SESSION frame to wake up a remote standby peer."""
        frame = RelayFrame(
            type=FrameType.ACTIVATE_SESSION,
            sender_id=self.agent_id,
            machine_id=self.machine_id,
            target_id=target_id,
            payload={
                "session_id": session_id,
                "relay_url": relay_url,
                "capsule": capsule_data,
                "task_id": task_id,
            },
        )
        await self._send_frame(frame)

    async def confirm_activated(
        self,
        target_id: str,
        session_id: str,
        status: str = "active",
        details: Optional[Dict[str, Any]] = None,
    ):
        """Sends a SESSION_ACTIVATED frame back to the session initiator."""
        payload = {"session_id": session_id, "status": status}
        if details:
            payload.update(details)
        frame = RelayFrame(
            type=FrameType.SESSION_ACTIVATED,
            sender_id=self.agent_id,
            machine_id=self.machine_id,
            target_id=target_id,
            payload=payload,
        )
        await self._send_frame(frame)

    async def transfer_capsule(self, target_id: str, capsule_dict: Dict[str, Any]):
        """Transfers a ContextCapsule directly over the WebSocket mesh."""
        frame = RelayFrame(
            type=FrameType.CAPSULE_TRANSFER,
            sender_id=self.agent_id,
            machine_id=self.machine_id,
            target_id=target_id,
            payload={"capsule": capsule_dict},
        )
        await self._send_frame(frame)

    def register_rpc_handler(self, method: str, handler: Callable[[Dict[str, Any]], Coroutine[Any, Any, Any]]):
        """Registers a coroutine to handle incoming RPC requests for a method."""
        self._rpc_handlers[method] = handler

    def on_message(self, callback: Callable[[RelayFrame], Coroutine[Any, Any, None]]):
        """Registers a callback for incoming direct messages."""
        self._message_callbacks.append(callback)

    async def subscribe(self, topic: str, callback: Optional[Callable[[RelayFrame], Coroutine[Any, Any, None]]] = None):
        """Subscribes to a broadcast topic."""
        if callback:
            self._topic_callbacks.setdefault(topic, []).append(callback)
        frame = RelayFrame(
            type=FrameType.SUBSCRIBE,
            sender_id=self.agent_id,
            machine_id=self.machine_id,
            topic=topic,
        )
        await self._send_frame(frame)

    async def publish(self, topic: str, payload: Dict[str, Any]):
        """Publishes a message to all subscribers of a topic."""
        frame = RelayFrame(
            type=FrameType.PUBLISH,
            sender_id=self.agent_id,
            machine_id=self.machine_id,
            topic=topic,
            payload=payload,
        )
        await self._send_frame(frame)

    async def send_message(self, target_id: str, payload: Dict[str, Any]):
        """Sends a direct point-to-point message to another agent."""
        frame = RelayFrame(
            type=FrameType.MESSAGE,
            sender_id=self.agent_id,
            machine_id=self.machine_id,
            target_id=target_id,
            payload=payload,
        )
        await self._send_frame(frame)

    async def rpc(self, target_id: str, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 15.0) -> Any:
        """
        Executes a remote procedure call on another agent and awaits the result.
        """
        req_id = f"rpc-{uuid.uuid4().hex[:8]}"
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending_rpc_futures[req_id] = fut

        frame = RelayFrame(
            type=FrameType.RPC_REQUEST,
            sender_id=self.agent_id,
            machine_id=self.machine_id,
            target_id=target_id,
            request_id=req_id,
            payload={"method": method, "params": params or {}},
        )
        await self._send_frame(frame)

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_rpc_futures.pop(req_id, None)
            raise TimeoutError(f"RPC call '{method}' to agent '{target_id}' timed out after {timeout}s.")

    async def list_peers(self, timeout: float = 5.0) -> List[AgentDescriptor]:
        """Queries the relay hub for all currently online agents."""
        req_id = f"peer-{uuid.uuid4().hex[:8]}"
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending_rpc_futures[req_id] = fut

        frame = RelayFrame(
            type=FrameType.PEER_LIST_REQ,
            sender_id=self.agent_id,
            machine_id=self.machine_id,
            request_id=req_id,
        )
        await self._send_frame(frame)

        try:
            # We intercept PEER_LIST_RESP inside the future
            res_dict = await asyncio.wait_for(fut, timeout=timeout)
            return [AgentDescriptor.model_validate(p) for p in res_dict.get("peers", [])]
        except Exception:
            # Fallback direct hook
            self._pending_rpc_futures.pop(req_id, None)
            return []
