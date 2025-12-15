package main

import (
	"database/sql"
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
	_ "github.com/lib/pq"
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
	ID        int    `json:"id"`
	Index     int    `json:"index"`
	Command   string `json:"command"`
	Status    string `json:"status"`
	Output    string `json:"output"`
	AgentID   int    `json:"agent_id"`
	Priority  int    `json:"priority"`
	BatchID   string `json:"batch_id"`
	CreatedAt string `json:"created_at"`
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

type LogEntry struct {
	ID        int    `json:"id"`
	AgentID   int    `json:"agent_id"`
	Level     string `json:"level"`
	Message   string `json:"message"`
	Command   string `json:"command"`
	Output    string `json:"output"`
	ExitCode  int    `json:"exit_code"`
	Duration  int64  `json:"duration_ms"`
	Timestamp string `json:"timestamp"`
}

type ResourceMetric struct {
	ID          int     `json:"id"`
	CPUPercent  float64 `json:"cpu_percent"`
	MemoryMB    float64 `json:"memory_mb"`
	MemoryPerc  float64 `json:"memory_percent"`
	Goroutines  int     `json:"goroutines"`
	NumGC       uint32  `json:"num_gc"`
	AllocMB     float64 `json:"alloc_mb"`
	SysMB       float64 `json:"sys_mb"`
	AgentCount  int     `json:"agent_count"`
	QueueCount  int     `json:"queue_count"`
	Timestamp   string  `json:"timestamp"`
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
	terminated  bool
	db          *sql.DB
	batchSize   int
}

func NewAgentManager() *AgentManager {
	godotenv.Load("../.env")

	logDir := os.Getenv("AI_LOG_DIR")
	if logDir == "" {
		logDir = "./logs"
	}
	os.MkdirAll(logDir, 0755)

	am := &AgentManager{
		agents:    make(map[int]*Agent),
		queue:     make([]QueueItem, 0),
		clients:   make(map[*websocket.Conn]bool),
		broadcast: make(chan Message, 100),
		logDir:    logDir,
		apiKey:    os.Getenv("OPENROUTER_API_KEY"),
		maxAgents: 10,
		running:   true,
		batchSize: 5,
	}

	am.initDatabase()
	am.loadStateFromDB()

	return am
}

func (am *AgentManager) initDatabase() {
	dbURL := os.Getenv("DATABASE_URL")
	if dbURL == "" {
		log.Println("DATABASE_URL not set, running without persistence")
		return
	}

	var err error
	am.db, err = sql.Open("postgres", dbURL)
	if err != nil {
		log.Printf("Error connecting to database: %v", err)
		return
	}

	if err = am.db.Ping(); err != nil {
		log.Printf("Error pinging database: %v", err)
		return
	}

	log.Println("Connected to PostgreSQL database")

	schema := `
	CREATE TABLE IF NOT EXISTS agents (
		id SERIAL PRIMARY KEY,
		name VARCHAR(255) NOT NULL,
		status VARCHAR(50) DEFAULT 'idle',
		current_task TEXT DEFAULT '',
		start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
		last_execute TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
		memory_usage FLOAT DEFAULT 0,
		cpu_usage FLOAT DEFAULT 0,
		network_usage FLOAT DEFAULT 0,
		tasks_done INT DEFAULT 0,
		tasks_failed INT DEFAULT 0,
		created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
	);

	CREATE TABLE IF NOT EXISTS queue (
		id SERIAL PRIMARY KEY,
		idx INT NOT NULL,
		command TEXT NOT NULL,
		status VARCHAR(50) DEFAULT 'pending',
		output TEXT DEFAULT '',
		agent_id INT DEFAULT 0,
		priority INT DEFAULT 0,
		batch_id VARCHAR(100) DEFAULT '',
		created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
		updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
	);

	CREATE TABLE IF NOT EXISTS logs (
		id SERIAL PRIMARY KEY,
		agent_id INT,
		level VARCHAR(20) DEFAULT 'info',
		message TEXT,
		command TEXT,
		output TEXT,
		exit_code INT DEFAULT 0,
		duration_ms BIGINT DEFAULT 0,
		created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
	);

	CREATE TABLE IF NOT EXISTS resource_metrics (
		id SERIAL PRIMARY KEY,
		cpu_percent FLOAT DEFAULT 0,
		memory_mb FLOAT DEFAULT 0,
		memory_percent FLOAT DEFAULT 0,
		goroutines INT DEFAULT 0,
		num_gc INT DEFAULT 0,
		alloc_mb FLOAT DEFAULT 0,
		sys_mb FLOAT DEFAULT 0,
		agent_count INT DEFAULT 0,
		queue_count INT DEFAULT 0,
		created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
	);

	CREATE INDEX IF NOT EXISTS idx_queue_status ON queue(status);
	CREATE INDEX IF NOT EXISTS idx_queue_priority ON queue(priority DESC);
	CREATE INDEX IF NOT EXISTS idx_logs_agent ON logs(agent_id);
	CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level);
	CREATE INDEX IF NOT EXISTS idx_metrics_time ON resource_metrics(created_at);
	`

	_, err = am.db.Exec(schema)
	if err != nil {
		log.Printf("Error creating schema: %v", err)
	}
}

func (am *AgentManager) loadStateFromDB() {
	if am.db == nil {
		return
	}

	rows, err := am.db.Query(`SELECT id, name, status, current_task, start_time, last_execute, 
		memory_usage, cpu_usage, network_usage, tasks_done, tasks_failed FROM agents`)
	if err != nil {
		log.Printf("Error loading agents: %v", err)
		return
	}
	defer rows.Close()

	for rows.Next() {
		var agent Agent
		err := rows.Scan(&agent.ID, &agent.Name, &agent.Status, &agent.CurrentTask,
			&agent.StartTime, &agent.LastExecute, &agent.MemoryUsage, &agent.CPUUsage,
			&agent.NetworkUsage, &agent.TasksDone, &agent.TasksFailed)
		if err != nil {
			log.Printf("Error scanning agent: %v", err)
			continue
		}
		am.agents[agent.ID] = &agent
	}

	qRows, err := am.db.Query(`SELECT id, idx, command, status, output, agent_id, priority, batch_id, created_at 
		FROM queue WHERE status != 'completed' ORDER BY priority DESC, id ASC`)
	if err != nil {
		log.Printf("Error loading queue: %v", err)
		return
	}
	defer qRows.Close()

	for qRows.Next() {
		var item QueueItem
		err := qRows.Scan(&item.ID, &item.Index, &item.Command, &item.Status, &item.Output,
			&item.AgentID, &item.Priority, &item.BatchID, &item.CreatedAt)
		if err != nil {
			log.Printf("Error scanning queue item: %v", err)
			continue
		}
		am.queue = append(am.queue, item)
	}

	log.Printf("Loaded %d agents and %d queue items from database", len(am.agents), len(am.queue))
}

func (am *AgentManager) saveAgentToDB(agent *Agent) {
	if am.db == nil {
		return
	}

	_, err := am.db.Exec(`
		INSERT INTO agents (id, name, status, current_task, start_time, last_execute, 
			memory_usage, cpu_usage, network_usage, tasks_done, tasks_failed)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
		ON CONFLICT (id) DO UPDATE SET
			name = EXCLUDED.name,
			status = EXCLUDED.status,
			current_task = EXCLUDED.current_task,
			last_execute = EXCLUDED.last_execute,
			memory_usage = EXCLUDED.memory_usage,
			cpu_usage = EXCLUDED.cpu_usage,
			network_usage = EXCLUDED.network_usage,
			tasks_done = EXCLUDED.tasks_done,
			tasks_failed = EXCLUDED.tasks_failed
	`, agent.ID, agent.Name, agent.Status, agent.CurrentTask, agent.StartTime,
		agent.LastExecute, agent.MemoryUsage, agent.CPUUsage, agent.NetworkUsage,
		agent.TasksDone, agent.TasksFailed)
	if err != nil {
		log.Printf("Error saving agent to DB: %v", err)
	}
}

func (am *AgentManager) saveQueueItemToDB(item *QueueItem) int {
	if am.db == nil {
		return 0
	}

	var id int
	err := am.db.QueryRow(`
		INSERT INTO queue (idx, command, status, output, agent_id, priority, batch_id)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
		RETURNING id
	`, item.Index, item.Command, item.Status, item.Output, item.AgentID, item.Priority, item.BatchID).Scan(&id)
	if err != nil {
		log.Printf("Error saving queue item to DB: %v", err)
		return 0
	}
	return id
}

func (am *AgentManager) updateQueueItemInDB(item *QueueItem) {
	if am.db == nil {
		return
	}

	_, err := am.db.Exec(`
		UPDATE queue SET status = $1, output = $2, agent_id = $3, updated_at = CURRENT_TIMESTAMP
		WHERE id = $4
	`, item.Status, item.Output, item.AgentID, item.ID)
	if err != nil {
		log.Printf("Error updating queue item in DB: %v", err)
	}
}

func (am *AgentManager) saveLogToDB(entry *LogEntry) {
	if am.db == nil {
		return
	}

	_, err := am.db.Exec(`
		INSERT INTO logs (agent_id, level, message, command, output, exit_code, duration_ms)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
	`, entry.AgentID, entry.Level, entry.Message, entry.Command, entry.Output, entry.ExitCode, entry.Duration)
	if err != nil {
		log.Printf("Error saving log to DB: %v", err)
	}
}

func (am *AgentManager) saveResourceMetricToDB(metric *ResourceMetric) {
	if am.db == nil {
		return
	}

	_, err := am.db.Exec(`
		INSERT INTO resource_metrics (cpu_percent, memory_mb, memory_percent, goroutines, num_gc, alloc_mb, sys_mb, agent_count, queue_count)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
	`, metric.CPUPercent, metric.MemoryMB, metric.MemoryPerc, metric.Goroutines, metric.NumGC, metric.AllocMB, metric.SysMB, metric.AgentCount, metric.QueueCount)
	if err != nil {
		log.Printf("Error saving resource metric to DB: %v", err)
	}
}

func (am *AgentManager) deleteAgentFromDB(id int) {
	if am.db == nil {
		return
	}

	_, err := am.db.Exec(`DELETE FROM agents WHERE id = $1`, id)
	if err != nil {
		log.Printf("Error deleting agent from DB: %v", err)
	}
}

func (am *AgentManager) deleteQueueItemFromDB(id int) {
	if am.db == nil {
		return
	}

	_, err := am.db.Exec(`DELETE FROM queue WHERE id = $1`, id)
	if err != nil {
		log.Printf("Error deleting queue item from DB: %v", err)
	}
}

func (am *AgentManager) GetLogs(limit int, agentID int, level string) []LogEntry {
	if am.db == nil {
		return nil
	}

	query := `SELECT id, agent_id, level, message, command, output, exit_code, duration_ms, created_at 
		FROM logs WHERE 1=1`
	args := []interface{}{}
	argNum := 1

	if agentID > 0 {
		query += fmt.Sprintf(" AND agent_id = $%d", argNum)
		args = append(args, agentID)
		argNum++
	}
	if level != "" {
		query += fmt.Sprintf(" AND level = $%d", argNum)
		args = append(args, level)
		argNum++
	}

	query += fmt.Sprintf(" ORDER BY created_at DESC LIMIT $%d", argNum)
	args = append(args, limit)

	rows, err := am.db.Query(query, args...)
	if err != nil {
		log.Printf("Error getting logs: %v", err)
		return nil
	}
	defer rows.Close()

	var logs []LogEntry
	for rows.Next() {
		var entry LogEntry
		err := rows.Scan(&entry.ID, &entry.AgentID, &entry.Level, &entry.Message,
			&entry.Command, &entry.Output, &entry.ExitCode, &entry.Duration, &entry.Timestamp)
		if err != nil {
			continue
		}
		logs = append(logs, entry)
	}
	return logs
}

func (am *AgentManager) GetResourceHistory(limit int) []ResourceMetric {
	if am.db == nil {
		return nil
	}

	rows, err := am.db.Query(`SELECT id, cpu_percent, memory_mb, memory_percent, goroutines, 
		num_gc, alloc_mb, sys_mb, agent_count, queue_count, created_at 
		FROM resource_metrics ORDER BY created_at DESC LIMIT $1`, limit)
	if err != nil {
		log.Printf("Error getting resource history: %v", err)
		return nil
	}
	defer rows.Close()

	var metrics []ResourceMetric
	for rows.Next() {
		var m ResourceMetric
		err := rows.Scan(&m.ID, &m.CPUPercent, &m.MemoryMB, &m.MemoryPerc, &m.Goroutines,
			&m.NumGC, &m.AllocMB, &m.SysMB, &m.AgentCount, &m.QueueCount, &m.Timestamp)
		if err != nil {
			continue
		}
		metrics = append(metrics, m)
	}
	return metrics
}

func (am *AgentManager) AddAgent(name string) *Agent {
	am.agentLock.Lock()
	defer am.agentLock.Unlock()

	if len(am.agents) >= am.maxAgents {
		return nil
	}

	id := 1
	for {
		if _, exists := am.agents[id]; !exists {
			break
		}
		id++
	}

	agent := &Agent{
		ID:          id,
		Name:        name,
		Status:      "idle",
		CurrentTask: "",
		StartTime:   time.Now(),
		LastExecute: time.Now(),
	}
	am.agents[id] = agent

	am.saveAgentToDB(agent)

	am.broadcastMessage(Message{
		Type:    "agent_added",
		Payload: agent,
	})

	am.saveLogToDB(&LogEntry{
		AgentID: id,
		Level:   "info",
		Message: fmt.Sprintf("Agent '%s' created", name),
	})

	return agent
}

func (am *AgentManager) RemoveAgent(id int) bool {
	am.agentLock.Lock()
	defer am.agentLock.Unlock()

	if agent, exists := am.agents[id]; exists {
		am.saveLogToDB(&LogEntry{
			AgentID: id,
			Level:   "info",
			Message: fmt.Sprintf("Agent '%s' removed", agent.Name),
		})

		delete(am.agents, id)
		am.deleteAgentFromDB(id)

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

func (am *AgentManager) validateCommand(command string) (string, bool) {
	if strings.HasPrefix(command, "RUN ") {
		actualCmd := strings.TrimPrefix(command, "RUN ")
		return actualCmd, true
	}
	return "", false
}

func (am *AgentManager) AddToQueue(commands map[string]string) {
	am.queueLock.Lock()
	defer am.queueLock.Unlock()

	batchID := fmt.Sprintf("batch_%d", time.Now().UnixNano())
	baseIndex := len(am.queue)

	for i := 1; i <= len(commands); i++ {
		key := fmt.Sprintf("%d", i)
		if cmd, exists := commands[key]; exists {
			item := QueueItem{
				Index:   baseIndex + i,
				Command: cmd,
				Status:  "pending",
				BatchID: batchID,
			}

			item.ID = am.saveQueueItemToDB(&item)
			am.queue = append(am.queue, item)
		}
	}

	am.broadcastMessage(Message{
		Type:    "queue_updated",
		Payload: am.queue,
	})

	am.saveLogToDB(&LogEntry{
		Level:   "info",
		Message: fmt.Sprintf("Added %d commands to queue (batch: %s)", len(commands), batchID),
	})
}

func (am *AgentManager) AddToQueueWithPriority(command string, priority int) {
	am.queueLock.Lock()
	defer am.queueLock.Unlock()

	item := QueueItem{
		Index:    len(am.queue) + 1,
		Command:  command,
		Status:   "pending",
		Priority: priority,
	}

	item.ID = am.saveQueueItemToDB(&item)
	am.queue = append(am.queue, item)

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
			am.deleteQueueItemFromDB(item.ID)
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

	var bestItem *QueueItem
	var bestIdx int = -1
	bestPriority := -1

	for i, item := range am.queue {
		if item.Status == "pending" && item.Priority > bestPriority {
			bestItem = &am.queue[i]
			bestIdx = i
			bestPriority = item.Priority
		}
	}

	if bestItem != nil {
		am.queue[bestIdx].Status = "running"
		am.updateQueueItemInDB(&am.queue[bestIdx])
		return bestItem
	}
	return nil
}

func (am *AgentManager) GetNextBatch(batchSize int) []QueueItem {
	am.queueLock.Lock()
	defer am.queueLock.Unlock()

	var batch []QueueItem
	for i := range am.queue {
		if am.queue[i].Status == "pending" && len(batch) < batchSize {
			am.queue[i].Status = "running"
			am.updateQueueItemInDB(&am.queue[i])
			batch = append(batch, am.queue[i])
		}
	}
	return batch
}

func (am *AgentManager) CompleteQueueItem(index int, output string, success bool) {
	am.queueLock.Lock()
	defer am.queueLock.Unlock()

	for i, item := range am.queue {
		if item.Index == index {
			if success {
				am.queue[i].Status = "completed"
			} else {
				am.queue[i].Status = "failed"
			}
			am.queue[i].Output = output
			am.updateQueueItemInDB(&am.queue[i])
			break
		}
	}
}

func (am *AgentManager) ExecuteCommand(agentID int, command string) CommandResult {
	if am.terminated {
		return CommandResult{
			AgentID: agentID,
			Command: command,
			Error:   "System terminated by <END!> signal",
		}
	}

	am.agentLock.Lock()
	agent, exists := am.agents[agentID]
	if exists {
		agent.Status = "running"
		agent.CurrentTask = command
		agent.LastExecute = time.Now()
		am.saveAgentToDB(agent)
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

	actualCommand, valid := am.validateCommand(command)
	if !valid {
		if !strings.HasPrefix(command, "RUN ") {
			actualCommand = command
		} else {
			result.Error = "Invalid command format. Use: RUN <command>"
			result.ExitCode = 1

			am.saveLogToDB(&LogEntry{
				AgentID:  agentID,
				Level:    "error",
				Message:  "Invalid command format",
				Command:  command,
				ExitCode: 1,
			})

			return result
		}
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
		am.saveAgentToDB(agent)
	}
	am.agentLock.Unlock()

	level := "info"
	if result.ExitCode != 0 {
		level = "error"
	}
	am.saveLogToDB(&LogEntry{
		AgentID:  agentID,
		Level:    level,
		Message:  "Command executed",
		Command:  actualCommand,
		Output:   result.Output,
		ExitCode: result.ExitCode,
		Duration: result.Duration,
	})

	am.logResultToFile(result)

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

func (am *AgentManager) logResultToFile(result CommandResult) {
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

	am.agentLock.RLock()
	agentCount := len(am.agents)
	am.agentLock.RUnlock()

	am.queueLock.RLock()
	queueCount := len(am.queue)
	am.queueLock.RUnlock()

	return map[string]interface{}{
		"alloc_mb":       float64(memStats.Alloc) / 1024 / 1024,
		"total_alloc_mb": float64(memStats.TotalAlloc) / 1024 / 1024,
		"sys_mb":         float64(memStats.Sys) / 1024 / 1024,
		"num_gc":         memStats.NumGC,
		"goroutines":     runtime.NumGoroutine(),
		"agent_count":    agentCount,
		"queue_count":    queueCount,
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
		for am.running && !am.terminated {
			item := am.GetNextQueueItem()
			if item != nil {
				am.queueLock.Lock()
				item.AgentID = agentID
				am.updateQueueItemInDB(item)
				am.queueLock.Unlock()

				result := am.ExecuteCommand(agentID, item.Command)
				am.CompleteQueueItem(item.Index, result.Output, result.ExitCode == 0)

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

			resources := am.GetResourceUsage()

			metric := &ResourceMetric{
				AllocMB:    resources["alloc_mb"].(float64),
				SysMB:      resources["sys_mb"].(float64),
				Goroutines: resources["goroutines"].(int),
				NumGC:      resources["num_gc"].(uint32),
				AgentCount: resources["agent_count"].(int),
				QueueCount: resources["queue_count"].(int),
			}
			am.saveResourceMetricToDB(metric)

			am.broadcastMessage(Message{
				Type:    "resource_update",
				Payload: resources,
			})

			time.Sleep(2 * time.Second)
		}
	}()
}

func (am *AgentManager) GracefulTerminate(signal string) {
	if signal == "<END!>" {
		am.terminated = true
		am.running = false

		am.saveLogToDB(&LogEntry{
			Level:   "warn",
			Message: "System terminated by <END!> signal",
		})

		am.broadcastMessage(Message{
			Type:    "terminated",
			Payload: map[string]string{"reason": "Graceful termination via <END!> signal"},
		})

		log.Println("System gracefully terminated via <END!> signal")
	}
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
			"agents":     manager.GetAgents(),
			"queue":      manager.GetQueueList(),
			"terminated": manager.terminated,
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

	case "get_logs":
		payload := msg.Payload.(map[string]interface{})
		limit := 50
		agentID := 0
		level := ""
		if l, ok := payload["limit"].(float64); ok {
			limit = int(l)
		}
		if a, ok := payload["agent_id"].(float64); ok {
			agentID = int(a)
		}
		if lv, ok := payload["level"].(string); ok {
			level = lv
		}
		conn.WriteJSON(Message{
			Type:    "logs",
			Payload: manager.GetLogs(limit, agentID, level),
		})

	case "get_resource_history":
		limit := 100
		if payload, ok := msg.Payload.(map[string]interface{}); ok {
			if l, ok := payload["limit"].(float64); ok {
				limit = int(l)
			}
		}
		conn.WriteJSON(Message{
			Type:    "resource_history",
			Payload: manager.GetResourceHistory(limit),
		})

	case "execute":
		payload := msg.Payload.(map[string]interface{})
		agentID := int(payload["agent_id"].(float64))
		command := payload["command"].(string)
		go manager.ExecuteCommand(agentID, command)

	case "terminate":
		manager.GracefulTerminate("<END!>")

	case "stop":
		manager.running = false
		manager.broadcastMessage(Message{
			Type:    "stopped",
			Payload: nil,
		})
	}
}

func handleChat(chat ChatMessage) {
	if strings.Contains(chat.Content, "<END!>") {
		manager.GracefulTerminate("<END!>")
		return
	}

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
			case "clear":
				manager.queueLock.Lock()
				for _, item := range manager.queue {
					manager.deleteQueueItemFromDB(item.ID)
				}
				manager.queue = make([]QueueItem, 0)
				manager.queueLock.Unlock()
				manager.broadcastMessage(Message{
					Type:    "queue_updated",
					Payload: manager.queue,
				})
			}
		}
	case "/chat":
		manager.broadcastMessage(Message{
			Type: "chat_message",
			Payload: map[string]string{
				"user":    chat.User,
				"content": chat.Content,
			},
		})
	}
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":     "ok",
		"agents":     len(manager.agents),
		"queue":      len(manager.queue),
		"resources":  manager.GetResourceUsage(),
		"terminated": manager.terminated,
		"db_connected": manager.db != nil,
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

func handleLogs(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	limit := 50
	agentID := 0
	level := ""

	q := r.URL.Query()
	if l := q.Get("limit"); l != "" {
		fmt.Sscanf(l, "%d", &limit)
	}
	if a := q.Get("agent_id"); a != "" {
		fmt.Sscanf(a, "%d", &agentID)
	}
	level = q.Get("level")

	json.NewEncoder(w).Encode(manager.GetLogs(limit, agentID, level))
}

func handleResourceHistory(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	limit := 100
	q := r.URL.Query()
	if l := q.Get("limit"); l != "" {
		fmt.Sscanf(l, "%d", &limit)
	}

	json.NewEncoder(w).Encode(manager.GetResourceHistory(limit))
}

func handleTerminate(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	if r.Method == "POST" {
		manager.GracefulTerminate("<END!>")
		json.NewEncoder(w).Encode(map[string]string{"status": "terminated"})
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
	http.HandleFunc("/logs", enableCORS(handleLogs))
	http.HandleFunc("/resources/history", enableCORS(handleResourceHistory))
	http.HandleFunc("/terminate", enableCORS(handleTerminate))

	port := os.Getenv("BACKEND_PORT")
	if port == "" {
		port = "8080"
	}

	log.Printf("AI Agent Backend starting on port %s", port)
	log.Printf("WebSocket endpoint: ws://localhost:%s/ws", port)
	log.Printf("Health check: http://localhost:%s/health", port)
	log.Printf("Database persistence: %v", manager.db != nil)

	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatal(err)
	}
}
