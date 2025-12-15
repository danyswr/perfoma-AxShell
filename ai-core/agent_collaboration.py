"""
Agent Collaboration - Inter-agent messaging and shared knowledge base
"""

import time
import threading
import json
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from collections import deque


class MessageType(Enum):
    FINDING = "finding"
    REQUEST_HELP = "request_help"
    OFFER_HELP = "offer_help"
    SHARE_KNOWLEDGE = "share_knowledge"
    STATUS_UPDATE = "status_update"
    TASK_HANDOFF = "task_handoff"
    BROADCAST = "broadcast"


class MessagePriority(Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


@dataclass
class AgentMessage:
    id: str
    sender_id: int
    receiver_id: Optional[int]
    message_type: MessageType
    priority: MessagePriority
    content: str
    data: Dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    read: bool = False
    acknowledged: bool = False
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sender_id": self.sender_id,
            "receiver_id": self.receiver_id,
            "message_type": self.message_type.value,
            "priority": self.priority.value,
            "content": self.content,
            "data": self.data,
            "timestamp": self.timestamp,
            "read": self.read,
            "acknowledged": self.acknowledged
        }


@dataclass
class SharedKnowledgeEntry:
    key: str
    value: Any
    contributor_id: int
    timestamp: float = field(default_factory=time.time)
    access_count: int = 0
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "contributor_id": self.contributor_id,
            "timestamp": self.timestamp,
            "access_count": self.access_count,
            "tags": self.tags
        }


class AgentCollaboration:
    def __init__(self):
        self.message_queues: Dict[int, deque] = {}
        self.broadcast_queue: deque = deque(maxlen=100)
        self.shared_knowledge: Dict[str, SharedKnowledgeEntry] = {}
        self.agent_subscriptions: Dict[int, List[str]] = {}
        self.agent_capabilities: Dict[int, List[str]] = {}
        
        self._lock = threading.Lock()
        self._next_message_id = 1
        
        self._callbacks: Dict[str, List[Callable]] = {
            "message_sent": [],
            "message_received": [],
            "knowledge_shared": [],
            "help_requested": [],
            "broadcast": []
        }
    
    def register_agent(self, agent_id: int, capabilities: Optional[List[str]] = None):
        with self._lock:
            if agent_id not in self.message_queues:
                self.message_queues[agent_id] = deque(maxlen=100)
            
            if capabilities:
                self.agent_capabilities[agent_id] = capabilities
            
            self.agent_subscriptions[agent_id] = []
    
    def unregister_agent(self, agent_id: int):
        with self._lock:
            if agent_id in self.message_queues:
                del self.message_queues[agent_id]
            if agent_id in self.agent_capabilities:
                del self.agent_capabilities[agent_id]
            if agent_id in self.agent_subscriptions:
                del self.agent_subscriptions[agent_id]
    
    def send_message(
        self,
        sender_id: int,
        receiver_id: Optional[int],
        message_type: MessageType,
        content: str,
        data: Optional[Dict] = None,
        priority: MessagePriority = MessagePriority.NORMAL
    ) -> AgentMessage:
        with self._lock:
            message_id = f"msg_{self._next_message_id}"
            self._next_message_id += 1
            
            message = AgentMessage(
                id=message_id,
                sender_id=sender_id,
                receiver_id=receiver_id,
                message_type=message_type,
                priority=priority,
                content=content,
                data=data or {}
            )
            
            if receiver_id is None:
                self.broadcast_queue.append(message)
                for queue in self.message_queues.values():
                    queue.append(message)
                self._notify("broadcast", message)
            else:
                if receiver_id in self.message_queues:
                    self.message_queues[receiver_id].append(message)
            
            self._notify("message_sent", message)
            return message
    
    def share_finding(
        self,
        sender_id: int,
        finding: str,
        severity: str,
        tool: str,
        raw_data: Optional[str] = None
    ) -> AgentMessage:
        return self.send_message(
            sender_id=sender_id,
            receiver_id=None,
            message_type=MessageType.FINDING,
            content=finding,
            data={
                "severity": severity,
                "tool": tool,
                "raw_data": raw_data[:500] if raw_data else None
            },
            priority=MessagePriority.HIGH if severity in ["critical", "high"] else MessagePriority.NORMAL
        )
    
    def request_help(
        self,
        sender_id: int,
        task_description: str,
        required_capability: Optional[str] = None
    ) -> AgentMessage:
        message = self.send_message(
            sender_id=sender_id,
            receiver_id=None,
            message_type=MessageType.REQUEST_HELP,
            content=task_description,
            data={"required_capability": required_capability},
            priority=MessagePriority.HIGH
        )
        
        self._notify("help_requested", {
            "sender_id": sender_id,
            "task": task_description,
            "capability": required_capability
        })
        
        return message
    
    def offer_help(
        self,
        sender_id: int,
        receiver_id: int,
        original_request_id: str
    ) -> AgentMessage:
        return self.send_message(
            sender_id=sender_id,
            receiver_id=receiver_id,
            message_type=MessageType.OFFER_HELP,
            content=f"Agent {sender_id} offering help",
            data={"request_id": original_request_id}
        )
    
    def handoff_task(
        self,
        sender_id: int,
        receiver_id: int,
        task_id: str,
        task_data: Dict
    ) -> AgentMessage:
        return self.send_message(
            sender_id=sender_id,
            receiver_id=receiver_id,
            message_type=MessageType.TASK_HANDOFF,
            content=f"Task handoff: {task_id}",
            data={"task_id": task_id, "task_data": task_data},
            priority=MessagePriority.HIGH
        )
    
    def get_messages(self, agent_id: int, unread_only: bool = False) -> List[AgentMessage]:
        if agent_id not in self.message_queues:
            return []
        
        messages = list(self.message_queues[agent_id])
        
        if unread_only:
            messages = [m for m in messages if not m.read]
        
        return sorted(messages, key=lambda m: (-m.priority.value, m.timestamp))
    
    def mark_read(self, agent_id: int, message_id: str):
        if agent_id in self.message_queues:
            for message in self.message_queues[agent_id]:
                if message.id == message_id:
                    message.read = True
                    break
    
    def acknowledge_message(self, agent_id: int, message_id: str):
        if agent_id in self.message_queues:
            for message in self.message_queues[agent_id]:
                if message.id == message_id:
                    message.acknowledged = True
                    break
    
    def share_knowledge(
        self,
        agent_id: int,
        key: str,
        value: Any,
        tags: Optional[List[str]] = None
    ):
        with self._lock:
            entry = SharedKnowledgeEntry(
                key=key,
                value=value,
                contributor_id=agent_id,
                tags=tags or []
            )
            
            self.shared_knowledge[key] = entry
            self._notify("knowledge_shared", entry)
    
    def get_knowledge(self, key: str) -> Optional[Any]:
        entry = self.shared_knowledge.get(key)
        if entry:
            entry.access_count += 1
            return entry.value
        return None
    
    def search_knowledge(self, query: str, tags: Optional[List[str]] = None) -> List[SharedKnowledgeEntry]:
        results = []
        query_lower = query.lower()
        
        for key, entry in self.shared_knowledge.items():
            if query_lower in key.lower():
                results.append(entry)
                continue
            
            if isinstance(entry.value, str) and query_lower in entry.value.lower():
                results.append(entry)
                continue
            
            if tags:
                if any(tag in entry.tags for tag in tags):
                    results.append(entry)
        
        return results
    
    def get_all_knowledge(self) -> Dict[str, Any]:
        return {k: v.to_dict() for k, v in self.shared_knowledge.items()}
    
    def find_capable_agent(self, capability: str) -> Optional[int]:
        for agent_id, capabilities in self.agent_capabilities.items():
            if capability in capabilities:
                return agent_id
        return None
    
    def subscribe(self, agent_id: int, topic: str):
        if agent_id in self.agent_subscriptions:
            if topic not in self.agent_subscriptions[agent_id]:
                self.agent_subscriptions[agent_id].append(topic)
    
    def unsubscribe(self, agent_id: int, topic: str):
        if agent_id in self.agent_subscriptions:
            if topic in self.agent_subscriptions[agent_id]:
                self.agent_subscriptions[agent_id].remove(topic)
    
    def broadcast_to_subscribers(self, topic: str, content: str, data: Optional[Dict] = None):
        for agent_id, subscriptions in self.agent_subscriptions.items():
            if topic in subscriptions:
                self.send_message(
                    sender_id=0,
                    receiver_id=agent_id,
                    message_type=MessageType.BROADCAST,
                    content=content,
                    data={"topic": topic, **(data or {})}
                )
    
    def get_summary(self) -> dict:
        total_messages = sum(len(q) for q in self.message_queues.values())
        unread_count = sum(
            sum(1 for m in q if not m.read)
            for q in self.message_queues.values()
        )
        
        return {
            "registered_agents": len(self.message_queues),
            "total_messages": total_messages,
            "unread_messages": unread_count,
            "broadcast_count": len(self.broadcast_queue),
            "knowledge_entries": len(self.shared_knowledge),
            "agents_with_capabilities": len(self.agent_capabilities)
        }
    
    def on(self, event: str, callback: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(callback)
    
    def _notify(self, event: str, data):
        for callback in self._callbacks.get(event, []):
            try:
                callback(data)
            except Exception as e:
                print(f"Collaboration callback error: {e}")
    
    def clear(self):
        with self._lock:
            self.message_queues.clear()
            self.broadcast_queue.clear()
            self.shared_knowledge.clear()
            self.agent_subscriptions.clear()
