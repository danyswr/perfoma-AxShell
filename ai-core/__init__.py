"""
AI-Core Module for Ax-Shell
Autonomous AI Agent Management System v2.0

Features:
- Goal System: Short/long-term objectives with success evaluation
- Planner: Task decomposition and execution planning
- Memory System: Short-term context + long-term knowledge base
- OTA Loop: Observe-Think-Act autonomous decision cycle
- Agent Collaboration: Inter-agent messaging and shared knowledge
- Resource Monitor: Real-time CPU, RAM, Network, Disk monitoring
"""

from .agent_manager import AgentManager, Agent
from .llm_client import LLMClient, ModelConfig, AVAILABLE_MODELS
from .queue_manager import QueueManager, QueueItem
from .websocket_client import WebSocketClient
from .orchestrator import Orchestrator, TargetConfig, Finding
from .goal_system import GoalSystem, Goal, GoalType, GoalPriority, GoalStatus, SuccessCriteria
from .planner import Planner, SubTask, TaskType, TaskStatus, ExecutionPlan
from .memory_system import MemorySystem, ShortTermMemory, LongTermMemory, MemoryEntry
from .ota_loop import OTALoop, AutonomyLevel, SafetyMode, Observation, Thought, Action
from .agent_collaboration import AgentCollaboration, AgentMessage, MessageType, MessagePriority
from .resource_monitor import ResourceMonitor, ResourceSnapshot, AgentResources, SystemResources

__all__ = [
    'AgentManager', 'Agent',
    'LLMClient', 'ModelConfig', 'AVAILABLE_MODELS',
    'QueueManager', 'QueueItem',
    'WebSocketClient',
    'Orchestrator', 'TargetConfig', 'Finding',
    'GoalSystem', 'Goal', 'GoalType', 'GoalPriority', 'GoalStatus', 'SuccessCriteria',
    'Planner', 'SubTask', 'TaskType', 'TaskStatus', 'ExecutionPlan',
    'MemorySystem', 'ShortTermMemory', 'LongTermMemory', 'MemoryEntry',
    'OTALoop', 'AutonomyLevel', 'SafetyMode', 'Observation', 'Thought', 'Action',
    'AgentCollaboration', 'AgentMessage', 'MessageType', 'MessagePriority',
    'ResourceMonitor', 'ResourceSnapshot', 'AgentResources', 'SystemResources'
]

__version__ = "2.0.0"
