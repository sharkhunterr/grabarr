#!/usr/bin/env bash
# Stop every Grabarr uvicorn process + anything else holding port 8080.
# Idempotent: safe to run even when nothing is running.

set -u

PORT="${PORT:-8080}"
PIDFILE=".grabarr.pid"

say() { printf '[grabarr] %s\n' "$1"; }

# 1. PID file, if present
if [ -f "$PIDFILE" ]; then
    pid=$(cat "$PIDFILE" 2>/dev/null || true)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        say "stopping pid $pid (from $PIDFILE)"
        kill "$pid" 2>/dev/null || true
    fi
    rm -f "$PIDFILE"
fi

# 2. Every uvicorn invocation of grabarr.api (covers parent + child + reloader)
if pgrep -f "uvicorn grabarr.api" >/dev/null 2>&1; then
    say "sending TERM to uvicorn grabarr.api processes"
    pkill -TERM -f "uvicorn grabarr.api" 2>/dev/null || true
fi

# 3. Wait up to 6 s for a graceful exit
for _ in 1 2 3 4 5 6; do
    pgrep -f "uvicorn grabarr.api" >/dev/null 2>&1 || break
    sleep 1
done

# 4. If anything survived (wedged shelfmark retry loops, runaway libtorrent),
#    force-kill it and anything still bound to PORT.
if pgrep -f "uvicorn grabarr.api" >/dev/null 2>&1; then
    say "force-killing surviving processes"
    pkill -KILL -f "uvicorn grabarr.api" 2>/dev/null || true
fi

if command -v lsof >/dev/null 2>&1; then
    pids=$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)
    if [ -n "$pids" ]; then
        say "releasing port $PORT (pids: $pids)"
        kill -KILL $pids 2>/dev/null || true
    fi
fi

say "stopped."
