"""
Resource Monitor - Real-time monitoring of CPU, RAM, Network, and Disk I/O per agent
"""

import time
import threading
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
from collections import deque


@dataclass
class ResourceSnapshot:
    timestamp: float
    cpu_percent: float
    memory_mb: float
    memory_percent: float
    network_rx_bytes: int
    network_tx_bytes: int
    disk_read_bytes: int
    disk_write_bytes: int
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "cpu_percent": round(self.cpu_percent, 2),
            "memory_mb": round(self.memory_mb, 2),
            "memory_percent": round(self.memory_percent, 2),
            "network_rx_mb": round(self.network_rx_bytes / 1024 / 1024, 2),
            "network_tx_mb": round(self.network_tx_bytes / 1024 / 1024, 2),
            "disk_read_mb": round(self.disk_read_bytes / 1024 / 1024, 2),
            "disk_write_mb": round(self.disk_write_bytes / 1024 / 1024, 2)
        }


@dataclass
class AgentResources:
    agent_id: int
    history: deque = field(default_factory=lambda: deque(maxlen=60))
    current: Optional[ResourceSnapshot] = None
    peak_cpu: float = 0.0
    peak_memory: float = 0.0
    total_network_rx: int = 0
    total_network_tx: int = 0
    total_disk_read: int = 0
    total_disk_write: int = 0
    alert_threshold_cpu: float = 80.0
    alert_threshold_memory: float = 80.0
    
    def add_snapshot(self, snapshot: ResourceSnapshot):
        self.history.append(snapshot)
        self.current = snapshot
        
        self.peak_cpu = max(self.peak_cpu, snapshot.cpu_percent)
        self.peak_memory = max(self.peak_memory, snapshot.memory_percent)
        
        if len(self.history) > 1:
            prev = self.history[-2]
            self.total_network_rx += max(0, snapshot.network_rx_bytes - prev.network_rx_bytes)
            self.total_network_tx += max(0, snapshot.network_tx_bytes - prev.network_tx_bytes)
            self.total_disk_read += max(0, snapshot.disk_read_bytes - prev.disk_read_bytes)
            self.total_disk_write += max(0, snapshot.disk_write_bytes - prev.disk_write_bytes)
    
    def get_average(self, period: int = 10) -> dict:
        if not self.history:
            return {"cpu": 0, "memory": 0}
        
        recent = list(self.history)[-period:]
        return {
            "cpu": sum(s.cpu_percent for s in recent) / len(recent),
            "memory": sum(s.memory_percent for s in recent) / len(recent)
        }
    
    def check_alerts(self) -> List[str]:
        alerts = []
        if self.current:
            if self.current.cpu_percent > self.alert_threshold_cpu:
                alerts.append(f"CPU usage high: {self.current.cpu_percent:.1f}%")
            if self.current.memory_percent > self.alert_threshold_memory:
                alerts.append(f"Memory usage high: {self.current.memory_percent:.1f}%")
        return alerts
    
    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "current": self.current.to_dict() if self.current else None,
            "peak_cpu": round(self.peak_cpu, 2),
            "peak_memory": round(self.peak_memory, 2),
            "total_network_rx_mb": round(self.total_network_rx / 1024 / 1024, 2),
            "total_network_tx_mb": round(self.total_network_tx / 1024 / 1024, 2),
            "total_disk_read_mb": round(self.total_disk_read / 1024 / 1024, 2),
            "total_disk_write_mb": round(self.total_disk_write / 1024 / 1024, 2),
            "average_10s": self.get_average(10)
        }


class SystemResources:
    def __init__(self):
        self.cpu_percent: float = 0.0
        self.memory_total: int = 0
        self.memory_used: int = 0
        self.memory_percent: float = 0.0
        self.disk_total: int = 0
        self.disk_used: int = 0
        self.disk_percent: float = 0.0
        self.network_interfaces: Dict[str, Dict] = {}
        self.uptime: float = 0.0
        self.load_average: tuple = (0.0, 0.0, 0.0)
    
    def update(self):
        try:
            with open("/proc/stat", "r") as f:
                cpu_line = f.readline()
                cpu_values = list(map(int, cpu_line.split()[1:8]))
                idle = cpu_values[3]
                total = sum(cpu_values)
                
                if hasattr(self, '_prev_idle') and hasattr(self, '_prev_total'):
                    idle_delta = idle - self._prev_idle
                    total_delta = total - self._prev_total
                    if total_delta > 0:
                        self.cpu_percent = 100.0 * (1.0 - idle_delta / total_delta)
                
                self._prev_idle = idle
                self._prev_total = total
        except Exception:
            pass
        
        try:
            with open("/proc/meminfo", "r") as f:
                lines = f.readlines()
                mem_info = {}
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 2:
                        mem_info[parts[0].rstrip(':')] = int(parts[1])
                
                self.memory_total = mem_info.get('MemTotal', 0) * 1024
                mem_available = mem_info.get('MemAvailable', 0) * 1024
                self.memory_used = self.memory_total - mem_available
                self.memory_percent = (self.memory_used / self.memory_total * 100) if self.memory_total > 0 else 0
        except Exception:
            pass
        
        try:
            statvfs = os.statvfs("/")
            self.disk_total = statvfs.f_blocks * statvfs.f_frsize
            self.disk_used = (statvfs.f_blocks - statvfs.f_bfree) * statvfs.f_frsize
            self.disk_percent = (self.disk_used / self.disk_total * 100) if self.disk_total > 0 else 0
        except Exception:
            pass
        
        try:
            with open("/proc/loadavg", "r") as f:
                parts = f.read().split()
                self.load_average = (float(parts[0]), float(parts[1]), float(parts[2]))
        except Exception:
            pass
        
        try:
            with open("/proc/uptime", "r") as f:
                self.uptime = float(f.read().split()[0])
        except Exception:
            pass
    
    def to_dict(self) -> dict:
        return {
            "cpu_percent": round(self.cpu_percent, 2),
            "memory_total_gb": round(self.memory_total / 1024 / 1024 / 1024, 2),
            "memory_used_gb": round(self.memory_used / 1024 / 1024 / 1024, 2),
            "memory_percent": round(self.memory_percent, 2),
            "disk_total_gb": round(self.disk_total / 1024 / 1024 / 1024, 2),
            "disk_used_gb": round(self.disk_used / 1024 / 1024 / 1024, 2),
            "disk_percent": round(self.disk_percent, 2),
            "load_average": self.load_average,
            "uptime_hours": round(self.uptime / 3600, 2)
        }


class ResourceMonitor:
    def __init__(self, update_interval: float = 2.0):
        self.update_interval = update_interval
        self.agent_resources: Dict[int, AgentResources] = {}
        self.system_resources = SystemResources()
        self.history: deque = deque(maxlen=300)
        
        self.running = False
        self._lock = threading.Lock()
        self._monitor_thread: Optional[threading.Thread] = None
        
        self._callbacks: Dict[str, List[Callable]] = {
            "update": [],
            "alert": [],
            "agent_alert": []
        }
        
        self._net_rx_prev = 0
        self._net_tx_prev = 0
        self._disk_read_prev = 0
        self._disk_write_prev = 0
    
    def register_agent(self, agent_id: int):
        with self._lock:
            if agent_id not in self.agent_resources:
                self.agent_resources[agent_id] = AgentResources(agent_id=agent_id)
    
    def unregister_agent(self, agent_id: int):
        with self._lock:
            if agent_id in self.agent_resources:
                del self.agent_resources[agent_id]
    
    def start(self):
        if self.running:
            return
        
        self.running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
    
    def stop(self):
        self.running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
    
    def _monitor_loop(self):
        while self.running:
            try:
                self._update()
                time.sleep(self.update_interval)
            except Exception as e:
                print(f"Resource monitor error: {e}")
                time.sleep(5)
    
    def _update(self):
        self.system_resources.update()
        
        net_rx, net_tx = self._get_network_stats()
        disk_read, disk_write = self._get_disk_stats()
        
        system_snapshot = ResourceSnapshot(
            timestamp=time.time(),
            cpu_percent=self.system_resources.cpu_percent,
            memory_mb=self.system_resources.memory_used / 1024 / 1024,
            memory_percent=self.system_resources.memory_percent,
            network_rx_bytes=net_rx,
            network_tx_bytes=net_tx,
            disk_read_bytes=disk_read,
            disk_write_bytes=disk_write
        )
        
        self.history.append(system_snapshot)
        
        num_agents = len(self.agent_resources)
        if num_agents > 0:
            for agent_id, agent_res in self.agent_resources.items():
                agent_snapshot = ResourceSnapshot(
                    timestamp=time.time(),
                    cpu_percent=self.system_resources.cpu_percent / num_agents,
                    memory_mb=self.system_resources.memory_used / 1024 / 1024 / num_agents,
                    memory_percent=self.system_resources.memory_percent / num_agents,
                    network_rx_bytes=net_rx,
                    network_tx_bytes=net_tx,
                    disk_read_bytes=disk_read,
                    disk_write_bytes=disk_write
                )
                
                agent_res.add_snapshot(agent_snapshot)
                
                alerts = agent_res.check_alerts()
                for alert in alerts:
                    self._notify("agent_alert", {"agent_id": agent_id, "alert": alert})
        
        self._notify("update", {
            "system": self.system_resources.to_dict(),
            "agents": {aid: ar.to_dict() for aid, ar in self.agent_resources.items()},
            "timestamp": time.time()
        })
    
    def _get_network_stats(self) -> tuple:
        rx_bytes = 0
        tx_bytes = 0
        
        try:
            with open("/proc/net/dev", "r") as f:
                lines = f.readlines()[2:]
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 10:
                        interface = parts[0].rstrip(':')
                        if interface not in ['lo']:
                            rx_bytes += int(parts[1])
                            tx_bytes += int(parts[9])
        except Exception:
            pass
        
        return rx_bytes, tx_bytes
    
    def _get_disk_stats(self) -> tuple:
        read_bytes = 0
        write_bytes = 0
        
        try:
            with open("/proc/diskstats", "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 14:
                        device = parts[2]
                        if device.startswith(('sd', 'nvme', 'vd')) and not device[-1].isdigit():
                            read_bytes += int(parts[5]) * 512
                            write_bytes += int(parts[9]) * 512
        except Exception:
            pass
        
        return read_bytes, write_bytes
    
    def get_agent_resources(self, agent_id: int) -> Optional[dict]:
        if agent_id in self.agent_resources:
            return self.agent_resources[agent_id].to_dict()
        return None
    
    def get_system_resources(self) -> dict:
        return self.system_resources.to_dict()
    
    def get_all_resources(self) -> dict:
        return {
            "system": self.system_resources.to_dict(),
            "agents": {aid: ar.to_dict() for aid, ar in self.agent_resources.items()},
            "history_points": len(self.history),
            "timestamp": time.time()
        }
    
    def get_history(self, last_n: int = 60) -> List[dict]:
        return [s.to_dict() for s in list(self.history)[-last_n:]]
    
    def set_agent_thresholds(self, agent_id: int, cpu_threshold: float, memory_threshold: float):
        if agent_id in self.agent_resources:
            self.agent_resources[agent_id].alert_threshold_cpu = cpu_threshold
            self.agent_resources[agent_id].alert_threshold_memory = memory_threshold
    
    def on(self, event: str, callback: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(callback)
    
    def _notify(self, event: str, data):
        for callback in self._callbacks.get(event, []):
            try:
                callback(data)
            except Exception as e:
                print(f"Resource monitor callback error: {e}")
    
    def get_summary(self) -> dict:
        return {
            "running": self.running,
            "monitored_agents": len(self.agent_resources),
            "system": self.system_resources.to_dict(),
            "update_interval": self.update_interval
        }
