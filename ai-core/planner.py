"""
Planner - Decomposes goals into executable sub-tasks and manages execution order
"""

import json
import time
import threading
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Tuple
from .goal_system import Goal, GoalType, GoalPriority, GoalStatus, SuccessCriteria


class TaskType(Enum):
    RECON = "reconnaissance"
    SCAN = "scan"
    ENUMERATE = "enumerate"
    ANALYZE = "analyze"
    EXPLOIT = "exploit"
    REPORT = "report"
    CUSTOM = "custom"


class TaskStatus(Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class SubTask:
    id: str
    name: str
    description: str
    task_type: TaskType
    command: str
    goal_id: str
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 5
    dependencies: List[str] = field(default_factory=list)
    estimated_duration: int = 60
    actual_duration: Optional[int] = None
    output: str = ""
    error: str = ""
    agent_id: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "task_type": self.task_type.value,
            "command": self.command,
            "goal_id": self.goal_id,
            "status": self.status.value,
            "priority": self.priority,
            "dependencies": self.dependencies,
            "estimated_duration": self.estimated_duration,
            "actual_duration": self.actual_duration,
            "output": self.output[:500] if self.output else "",
            "agent_id": self.agent_id,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "retry_count": self.retry_count
        }


@dataclass
class ExecutionPlan:
    id: str
    goal_id: str
    name: str
    tasks: List[str]
    phases: Dict[int, List[str]]
    created_at: float = field(default_factory=time.time)
    current_phase: int = 0
    status: str = "pending"
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "goal_id": self.goal_id,
            "name": self.name,
            "tasks": self.tasks,
            "phases": self.phases,
            "current_phase": self.current_phase,
            "status": self.status
        }


class Planner:
    RECON_TOOLS = {
        "ip": [
            ("nmap -sn {target}", "Host discovery"),
            ("nmap -sV -sC {target}", "Service version detection"),
            ("nmap -O {target}", "OS detection"),
        ],
        "url": [
            ("curl -I {target}", "HTTP headers"),
            ("whatweb {target}", "Web technology detection"),
            ("nikto -h {target}", "Web vulnerability scan"),
            ("gobuster dir -u {target} -w /usr/share/wordlists/dirb/common.txt", "Directory enumeration"),
        ],
        "domain": [
            ("whois {target}", "WHOIS lookup"),
            ("dig {target} ANY", "DNS records"),
            ("nslookup {target}", "Name server lookup"),
            ("subfinder -d {target}", "Subdomain enumeration"),
            ("amass enum -d {target}", "Asset discovery"),
        ],
        "path": [
            ("ls -la {target}", "Directory listing"),
            ("find {target} -type f", "File discovery"),
            ("file {target}/*", "File type detection"),
        ]
    }
    
    STEALTH_MODIFIERS = {
        "nmap": "-T2 --scan-delay 1s",
        "gobuster": "-t 1 --delay 1s",
        "nikto": "-Pause 2",
        "curl": "--max-time 30",
    }
    
    AGGRESSIVE_MODIFIERS = {
        "nmap": "-T5 -A --script=vuln",
        "gobuster": "-t 50",
        "nikto": "-Tuning 9",
    }
    
    def __init__(self):
        self.tasks: Dict[str, SubTask] = {}
        self.plans: Dict[str, ExecutionPlan] = {}
        self._lock = threading.Lock()
        self._next_task_id = 1
        self._next_plan_id = 1
        self._callbacks: Dict[str, List[Callable]] = {
            "plan_created": [],
            "task_created": [],
            "task_started": [],
            "task_completed": [],
            "task_failed": [],
            "phase_completed": []
        }
    
    def create_plan(self, goal: Goal, stealth: bool = False, aggressive: bool = False) -> ExecutionPlan:
        target = goal.metadata.get("target", "")
        category = self._detect_category(target)
        
        tasks = self._generate_tasks(goal.id, target, category, stealth, aggressive)
        
        phases = self._organize_into_phases(tasks)
        
        with self._lock:
            plan_id = f"plan_{self._next_plan_id}"
            self._next_plan_id += 1
            
            plan = ExecutionPlan(
                id=plan_id,
                goal_id=goal.id,
                name=f"Plan for {goal.name}",
                tasks=[t.id for t in tasks],
                phases=phases
            )
            
            self.plans[plan_id] = plan
            
            for task in tasks:
                self.tasks[task.id] = task
            
            self._notify("plan_created", plan)
            return plan
    
    def _detect_category(self, target: str) -> str:
        import re
        
        ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}(/\d{1,2})?$'
        if re.match(ip_pattern, target):
            return "ip"
        
        if target.startswith(("http://", "https://")):
            return "url"
        
        if target.startswith("/") or target.startswith("./"):
            return "path"
        
        domain_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$'
        if re.match(domain_pattern, target):
            return "domain"
        
        return "url"
    
    def _generate_tasks(
        self, 
        goal_id: str, 
        target: str, 
        category: str, 
        stealth: bool, 
        aggressive: bool
    ) -> List[SubTask]:
        tasks = []
        tools = self.RECON_TOOLS.get(category, self.RECON_TOOLS["url"])
        
        for i, (cmd_template, description) in enumerate(tools):
            command = cmd_template.format(target=target)
            
            tool_name = command.split()[0]
            if stealth and tool_name in self.STEALTH_MODIFIERS:
                command = self._apply_modifier(command, self.STEALTH_MODIFIERS[tool_name])
            elif aggressive and tool_name in self.AGGRESSIVE_MODIFIERS:
                command = self._apply_modifier(command, self.AGGRESSIVE_MODIFIERS[tool_name])
            
            with self._lock:
                task_id = f"task_{self._next_task_id}"
                self._next_task_id += 1
            
            task = SubTask(
                id=task_id,
                name=description,
                description=f"Execute: {command}",
                task_type=self._get_task_type(tool_name),
                command=f"RUN {command}",
                goal_id=goal_id,
                priority=10 - i,
                estimated_duration=self._estimate_duration(tool_name, stealth)
            )
            
            if i > 0 and len(tasks) > 0:
                pass
            
            tasks.append(task)
            self._notify("task_created", task)
        
        return tasks
    
    def _apply_modifier(self, command: str, modifier: str) -> str:
        parts = command.split()
        tool = parts[0]
        args = parts[1:]
        return f"{tool} {modifier} {' '.join(args)}"
    
    def _get_task_type(self, tool_name: str) -> TaskType:
        recon_tools = ["whois", "dig", "nslookup", "curl", "whatweb"]
        scan_tools = ["nmap", "masscan", "rustscan"]
        enum_tools = ["gobuster", "dirb", "ffuf", "subfinder", "amass"]
        analyze_tools = ["nikto", "nuclei", "wpscan"]
        
        if tool_name in recon_tools:
            return TaskType.RECON
        elif tool_name in scan_tools:
            return TaskType.SCAN
        elif tool_name in enum_tools:
            return TaskType.ENUMERATE
        elif tool_name in analyze_tools:
            return TaskType.ANALYZE
        return TaskType.CUSTOM
    
    def _estimate_duration(self, tool_name: str, stealth: bool) -> int:
        base_durations = {
            "nmap": 120,
            "nikto": 300,
            "gobuster": 180,
            "whois": 5,
            "dig": 3,
            "curl": 5,
            "whatweb": 30,
            "subfinder": 60,
            "amass": 180,
        }
        
        duration = base_durations.get(tool_name, 60)
        if stealth:
            duration *= 3
        return duration
    
    def _organize_into_phases(self, tasks: List[SubTask]) -> Dict[int, List[str]]:
        phases = {
            0: [],
            1: [],
            2: [],
            3: []
        }
        
        for task in tasks:
            if task.task_type == TaskType.RECON:
                phases[0].append(task.id)
            elif task.task_type == TaskType.SCAN:
                phases[1].append(task.id)
            elif task.task_type == TaskType.ENUMERATE:
                phases[2].append(task.id)
            else:
                phases[3].append(task.id)
        
        return {k: v for k, v in phases.items() if v}
    
    def add_custom_task(
        self,
        goal_id: str,
        command: str,
        name: str = "Custom Task",
        priority: int = 5
    ) -> SubTask:
        with self._lock:
            task_id = f"task_{self._next_task_id}"
            self._next_task_id += 1
            
            task = SubTask(
                id=task_id,
                name=name,
                description=f"Custom: {command}",
                task_type=TaskType.CUSTOM,
                command=command if command.startswith("RUN ") else f"RUN {command}",
                goal_id=goal_id,
                priority=priority
            )
            
            self.tasks[task_id] = task
            self._notify("task_created", task)
            return task
    
    def add_tasks_from_llm(self, goal_id: str, commands: Dict[str, str]) -> List[SubTask]:
        tasks = []
        for key in sorted(commands.keys(), key=lambda x: int(x)):
            command = commands[key]
            task = self.add_custom_task(
                goal_id=goal_id,
                command=command,
                name=f"LLM Task {key}",
                priority=10 - int(key)
            )
            tasks.append(task)
        return tasks
    
    def start_task(self, task_id: str, agent_id: int) -> bool:
        with self._lock:
            if task_id not in self.tasks:
                return False
            
            task = self.tasks[task_id]
            task.status = TaskStatus.RUNNING
            task.agent_id = agent_id
            task.started_at = time.time()
            
            self._notify("task_started", task)
            return True
    
    def complete_task(self, task_id: str, output: str, success: bool = True) -> bool:
        with self._lock:
            if task_id not in self.tasks:
                return False
            
            task = self.tasks[task_id]
            task.output = output
            task.completed_at = time.time()
            task.actual_duration = int(task.completed_at - (task.started_at or task.completed_at))
            
            if success:
                task.status = TaskStatus.COMPLETED
                self._notify("task_completed", task)
            else:
                task.retry_count += 1
                if task.retry_count >= task.max_retries:
                    task.status = TaskStatus.FAILED
                    self._notify("task_failed", task)
                else:
                    task.status = TaskStatus.PENDING
            
            return True
    
    def get_next_task(self, plan_id: Optional[str] = None) -> Optional[SubTask]:
        with self._lock:
            pending_tasks = [
                t for t in self.tasks.values() 
                if t.status == TaskStatus.PENDING
            ]
            
            if plan_id and plan_id in self.plans:
                plan = self.plans[plan_id]
                phase_tasks = plan.phases.get(plan.current_phase, [])
                pending_tasks = [t for t in pending_tasks if t.id in phase_tasks]
            
            if not pending_tasks:
                if plan_id and plan_id in self.plans:
                    self._advance_phase(plan_id)
                    return self.get_next_task(plan_id)
                return None
            
            pending_tasks.sort(key=lambda t: (-t.priority, t.created_at))
            
            for task in pending_tasks:
                deps_met = all(
                    self.tasks.get(dep_id, SubTask("", "", "", TaskType.CUSTOM, "", "")).status == TaskStatus.COMPLETED
                    for dep_id in task.dependencies
                )
                if deps_met:
                    return task
            
            return None
    
    def _advance_phase(self, plan_id: str):
        if plan_id not in self.plans:
            return
        
        plan = self.plans[plan_id]
        current_phase_tasks = plan.phases.get(plan.current_phase, [])
        
        all_complete = all(
            self.tasks.get(tid, SubTask("", "", "", TaskType.CUSTOM, "", "")).status in 
            [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED]
            for tid in current_phase_tasks
        )
        
        if all_complete:
            self._notify("phase_completed", {"plan_id": plan_id, "phase": plan.current_phase})
            next_phase = plan.current_phase + 1
            if next_phase in plan.phases:
                plan.current_phase = next_phase
            else:
                plan.status = "completed"
    
    def get_plan_progress(self, plan_id: str) -> dict:
        if plan_id not in self.plans:
            return {}
        
        plan = self.plans[plan_id]
        total = len(plan.tasks)
        completed = sum(
            1 for tid in plan.tasks 
            if tid in self.tasks and self.tasks[tid].status == TaskStatus.COMPLETED
        )
        failed = sum(
            1 for tid in plan.tasks 
            if tid in self.tasks and self.tasks[tid].status == TaskStatus.FAILED
        )
        
        return {
            "plan_id": plan_id,
            "total_tasks": total,
            "completed": completed,
            "failed": failed,
            "current_phase": plan.current_phase,
            "total_phases": len(plan.phases),
            "progress": (completed / total * 100) if total > 0 else 0,
            "status": plan.status
        }
    
    def get_tasks_for_queue(self) -> List[dict]:
        return [t.to_dict() for t in self.tasks.values() if t.status == TaskStatus.PENDING]
    
    def on(self, event: str, callback: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(callback)
    
    def _notify(self, event: str, data):
        for callback in self._callbacks.get(event, []):
            try:
                callback(data)
            except Exception as e:
                print(f"Planner callback error: {e}")
    
    def clear(self):
        with self._lock:
            self.tasks.clear()
            self.plans.clear()
