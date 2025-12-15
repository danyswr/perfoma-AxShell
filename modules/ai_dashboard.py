"""
AI Dashboard Module for Ax-Shell
Autonomous AI Agent Management Interface with Real-time WebSocket Integration
"""

import os
import sys
import time
import threading
import json

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Gdk, Pango, cairo

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
    from ai_core.resource_monitor import ResourceMonitor
    AI_CORE_AVAILABLE = True
except ImportError:
    AI_CORE_AVAILABLE = False
    Orchestrator = None
    Agent = None
    ResourceMonitor = None

try:
    from ai_core.websocket_client import WebSocketClient, BackendClient
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    WebSocketClient = None
    BackendClient = None


class ProgressBar(Gtk.DrawingArea):
    def __init__(self, color="#4ade80", bg_color="rgba(255,255,255,0.1)", **kwargs):
        super().__init__(**kwargs)
        self.value = 0.0
        self.color = color
        self.bg_color = bg_color
        self.set_size_request(-1, 8)
        self.connect("draw", self._on_draw)
    
    def set_value(self, value: float):
        self.value = max(0.0, min(100.0, value))
        self.queue_draw()
    
    def set_color(self, color: str):
        self.color = color
        self.queue_draw()
    
    def _on_draw(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        
        cr.set_source_rgba(1, 1, 1, 0.1)
        self._draw_rounded_rect(cr, 0, 0, width, height, height / 2)
        cr.fill()
        
        if self.value > 0:
            fill_width = (width * self.value) / 100.0
            color = self._parse_color(self.color)
            cr.set_source_rgba(*color)
            self._draw_rounded_rect(cr, 0, 0, fill_width, height, height / 2)
            cr.fill()
        
        return False
    
    def _draw_rounded_rect(self, cr, x, y, width, height, radius):
        if width < 2 * radius:
            radius = width / 2
        if height < 2 * radius:
            radius = height / 2
        
        cr.new_path()
        cr.arc(x + radius, y + radius, radius, 3.14159, 1.5 * 3.14159)
        cr.arc(x + width - radius, y + radius, radius, 1.5 * 3.14159, 2 * 3.14159)
        cr.arc(x + width - radius, y + height - radius, radius, 0, 0.5 * 3.14159)
        cr.arc(x + radius, y + height - radius, radius, 0.5 * 3.14159, 3.14159)
        cr.close_path()
    
    def _parse_color(self, color: str):
        if color.startswith("#"):
            hex_color = color.lstrip("#")
            r = int(hex_color[0:2], 16) / 255.0
            g = int(hex_color[2:4], 16) / 255.0
            b = int(hex_color[4:6], 16) / 255.0
            return (r, g, b, 1.0)
        return (0.29, 0.87, 0.5, 1.0)


class ResourceBar(Box):
    def __init__(self, label: str, icon: str, color: str = "#4ade80", **kwargs):
        super().__init__(
            orientation="v",
            spacing=4,
            style_classes=["resource-bar"],
            **kwargs
        )
        
        header = Box(orientation="h", spacing=8)
        header.add(Label(markup=icon, style_classes=["resource-icon"]))
        self.label = Label(label=label, style_classes=["resource-label"], h_expand=True, h_align="start")
        header.add(self.label)
        self.value_label = Label(label="0%", style_classes=["resource-value"])
        header.add(self.value_label)
        self.add(header)
        
        self.progress = ProgressBar(color=color)
        self.add(self.progress)
        self.color = color
    
    def update(self, value: float, display_text: str = None):
        self.progress.set_value(value)
        if display_text:
            self.value_label.set_label(display_text)
        else:
            self.value_label.set_label(f"{value:.1f}%")
        
        if value > 80:
            self.progress.set_color("#f87171")
        elif value > 60:
            self.progress.set_color("#fbbf24")
        else:
            self.progress.set_color(self.color)


class ResourceMonitorPanel(Box):
    def __init__(self, **kwargs):
        super().__init__(
            name="resource-monitor-panel",
            orientation="v",
            spacing=8,
            style_classes=["ai-section", "resource-panel"],
            **kwargs
        )
        
        header = Box(orientation="h", spacing=8)
        header.add(Label(markup=icons.ai_metrics, style_classes=["panel-icon"]))
        header.add(Label(label="System Resources", style_classes=["section-title"]))
        self.add(header)
        
        self.cpu_bar = ResourceBar("CPU", icons.cpu, "#60a5fa")
        self.add(self.cpu_bar)
        
        self.ram_bar = ResourceBar("RAM", icons.memory, "#a78bfa")
        self.add(self.ram_bar)
        
        self.network_bar = ResourceBar("Network", icons.ai_network, "#34d399")
        self.add(self.network_bar)
        
        self.disk_bar = ResourceBar("Disk I/O", icons.disk, "#fbbf24")
        self.add(self.disk_bar)
        
        stats_box = Box(orientation="h", spacing=16, style_classes=["stats-row"])
        
        self.uptime_label = Label(label="Uptime: --:--", style_classes=["stat-label"])
        stats_box.add(self.uptime_label)
        
        self.load_label = Label(label="Load: --", style_classes=["stat-label"])
        stats_box.add(self.load_label)
        
        self.add(stats_box)
    
    def update(self, data: dict):
        if "cpu_percent" in data:
            self.cpu_bar.update(data["cpu_percent"])
        
        if "memory_percent" in data:
            mem_used = data.get("memory_used_gb", 0)
            mem_total = data.get("memory_total_gb", 0)
            self.ram_bar.update(data["memory_percent"], f"{mem_used:.1f}/{mem_total:.1f} GB")
        
        if "disk_percent" in data:
            disk_used = data.get("disk_used_gb", 0)
            disk_total = data.get("disk_total_gb", 0)
            self.disk_bar.update(data["disk_percent"], f"{disk_used:.0f}/{disk_total:.0f} GB")
        
        if "load_average" in data:
            load = data["load_average"]
            self.load_label.set_label(f"Load: {load[0]:.2f}")
        
        if "uptime_hours" in data:
            hours = data["uptime_hours"]
            h = int(hours)
            m = int((hours - h) * 60)
            self.uptime_label.set_label(f"Uptime: {h}h {m}m")


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
        self.status_dot = Label(label="", style_classes=["status-dot", "idle"])
        header.add(self.status_dot)
        
        self.name_label = Label(
            label=f"Agent {agent_id}: {name}",
            style_classes=["agent-name"],
            h_align="start",
            h_expand=True
        )
        header.add(self.name_label)
        
        self.remove_btn = Button(
            name="agent-remove-btn",
            child=Label(markup=icons.close),
            tooltip_text="Remove Agent",
            on_clicked=lambda *_: self._on_remove()
        )
        header.add(self.remove_btn)
        self.add(header)
        
        self.task_label = Label(
            label="Idle",
            style_classes=["agent-task"],
            h_align="start",
            ellipsize=Pango.EllipsizeMode.END,
            max_width_chars=30
        )
        self.add(self.task_label)
        
        resources_box = Box(orientation="v", spacing=4, style_classes=["agent-resources"])
        
        cpu_row = Box(orientation="h", spacing=8)
        cpu_row.add(Label(label="CPU", style_classes=["metric-label"]))
        self.cpu_progress = ProgressBar(color="#60a5fa")
        self.cpu_progress.set_hexpand(True)
        cpu_row.pack_start(self.cpu_progress, True, True, 0)
        self.cpu_value = Label(label="0%", style_classes=["metric-value"])
        cpu_row.add(self.cpu_value)
        resources_box.add(cpu_row)
        
        ram_row = Box(orientation="h", spacing=8)
        ram_row.add(Label(label="RAM", style_classes=["metric-label"]))
        self.ram_progress = ProgressBar(color="#a78bfa")
        self.ram_progress.set_hexpand(True)
        ram_row.pack_start(self.ram_progress, True, True, 0)
        self.ram_value = Label(label="0 MB", style_classes=["metric-value"])
        ram_row.add(self.ram_value)
        resources_box.add(ram_row)
        
        self.add(resources_box)
        
        footer = Box(orientation="h", spacing=8, style_classes=["agent-footer"])
        
        self.timer_label = Label(
            label="00:00:00",
            style_classes=["agent-timer"],
        )
        footer.add(self.timer_label)
        
        footer.pack_end(Box(orientation="h", spacing=8, children=[
            Label(label="", style_classes=["tasks-icon"]),
            self._create_counter("done", "#4ade80"),
            self._create_counter("failed", "#f87171"),
        ]), False, False, 0)
        
        self.add(footer)
        
        self._start_timer()
    
    def _create_counter(self, name: str, color: str):
        box = Box(orientation="h", spacing=2, style_classes=[f"counter-{name}"])
        label = Label(label="0", style_classes=["counter-value"])
        setattr(self, f"{name}_label", label)
        box.add(label)
        return box
    
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
        
        for s in ["idle", "running", "completed", "error"]:
            self.status_dot.get_style_context().remove_class(s)
        self.status_dot.get_style_context().add_class(status)
        
        if task:
            display_task = task[:40] + "..." if len(task) > 40 else task
            self.task_label.set_label(display_task)
        else:
            self.task_label.set_label(status.capitalize())
    
    def update_metrics(self, memory: float = 0, tasks_done: int = 0, tasks_failed: int = 0, cpu: float = 0):
        self.cpu_progress.set_value(cpu)
        self.cpu_value.set_label(f"{cpu:.0f}%")
        
        self.ram_progress.set_value(min(100, memory / 10))
        self.ram_value.set_label(f"{memory:.0f} MB")
        
        self.done_label.set_label(str(tasks_done))
        self.failed_label.set_label(str(tasks_failed))


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
            min_content_height=150,
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
        self.queue_count = Label(label="(0)", style_classes=["queue-count"])
        header.add(self.queue_count)
        self.add(header)
        
        self.queue_scroll = ScrolledWindow(
            h_scrollbar_policy="never",
            v_scrollbar_policy="automatic",
            h_expand=True,
            v_expand=True,
            min_content_height=100,
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
        
        self.queue_count.set_label(f"({len(items)})")
        
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
            display_cmd = cmd[:35] + "..." if len(cmd) > 35 else cmd
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


class LogPanel(Box):
    def __init__(self, **kwargs):
        super().__init__(
            name="log-panel",
            orientation="v",
            spacing=8,
            style_classes=["ai-section"],
            **kwargs
        )
        
        header = Box(orientation="h", spacing=8)
        header.add(Label(markup=icons.ai_log, style_classes=["panel-icon"]))
        header.add(Label(label="Activity Log", style_classes=["section-title"]))
        
        self.clear_btn = Button(
            child=Label(markup=icons.trash),
            name="clear-log-btn",
            tooltip_text="Clear Log",
            on_clicked=lambda *_: self.clear()
        )
        header.pack_end(self.clear_btn, False, False, 0)
        self.add(header)
        
        self.log_scroll = ScrolledWindow(
            h_scrollbar_policy="never",
            v_scrollbar_policy="automatic",
            h_expand=True,
            v_expand=True,
            min_content_height=80,
        )
        
        self.log_box = Box(
            orientation="v",
            spacing=2,
            style_classes=["log-list"]
        )
        self.log_scroll.add(self.log_box)
        self.add(self.log_scroll)
        
        self.max_entries = 50
    
    def add_entry(self, level: str, message: str):
        timestamp = time.strftime("%H:%M:%S")
        
        entry = Box(
            orientation="h",
            spacing=8,
            style_classes=["log-entry", f"log-{level}"]
        )
        
        time_label = Label(label=timestamp, style_classes=["log-time"])
        level_label = Label(label=f"[{level.upper()}]", style_classes=["log-level"])
        msg_label = Label(
            label=message,
            style_classes=["log-message"],
            h_expand=True,
            h_align="start",
            ellipsize=Pango.EllipsizeMode.END,
            max_width_chars=60
        )
        
        entry.add(time_label)
        entry.add(level_label)
        entry.add(msg_label)
        
        self.log_box.add(entry)
        entry.show_all()
        
        children = self.log_box.get_children()
        if len(children) > self.max_entries:
            self.log_box.remove(children[0])
        
        adj = self.log_scroll.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper()))
    
    def clear(self):
        for child in self.log_box.get_children():
            self.log_box.remove(child)


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
        self.resource_monitor = ResourceMonitor() if AI_CORE_AVAILABLE and ResourceMonitor else None
        self.agent_cards = {}
        
        self.ws_client = None
        self.backend_client = None
        if WEBSOCKET_AVAILABLE:
            self.ws_client = WebSocketClient()
            self.backend_client = BackendClient()
        
        self._build_ui()
        self._setup_callbacks()
        self._setup_websocket()
        self._start_monitoring()
    
    def _build_ui(self):
        header = Box(orientation="h", spacing=12, style_classes=["ai-header"])
        header.add(Label(markup=icons.ai_brain, style_classes=["ai-icon"]))
        header.add(Label(label="AI Agent Dashboard", style_classes=["ai-title"]))
        
        self.status_indicator = Box(orientation="h", spacing=4, style_classes=["status-box"])
        self.status_dot = Label(label="", style_classes=["connection-dot", "disconnected"])
        self.status_text = Label(label="Ready", style_classes=["status-text"])
        self.status_indicator.add(self.status_dot)
        self.status_indicator.add(self.status_text)
        header.pack_end(self.status_indicator, False, False, 0)
        self.add(header)
        
        main_content = Box(orientation="h", spacing=12, h_expand=True, v_expand=True)
        
        left_panel = Box(orientation="v", spacing=12, style_classes=["ai-left-panel"])
        left_panel.set_size_request(320, -1)
        
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
        
        self.resource_panel = ResourceMonitorPanel()
        left_panel.add(self.resource_panel)
        
        self.queue_panel = QueuePanel(on_remove=self._on_queue_remove)
        left_panel.add(self.queue_panel)
        
        main_content.add(left_panel)
        
        right_panel = Box(orientation="v", spacing=12, h_expand=True, style_classes=["ai-right-panel"])
        
        agents_header = Box(orientation="h", spacing=8)
        agents_header.add(Label(label="Agents", style_classes=["section-title"]))
        self.agent_count = Label(label="(0/10)", style_classes=["agent-count"])
        agents_header.add(self.agent_count)
        
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
        
        bottom_panel = Box(orientation="h", spacing=12, style_classes=["bottom-panel"])
        
        self.live_chat = LiveChat(on_send=self._on_chat_send)
        self.live_chat.set_hexpand(True)
        bottom_panel.add(self.live_chat)
        
        self.log_panel = LogPanel()
        self.log_panel.set_size_request(300, -1)
        bottom_panel.add(self.log_panel)
        
        right_panel.add(bottom_panel)
        
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
        
        if self.resource_monitor:
            self.resource_monitor.on("update", lambda d: GLib.idle_add(self._on_resource_update, d))
    
    def _setup_websocket(self):
        if not self.ws_client:
            return
        
        self.ws_client.on("connected", lambda d: GLib.idle_add(self._on_ws_connected, d))
        self.ws_client.on("disconnected", lambda d: GLib.idle_add(self._on_ws_disconnected, d))
        self.ws_client.on("error", lambda d: GLib.idle_add(self._on_ws_error, d))
        
        self.ws_client.on("agent_added", lambda d: GLib.idle_add(self._on_ws_agent_added, d))
        self.ws_client.on("agent_removed", lambda d: GLib.idle_add(self._on_ws_agent_removed, d))
        self.ws_client.on("agent_status", lambda d: GLib.idle_add(self._on_ws_agent_status, d))
        self.ws_client.on("agents", lambda d: GLib.idle_add(self._on_ws_agents_list, d))
        
        self.ws_client.on("queue_updated", lambda d: GLib.idle_add(self._on_ws_queue_updated, d))
        self.ws_client.on("queue_list", lambda d: GLib.idle_add(self._on_ws_queue_updated, d))
        
        self.ws_client.on("command_result", lambda d: GLib.idle_add(self._on_ws_command_result, d))
        self.ws_client.on("resource_update", lambda d: GLib.idle_add(self._on_ws_resource_update, d))
        self.ws_client.on("logs", lambda d: GLib.idle_add(self._on_ws_logs, d))
        
        self.ws_client.on("chat_message", lambda d: GLib.idle_add(self._on_ws_chat_message, d))
        self.ws_client.on("terminated", lambda d: GLib.idle_add(self._on_ws_terminated, d))
        
        self.ws_client.connect()
    
    def _on_ws_connected(self, data):
        self._set_status("Connected", True)
        self.log_panel.add_entry("info", "Connected to backend server")
        self.ws_client.get_agents()
        self.ws_client.get_queue_list()
    
    def _on_ws_disconnected(self, data):
        self._set_status("Disconnected", False)
        self.log_panel.add_entry("warn", "Disconnected from backend server")
    
    def _on_ws_error(self, data):
        msg = data.get("message", "Unknown error") if data else "Connection error"
        self.log_panel.add_entry("error", f"WebSocket error: {msg}")
    
    def _on_ws_agent_added(self, data):
        if not data:
            return
        agent_id = data.get("id")
        name = data.get("name", f"Agent-{agent_id}")
        
        if agent_id not in self.agent_cards:
            card = AgentCard(
                agent_id=agent_id,
                name=name,
                on_remove=self._on_remove_agent
            )
            self.agent_cards[agent_id] = card
            self.agents_grid.add(card)
            card.show_all()
            self.agent_count.set_label(f"({len(self.agent_cards)}/10)")
            self.log_panel.add_entry("info", f"Agent {name} added")
    
    def _on_ws_agent_removed(self, data):
        if not data:
            return
        agent_id = data.get("id")
        if agent_id in self.agent_cards:
            card = self.agent_cards.pop(agent_id)
            parent = card.get_parent()
            if parent:
                self.agents_grid.remove(parent)
            self.agent_count.set_label(f"({len(self.agent_cards)}/10)")
            self.log_panel.add_entry("info", f"Agent {agent_id} removed")
    
    def _on_ws_agent_status(self, data):
        if not data:
            return
        agent_id = data.get("id")
        if agent_id in self.agent_cards:
            card = self.agent_cards[agent_id]
            card.update_status(
                data.get("status", "idle"),
                data.get("current_task", "")
            )
            card.update_metrics(
                data.get("memory_usage", 0),
                data.get("tasks_done", 0),
                data.get("tasks_failed", 0),
                data.get("cpu_usage", 0)
            )
    
    def _on_ws_agents_list(self, data):
        if not data:
            return
        for agent_data in data:
            self._on_ws_agent_added(agent_data)
    
    def _on_ws_queue_updated(self, data):
        if data:
            self.queue_panel.update_queue(data)
    
    def _on_ws_command_result(self, data):
        if not data:
            return
        agent_id = data.get("agent_id", 0)
        command = data.get("command", "")[:30]
        exit_code = data.get("exit_code", 0)
        
        level = "info" if exit_code == 0 else "error"
        status = "completed" if exit_code == 0 else "failed"
        self.log_panel.add_entry(level, f"Agent {agent_id}: {command}... [{status}]")
    
    def _on_ws_resource_update(self, data):
        if not data:
            return
        alloc_mb = data.get("alloc_mb", 0)
        sys_mb = data.get("sys_mb", 0)
        goroutines = data.get("goroutines", 0)
        
        mem_percent = (alloc_mb / sys_mb * 100) if sys_mb > 0 else 0
        
        mock_data = {
            "cpu_percent": min(goroutines * 5, 100),
            "memory_percent": mem_percent,
            "memory_used_gb": alloc_mb / 1024,
            "memory_total_gb": sys_mb / 1024,
            "disk_percent": 50,
            "disk_used_gb": 250,
            "disk_total_gb": 500,
            "load_average": (goroutines / 10, 0.8, 0.6),
            "uptime_hours": 1
        }
        self.resource_panel.update(mock_data)
    
    def _on_ws_logs(self, data):
        if not data:
            return
        for log in reversed(data[:10]):
            level = log.get("level", "info")
            message = log.get("message", "")
            self.log_panel.add_entry(level, message)
    
    def _on_ws_chat_message(self, data):
        if not data:
            return
        user = data.get("user", "system")
        content = data.get("content", "")
        self.live_chat.add_message(user, content)
    
    def _on_ws_terminated(self, data):
        self._set_status("Terminated", False)
        reason = data.get("reason", "System terminated") if data else "System terminated"
        self.log_panel.add_entry("warn", reason)
        self.live_chat.add_message("system", f"<END!> {reason}")
    
    def _start_monitoring(self):
        if self.resource_monitor:
            self.resource_monitor.start()
        
        def mock_update():
            if not self.get_parent():
                return False
            
            import random
            mock_data = {
                "cpu_percent": random.uniform(10, 60),
                "memory_percent": random.uniform(30, 70),
                "memory_used_gb": random.uniform(4, 12),
                "memory_total_gb": 16,
                "disk_percent": random.uniform(40, 60),
                "disk_used_gb": random.uniform(100, 300),
                "disk_total_gb": 500,
                "load_average": (random.uniform(0.5, 2.0), 0.8, 0.6),
                "uptime_hours": random.uniform(10, 100)
            }
            self.resource_panel.update(mock_data)
            
            for agent_id, card in self.agent_cards.items():
                card.update_metrics(
                    memory=random.uniform(50, 200),
                    tasks_done=random.randint(0, 10),
                    tasks_failed=random.randint(0, 2),
                    cpu=random.uniform(5, 40)
                )
            
            return True
        
        GLib.timeout_add(2000, mock_update)
    
    def _on_resource_update(self, data: dict):
        if "system" in data:
            self.resource_panel.update(data["system"])
        
        if "agents" in data:
            for agent_id, agent_data in data["agents"].items():
                if agent_id in self.agent_cards:
                    current = agent_data.get("current", {})
                    self.agent_cards[agent_id].update_metrics(
                        memory=current.get("memory_mb", 0),
                        cpu=current.get("cpu_percent", 0)
                    )
    
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
            self.log_panel.add_entry("warn", "Maximum agents reached (10)")
            return
        
        agent_id = len(self.agent_cards) + 1
        name = f"Worker-{agent_id}"
        
        if self.ws_client and self.ws_client.connected:
            self.ws_client.add_agent(name)
        else:
            card = AgentCard(
                agent_id=agent_id,
                name=name,
                on_remove=self._on_remove_agent
            )
            
            self.agent_cards[agent_id] = card
            self.agents_grid.add(card)
            card.show_all()
            
            self.agent_count.set_label(f"({len(self.agent_cards)}/10)")
            self.log_panel.add_entry("info", f"Agent {name} created")
            
            if self.orchestrator:
                self.orchestrator.add_agent(name)
            
            if self.resource_monitor:
                self.resource_monitor.register_agent(agent_id)
    
    def _on_remove_agent(self, agent_id: int):
        if self.ws_client and self.ws_client.connected:
            self.ws_client.remove_agent(agent_id)
        else:
            if agent_id in self.agent_cards:
                card = self.agent_cards.pop(agent_id)
                parent = card.get_parent()
                if parent:
                    self.agents_grid.remove(parent)
                
                self.agent_count.set_label(f"({len(self.agent_cards)}/10)")
                self.log_panel.add_entry("info", f"Agent {agent_id} removed")
                
                if self.orchestrator:
                    self.orchestrator.remove_agent(agent_id)
                
                if self.resource_monitor:
                    self.resource_monitor.unregister_agent(agent_id)
    
    def _on_start(self, *args):
        target = self.target_entry.get_text().strip()
        if not target:
            self.live_chat.add_message("system", "Please enter a target")
            self.log_panel.add_entry("error", "No target specified")
            return
        
        category = self.category_combo.get_active_text() or "Auto-detect"
        instructions = self.instructions_entry.get_text().strip()
        
        if self.orchestrator:
            self.orchestrator.set_target(target, category, self.current_mode, instructions)
            
            if len(self.agent_cards) == 0:
                self._on_add_agent()
            
            self.orchestrator.start()
        
        self._set_status("Running", True)
        self.log_panel.add_entry("info", f"Started execution on {target}")
    
    def _on_stop(self, *args):
        if self.ws_client and self.ws_client.connected:
            self.ws_client.terminate()
            self.log_panel.add_entry("info", "Sent <END!> termination signal")
        
        if self.orchestrator:
            self.orchestrator.stop()
        
        self._set_status("Stopped", False)
        self.log_panel.add_entry("info", "Execution stopped")
    
    def _set_status(self, text: str, connected: bool):
        self.status_text.set_label(text)
        self.status_dot.get_style_context().remove_class("connected")
        self.status_dot.get_style_context().remove_class("disconnected")
        self.status_dot.get_style_context().add_class("connected" if connected else "disconnected")
    
    def _on_chat_send(self, message: str):
        if self.ws_client and self.ws_client.connected:
            if message.startswith("/queue"):
                mode = "/queue"
                content = message[7:].strip()
            elif message.startswith("/chat"):
                mode = "/chat"
                content = message[6:].strip()
            else:
                parts = message.split(" ", 1)
                mode = parts[0] if parts[0] in ["/chat", "/queue"] else "/chat"
                content = parts[1] if len(parts) > 1 else message
            
            self.ws_client.chat(mode, content)
            
            if "<END!>" in content:
                self.log_panel.add_entry("warn", "Sent <END!> termination signal via chat")
        elif self.orchestrator:
            def send_async():
                response = self.orchestrator.chat(message)
                GLib.idle_add(self.live_chat.add_message, "ai", response)
            
            threading.Thread(target=send_async, daemon=True).start()
        
        self.log_panel.add_entry("info", f"Chat: {message[:30]}...")
    
    def _on_queue_remove(self, index: int):
        if self.ws_client and self.ws_client.connected:
            self.ws_client.remove_from_queue(index)
        elif self.orchestrator:
            self.orchestrator.queue_manager.remove(index)
        self.log_panel.add_entry("info", f"Removed queue item #{index}")
    
    def _on_orchestrator_started(self, data):
        self.live_chat.add_message("system", f"Started execution on target: {data.target}")
    
    def _on_orchestrator_stopped(self):
        self.live_chat.add_message("system", "Execution stopped")
    
    def _on_finding(self, finding):
        self.live_chat.add_message("finding", f"[{finding.severity.upper()}] {finding.title}")
        self.log_panel.add_entry(finding.severity, finding.title)
    
    def _on_completed(self, data):
        self.live_chat.add_message("system", f"Completed! Findings: {data['findings']}")
        self._set_status("Completed", True)
        self.log_panel.add_entry("info", f"Scan completed with {data['findings']} findings")
    
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
                    agent_data.get("tasks_failed", 0),
                    agent_data.get("cpu_usage", 0)
                )
    
    def update_queue(self, queue_data: list):
        self.queue_panel.update_queue(queue_data)
