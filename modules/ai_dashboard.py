"""
AI Dashboard Module for Ax-Shell
Autonomous AI Agent Management Interface
"""

import os
import sys
import time
import threading
import json

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Gdk, Pango

from fabric.widgets.box import Box
from fabric.widgets.button import Button
from fabric.widgets.entry import Entry
from fabric.widgets.label import Label
from fabric.widgets.scrolledwindow import ScrolledWindow
from fabric.widgets.revealer import Revealer

import modules.icons as icons
import config.data as data

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from ai_core.orchestrator import Orchestrator
    from ai_core.agent_manager import Agent
    AI_CORE_AVAILABLE = True
except ImportError:
    AI_CORE_AVAILABLE = False
    Orchestrator = None
    Agent = None


class AgentCard(Box):
    def __init__(self, agent_id: int, name: str, on_remove=None, **kwargs):
        super().__init__(
            name="agent-card",
            orientation="v",
            spacing=8,
            style_classes=["agent-card"],
            **kwargs
        )
        
        self.agent_id = agent_id
        self.agent_name = name
        self.on_remove = on_remove
        self.start_time = time.time()
        self.status = "idle"
        
        header = Box(orientation="h", spacing=8)
        self.name_label = Label(
            label=f"Agent {agent_id}: {name}",
            style_classes=["agent-name"],
            h_align="start"
        )
        
        self.remove_btn = Button(
            name="agent-remove-btn",
            child=Label(markup=icons.close),
            tooltip_text="Remove Agent",
            on_clicked=lambda *_: self._on_remove()
        )
        
        header.add(self.name_label)
        header.pack_end(self.remove_btn, False, False, 0)
        self.add(header)
        
        self.status_label = Label(
            label="Status: Idle",
            style_classes=["agent-status", "idle"],
            h_align="start"
        )
        self.add(self.status_label)
        
        self.task_label = Label(
            label="Task: None",
            style_classes=["agent-task"],
            h_align="start",
            ellipsize=Pango.EllipsizeMode.END,
            max_width_chars=30
        )
        self.add(self.task_label)
        
        metrics_box = Box(orientation="h", spacing=16)
        
        self.timer_label = Label(
            label="00:00:00",
            style_classes=["agent-timer"],
        )
        metrics_box.add(self.timer_label)
        
        self.memory_label = Label(
            label="RAM: 0 MB",
            style_classes=["agent-memory"],
        )
        metrics_box.add(self.memory_label)
        
        self.add(metrics_box)
        
        progress_box = Box(orientation="h", spacing=8)
        self.tasks_done_label = Label(
            label="Done: 0",
            style_classes=["agent-progress"],
        )
        self.tasks_failed_label = Label(
            label="Failed: 0",
            style_classes=["agent-failed"],
        )
        progress_box.add(self.tasks_done_label)
        progress_box.add(self.tasks_failed_label)
        self.add(progress_box)
        
        self._start_timer()
    
    def _on_remove(self):
        if self.on_remove:
            self.on_remove(self.agent_id)
    
    def _start_timer(self):
        def update_timer():
            if not self.get_parent():
                return False
            elapsed = int(time.time() - self.start_time)
            hours = elapsed // 3600
            minutes = (elapsed % 3600) // 60
            seconds = elapsed % 60
            self.timer_label.set_label(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
            return True
        
        GLib.timeout_add(1000, update_timer)
    
    def update_status(self, status: str, task: str = ""):
        self.status = status
        self.status_label.set_label(f"Status: {status.capitalize()}")
        
        self.status_label.get_style_context().remove_class("idle")
        self.status_label.get_style_context().remove_class("running")
        self.status_label.get_style_context().add_class(status)
        
        if task:
            display_task = task[:50] + "..." if len(task) > 50 else task
            self.task_label.set_label(f"Task: {display_task}")
        else:
            self.task_label.set_label("Task: None")
    
    def update_metrics(self, memory: float, tasks_done: int, tasks_failed: int):
        self.memory_label.set_label(f"RAM: {memory:.1f} MB")
        self.tasks_done_label.set_label(f"Done: {tasks_done}")
        self.tasks_failed_label.set_label(f"Failed: {tasks_failed}")


class LiveChat(Box):
    def __init__(self, on_send=None, **kwargs):
        super().__init__(
            name="live-chat",
            orientation="v",
            spacing=8,
            **kwargs
        )
        
        self.on_send = on_send
        self.current_mode = "/chat"
        
        mode_box = Box(orientation="h", spacing=4)
        
        self.chat_mode_btn = Button(
            label="/chat",
            name="chat-mode-btn",
            style_classes=["mode-active"],
            on_clicked=lambda *_: self._set_mode("/chat")
        )
        self.queue_mode_btn = Button(
            label="/queue",
            name="queue-mode-btn",
            on_clicked=lambda *_: self._set_mode("/queue")
        )
        
        mode_box.add(self.chat_mode_btn)
        mode_box.add(self.queue_mode_btn)
        self.add(mode_box)
        
        self.messages_scroll = ScrolledWindow(
            h_scrollbar_policy="never",
            v_scrollbar_policy="automatic",
            h_expand=True,
            v_expand=True,
            min_content_height=200,
        )
        
        self.messages_box = Box(
            orientation="v",
            spacing=4,
            style_classes=["chat-messages"]
        )
        self.messages_scroll.add(self.messages_box)
        self.add(self.messages_scroll)
        
        input_box = Box(orientation="h", spacing=8)
        
        self.input_entry = Entry(
            placeholder="Type a message or command...",
            h_expand=True,
        )
        self.input_entry.connect("activate", self._on_send)
        
        self.send_btn = Button(
            child=Label(markup=icons.ai_send),
            name="chat-send-btn",
            on_clicked=self._on_send
        )
        
        input_box.add(self.input_entry)
        input_box.add(self.send_btn)
        self.add(input_box)
    
    def _set_mode(self, mode: str):
        self.current_mode = mode
        
        if mode == "/chat":
            self.chat_mode_btn.add_style_class("mode-active")
            self.queue_mode_btn.remove_style_class("mode-active")
        else:
            self.queue_mode_btn.add_style_class("mode-active")
            self.chat_mode_btn.remove_style_class("mode-active")
    
    def _on_send(self, *args):
        text = self.input_entry.get_text().strip()
        if not text:
            return
        
        self.add_message("user", text)
        self.input_entry.set_text("")
        
        if self.on_send:
            full_message = f"{self.current_mode} {text}"
            self.on_send(full_message)
    
    def add_message(self, sender: str, content: str):
        msg_box = Box(
            orientation="h",
            spacing=8,
            style_classes=[f"chat-message", f"chat-{sender}"]
        )
        
        sender_label = Label(
            label=f"{sender}:",
            style_classes=["chat-sender"]
        )
        content_label = Label(
            label=content,
            style_classes=["chat-content"],
            wrap=True,
            max_width_chars=50
        )
        
        msg_box.add(sender_label)
        msg_box.add(content_label)
        self.messages_box.add(msg_box)
        msg_box.show_all()
        
        adj = self.messages_scroll.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper()))


class QueuePanel(Box):
    def __init__(self, on_remove=None, **kwargs):
        super().__init__(
            name="queue-panel",
            orientation="v",
            spacing=8,
            **kwargs
        )
        
        self.on_remove = on_remove
        
        header = Box(orientation="h", spacing=8)
        header.add(Label(markup=icons.ai_queue, style_classes=["panel-icon"]))
        header.add(Label(label="Command Queue", style_classes=["panel-title"]))
        self.add(header)
        
        self.queue_scroll = ScrolledWindow(
            h_scrollbar_policy="never",
            v_scrollbar_policy="automatic",
            h_expand=True,
            v_expand=True,
            min_content_height=150,
        )
        
        self.queue_list = Box(
            orientation="v",
            spacing=4,
            style_classes=["queue-list"]
        )
        self.queue_scroll.add(self.queue_list)
        self.add(self.queue_scroll)
    
    def update_queue(self, items: list):
        for child in self.queue_list.get_children():
            self.queue_list.remove(child)
        
        for item in items:
            item_box = Box(
                orientation="h",
                spacing=8,
                style_classes=["queue-item", f"queue-{item.get('status', 'pending')}"]
            )
            
            index_label = Label(
                label=f"#{item['index']}",
                style_classes=["queue-index"]
            )
            
            cmd = item.get('command', '')
            display_cmd = cmd[:40] + "..." if len(cmd) > 40 else cmd
            cmd_label = Label(
                label=display_cmd,
                style_classes=["queue-command"],
                h_expand=True,
                h_align="start"
            )
            
            status_label = Label(
                label=item.get('status', 'pending'),
                style_classes=["queue-status"]
            )
            
            remove_btn = Button(
                child=Label(markup=icons.trash),
                name="queue-remove-btn",
                on_clicked=lambda *_, idx=item['index']: self._remove_item(idx)
            )
            
            item_box.add(index_label)
            item_box.add(cmd_label)
            item_box.add(status_label)
            item_box.add(remove_btn)
            
            self.queue_list.add(item_box)
        
        self.queue_list.show_all()
    
    def _remove_item(self, index: int):
        if self.on_remove:
            self.on_remove(index)


class AIDashboard(Box):
    def __init__(self, notch=None, **kwargs):
        super().__init__(
            name="ai-dashboard",
            orientation="v",
            spacing=12,
            h_expand=True,
            v_expand=True,
            style_classes=["ai-dashboard"],
            **kwargs
        )
        
        self.notch = notch
        self.orchestrator = Orchestrator() if AI_CORE_AVAILABLE else None
        self.agent_cards = {}
        
        self._build_ui()
        self._setup_callbacks()
    
    def _build_ui(self):
        header = Box(orientation="h", spacing=12, style_classes=["ai-header"])
        header.add(Label(markup=icons.ai_brain, style_classes=["ai-icon"]))
        header.add(Label(label="AI Agent Dashboard", style_classes=["ai-title"]))
        
        self.status_indicator = Label(
            label="Disconnected",
            style_classes=["status-disconnected"]
        )
        header.pack_end(self.status_indicator, False, False, 0)
        self.add(header)
        
        main_content = Box(orientation="h", spacing=12, h_expand=True, v_expand=True)
        
        left_panel = Box(orientation="v", spacing=12, style_classes=["ai-left-panel"])
        left_panel.set_size_request(350, -1)
        
        target_section = Box(orientation="v", spacing=8, style_classes=["ai-section"])
        target_section.add(Label(label="Target Configuration", style_classes=["section-title"], h_align="start"))
        
        self.target_entry = Entry(placeholder="Target (IP/URL/Domain/Path)")
        target_section.add(self.target_entry)
        
        category_box = Box(orientation="h", spacing=8)
        category_box.add(Label(label="Category:", h_align="start"))
        self.category_combo = Gtk.ComboBoxText()
        for cat in ["IP", "URL/Domain", "Path", "Auto-detect"]:
            self.category_combo.append_text(cat)
        self.category_combo.set_active(3)
        category_box.add(self.category_combo)
        target_section.add(category_box)
        
        self.instructions_entry = Entry(placeholder="Custom instructions...")
        target_section.add(self.instructions_entry)
        
        left_panel.add(target_section)
        
        mode_section = Box(orientation="v", spacing=8, style_classes=["ai-section"])
        mode_section.add(Label(label="Execution Mode", style_classes=["section-title"], h_align="start"))
        
        mode_box = Box(orientation="h", spacing=8)
        self.stealth_btn = Button(
            child=Box(
                orientation="h",
                spacing=4,
                children=[Label(markup=icons.ai_stealth), Label(label="Stealth")]
            ),
            name="mode-btn",
            on_clicked=lambda *_: self._set_mode("stealth")
        )
        self.aggressive_btn = Button(
            child=Box(
                orientation="h",
                spacing=4,
                children=[Label(markup=icons.ai_aggressive), Label(label="Aggressive")]
            ),
            name="mode-btn",
            on_clicked=lambda *_: self._set_mode("aggressive")
        )
        mode_box.add(self.stealth_btn)
        mode_box.add(self.aggressive_btn)
        mode_section.add(mode_box)
        left_panel.add(mode_section)
        
        model_section = Box(orientation="v", spacing=8, style_classes=["ai-section"])
        model_section.add(Label(label="AI Model", style_classes=["section-title"], h_align="start"))
        
        self.model_combo = Gtk.ComboBoxText()
        models = ["GPT-4o", "Claude 3.5 Sonnet", "Gemini Pro 1.5", "Llama 3.1 70B", "Custom"]
        for model in models:
            self.model_combo.append_text(model)
        self.model_combo.set_active(0)
        model_section.add(self.model_combo)
        left_panel.add(model_section)
        
        control_section = Box(orientation="h", spacing=8, style_classes=["ai-section"])
        self.start_btn = Button(
            child=Box(
                orientation="h",
                spacing=4,
                children=[Label(markup=icons.ai_play), Label(label="Start")]
            ),
            name="start-btn",
            style_classes=["control-btn", "start"],
            on_clicked=self._on_start
        )
        self.stop_btn = Button(
            child=Box(
                orientation="h",
                spacing=4,
                children=[Label(markup=icons.ai_stop), Label(label="Stop")]
            ),
            name="stop-btn",
            style_classes=["control-btn", "stop"],
            on_clicked=self._on_stop
        )
        control_section.add(self.start_btn)
        control_section.add(self.stop_btn)
        left_panel.add(control_section)
        
        self.queue_panel = QueuePanel(on_remove=self._on_queue_remove)
        left_panel.add(self.queue_panel)
        
        main_content.add(left_panel)
        
        right_panel = Box(orientation="v", spacing=12, h_expand=True, style_classes=["ai-right-panel"])
        
        agents_header = Box(orientation="h", spacing=8)
        agents_header.add(Label(label="Agents", style_classes=["section-title"]))
        
        self.add_agent_btn = Button(
            child=Label(markup=icons.add),
            name="add-agent-btn",
            tooltip_text="Add Agent",
            on_clicked=self._on_add_agent
        )
        agents_header.pack_end(self.add_agent_btn, False, False, 0)
        right_panel.add(agents_header)
        
        self.agents_scroll = ScrolledWindow(
            h_scrollbar_policy="never",
            v_scrollbar_policy="automatic",
            h_expand=True,
            v_expand=True,
        )
        
        self.agents_grid = Gtk.FlowBox()
        self.agents_grid.set_valign(Gtk.Align.START)
        self.agents_grid.set_max_children_per_line(3)
        self.agents_grid.set_selection_mode(Gtk.SelectionMode.NONE)
        self.agents_grid.set_homogeneous(True)
        self.agents_grid.set_column_spacing(12)
        self.agents_grid.set_row_spacing(12)
        
        self.agents_scroll.add(self.agents_grid)
        right_panel.add(self.agents_scroll)
        
        self.live_chat = LiveChat(on_send=self._on_chat_send)
        right_panel.add(self.live_chat)
        
        main_content.add(right_panel)
        self.add(main_content)
        
        self.current_mode = "stealth"
        self._set_mode("stealth")
    
    def _setup_callbacks(self):
        if self.orchestrator:
            self.orchestrator.on("started", lambda d: GLib.idle_add(self._on_orchestrator_started, d))
            self.orchestrator.on("stopped", lambda d: GLib.idle_add(self._on_orchestrator_stopped))
            self.orchestrator.on("finding", lambda f: GLib.idle_add(self._on_finding, f))
            self.orchestrator.on("completed", lambda d: GLib.idle_add(self._on_completed, d))
    
    def _set_mode(self, mode: str):
        self.current_mode = mode
        if mode == "stealth":
            self.stealth_btn.add_style_class("mode-active")
            self.aggressive_btn.remove_style_class("mode-active")
        else:
            self.aggressive_btn.add_style_class("mode-active")
            self.stealth_btn.remove_style_class("mode-active")
    
    def _on_add_agent(self, *args):
        if len(self.agent_cards) >= 10:
            return
        
        agent_id = len(self.agent_cards) + 1
        name = f"Worker-{agent_id}"
        
        card = AgentCard(
            agent_id=agent_id,
            name=name,
            on_remove=self._on_remove_agent
        )
        
        self.agent_cards[agent_id] = card
        self.agents_grid.add(card)
        card.show_all()
        
        if self.orchestrator:
            self.orchestrator.add_agent(name)
    
    def _on_remove_agent(self, agent_id: int):
        if agent_id in self.agent_cards:
            card = self.agent_cards.pop(agent_id)
            parent = card.get_parent()
            if parent:
                self.agents_grid.remove(parent)
            
            if self.orchestrator:
                self.orchestrator.remove_agent(agent_id)
    
    def _on_start(self, *args):
        target = self.target_entry.get_text().strip()
        if not target:
            self.live_chat.add_message("system", "Please enter a target")
            return
        
        category = self.category_combo.get_active_text() or "Auto-detect"
        instructions = self.instructions_entry.get_text().strip()
        
        if self.orchestrator:
            self.orchestrator.set_target(target, category, self.current_mode, instructions)
            
            if len(self.agent_cards) == 0:
                self._on_add_agent()
            
            self.orchestrator.start()
        
        self.status_indicator.set_label("Running")
        self.status_indicator.get_style_context().remove_class("status-disconnected")
        self.status_indicator.get_style_context().add_class("status-connected")
    
    def _on_stop(self, *args):
        if self.orchestrator:
            self.orchestrator.stop()
        
        self.status_indicator.set_label("Stopped")
        self.status_indicator.get_style_context().remove_class("status-connected")
        self.status_indicator.get_style_context().add_class("status-disconnected")
    
    def _on_chat_send(self, message: str):
        if self.orchestrator:
            def send_async():
                response = self.orchestrator.chat(message)
                GLib.idle_add(self.live_chat.add_message, "ai", response)
            
            threading.Thread(target=send_async, daemon=True).start()
    
    def _on_queue_remove(self, index: int):
        if self.orchestrator:
            self.orchestrator.queue_manager.remove(index)
    
    def _on_orchestrator_started(self, data):
        self.live_chat.add_message("system", f"Started execution on target: {data.target}")
    
    def _on_orchestrator_stopped(self):
        self.live_chat.add_message("system", "Execution stopped")
    
    def _on_finding(self, finding):
        self.live_chat.add_message("finding", f"[{finding.severity.upper()}] {finding.title}")
    
    def _on_completed(self, data):
        self.live_chat.add_message("system", f"Completed! Findings: {data['findings']}")
        self.status_indicator.set_label("Completed")
    
    def update_agents(self, agents_data: list):
        for agent_data in agents_data:
            agent_id = agent_data.get("id")
            if agent_id in self.agent_cards:
                card = self.agent_cards[agent_id]
                card.update_status(
                    agent_data.get("status", "idle"),
                    agent_data.get("current_task", "")
                )
                card.update_metrics(
                    agent_data.get("memory_usage", 0),
                    agent_data.get("tasks_done", 0),
                    agent_data.get("tasks_failed", 0)
                )
    
    def update_queue(self, queue_data: list):
        self.queue_panel.update_queue(queue_data)
