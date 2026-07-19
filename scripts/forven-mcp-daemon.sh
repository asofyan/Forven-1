#!/bin/bash
# Forven MCP Server Daemon
# Runs the MCP server with Streamable HTTP transport for persistent access

set -euo pipefail

VENV="/home/hms/forven/.venv"
PYTHON="${VENV}/bin/python"
ENV_FILE="/home/hms/forven/.env"
LOG_FILE="/home/hms/forven/logs/mcp-server.log"
PID_FILE="/home/hms/forven/.mcp-server.pid"
PORT="${FORVEN_MCP_PORT:-8005}"
HOST="${FORVEN_MCP_HOST:-127.0.0.1}"

# Create logs directory if it doesn't exist
mkdir -p "$(dirname "$LOG_FILE")"

# Load environment variables
if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

# Export MCP-specific env vars (override from .env if needed)
export FORVEN_API_URL="${FORVEN_API_URL:-http://127.0.0.1:8004}"
export FORVEN_API_KEY="${FORVEN_API_KEY:-92ec5b339a6a980a8c3d6dc31b237ac4e9572a520921ce454fb5bf049839d7c0}"
export FORVEN_OPERATOR_KEY="${FORVEN_OPERATOR_KEY:-295dc8d02f34f301b6456ae19f4b5b02e8bddc815b124729c020d57dba573566}"

# Function to check if server is running
is_running() {
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

# Function to start the server
start() {
    if is_running; then
        echo "Forven MCP server is already running (PID: $(cat "$PID_FILE"))"
        return 0
    fi

    echo "Starting Forven MCP server on ${HOST}:${PORT}..."
    cd /home/hms/forven

    nohup "$PYTHON" -m forven.mcp_server \
        --transport http \
        --host "$HOST" \
        --port "$PORT" \
        >> "$LOG_FILE" 2>&1 &

    local pid=$!
    echo "$pid" > "$PID_FILE"
    sleep 2

    if is_running; then
        echo "Forven MCP server started successfully (PID: $pid)"
        echo "Endpoint: http://${HOST}:${PORT}"
        echo "Health check: http://${HOST}:${PORT}/health"
        echo "MCP endpoint: http://${HOST}:${PORT}/mcp"
    else
        echo "Failed to start Forven MCP server"
        tail -20 "$LOG_FILE"
        return 1
    fi
}

# Function to stop the server
stop() {
    if ! is_running; then
        echo "Forven MCP server is not running"
        rm -f "$PID_FILE"
        return 0
    fi

    local pid
    pid=$(cat "$PID_FILE")
    echo "Stopping Forven MCP server (PID: $pid)..."

    kill "$pid" 2>/dev/null || true
    sleep 2

    if is_running; then
        echo "Force killing..."
        kill -9 "$pid" 2>/dev/null || true
        sleep 1
    fi

    rm -f "$PID_FILE"
    echo "Forven MCP server stopped"
}

# Function to restart the server
restart() {
    stop
    sleep 1
    start
}

# Function to show status
status() {
    if is_running; then
        local pid
        pid=$(cat "$PID_FILE")
        echo "Forven MCP server is running (PID: $pid)"
        echo "Endpoint: http://${HOST}:${PORT}"
        echo "Health check:"
        curl -s "http://${HOST}:${PORT}/health" 2>/dev/null || echo "  (health check failed)"
    else
        echo "Forven MCP server is not running"
    fi
}

# Function to show logs
logs() {
    if [[ -f "$LOG_FILE" ]]; then
        tail -${1:-50} "$LOG_FILE"
    else
        echo "No log file found"
    fi
}

# Main
case "${1:-start}" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs "${2:-50}"
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs [lines]}"
        exit 1
        ;;
esac