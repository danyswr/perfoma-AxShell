"""
WebSocket Client for AI Dashboard
Connects to the Go backend for real-time communication
"""

import os
import json
import threading
import time
from typing import Callable, Dict, Any, Optional

try:
    import websocket
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False


class WebSocketClient:
    def __init__(self, url: str = None):
        self.url = url or os.getenv("WS_URL", "ws://localhost:8080/ws")
        self.ws: Optional[websocket.WebSocketApp] = None
        self.connected = False
        self.terminated = False
        self.callbacks: Dict[str, list] = {}
        self.reconnect_delay = 1
        self.max_reconnect_delay = 30
        self._thread: Optional[threading.Thread] = None
        self._running = False
    
    def on(self, event: str, callback: Callable):
        if event not in self.callbacks:
            self.callbacks[event] = []
        self.callbacks[event].append(callback)
    
    def off(self, event: str, callback: Callable = None):
        if event in self.callbacks:
            if callback:
                self.callbacks[event] = [cb for cb in self.callbacks[event] if cb != callback]
            else:
                self.callbacks[event] = []
    
    def emit(self, event: str, data: Any = None):
        if event in self.callbacks:
            for callback in self.callbacks[event]:
                try:
                    callback(data)
                except Exception as e:
                    print(f"Error in callback for {event}: {e}")
    
    def connect(self):
        if not WEBSOCKET_AVAILABLE:
            print("WebSocket library not available")
            self.emit("error", {"message": "WebSocket library not available"})
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
    
    def _run(self):
        while self._running:
            try:
                self.ws = websocket.WebSocketApp(
                    self.url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close
                )
                self.ws.run_forever()
            except Exception as e:
                print(f"WebSocket connection error: {e}")
            
            if self._running and not self.terminated:
                print(f"Reconnecting in {self.reconnect_delay} seconds...")
                time.sleep(self.reconnect_delay)
                self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)
    
    def _on_open(self, ws):
        self.connected = True
        self.reconnect_delay = 1
        print(f"Connected to WebSocket server at {self.url}")
        self.emit("connected", {"url": self.url})
    
    def _on_message(self, ws, message: str):
        try:
            data = json.loads(message)
            msg_type = data.get("type", "unknown")
            payload = data.get("payload")
            
            if msg_type == "terminated":
                self.terminated = True
            
            self.emit(msg_type, payload)
            self.emit("message", data)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON message: {e}")
    
    def _on_error(self, ws, error):
        print(f"WebSocket error: {error}")
        self.emit("error", {"message": str(error)})
    
    def _on_close(self, ws, close_status_code, close_msg):
        self.connected = False
        print(f"WebSocket closed: {close_status_code} - {close_msg}")
        self.emit("disconnected", {"code": close_status_code, "message": close_msg})
    
    def send(self, msg_type: str, payload: Any = None):
        if not self.connected or not self.ws:
            print("Not connected to WebSocket server")
            return False
        
        try:
            message = json.dumps({"type": msg_type, "payload": payload})
            self.ws.send(message)
            return True
        except Exception as e:
            print(f"Error sending message: {e}")
            return False
    
    def add_agent(self, name: str):
        return self.send("add_agent", {"name": name})
    
    def remove_agent(self, agent_id: int):
        return self.send("remove_agent", {"id": agent_id})
    
    def add_to_queue(self, commands: Dict[str, str]):
        return self.send("add_queue", commands)
    
    def get_queue_list(self):
        return self.send("queue_list")
    
    def remove_from_queue(self, index: int):
        return self.send("queue_rm", {"index": index})
    
    def execute_command(self, agent_id: int, command: str):
        return self.send("execute", {"agent_id": agent_id, "command": command})
    
    def chat(self, mode: str, content: str):
        return self.send("chat", {"mode": mode, "content": content})
    
    def get_agents(self):
        return self.send("get_agents")
    
    def get_resources(self):
        return self.send("get_resources")
    
    def get_logs(self, limit: int = 50, agent_id: int = 0, level: str = ""):
        return self.send("get_logs", {"limit": limit, "agent_id": agent_id, "level": level})
    
    def get_resource_history(self, limit: int = 100):
        return self.send("get_resource_history", {"limit": limit})
    
    def terminate(self):
        return self.send("terminate")
    
    def stop(self):
        return self.send("stop")
    
    def disconnect(self):
        self._running = False
        if self.ws:
            self.ws.close()
        self.connected = False
        self.emit("disconnected", {"reason": "manual"})


class BackendClient:
    """
    HTTP client for REST API calls to the backend
    """
    def __init__(self, base_url: str = None):
        self.base_url = base_url or os.getenv("BACKEND_URL", "http://localhost:8080")
        try:
            import requests
            self.requests = requests
            self.available = True
        except ImportError:
            self.available = False
    
    def _get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        if not self.available:
            return None
        try:
            response = self.requests.get(f"{self.base_url}{endpoint}", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"HTTP GET error: {e}")
            return None
    
    def _post(self, endpoint: str, data: dict = None) -> Optional[dict]:
        if not self.available:
            return None
        try:
            response = self.requests.post(f"{self.base_url}{endpoint}", json=data, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"HTTP POST error: {e}")
            return None
    
    def _delete(self, endpoint: str, data: dict = None) -> Optional[dict]:
        if not self.available:
            return None
        try:
            response = self.requests.delete(f"{self.base_url}{endpoint}", json=data, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"HTTP DELETE error: {e}")
            return None
    
    def health_check(self) -> Optional[dict]:
        return self._get("/health")
    
    def get_agents(self) -> Optional[list]:
        return self._get("/agents")
    
    def add_agent(self, name: str) -> Optional[dict]:
        return self._post("/agents", {"name": name})
    
    def get_queue(self) -> Optional[list]:
        return self._get("/queue")
    
    def add_to_queue(self, commands: dict) -> Optional[dict]:
        return self._post("/queue", commands)
    
    def remove_from_queue(self, index: int) -> Optional[dict]:
        return self._delete("/queue", {"index": index})
    
    def get_logs(self, limit: int = 50, agent_id: int = 0, level: str = "") -> Optional[list]:
        params = {"limit": limit}
        if agent_id > 0:
            params["agent_id"] = agent_id
        if level:
            params["level"] = level
        return self._get("/logs", params)
    
    def get_resource_history(self, limit: int = 100) -> Optional[list]:
        return self._get("/resources/history", {"limit": limit})
    
    def terminate(self) -> Optional[dict]:
        return self._post("/terminate")
