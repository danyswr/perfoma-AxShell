package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"github.com/joho/godotenv"
)

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool {
		return true
	},
}

type Agent struct {
	ID           int       `json:"id"`
	Name         string    `json:"name"`
	Status       string    `json:"status"`
	CurrentTask  string    `json:"current_task"`
	StartTime    time.Time `json:"start_time"`
	LastExecute  time.Time `json:"last_execute"`
	MemoryUsage  float64   `json:"memory_usage"`
	CPUUsage     float64   `json:"cpu_usage"`
	NetworkUsage float64   `json:"network_usage"`
	TasksDone    int       `json:"tasks_done"`
	TasksFailed  int       `json:"tasks_failed"`
}

type QueueItem struct {
	Index   int    `json:"index"`
	Command string `json:"command"`
	Status  string `json:"status"`
	Output  string `json:"output"`
	AgentID int    `json:"agent_id"`
}

type CommandResult struct {
	AgentID   int    `json:"agent_id"`
	Command   string `json:"command"`
	Output    string `json:"output"`
	Error     string `json:"error"`
	ExitCode  int    `json:"exit_code"`
	Duration  int64  `json:"duration_ms"`
	Timestamp string `json:"timestamp"`
}

type Message struct {
	Type    string      `json:"type"`
	Payload interface{} `json:"payload"`
}

type ChatMessage struct {
	Mode    string `json:"mode"`
	Content string `json:"content"`
	User    string `json:"user"`
}

type AgentManager struct {
	agents      map[int]*Agent
	queue       []QueueItem
	queueLock   sync.RWMutex
	agentLock   sync.RWMutex
	clients     map[*websocket.Conn]bool
	clientLock  sync.RWMutex
	broadcast   chan Message
	logDir      string
	apiKey      string
	stealthMode bool
	maxAgents   int
	running     bool
}

func NewAgentManager() *AgentManager {
	godotenv.Load("../.env")

	logDir := os.Getenv("AI_LOG_DIR")
	if logDir == "" {
		logDir = "./logs"
	}
	os.MkdirAll(logDir, 0755)

	return &AgentManager{
		agents:    make(map[int]*Agent),
		queue:     make([]QueueItem, 0),
		clients:   make(map[*websocket.Conn]bool),
		broadcast: make(chan Message, 100),
		logDir:    logDir,
		apiKey:    os.Getenv("OPENROUTER_API_KEY"),
		maxAgents: 10,
		running:   true,
	}
}

func (am *AgentManager) AddAgent(name string) *Agent {
	am.agentLock.Lock()
	defer am.agentLock.Unlock()

	if len(am.agents) >= am.maxAgents {
		return nil
	}

	id := len(am.agents) + 1
	agent := &Agent{
		ID:          id,
		Name:        name,
		Status:      "idle",
		CurrentTask: "",
		StartTime:   time.Now(),
		LastExecute: time.Now(),
	}
	am.agents[id] = agent

	am.broadcastMessage(Message{
		Type:    "agent_added",
		Payload: agent,
	})

	return agent
}

func (am *AgentManager) RemoveAgent(id int) bool {
	am.agentLock.Lock()
	defer am.agentLock.Unlock()

	if _, exists := am.agents[id]; exists {
		delete(am.agents, id)
		am.broadcastMessage(Message{
			Type:    "agent_removed",
			Payload: map[string]int{"id": id},
		})
		return true
	}
	return false
}

func (am *AgentManager) GetAgents() []*Agent {
	am.agentLock.RLock()
	defer am.agentLock.RUnlock()

	agents := make([]*Agent, 0, len(am.agents))
	for _, agent := range am.agents {
		agents = append(agents, agent)
	}
	return agents
}

func (am *AgentManager) AddToQueue(commands map[string]string) {
	am.queueLock.Lock()
	defer am.queueLock.Unlock()

	baseIndex := len(am.queue)
	for i := 1; i <= len(commands); i++ {
		key := fmt.Sprintf("%d", i)
		if cmd, exists := commands[key]; exists {
			item := QueueItem{
				Index:   baseIndex + i,
				Command: cmd,
				Status:  "pending",
			}
			am.queue = append(am.queue, item)
		}
	}

	am.broadcastMessage(Message{
		Type:    "queue_updated",
		Payload: am.queue,
	})
}

func (am *AgentManager) GetQueueList() []QueueItem {
	am.queueLock.RLock()
	defer am.queueLock.RUnlock()
	return am.queue
}

func (am *AgentManager) RemoveFromQueue(index int) bool {
	am.queueLock.Lock()
	defer am.queueLock.Unlock()

	for i, item := range am.queue {
		if item.Index == index {
			am.queue = append(am.queue[:i], am.queue[i+1:]...)
			am.broadcastMessage(Message{
				Type:    "queue_updated",
				Payload: am.queue,
			})
			return true
		}
	}
	return false
}

func (am *AgentManager) GetNextQueueItem() *QueueItem {
	am.queueLock.Lock()
	defer am.queueLock.Unlock()

	for i, item := range am.queue {
		if item.Status == "pending" {
			am.queue[i].Status = "running"
			return &am.queue[i]
		}
	}
	return nil
}

func (am *AgentManager) ExecuteCommand(agentID int, command string) CommandResult {
	am.agentLock.Lock()
	agent, exists := am.agents[agentID]
	if exists {
		agent.Status = "running"
		agent.CurrentTask = command
		agent.LastExecute = time.Now()
	}
	am.agentLock.Unlock()

	am.broadcastMessage(Message{
		Type:    "agent_status",
		Payload: agent,
	})

	startTime := time.Now()
	result := CommandResult{
		AgentID:   agentID,
		Command:   command,
		Timestamp: time.Now().Format(time.RFC3339),
	}

	actualCommand := command
	if strings.HasPrefix(command, "RUN ") {
		actualCommand = strings.TrimPrefix(command, "RUN ")
	}

	var cmd *exec.Cmd
	if runtime.GOOS == "windows" {
		cmd = exec.Command("cmd", "/C", actualCommand)
	} else {
		cmd = exec.Command("sh", "-c", actualCommand)
	}

	output, err := cmd.CombinedOutput()
	result.Output = string(output)
	result.Duration = time.Since(startTime).Milliseconds()

	if err != nil {
		result.Error = err.Error()
		if exitErr, ok := err.(*exec.ExitError); ok {
			result.ExitCode = exitErr.ExitCode()
		} else {
			result.ExitCode = 1
		}
	}

	am.agentLock.Lock()
	if exists {
		agent.Status = "idle"
		agent.CurrentTask = ""
		if result.ExitCode == 0 {
			agent.TasksDone++
		} else {
			agent.TasksFailed++
		}
	}
	am.agentLock.Unlock()

	am.logResult(result)

	am.broadcastMessage(Message{
		Type:    "command_result",
		Payload: result,
	})

	am.broadcastMessage(Message{
		Type:    "agent_status",
		Payload: agent,
	})

	return result
}

func (am *AgentManager) logResult(result CommandResult) {
	filename := fmt.Sprintf("%s/agent_%d_%s.log", am.logDir, result.AgentID, time.Now().Format("2006-01-02"))
	f, err := os.OpenFile(filename, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		log.Printf("Error opening log file: %v", err)
		return
	}
	defer f.Close()

	logEntry := fmt.Sprintf("[%s] Command: %s\nOutput: %s\nError: %s\nExitCode: %d\nDuration: %dms\n\n",
		result.Timestamp, result.Command, result.Output, result.Error, result.ExitCode, result.Duration)
	f.WriteString(logEntry)
}

func (am *AgentManager) GetResourceUsage() map[string]interface{} {
	var memStats runtime.MemStats
	runtime.ReadMemStats(&memStats)

	return map[string]interface{}{
		"alloc_mb":       float64(memStats.Alloc) / 1024 / 1024,
		"total_alloc_mb": float64(memStats.TotalAlloc) / 1024 / 1024,
		"sys_mb":         float64(memStats.Sys) / 1024 / 1024,
		"num_gc":         memStats.NumGC,
		"goroutines":     runtime.NumGoroutine(),
	}
}

func (am *AgentManager) broadcastMessage(msg Message) {
	am.clientLock.RLock()
	defer am.clientLock.RUnlock()

	for client := range am.clients {
		err := client.WriteJSON(msg)
		if err != nil {
			log.Printf("WebSocket write error: %v", err)
			client.Close()
			delete(am.clients, client)
		}
	}
}

func (am *AgentManager) StartAgentLoop(agentID int) {
	go func() {
		for am.running {
			item := am.GetNextQueueItem()
			if item != nil {
				am.ExecuteCommand(agentID, item.Command)
				time.Sleep(500 * time.Millisecond)
			} else {
				time.Sleep(1 * time.Second)
			}
		}
	}()
}

func (am *AgentManager) MonitorResources() {
	go func() {
		for am.running {
			am.agentLock.Lock()
			for _, agent := range am.agents {
				var memStats runtime.MemStats
				runtime.ReadMemStats(&memStats)
				agent.MemoryUsage = float64(memStats.Alloc) / 1024 / 1024 / float64(len(am.agents)+1)
			}
			am.agentLock.Unlock()

			am.broadcastMessage(Message{
				Type:    "resource_update",
				Payload: am.GetResourceUsage(),
			})

			time.Sleep(2 * time.Second)
		}
	}()
}

var manager *AgentManager

func handleWebSocket(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("WebSocket upgrade error: %v", err)
		return
	}
	defer conn.Close()

	manager.clientLock.Lock()
	manager.clients[conn] = true
	manager.clientLock.Unlock()

	conn.WriteJSON(Message{
		Type: "connected",
		Payload: map[string]interface{}{
			"agents": manager.GetAgents(),
			"queue":  manager.GetQueueList(),
		},
	})

	for {
		var msg Message
		err := conn.ReadJSON(&msg)
		if err != nil {
			log.Printf("WebSocket read error: %v", err)
			manager.clientLock.Lock()
			delete(manager.clients, conn)
			manager.clientLock.Unlock()
			break
		}

		handleMessage(conn, msg)
	}
}

func handleMessage(conn *websocket.Conn, msg Message) {
	switch msg.Type {
	case "add_agent":
		payload := msg.Payload.(map[string]interface{})
		name := payload["name"].(string)
		agent := manager.AddAgent(name)
		if agent != nil {
			manager.StartAgentLoop(agent.ID)
		}

	case "remove_agent":
		payload := msg.Payload.(map[string]interface{})
		id := int(payload["id"].(float64))
		manager.RemoveAgent(id)

	case "add_queue":
		payload := msg.Payload.(map[string]interface{})
		commands := make(map[string]string)
		for k, v := range payload {
			commands[k] = v.(string)
		}
		manager.AddToQueue(commands)

	case "queue_list":
		conn.WriteJSON(Message{
			Type:    "queue_list",
			Payload: manager.GetQueueList(),
		})

	case "queue_rm":
		payload := msg.Payload.(map[string]interface{})
		index := int(payload["index"].(float64))
		manager.RemoveFromQueue(index)

	case "chat":
		payload := msg.Payload.(map[string]interface{})
		chatMsg := ChatMessage{
			Mode:    payload["mode"].(string),
			Content: payload["content"].(string),
			User:    "user",
		}
		handleChat(chatMsg)

	case "get_agents":
		conn.WriteJSON(Message{
			Type:    "agents",
			Payload: manager.GetAgents(),
		})

	case "get_resources":
		conn.WriteJSON(Message{
			Type:    "resources",
			Payload: manager.GetResourceUsage(),
		})

	case "execute":
		payload := msg.Payload.(map[string]interface{})
		agentID := int(payload["agent_id"].(float64))
		command := payload["command"].(string)
		go manager.ExecuteCommand(agentID, command)

	case "stop":
		manager.running = false
		manager.broadcastMessage(Message{
			Type:    "stopped",
			Payload: nil,
		})
	}
}

func handleChat(chat ChatMessage) {
	switch chat.Mode {
	case "/queue":
		parts := strings.Fields(chat.Content)
		if len(parts) >= 1 {
			switch parts[0] {
			case "list":
				manager.broadcastMessage(Message{
					Type:    "queue_list",
					Payload: manager.GetQueueList(),
				})
			case "rm":
				if len(parts) >= 2 {
					var index int
					fmt.Sscanf(parts[1], "%d", &index)
					manager.RemoveFromQueue(index)
				}
			case "add":
				if len(parts) >= 2 {
					jsonStr := strings.Join(parts[1:], " ")
					var commands map[string]string
					if err := json.Unmarshal([]byte(jsonStr), &commands); err == nil {
						manager.AddToQueue(commands)
					}
				}
			}
		}
	case "/chat":
		manager.broadcastMessage(Message{
			Type: "chat_message",
			Payload: map[string]string{
				"user":    "user",
				"content": chat.Content,
			},
		})
	}
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":    "ok",
		"agents":    len(manager.agents),
		"queue":     len(manager.queue),
		"resources": manager.GetResourceUsage(),
	})
}

func handleAgents(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	switch r.Method {
	case "GET":
		json.NewEncoder(w).Encode(manager.GetAgents())
	case "POST":
		var data map[string]string
		json.NewDecoder(r.Body).Decode(&data)
		agent := manager.AddAgent(data["name"])
		if agent != nil {
			manager.StartAgentLoop(agent.ID)
			json.NewEncoder(w).Encode(agent)
		} else {
			http.Error(w, "Max agents reached", http.StatusBadRequest)
		}
	}
}

func handleQueue(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	switch r.Method {
	case "GET":
		json.NewEncoder(w).Encode(manager.GetQueueList())
	case "POST":
		var commands map[string]string
		json.NewDecoder(r.Body).Decode(&commands)
		manager.AddToQueue(commands)
		json.NewEncoder(w).Encode(map[string]string{"status": "added"})
	case "DELETE":
		var data map[string]int
		json.NewDecoder(r.Body).Decode(&data)
		manager.RemoveFromQueue(data["index"])
		json.NewEncoder(w).Encode(map[string]string{"status": "removed"})
	}
}

func enableCORS(handler http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")

		if r.Method == "OPTIONS" {
			w.WriteHeader(http.StatusOK)
			return
		}

		handler(w, r)
	}
}

func main() {
	manager = NewAgentManager()
	manager.MonitorResources()

	http.HandleFunc("/ws", handleWebSocket)
	http.HandleFunc("/health", enableCORS(handleHealth))
	http.HandleFunc("/agents", enableCORS(handleAgents))
	http.HandleFunc("/queue", enableCORS(handleQueue))

	port := os.Getenv("BACKEND_PORT")
	if port == "" {
		port = "8080"
	}

	log.Printf("AI Agent Backend starting on port %s", port)
	log.Printf("WebSocket endpoint: ws://localhost:%s/ws", port)
	log.Printf("Health check: http://localhost:%s/health", port)

	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatal(err)
	}
}
