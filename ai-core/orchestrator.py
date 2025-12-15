"""
Orchestrator - Main coordinator for AI agent operations
"""

import os
import time
import threading
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass

from .agent_manager import AgentManager, Agent
from .queue_manager import QueueManager, QueueItem
from .llm_client import LLMClient
from .websocket_client import WebSocketClient


@dataclass
class TargetConfig:
    target: str
    category: str
    mode: str
    instructions: str
    stealth: bool = False
    aggressive: bool = False


@dataclass 
class Finding:
    severity: str
    title: str
    description: str
    agent_id: int
    timestamp: float
    raw_output: str


class Orchestrator:
    def __init__(self):
        self.agent_manager = AgentManager(max_agents=10)
        self.queue_manager = QueueManager()
        self.llm_client = LLMClient()
        self.ws_client = WebSocketClient()
        
        self.target_config: Optional[TargetConfig] = None
        self.findings: List[Finding] = []
        self.running = False
        self._lock = threading.Lock()
        self._worker_threads: List[threading.Thread] = []
        
        self._callbacks: Dict[str, List[Callable]] = {
            "started": [],
            "stopped": [],
            "finding": [],
            "progress": [],
            "error": [],
            "completed": []
        }
        
        self._setup_callbacks()
    
    def _setup_callbacks(self):
        self.ws_client.on("command_result", self._handle_command_result)
        self.ws_client.on("agent_status", self._handle_agent_status)
        self.ws_client.on("resource_update", self._handle_resource_update)
    
    def configure(self, api_key: str, model_id: str, log_dir: str = "./logs"):
        self.llm_client.set_api_key(api_key)
        self.llm_client.set_model(model_id)
        os.makedirs(log_dir, exist_ok=True)
    
    def set_target(self, target: str, category: str, mode: str, instructions: str = ""):
        self.target_config = TargetConfig(
            target=target,
            category=category,
            mode=mode,
            instructions=instructions,
            stealth=(mode == "stealth"),
            aggressive=(mode == "aggressive")
        )
    
    def add_agent(self, name: str) -> Optional[Agent]:
        agent = self.agent_manager.add_agent(name)
        if agent:
            self.ws_client.add_agent(name)
        return agent
    
    def remove_agent(self, agent_id: int) -> bool:
        success = self.agent_manager.remove_agent(agent_id)
        if success:
            self.ws_client.remove_agent(agent_id)
        return success
    
    def start(self):
        if not self.target_config:
            self._notify("error", "No target configured")
            return
        
        self.running = True
        self._notify("started", self.target_config)
        
        self.ws_client.connect()
        
        response = self.llm_client.generate_plan(
            self.target_config.target,
            self.target_config.category,
            self.target_config.mode,
            self.target_config.instructions
        )
        
        commands = self.llm_client.parse_commands(response)
        if commands:
            self.queue_manager.add_commands(commands)
            self.ws_client.add_to_queue(commands)
        
        for agent in self.agent_manager.get_all_agents():
            thread = threading.Thread(
                target=self._agent_worker,
                args=(agent.id,),
                daemon=True
            )
            thread.start()
            self._worker_threads.append(thread)
    
    def stop(self):
        self.running = False
        self.ws_client.stop()
        self._notify("stopped", None)
    
    def pause(self):
        self.running = False
        self._notify("progress", {"status": "paused"})
    
    def resume(self):
        self.running = True
        self._notify("progress", {"status": "resumed"})
    
    def chat(self, message: str) -> str:
        if message.startswith("/queue "):
            return self._handle_queue_command(message[7:])
        elif message.startswith("/chat "):
            response = self.llm_client.chat(message[6:])
            self.ws_client.chat("/chat", message[6:])
            return response
        else:
            return self.llm_client.chat(message)
    
    def _handle_queue_command(self, command: str) -> str:
        parts = command.split()
        if not parts:
            return "Invalid queue command"
        
        action = parts[0]
        
        if action == "list":
            items = self.queue_manager.get_all()
            return "\n".join([f"{item.index}: {item.command} [{item.status}]" for item in items])
        
        elif action == "rm" and len(parts) > 1:
            try:
                index = int(parts[1])
                success = self.queue_manager.remove(index)
                self.ws_client.remove_from_queue(index)
                return f"Removed item {index}" if success else f"Item {index} not found"
            except ValueError:
                return "Invalid index"
        
        elif action == "add" and len(parts) > 1:
            import json
            try:
                json_str = " ".join(parts[1:])
                commands = json.loads(json_str)
                self.queue_manager.add_commands(commands)
                self.ws_client.add_to_queue(commands)
                return f"Added {len(commands)} commands to queue"
            except json.JSONDecodeError:
                return "Invalid JSON format"
        
        elif action == "clear":
            self.queue_manager.clear()
            return "Queue cleared"
        
        return "Unknown queue command"
    
    def _agent_worker(self, agent_id: int):
        delay = 0.5 if self.target_config and self.target_config.stealth else 0.1
        
        while self.running:
            item = self.queue_manager.get_next_pending()
            if item:
                self.agent_manager.update_agent_status(agent_id, "running", item.command)
                self.ws_client.execute_command(agent_id, item.command)
                
                time.sleep(delay)
            else:
                if self.queue_manager.get_pending_count() == 0 and self.queue_manager.get_running_count() == 0:
                    self._request_more_commands()
                time.sleep(1)
    
    def _request_more_commands(self):
        with self._lock:
            if not self.running:
                return
            
            findings_text = [f.description for f in self.findings[-10:]]
            response = self.llm_client.continue_execution(
                findings_text,
                self.target_config.instructions if self.target_config else ""
            )
            
            if self.llm_client.check_end_signal(response):
                self.running = False
                self._notify("completed", {
                    "findings": len(self.findings),
                    "queue_summary": self.queue_manager.get_summary(),
                    "agent_summary": self.agent_manager.get_summary()
                })
            else:
                commands = self.llm_client.parse_commands(response)
                if commands:
                    self.queue_manager.add_commands(commands)
                    self.ws_client.add_to_queue(commands)
    
    def _handle_command_result(self, result: dict):
        output = result.get("output", "")
        error = result.get("error", "")
        agent_id = result.get("agent_id", 0)
        command = result.get("command", "")
        
        success = result.get("exit_code", 1) == 0
        self.agent_manager.increment_task_count(agent_id, success)
        self.agent_manager.update_agent_status(agent_id, "idle")
        
        if output:
            finding = Finding(
                severity="info",
                title=f"Command Result: {command[:50]}",
                description=output[:500],
                agent_id=agent_id,
                timestamp=time.time(),
                raw_output=output
            )
            self.findings.append(finding)
            self._notify("finding", finding)
    
    def _handle_agent_status(self, status: dict):
        agent_id = status.get("id", 0)
        if agent_id:
            self.agent_manager.update_agent_status(
                agent_id,
                status.get("status", "idle"),
                status.get("current_task", "")
            )
    
    def _handle_resource_update(self, resources: dict):
        pass
    
    def get_findings(self) -> List[Finding]:
        return self.findings
    
    def get_status(self) -> dict:
        return {
            "running": self.running,
            "target": self.target_config.target if self.target_config else None,
            "agents": self.agent_manager.get_summary(),
            "queue": self.queue_manager.get_summary(),
            "findings": len(self.findings)
        }
    
    def on(self, event: str, callback: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(callback)
    
    def _notify(self, event: str, data):
        for callback in self._callbacks.get(event, []):
            try:
                callback(data)
            except Exception as e:
                print(f"Orchestrator callback error: {e}")
    
    def export_findings(self, filepath: str):
        import json
        with open(filepath, "w") as f:
            json.dump([{
                "severity": f.severity,
                "title": f.title,
                "description": f.description,
                "agent_id": f.agent_id,
                "timestamp": f.timestamp
            } for f in self.findings], f, indent=2)
    
    def save_log(self, filepath: str, content: str):
        with open(filepath, "a") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {content}\n")


def main():
    print("[AI] Orchestrator started")
    while True:
        cmd = input("ai> ")
        if cmd.lower() in ("exit", "quit"):
            print("[AI] shutdown")
            break
        print(f"[AI] received task: {cmd}")

if __name__ == "__main__":
    main()
