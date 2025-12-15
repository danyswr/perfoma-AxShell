"""
Goal System - Manages short-term and long-term objectives with success evaluation
"""

import json
import time
import threading
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
from datetime import datetime


class GoalStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class GoalPriority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class GoalType(Enum):
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    MILESTONE = "milestone"


@dataclass
class SuccessCriteria:
    description: str
    metric_type: str
    target_value: Optional[float] = None
    current_value: float = 0.0
    is_met: bool = False
    
    def evaluate(self, value: float) -> bool:
        self.current_value = value
        if self.metric_type == "threshold":
            self.is_met = value >= (self.target_value or 0)
        elif self.metric_type == "boolean":
            self.is_met = value > 0
        elif self.metric_type == "count":
            self.is_met = value >= (self.target_value or 1)
        return self.is_met
    
    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "metric_type": self.metric_type,
            "target_value": self.target_value,
            "current_value": self.current_value,
            "is_met": self.is_met
        }


@dataclass
class Goal:
    id: str
    name: str
    description: str
    goal_type: GoalType
    priority: GoalPriority
    status: GoalStatus = GoalStatus.PENDING
    parent_id: Optional[str] = None
    sub_goals: List[str] = field(default_factory=list)
    success_criteria: List[SuccessCriteria] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    progress: float = 0.0
    findings: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    
    def start(self):
        self.status = GoalStatus.IN_PROGRESS
        self.started_at = time.time()
    
    def complete(self, success: bool = True):
        self.status = GoalStatus.COMPLETED if success else GoalStatus.FAILED
        self.completed_at = time.time()
        self.progress = 100.0 if success else self.progress
    
    def update_progress(self, progress: float):
        self.progress = min(100.0, max(0.0, progress))
    
    def add_finding(self, finding: str):
        self.findings.append(finding)
    
    def evaluate_success(self) -> bool:
        if not self.success_criteria:
            return self.progress >= 100.0
        return all(criteria.is_met for criteria in self.success_criteria)
    
    def get_duration(self) -> Optional[float]:
        if self.started_at:
            end = self.completed_at or time.time()
            return end - self.started_at
        return None
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "goal_type": self.goal_type.value,
            "priority": self.priority.value,
            "status": self.status.value,
            "parent_id": self.parent_id,
            "sub_goals": self.sub_goals,
            "success_criteria": [c.to_dict() for c in self.success_criteria],
            "dependencies": self.dependencies,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "progress": self.progress,
            "findings": self.findings,
            "duration": self.get_duration()
        }


class GoalSystem:
    def __init__(self):
        self.goals: Dict[str, Goal] = {}
        self.active_goals: List[str] = []
        self.goal_history: List[str] = []
        self._lock = threading.Lock()
        self._next_id = 1
        self._callbacks: Dict[str, List[Callable]] = {
            "goal_created": [],
            "goal_started": [],
            "goal_completed": [],
            "goal_failed": [],
            "goal_updated": [],
            "milestone_reached": []
        }
    
    def create_goal(
        self,
        name: str,
        description: str,
        goal_type: GoalType = GoalType.SHORT_TERM,
        priority: GoalPriority = GoalPriority.MEDIUM,
        parent_id: Optional[str] = None,
        success_criteria: Optional[List[SuccessCriteria]] = None,
        dependencies: Optional[List[str]] = None
    ) -> Goal:
        with self._lock:
            goal_id = f"goal_{self._next_id}"
            self._next_id += 1
            
            goal = Goal(
                id=goal_id,
                name=name,
                description=description,
                goal_type=goal_type,
                priority=priority,
                parent_id=parent_id,
                success_criteria=success_criteria or [],
                dependencies=dependencies or []
            )
            
            self.goals[goal_id] = goal
            
            if parent_id and parent_id in self.goals:
                self.goals[parent_id].sub_goals.append(goal_id)
            
            self._notify("goal_created", goal)
            return goal
    
    def create_from_objective(self, objective: str, target: str, mode: str) -> Goal:
        main_goal = self.create_goal(
            name=f"Analyze {target}",
            description=objective,
            goal_type=GoalType.LONG_TERM,
            priority=GoalPriority.HIGH,
            success_criteria=[
                SuccessCriteria(
                    description="Complete all reconnaissance tasks",
                    metric_type="boolean"
                ),
                SuccessCriteria(
                    description="Collect findings",
                    metric_type="count",
                    target_value=1
                )
            ]
        )
        
        main_goal.metadata = {
            "target": target,
            "mode": mode,
            "objective": objective
        }
        
        return main_goal
    
    def start_goal(self, goal_id: str) -> bool:
        with self._lock:
            if goal_id not in self.goals:
                return False
            
            goal = self.goals[goal_id]
            
            for dep_id in goal.dependencies:
                if dep_id in self.goals:
                    dep_goal = self.goals[dep_id]
                    if dep_goal.status != GoalStatus.COMPLETED:
                        return False
            
            goal.start()
            if goal_id not in self.active_goals:
                self.active_goals.append(goal_id)
            
            self._notify("goal_started", goal)
            return True
    
    def complete_goal(self, goal_id: str, success: bool = True) -> bool:
        with self._lock:
            if goal_id not in self.goals:
                return False
            
            goal = self.goals[goal_id]
            goal.complete(success)
            
            if goal_id in self.active_goals:
                self.active_goals.remove(goal_id)
            
            self.goal_history.append(goal_id)
            
            event = "goal_completed" if success else "goal_failed"
            self._notify(event, goal)
            
            if goal.parent_id:
                self._update_parent_progress(goal.parent_id)
            
            return True
    
    def update_goal_progress(self, goal_id: str, progress: float):
        with self._lock:
            if goal_id in self.goals:
                goal = self.goals[goal_id]
                goal.update_progress(progress)
                self._notify("goal_updated", goal)
    
    def add_finding_to_goal(self, goal_id: str, finding: str):
        with self._lock:
            if goal_id in self.goals:
                goal = self.goals[goal_id]
                goal.add_finding(finding)
                
                for criteria in goal.success_criteria:
                    if criteria.metric_type == "count":
                        criteria.evaluate(len(goal.findings))
    
    def evaluate_goal(self, goal_id: str) -> bool:
        if goal_id not in self.goals:
            return False
        
        goal = self.goals[goal_id]
        
        if goal.sub_goals:
            completed_sub = sum(
                1 for sg_id in goal.sub_goals
                if sg_id in self.goals and 
                self.goals[sg_id].status == GoalStatus.COMPLETED
            )
            total_sub = len(goal.sub_goals)
            goal.update_progress((completed_sub / total_sub) * 100 if total_sub > 0 else 0)
        
        return goal.evaluate_success()
    
    def _update_parent_progress(self, parent_id: str):
        if parent_id not in self.goals:
            return
        
        parent = self.goals[parent_id]
        if not parent.sub_goals:
            return
        
        total_progress = 0.0
        for sg_id in parent.sub_goals:
            if sg_id in self.goals:
                total_progress += self.goals[sg_id].progress
        
        avg_progress = total_progress / len(parent.sub_goals)
        parent.update_progress(avg_progress)
        
        if avg_progress >= 100.0 and parent.evaluate_success():
            self._notify("milestone_reached", parent)
    
    def get_goal(self, goal_id: str) -> Optional[Goal]:
        return self.goals.get(goal_id)
    
    def get_active_goals(self) -> List[Goal]:
        return [self.goals[gid] for gid in self.active_goals if gid in self.goals]
    
    def get_goals_by_type(self, goal_type: GoalType) -> List[Goal]:
        return [g for g in self.goals.values() if g.goal_type == goal_type]
    
    def get_pending_goals(self) -> List[Goal]:
        return [g for g in self.goals.values() if g.status == GoalStatus.PENDING]
    
    def get_next_goal(self) -> Optional[Goal]:
        pending = self.get_pending_goals()
        pending.sort(key=lambda g: (-g.priority.value, g.created_at))
        
        for goal in pending:
            deps_satisfied = all(
                self.goals.get(dep_id, Goal("", "", "", GoalType.SHORT_TERM, GoalPriority.LOW)).status == GoalStatus.COMPLETED
                for dep_id in goal.dependencies
            )
            if deps_satisfied:
                return goal
        
        return None
    
    def get_summary(self) -> dict:
        total = len(self.goals)
        completed = sum(1 for g in self.goals.values() if g.status == GoalStatus.COMPLETED)
        failed = sum(1 for g in self.goals.values() if g.status == GoalStatus.FAILED)
        in_progress = sum(1 for g in self.goals.values() if g.status == GoalStatus.IN_PROGRESS)
        pending = sum(1 for g in self.goals.values() if g.status == GoalStatus.PENDING)
        
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "in_progress": in_progress,
            "pending": pending,
            "success_rate": (completed / total * 100) if total > 0 else 0,
            "active_goals": len(self.active_goals)
        }
    
    def on(self, event: str, callback: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(callback)
    
    def _notify(self, event: str, goal: Goal):
        for callback in self._callbacks.get(event, []):
            try:
                callback(goal)
            except Exception as e:
                print(f"Goal callback error: {e}")
    
    def export_goals(self, filepath: str):
        with open(filepath, "w") as f:
            json.dump({
                "goals": {gid: g.to_dict() for gid, g in self.goals.items()},
                "summary": self.get_summary()
            }, f, indent=2)
    
    def clear(self):
        with self._lock:
            self.goals.clear()
            self.active_goals.clear()
            self.goal_history.clear()
