"""
LLM Client - Handles communication with OpenRouter API
"""

import os
import json
import time
import threading
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass


@dataclass
class ModelConfig:
    id: str
    name: str
    provider: str
    max_tokens: int = 4096
    
AVAILABLE_MODELS = [
    ModelConfig("openai/gpt-4o", "GPT-4o", "OpenAI", 128000),
    ModelConfig("anthropic/claude-3.5-sonnet", "Claude 3.5 Sonnet", "Anthropic", 200000),
    ModelConfig("google/gemini-pro-1.5", "Gemini Pro 1.5", "Google", 1000000),
    ModelConfig("meta-llama/llama-3.1-70b-instruct", "Llama 3.1 70B", "Meta", 131072),
    ModelConfig("custom", "Custom Model", "Custom", 4096),
]


class LLMClient:
    def __init__(self, api_key: str = None, model_id: str = "openai/gpt-4o"):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.model_id = model_id
        self.base_url = "https://openrouter.ai/api/v1"
        self.conversation_history: List[Dict] = []
        self._lock = threading.Lock()
        self._callbacks: Dict[str, List[Callable]] = {
            "response": [],
            "error": [],
            "stream": []
        }
        
        self.system_prompt = """You are an autonomous AI agent coordinator. Your task is to:
1. Analyze the user's target and objectives
2. Plan a series of reconnaissance/security testing commands
3. Output commands in the format: RUN <command>
4. Coordinate multiple agents efficiently
5. Aggregate findings and report severity levels

When you've completed all objectives, output: <END!>

Important rules:
- Use stealth mode techniques when requested
- Respect rate limits with appropriate delays
- Share findings between agents
- Log all important discoveries
"""
    
    def set_api_key(self, api_key: str):
        self.api_key = api_key
    
    def set_model(self, model_id: str):
        self.model_id = model_id
    
    def get_available_models(self) -> List[ModelConfig]:
        return AVAILABLE_MODELS
    
    def parse_commands(self, response: str) -> Dict[str, str]:
        commands = {}
        lines = response.strip().split('\n')
        index = 1
        
        for line in lines:
            line = line.strip()
            if line.startswith("RUN "):
                commands[str(index)] = line
                index += 1
        
        return commands
    
    def check_end_signal(self, response: str) -> bool:
        return "<END!>" in response
    
    def generate_plan(self, target: str, category: str, mode: str, instructions: str = "") -> str:
        prompt = f"""Target: {target}
Category: {category}
Mode: {mode}
Custom Instructions: {instructions}

Generate a comprehensive plan with commands to execute. Output each command as:
RUN <command>

Consider:
- Target type and appropriate tools
- Stealth requirements if mode is stealth
- Parallel execution opportunities
- Information gathering sequence
"""
        return self._send_message(prompt)
    
    def continue_execution(self, findings: List[str], remaining_objectives: str) -> str:
        findings_text = "\n".join(findings)
        prompt = f"""Current findings:
{findings_text}

Remaining objectives: {remaining_objectives}

Based on current findings, generate the next batch of commands.
Output: RUN <command>
Or if complete: <END!>
"""
        return self._send_message(prompt)
    
    def chat(self, message: str) -> str:
        return self._send_message(message)
    
    def _send_message(self, message: str) -> str:
        try:
            import requests
            
            self.conversation_history.append({
                "role": "user",
                "content": message
            })
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://ax-shell.local",
                "X-Title": "Ax-Shell AI Agent"
            }
            
            data = {
                "model": self.model_id,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    *self.conversation_history
                ]
            }
            
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=data,
                timeout=120
            )
            
            if response.status_code == 200:
                result = response.json()
                assistant_message = result["choices"][0]["message"]["content"]
                
                self.conversation_history.append({
                    "role": "assistant",
                    "content": assistant_message
                })
                
                self._notify("response", assistant_message)
                return assistant_message
            else:
                error = f"API Error: {response.status_code} - {response.text}"
                self._notify("error", error)
                return error
                
        except Exception as e:
            error = f"Request Error: {str(e)}"
            self._notify("error", error)
            return error
    
    def on(self, event: str, callback: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(callback)
    
    def _notify(self, event: str, data):
        for callback in self._callbacks.get(event, []):
            try:
                callback(data)
            except Exception as e:
                print(f"Callback error: {e}")
    
    def reset_conversation(self):
        self.conversation_history = []
    
    def set_system_prompt(self, prompt: str):
        self.system_prompt = prompt
