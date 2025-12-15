"""
Agent Manager - Handles AI agent lifecycle and coordination
"""

import json
import os
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
from datetime import datetime


@dataclass
class Agent:
    id: int
    name: str
    status: str = "idle"
    current_task: str = ""
    start_time: float = field(default_factory=time.time)
    last_execute: float = field(default_factory=time.time)
    memory_usage: float = 0.0
    cpu_usage: float = 0.0
    network_usage: float = 0.0
    tasks_done: int = 0
    tasks_failed: int = 0
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "current_task": self.current_task,
            "start_time": self.start_time,
            "last_execute": self.last_execute,
            "memory_usage": self.memory_usage,
            "cpu_usage": self.cpu_usage,
            "network_usage": self.network_usage,
            "tasks_done": self.tasks_done,
            "tasks_failed": self.tasks_failed,
            "uptime": time.time() - self.start_time
        }


class AgentManager:
    def __init__(self, max_agents: int = 10):
        self.agents: Dict[int, Agent] = {}
        self.max_agents = max_agents
        self._lock = threading.Lock()
        self._next_id = 1
        self._callbacks: Dict[str, List[Callable]] = {
            "agent_added": [],
            "agent_removed": [],
            "agent_updated": [],
            "status_changed": []
        }
    
    def add_agent(self, name: str) -> Optional[Agent]:
        with self._lock:
            if len(self.agents) >= self.max_agents:
                return None
            
            agent = Agent(
                id=self._next_id,
                name=name
            )
            self.agents[self._next_id] = agent
            self._next_id += 1
            
            self._notify("agent_added", agent)
            return agent
    
    def remove_agent(self, agent_id: int) -> bool:
        with self._lock:
            if agent_id in self.agents:
                agent = self.agents.pop(agent_id)
                self._notify("agent_removed", agent)
                return True
            return False
    
    def get_agent(self, agent_id: int) -> Optional[Agent]:
        return self.agents.get(agent_id)
    
    def get_all_agents(self) -> List[Agent]:
        return list(self.agents.values())
    
    def get_idle_agent(self) -> Optional[Agent]:
        for agent in self.agents.values():
            if agent.status == "idle":
                return agent
        return None
    
    def update_agent_status(self, agent_id: int, status: str, task: str = ""):
        with self._lock:
            if agent_id in self.agents:
                agent = self.agents[agent_id]
                old_status = agent.status
                agent.status = status
                agent.current_task = task
                agent.last_execute = time.time()
                
                if old_status != status:
                    self._notify("status_changed", agent)
                self._notify("agent_updated", agent)
    
    def update_agent_metrics(self, agent_id: int, memory: float, cpu: float, network: float):
        with self._lock:
            if agent_id in self.agents:
                agent = self.agents[agent_id]
                agent.memory_usage = memory
                agent.cpu_usage = cpu
                agent.network_usage = network
                self._notify("agent_updated", agent)
    
    def increment_task_count(self, agent_id: int, success: bool):
        with self._lock:
            if agent_id in self.agents:
                agent = self.agents[agent_id]
                if success:
                    agent.tasks_done += 1
                else:
                    agent.tasks_failed += 1
    
    def on(self, event: str, callback: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(callback)
    
    def _notify(self, event: str, agent: Agent):
        for callback in self._callbacks.get(event, []):
            try:
                callback(agent)
            except Exception as e:
                print(f"Error in callback: {e}")
    
    def get_summary(self) -> dict:
        total = len(self.agents)
        idle = sum(1 for a in self.agents.values() if a.status == "idle")
        running = sum(1 for a in self.agents.values() if a.status == "running")
        
        return {
            "total_agents": total,
            "idle_agents": idle,
            "running_agents": running,
            "max_agents": self.max_agents,
            "total_tasks_done": sum(a.tasks_done for a in self.agents.values()),
            "total_tasks_failed": sum(a.tasks_failed for a in self.agents.values())
        }
