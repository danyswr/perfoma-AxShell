# Ax-Shell

## Overview

Ax-Shell is a highly customizable desktop shell for Hyprland (Wayland compositor) built with Python and the Fabric framework. It provides a complete desktop environment experience including a status bar, dock, notification system, app launcher, dashboard with widgets, and various utilities like clipboard history, emoji picker, and wallpaper selector.

The project also includes an experimental AI-Core module for autonomous AI agent management, designed for security reconnaissance and testing workflows with multi-agent coordination.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Frontend Architecture

**UI Framework**: GTK 3.0 with Fabric widgets library
- Custom Wayland window management via `widgets/wayland.py`
- CSS-based theming with modular stylesheets in `styles/` directory
- Component-based architecture with reusable widgets in `modules/`

**Key UI Components**:
- `Bar`: Status bar with workspaces, system tray, metrics, and controls (includes AI dashboard button)
- `Notch`: Central notification/widget hub with expandable dashboard
- `Dock`: Application dock with pinned apps and running window indicators
- `Launcher`: Application search and launcher with calculator/converter features
- `Overview`: Workspace overview with window management
- `Dashboard`: Tabbed interface for widgets, pins, kanban, wallpapers, and mixer
- `AIDashboard`: AI agent management interface with live chat, queue management, and agent monitoring

**Theming System**: 
- Multiple panel themes: "Notch", "Panel" with various positions
- Bar themes: "Pills", "Dense", "Edge", "EdgeCenter"
- Dynamic color theming via Matugen integration
- CSS variables for consistent styling across components

### Backend Architecture

**Service Layer** (`services/`):
- `Brightness`: Screen brightness control with ddcutil/brightnessctl backends
- `NetworkClient`: NetworkManager integration for WiFi/ethernet management
- `MprisPlayer`: Media player control via MPRIS protocol
- `MonitorFocusService`: Multi-monitor focus tracking via Hyprland events

**Configuration System** (`config/`):
- JSON-based configuration in `config/config.json`
- Settings GUI built with Fabric widgets
- Hot-reloadable keybind configuration
- Per-component visibility and behavior settings

**Multi-Monitor Support**:
- `MonitorManager` for tracking connected displays
- Per-monitor Bar, Notch, and Dock instances
- Focus-aware component activation

### AI-Core Module Architecture

**Purpose**: Autonomous AI agent coordination for security testing workflows

**Python Components** (`ai-core/`):
- `Orchestrator`: Main coordinator managing agents, queues, and LLM communication
- `AgentManager`: Handles agent lifecycle (create, monitor, destroy) with max 10 agents
- `QueueManager`: Command queue with priority ordering and dependency management
- `LLMClient`: OpenRouter API integration for multiple LLM models (GPT-4, Claude, Gemini, Llama)
- `WebSocketClient`: Real-time communication with Go backend

**Go Backend** (`backend/`):
- WebSocket server for real-time agent communication
- REST API endpoints for agents, queue, logs, resource history, and health monitoring
- **PostgreSQL persistence** for agents, queue, logs, and resource metrics
- Command execution with strict `RUN <command>` validation and blocked dangerous patterns
- **Graceful termination** via `<END!>` signal
- Batch queue with priority support
- Resource monitoring (memory, CPU, goroutines)

**Dashboard GUI** (`modules/ai_dashboard.py`):
- `AgentCard`: Individual agent status with timer, memory usage, and progress
- `LiveChat`: Dual-mode chat (/chat for conversation, /queue for commands)
- `QueuePanel`: Visual queue management with add/remove/list operations
- Target input with category selection (IP, URL, domain, path)
- Mode selection (Stealth/Aggressive)
- Model selection (GPT-4, Claude, Gemini, Llama, Custom)

**Execution Model**:
- LLM outputs commands in `RUN <command>` format
- Queue system manages execution order across agents
- Agents execute concurrently with different completion times
- Results aggregated and fed back to LLM for next decisions
- `<END!>` token signals completion of objectives

**Keybind**: SUPER+I opens AI Dashboard

### Data Storage

**Local Storage**:
- JSON files for configuration (`config/config.json`, `config/dock.json`)
- Cache directory at `~/.cache/ax-shell/` for thumbnails, fonts, notifications
- Persistent files: `~/.pins.json` for pins, `~/.current.wall` symlink for wallpaper

**No Database**: Application uses file-based storage only

### Process Management

- `setproctitle` for process identification
- GLib main loop for event handling
- Threading for background tasks (wallpaper thumbnails, LLM requests)
- Subprocess management for external commands (screenshots, screen recording)

## External Dependencies

### System Requirements
- **Hyprland**: Wayland compositor (required)
- **NetworkManager**: Network management service
- **Python 3**: With GTK 3.0, GLib bindings

### Python Dependencies
- **Fabric**: GTK widget framework for desktop shells
- **PyGObject (gi)**: GTK/GLib Python bindings
- **psutil**: System metrics (CPU, memory, disk)
- **Pillow (PIL)**: Image processing for thumbnails
- **ijson**: Streaming JSON parsing for emoji data
- **watchdog**: File system monitoring
- **loguru**: Logging framework
- **toml**: TOML config parsing
- **numpy**: Numerical operations (launcher calculations)
- **PyOpenGL**: OpenGL shaders for visual effects
- **websocket-client**: WebSocket communication (AI module)
- **pywayland**: Wayland protocol bindings

### External Tools Integration
- **Playerctl**: MPRIS media player control
- **brightnessctl/ddcutil**: Brightness control
- **powerprofilesctl**: Power profile management
- **cliphist**: Clipboard history
- **wl-copy**: Wayland clipboard
- **hyprshot**: Screenshot utility
- **matugen**: Dynamic color scheme generation
- **cava**: Audio visualizer

### Third-Party Services
- **OpenRouter API**: LLM access for AI agent module (GPT-4, Claude, Gemini, Llama models)
- **wttr.in**: Weather data API

### Fonts and Assets
- **tabler-icons**: Icon font used throughout UI
- Emoji data from bundled `assets/emoji.json`