"""
Observe-Think-Act Loop - Core autonomous decision-making cycle
"""

import time
import threading
import json
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from .goal_system import GoalSystem, Goal, GoalStatus
from .planner import Planner, SubTask, TaskStatus
from .memory_system import MemorySystem


class AutonomyLevel(Enum):
    MANUAL = 0
    SUPERVISED = 1
    SEMI_AUTONOMOUS = 2
    AUTONOMOUS = 3
    FULL_AUTONOMOUS = 4


class SafetyMode(Enum):
    STRICT = "strict"
    MODERATE = "moderate"
    PERMISSIVE = "permissive"


@dataclass
class Observation:
    timestamp: float
    observation_type: str
    data: Dict
    source: str
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "type": self.observation_type,
            "data": self.data,
            "source": self.source
        }


@dataclass
class Thought:
    timestamp: float
    reasoning: str
    conclusions: List[str]
    proposed_actions: List[Dict]
    confidence: float
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "reasoning": self.reasoning,
            "conclusions": self.conclusions,
            "proposed_actions": self.proposed_actions,
            "confidence": self.confidence
        }


@dataclass
class Action:
    id: str
    action_type: str
    parameters: Dict
    requires_approval: bool = False
    approved: bool = True
    executed: bool = False
    result: Optional[Dict] = None
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.action_type,
            "parameters": self.parameters,
            "requires_approval": self.requires_approval,
            "approved": self.approved,
            "executed": self.executed,
            "result": self.result,
            "timestamp": self.timestamp
        }


class OTALoop:
    DANGEROUS_COMMANDS = [
        "rm -rf", "mkfs", "dd if=", "> /dev/", 
        "chmod -R 777", ":(){:|:&};:", "wget | sh",
        "curl | bash", "shutdown", "reboot", "halt"
    ]
    
    ALLOWED_TOOLS = [
        "nmap", "nikto", "gobuster", "dirb", "ffuf",
        "whatweb", "whois", "dig", "nslookup", "curl",
        "wget", "subfinder", "amass", "nuclei", "httpx",
        "masscan", "rustscan", "wpscan", "sqlmap", "hydra",
        "ls", "cat", "head", "tail", "grep", "find", "file"
    ]
    
    def __init__(
        self,
        goal_system: GoalSystem,
        planner: Planner,
        memory: MemorySystem,
        llm_client = None,
        executor = None
    ):
        self.goal_system = goal_system
        self.planner = planner
        self.memory = memory
        self.llm_client = llm_client
        self.executor = executor
        
        self.autonomy_level = AutonomyLevel.SUPERVISED
        self.safety_mode = SafetyMode.MODERATE
        
        self.running = False
        self.paused = False
        self.loop_count = 0
        self.max_loops = 100
        self.loop_delay = 1.0
        
        self.observations: List[Observation] = []
        self.thoughts: List[Thought] = []
        self.actions: List[Action] = []
        self.pending_approvals: List[Action] = []
        
        self._lock = threading.Lock()
        self._loop_thread: Optional[threading.Thread] = None
        self._next_action_id = 1
        
        self._callbacks: Dict[str, List[Callable]] = {
            "observation": [],
            "thought": [],
            "action_proposed": [],
            "action_executed": [],
            "approval_required": [],
            "loop_iteration": [],
            "error": []
        }
    
    def set_autonomy_level(self, level: AutonomyLevel):
        self.autonomy_level = level
    
    def set_safety_mode(self, mode: SafetyMode):
        self.safety_mode = mode
    
    def start(self):
        if self.running:
            return
        
        self.running = True
        self.paused = False
        self.loop_count = 0
        
        self._loop_thread = threading.Thread(target=self._main_loop, daemon=True)
        self._loop_thread.start()
    
    def stop(self):
        self.running = False
        if self._loop_thread:
            self._loop_thread.join(timeout=5)
    
    def pause(self):
        self.paused = True
    
    def resume(self):
        self.paused = False
    
    def _main_loop(self):
        while self.running and self.loop_count < self.max_loops:
            if self.paused:
                time.sleep(0.5)
                continue
            
            try:
                self.loop_count += 1
                self._notify("loop_iteration", {"count": self.loop_count})
                
                observation = self._observe()
                if observation:
                    self.observations.append(observation)
                    self._notify("observation", observation)
                
                thought = self._think(observation)
                if thought:
                    self.thoughts.append(thought)
                    self._notify("thought", thought)
                
                for proposed_action in thought.proposed_actions if thought else []:
                    action = self._prepare_action(proposed_action)
                    if action:
                        self._act(action)
                
                if self._check_completion():
                    self.running = False
                    break
                
                time.sleep(self.loop_delay)
                
            except Exception as e:
                self._notify("error", {"error": str(e), "loop": self.loop_count})
                time.sleep(2)
    
    def _observe(self) -> Optional[Observation]:
        observations_data = {}
        
        active_goals = self.goal_system.get_active_goals()
        if active_goals:
            observations_data["active_goals"] = [
                {"id": g.id, "name": g.name, "progress": g.progress, "status": g.status.value}
                for g in active_goals
            ]
        
        pending_tasks = [t for t in self.planner.tasks.values() if t.status == TaskStatus.PENDING]
        running_tasks = [t for t in self.planner.tasks.values() if t.status == TaskStatus.RUNNING]
        
        observations_data["tasks"] = {
            "pending": len(pending_tasks),
            "running": len(running_tasks),
            "next_task": pending_tasks[0].to_dict() if pending_tasks else None
        }
        
        observations_data["memory_context"] = self.memory.short_term.get_summary()
        
        recent_findings = self.memory.short_term.get_recent_findings()
        if recent_findings:
            observations_data["recent_findings"] = recent_findings[-3:]
        
        if not observations_data.get("active_goals") and not observations_data.get("tasks", {}).get("pending"):
            return None
        
        return Observation(
            timestamp=time.time(),
            observation_type="state_update",
            data=observations_data,
            source="ota_loop"
        )
    
    def _think(self, observation: Optional[Observation]) -> Optional[Thought]:
        if not observation:
            return None
        
        reasoning_parts = []
        conclusions = []
        proposed_actions = []
        confidence = 0.8
        
        tasks_data = observation.data.get("tasks", {})
        next_task = tasks_data.get("next_task")
        
        if next_task:
            reasoning_parts.append(f"Found pending task: {next_task.get('name', 'Unknown')}")
            conclusions.append("Should execute the next pending task")
            
            proposed_actions.append({
                "type": "execute_task",
                "task_id": next_task.get("id"),
                "command": next_task.get("command", "")
            })
        
        active_goals = observation.data.get("active_goals", [])
        for goal_data in active_goals:
            if goal_data.get("progress", 0) < 50:
                reasoning_parts.append(f"Goal '{goal_data.get('name')}' needs more progress")
        
        recent_findings = observation.data.get("recent_findings", [])
        for finding in recent_findings:
            if finding.get("severity") in ["critical", "high"]:
                reasoning_parts.append(f"High-severity finding detected: {finding.get('content', '')[:50]}")
                conclusions.append("May need to prioritize based on critical findings")
        
        if not proposed_actions:
            if not tasks_data.get("pending") and self.llm_client:
                reasoning_parts.append("No pending tasks, may need to generate more")
                proposed_actions.append({
                    "type": "request_more_tasks",
                    "context": self.memory.get_context_for_llm()
                })
        
        if not reasoning_parts:
            return None
        
        return Thought(
            timestamp=time.time(),
            reasoning=" | ".join(reasoning_parts),
            conclusions=conclusions,
            proposed_actions=proposed_actions,
            confidence=confidence
        )
    
    def _prepare_action(self, proposed: Dict) -> Optional[Action]:
        with self._lock:
            action_id = f"action_{self._next_action_id}"
            self._next_action_id += 1
        
        action_type = proposed.get("type", "unknown")
        requires_approval = self._check_requires_approval(proposed)
        
        action = Action(
            id=action_id,
            action_type=action_type,
            parameters=proposed,
            requires_approval=requires_approval,
            approved=not requires_approval
        )
        
        self.actions.append(action)
        
        if requires_approval:
            self.pending_approvals.append(action)
            self._notify("approval_required", action)
            return None
        
        return action
    
    def _check_requires_approval(self, proposed: Dict) -> bool:
        if self.autonomy_level == AutonomyLevel.MANUAL:
            return True
        
        if self.autonomy_level == AutonomyLevel.FULL_AUTONOMOUS:
            return False
        
        command = proposed.get("command", "")
        
        if self.safety_mode == SafetyMode.STRICT:
            return True
        
        if self._is_dangerous_command(command):
            return True
        
        if self.autonomy_level == AutonomyLevel.SUPERVISED:
            action_type = proposed.get("type", "")
            if action_type in ["execute_task", "execute_command"]:
                return True
        
        return False
    
    def _is_dangerous_command(self, command: str) -> bool:
        command_lower = command.lower()
        
        for dangerous in self.DANGEROUS_COMMANDS:
            if dangerous in command_lower:
                return True
        
        return False
    
    def _is_allowed_tool(self, command: str) -> bool:
        if command.startswith("RUN "):
            command = command[4:]
        
        tool = command.split()[0] if command else ""
        return tool in self.ALLOWED_TOOLS
    
    def _act(self, action: Action):
        if not action.approved:
            return
        
        self._notify("action_proposed", action)
        
        try:
            result = self._execute_action(action)
            action.result = result
            action.executed = True
            self._notify("action_executed", action)
            
        except Exception as e:
            action.result = {"error": str(e)}
            action.executed = False
            self._notify("error", {"action": action.id, "error": str(e)})
    
    def _execute_action(self, action: Action) -> Dict:
        action_type = action.action_type
        params = action.parameters
        
        if action_type == "execute_task":
            task_id = params.get("task_id")
            command = params.get("command", "")
            
            if self.executor:
                result = self.executor.execute_command(1, command)
                
                if task_id:
                    success = result.get("exit_code", 1) == 0
                    self.planner.complete_task(task_id, result.get("output", ""), success)
                
                return result
            
            return {"status": "no_executor", "command": command}
        
        elif action_type == "request_more_tasks":
            if self.llm_client:
                context = params.get("context", "")
                active_goals = self.goal_system.get_active_goals()
                
                if active_goals:
                    goal = active_goals[0]
                    response = self.llm_client.continue_execution(
                        [f.content for f in self.memory.short_term.recent_findings],
                        goal.description
                    )
                    
                    commands = self.llm_client.parse_commands(response)
                    if commands:
                        tasks = self.planner.add_tasks_from_llm(goal.id, commands)
                        return {"status": "tasks_added", "count": len(tasks)}
                    
                    if self.llm_client.check_end_signal(response):
                        return {"status": "completed", "signal": "END"}
            
            return {"status": "no_llm_client"}
        
        return {"status": "unknown_action_type"}
    
    def _check_completion(self) -> bool:
        active_goals = self.goal_system.get_active_goals()
        
        for goal in active_goals:
            if self.goal_system.evaluate_goal(goal.id):
                self.goal_system.complete_goal(goal.id, True)
        
        pending_tasks = [t for t in self.planner.tasks.values() if t.status == TaskStatus.PENDING]
        running_tasks = [t for t in self.planner.tasks.values() if t.status == TaskStatus.RUNNING]
        
        if not active_goals and not pending_tasks and not running_tasks:
            return True
        
        return False
    
    def approve_action(self, action_id: str) -> bool:
        for action in self.pending_approvals:
            if action.id == action_id:
                action.approved = True
                self.pending_approvals.remove(action)
                self._act(action)
                return True
        return False
    
    def reject_action(self, action_id: str) -> bool:
        for action in self.pending_approvals:
            if action.id == action_id:
                action.approved = False
                self.pending_approvals.remove(action)
                return True
        return False
    
    def get_pending_approvals(self) -> List[Action]:
        return self.pending_approvals.copy()
    
    def inject_observation(self, observation_type: str, data: Dict, source: str = "external"):
        observation = Observation(
            timestamp=time.time(),
            observation_type=observation_type,
            data=data,
            source=source
        )
        self.observations.append(observation)
        self._notify("observation", observation)
    
    def get_state(self) -> dict:
        return {
            "running": self.running,
            "paused": self.paused,
            "loop_count": self.loop_count,
            "autonomy_level": self.autonomy_level.name,
            "safety_mode": self.safety_mode.value,
            "pending_approvals": len(self.pending_approvals),
            "total_observations": len(self.observations),
            "total_thoughts": len(self.thoughts),
            "total_actions": len(self.actions)
        }
    
    def on(self, event: str, callback: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(callback)
    
    def _notify(self, event: str, data):
        for callback in self._callbacks.get(event, []):
            try:
                callback(data)
            except Exception as e:
                print(f"OTA callback error: {e}")
