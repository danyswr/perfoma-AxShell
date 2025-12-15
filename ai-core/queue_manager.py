"""
Queue Manager - Handles command queue and distribution
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
from collections import deque


@dataclass
class QueueItem:
    index: int
    command: str
    status: str = "pending"
    output: str = ""
    error: str = ""
    agent_id: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "command": self.command,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "agent_id": self.agent_id,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration": (self.completed_at - self.started_at) if self.completed_at and self.started_at else None
        }


class QueueManager:
    def __init__(self):
        self.queue: List[QueueItem] = []
        self._lock = threading.Lock()
        self._next_index = 1
        self._callbacks: Dict[str, List[Callable]] = {
            "item_added": [],
            "item_removed": [],
            "item_updated": [],
            "queue_cleared": []
        }
    
    def add_commands(self, commands: Dict[str, str]) -> List[QueueItem]:
        added_items = []
        with self._lock:
            for key in sorted(commands.keys(), key=lambda x: int(x)):
                item = QueueItem(
                    index=self._next_index,
                    command=commands[key]
                )
                self.queue.append(item)
                added_items.append(item)
                self._next_index += 1
                self._notify("item_added", item)
        
        return added_items
    
    def add_single(self, command: str) -> QueueItem:
        with self._lock:
            item = QueueItem(
                index=self._next_index,
                command=command
            )
            self.queue.append(item)
            self._next_index += 1
            self._notify("item_added", item)
            return item
    
    def remove(self, index: int) -> bool:
        with self._lock:
            for i, item in enumerate(self.queue):
                if item.index == index:
                    removed = self.queue.pop(i)
                    self._notify("item_removed", removed)
                    return True
            return False
    
    def get_next_pending(self) -> Optional[QueueItem]:
        with self._lock:
            for item in self.queue:
                if item.status == "pending":
                    item.status = "running"
                    item.started_at = time.time()
                    self._notify("item_updated", item)
                    return item
            return None
    
    def update_item(self, index: int, status: str, output: str = "", error: str = "", agent_id: int = None):
        with self._lock:
            for item in self.queue:
                if item.index == index:
                    item.status = status
                    item.output = output
                    item.error = error
                    if agent_id:
                        item.agent_id = agent_id
                    if status in ["completed", "failed"]:
                        item.completed_at = time.time()
                    self._notify("item_updated", item)
                    return
    
    def get_all(self) -> List[QueueItem]:
        return list(self.queue)
    
    def get_pending_count(self) -> int:
        return sum(1 for item in self.queue if item.status == "pending")
    
    def get_running_count(self) -> int:
        return sum(1 for item in self.queue if item.status == "running")
    
    def clear(self):
        with self._lock:
            self.queue = []
            self._notify("queue_cleared", None)
    
    def clear_completed(self):
        with self._lock:
            self.queue = [item for item in self.queue if item.status not in ["completed", "failed"]]
    
    def on(self, event: str, callback: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(callback)
    
    def _notify(self, event: str, item: Optional[QueueItem]):
        for callback in self._callbacks.get(event, []):
            try:
                callback(item)
            except Exception as e:
                print(f"Callback error: {e}")
    
    def get_summary(self) -> dict:
        return {
            "total": len(self.queue),
            "pending": self.get_pending_count(),
            "running": self.get_running_count(),
            "completed": sum(1 for item in self.queue if item.status == "completed"),
            "failed": sum(1 for item in self.queue if item.status == "failed")
        }
