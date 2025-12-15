"""
Memory System - Short-term context and long-term knowledge base for persistent AI state
"""

import json
import os
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from collections import deque
import hashlib


@dataclass
class MemoryEntry:
    id: str
    content: str
    entry_type: str
    source: str
    timestamp: float = field(default_factory=time.time)
    importance: float = 0.5
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    metadata: Dict = field(default_factory=dict)
    embedding: Optional[List[float]] = None
    
    def access(self):
        self.access_count += 1
        self.last_accessed = time.time()
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "entry_type": self.entry_type,
            "source": self.source,
            "timestamp": self.timestamp,
            "importance": self.importance,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed,
            "metadata": self.metadata
        }


@dataclass
class ConversationTurn:
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)
    tokens: int = 0
    
    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp
        }


class ShortTermMemory:
    def __init__(self, max_turns: int = 50, max_tokens: int = 8000):
        self.conversation: deque = deque(maxlen=max_turns)
        self.working_context: Dict[str, Any] = {}
        self.recent_findings: deque = deque(maxlen=20)
        self.current_focus: Optional[str] = None
        self.max_tokens = max_tokens
        self._lock = threading.Lock()
    
    def add_turn(self, role: str, content: str):
        with self._lock:
            turn = ConversationTurn(
                role=role,
                content=content,
                tokens=len(content.split())
            )
            self.conversation.append(turn)
            self._trim_to_token_limit()
    
    def _trim_to_token_limit(self):
        total_tokens = sum(turn.tokens for turn in self.conversation)
        while total_tokens > self.max_tokens and len(self.conversation) > 2:
            removed = self.conversation.popleft()
            total_tokens -= removed.tokens
    
    def add_finding(self, finding: str, severity: str = "info"):
        with self._lock:
            self.recent_findings.append({
                "content": finding,
                "severity": severity,
                "timestamp": time.time()
            })
    
    def set_context(self, key: str, value: Any):
        with self._lock:
            self.working_context[key] = {
                "value": value,
                "updated_at": time.time()
            }
    
    def get_context(self, key: str) -> Optional[Any]:
        ctx = self.working_context.get(key)
        return ctx["value"] if ctx else None
    
    def set_focus(self, focus: str):
        self.current_focus = focus
    
    def get_conversation_history(self, last_n: Optional[int] = None) -> List[dict]:
        turns = list(self.conversation)
        if last_n:
            turns = turns[-last_n:]
        return [t.to_dict() for t in turns]
    
    def get_recent_findings(self) -> List[dict]:
        return list(self.recent_findings)
    
    def get_summary(self) -> dict:
        return {
            "conversation_turns": len(self.conversation),
            "total_tokens": sum(t.tokens for t in self.conversation),
            "working_context_keys": list(self.working_context.keys()),
            "recent_findings": len(self.recent_findings),
            "current_focus": self.current_focus
        }
    
    def clear(self):
        with self._lock:
            self.conversation.clear()
            self.working_context.clear()
            self.recent_findings.clear()
            self.current_focus = None


class LongTermMemory:
    def __init__(self, storage_path: str = "./.ai_memory"):
        self.storage_path = storage_path
        self.memories: Dict[str, MemoryEntry] = {}
        self.knowledge_base: Dict[str, Dict] = {}
        self.target_history: Dict[str, List[dict]] = {}
        self._lock = threading.Lock()
        self._next_id = 1
        
        self._ensure_storage()
        self._load_from_disk()
    
    def _ensure_storage(self):
        os.makedirs(self.storage_path, exist_ok=True)
        os.makedirs(os.path.join(self.storage_path, "findings"), exist_ok=True)
        os.makedirs(os.path.join(self.storage_path, "targets"), exist_ok=True)
    
    def store(
        self,
        content: str,
        entry_type: str,
        source: str,
        importance: float = 0.5,
        metadata: Optional[Dict] = None
    ) -> MemoryEntry:
        with self._lock:
            entry_id = self._generate_id(content)
            
            entry = MemoryEntry(
                id=entry_id,
                content=content,
                entry_type=entry_type,
                source=source,
                importance=importance,
                metadata=metadata or {}
            )
            
            self.memories[entry_id] = entry
            self._save_entry(entry)
            
            return entry
    
    def _generate_id(self, content: str) -> str:
        hash_input = f"{content}{time.time()}{self._next_id}"
        self._next_id += 1
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]
    
    def retrieve(self, query: str, entry_type: Optional[str] = None, limit: int = 10) -> List[MemoryEntry]:
        results = []
        query_lower = query.lower()
        
        for entry in self.memories.values():
            if entry_type and entry.entry_type != entry_type:
                continue
            
            if query_lower in entry.content.lower():
                entry.access()
                results.append(entry)
        
        results.sort(key=lambda e: (-e.importance, -e.access_count, -e.timestamp))
        return results[:limit]
    
    def store_finding(
        self,
        target: str,
        finding: str,
        severity: str,
        tool: str,
        raw_output: str = ""
    ):
        metadata = {
            "target": target,
            "severity": severity,
            "tool": tool,
            "raw_output": raw_output[:1000]
        }
        
        importance = {"critical": 1.0, "high": 0.8, "medium": 0.6, "low": 0.4, "info": 0.2}.get(
            severity.lower(), 0.5
        )
        
        self.store(
            content=finding,
            entry_type="finding",
            source=tool,
            importance=importance,
            metadata=metadata
        )
        
        if target not in self.target_history:
            self.target_history[target] = []
        
        self.target_history[target].append({
            "finding": finding,
            "severity": severity,
            "tool": tool,
            "timestamp": time.time()
        })
    
    def store_knowledge(self, category: str, key: str, value: Any):
        if category not in self.knowledge_base:
            self.knowledge_base[category] = {}
        
        self.knowledge_base[category][key] = {
            "value": value,
            "updated_at": time.time()
        }
        
        self._save_knowledge_base()
    
    def get_knowledge(self, category: str, key: Optional[str] = None) -> Optional[Any]:
        if category not in self.knowledge_base:
            return None
        
        if key:
            entry = self.knowledge_base[category].get(key)
            return entry["value"] if entry else None
        
        return {k: v["value"] for k, v in self.knowledge_base[category].items()}
    
    def get_target_history(self, target: str) -> List[dict]:
        return self.target_history.get(target, [])
    
    def get_all_targets(self) -> List[str]:
        return list(self.target_history.keys())
    
    def get_findings_by_severity(self, severity: str) -> List[MemoryEntry]:
        return [
            e for e in self.memories.values()
            if e.entry_type == "finding" and 
            e.metadata.get("severity", "").lower() == severity.lower()
        ]
    
    def _save_entry(self, entry: MemoryEntry):
        filepath = os.path.join(self.storage_path, f"{entry.entry_type}_{entry.id}.json")
        with open(filepath, "w") as f:
            json.dump(entry.to_dict(), f, indent=2)
    
    def _save_knowledge_base(self):
        filepath = os.path.join(self.storage_path, "knowledge_base.json")
        with open(filepath, "w") as f:
            json.dump(self.knowledge_base, f, indent=2)
    
    def _load_from_disk(self):
        kb_path = os.path.join(self.storage_path, "knowledge_base.json")
        if os.path.exists(kb_path):
            try:
                with open(kb_path, "r") as f:
                    self.knowledge_base = json.load(f)
            except Exception:
                pass
        
        for filename in os.listdir(self.storage_path):
            if filename.endswith(".json") and filename != "knowledge_base.json":
                filepath = os.path.join(self.storage_path, filename)
                try:
                    with open(filepath, "r") as f:
                        data = json.load(f)
                        entry = MemoryEntry(
                            id=data["id"],
                            content=data["content"],
                            entry_type=data["entry_type"],
                            source=data["source"],
                            timestamp=data.get("timestamp", time.time()),
                            importance=data.get("importance", 0.5),
                            access_count=data.get("access_count", 0),
                            last_accessed=data.get("last_accessed", time.time()),
                            metadata=data.get("metadata", {})
                        )
                        self.memories[entry.id] = entry
                except Exception:
                    pass
    
    def export_report(self, filepath: str, target: Optional[str] = None):
        report = {
            "generated_at": datetime.now().isoformat(),
            "total_memories": len(self.memories),
            "findings": []
        }
        
        findings = [e for e in self.memories.values() if e.entry_type == "finding"]
        
        if target:
            findings = [f for f in findings if f.metadata.get("target") == target]
        
        findings.sort(key=lambda f: -f.importance)
        
        for finding in findings:
            report["findings"].append({
                "content": finding.content,
                "severity": finding.metadata.get("severity", "info"),
                "tool": finding.source,
                "target": finding.metadata.get("target", "unknown"),
                "timestamp": datetime.fromtimestamp(finding.timestamp).isoformat()
            })
        
        with open(filepath, "w") as f:
            json.dump(report, f, indent=2)
    
    def get_summary(self) -> dict:
        findings = [e for e in self.memories.values() if e.entry_type == "finding"]
        
        severity_counts = {}
        for f in findings:
            sev = f.metadata.get("severity", "info")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
        
        return {
            "total_memories": len(self.memories),
            "total_findings": len(findings),
            "severity_distribution": severity_counts,
            "knowledge_categories": list(self.knowledge_base.keys()),
            "targets_analyzed": len(self.target_history)
        }
    
    def clear(self):
        with self._lock:
            self.memories.clear()
            self.knowledge_base.clear()
            self.target_history.clear()


class MemorySystem:
    def __init__(self, storage_path: str = "./.ai_memory"):
        self.short_term = ShortTermMemory()
        self.long_term = LongTermMemory(storage_path)
    
    def add_message(self, role: str, content: str):
        self.short_term.add_turn(role, content)
    
    def add_finding(self, target: str, finding: str, severity: str, tool: str, raw_output: str = ""):
        self.short_term.add_finding(finding, severity)
        self.long_term.store_finding(target, finding, severity, tool, raw_output)
    
    def set_working_context(self, key: str, value: Any):
        self.short_term.set_context(key, value)
    
    def get_working_context(self, key: str) -> Optional[Any]:
        return self.short_term.get_context(key)
    
    def store_knowledge(self, category: str, key: str, value: Any):
        self.long_term.store_knowledge(category, key, value)
    
    def get_knowledge(self, category: str, key: Optional[str] = None) -> Optional[Any]:
        return self.long_term.get_knowledge(category, key)
    
    def search(self, query: str, limit: int = 10) -> List[MemoryEntry]:
        return self.long_term.retrieve(query, limit=limit)
    
    def get_context_for_llm(self, max_tokens: int = 2000) -> str:
        context_parts = []
        
        if self.short_term.current_focus:
            context_parts.append(f"Current Focus: {self.short_term.current_focus}")
        
        working_ctx = self.short_term.working_context
        if working_ctx:
            ctx_items = [f"- {k}: {v['value']}" for k, v in working_ctx.items()]
            context_parts.append("Working Context:\n" + "\n".join(ctx_items))
        
        findings = self.short_term.get_recent_findings()
        if findings:
            findings_text = "\n".join([f"- [{f['severity']}] {f['content']}" for f in findings[-5:]])
            context_parts.append(f"Recent Findings:\n{findings_text}")
        
        return "\n\n".join(context_parts)[:max_tokens]
    
    def get_full_summary(self) -> dict:
        return {
            "short_term": self.short_term.get_summary(),
            "long_term": self.long_term.get_summary()
        }
    
    def clear_short_term(self):
        self.short_term.clear()
    
    def export_findings(self, filepath: str, target: Optional[str] = None):
        self.long_term.export_report(filepath, target)
