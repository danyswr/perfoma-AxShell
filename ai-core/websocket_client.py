"""
WebSocket Client - Real-time communication with Go backend
"""

import json
import threading
import time
from typing import Callable, Dict, List, Optional
from dataclasses import dataclass


class WebSocketClient:
    def __init__(self, url: str = "ws://localhost:8080/ws"):
        self.url = url
        self.ws = None
        self._connected = False
        self._lock = threading.Lock()
        self._callbacks: Dict[str, List[Callable]] = {
            "connected": [],
            "disconnected": [],
            "message": [],
            "error": [],
            "agent_added": [],
            "agent_removed": [],
            "agent_status": [],
            "queue_updated": [],
            "command_result": [],
            "resource_update": [],
            "chat_message": []
        }
        self._reconnect_thread = None
        self._should_reconnect = True
    
    def connect(self) -> bool:
        try:
            import websocket
            
            self.ws = websocket.WebSocketApp(
                self.url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close
            )
            
            self._ws_thread = threading.Thread(target=self.ws.run_forever, daemon=True)
            self._ws_thread.start()
            
            timeout = 5
            start = time.time()
            while not self._connected and time.time() - start < timeout:
                time.sleep(0.1)
            
            return self._connected
            
        except ImportError:
            print("websocket-client not installed. Using fallback HTTP polling.")
            return self._start_polling()
        except Exception as e:
            self._notify("error", str(e))
            return False
    
    def disconnect(self):
        self._should_reconnect = False
        if self.ws:
            self.ws.close()
        self._connected = False
    
    def is_connected(self) -> bool:
        return self._connected
    
    def send(self, msg_type: str, payload: dict):
        if self.ws and self._connected:
            try:
                message = json.dumps({
                    "type": msg_type,
                    "payload": payload
                })
                self.ws.send(message)
            except Exception as e:
                self._notify("error", str(e))
    
    def add_agent(self, name: str):
        self.send("add_agent", {"name": name})
    
    def remove_agent(self, agent_id: int):
        self.send("remove_agent", {"id": agent_id})
    
    def add_to_queue(self, commands: Dict[str, str]):
        self.send("add_queue", commands)
    
    def get_queue(self):
        self.send("queue_list", {})
    
    def remove_from_queue(self, index: int):
        self.send("queue_rm", {"index": index})
    
    def execute_command(self, agent_id: int, command: str):
        self.send("execute", {
            "agent_id": agent_id,
            "command": command
        })
    
    def chat(self, mode: str, content: str):
        self.send("chat", {
            "mode": mode,
            "content": content
        })
    
    def get_agents(self):
        self.send("get_agents", {})
    
    def get_resources(self):
        self.send("get_resources", {})
    
    def stop(self):
        self.send("stop", {})
    
    def on(self, event: str, callback: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(callback)
    
    def _notify(self, event: str, data):
        for callback in self._callbacks.get(event, []):
            try:
                callback(data)
            except Exception as e:
                print(f"WebSocket callback error: {e}")
    
    def _on_open(self, ws):
        self._connected = True
        self._notify("connected", None)
    
    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")
            payload = data.get("payload", {})
            
            self._notify("message", data)
            
            if msg_type in self._callbacks:
                self._notify(msg_type, payload)
                
        except json.JSONDecodeError:
            self._notify("error", "Invalid JSON received")
    
    def _on_error(self, ws, error):
        self._notify("error", str(error))
    
    def _on_close(self, ws, close_status_code, close_msg):
        self._connected = False
        self._notify("disconnected", {"code": close_status_code, "message": close_msg})
        
        if self._should_reconnect:
            self._schedule_reconnect()
    
    def _schedule_reconnect(self):
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            return
        
        def reconnect():
            time.sleep(5)
            if self._should_reconnect and not self._connected:
                self.connect()
        
        self._reconnect_thread = threading.Thread(target=reconnect, daemon=True)
        self._reconnect_thread.start()
    
    def _start_polling(self) -> bool:
        def poll():
            import requests
            while self._should_reconnect:
                try:
                    base_url = self.url.replace("ws://", "http://").replace("/ws", "")
                    
                    response = requests.get(f"{base_url}/health", timeout=5)
                    if response.status_code == 200:
                        if not self._connected:
                            self._connected = True
                            self._notify("connected", None)
                        
                        agents_resp = requests.get(f"{base_url}/agents", timeout=5)
                        if agents_resp.status_code == 200:
                            self._notify("agent_status", agents_resp.json())
                    else:
                        if self._connected:
                            self._connected = False
                            self._notify("disconnected", {"code": response.status_code})
                            
                except Exception as e:
                    if self._connected:
                        self._connected = False
                        self._notify("disconnected", {"error": str(e)})
                
                time.sleep(2)
        
        self._poll_thread = threading.Thread(target=poll, daemon=True)
        self._poll_thread.start()
        return True
