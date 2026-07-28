#!/usr/bin/env bash
# tunnel.sh — LiveKit ngrok tunnel for Simli avatar
#
# Usage:  ./tunnel.sh
#
# Starts ngrok on LiveKit port 7880, reads the public URL,
# updates .env SIMLI_LIVEKIT_URL, and restarts Docker.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

log() { echo "[tunnel] $*"; }
die() { echo "[tunnel] ERROR: $*" >&2; exit 1; }

cleanup() {
  log "stopping ngrok..."
  kill "$NGROK_PID" 2>/dev/null || true
  wait "$NGROK_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

command -v ngrok  >/dev/null 2>&1 || die "ngrok not found"
command -v docker >/dev/null 2>&1 || die "docker not found"
[[ -f "$ENV_FILE" ]] || die ".env not found"

# ── kill any existing ngrok on 4040 ──────────────────────────────────────────
pkill -f "ngrok" 2>/dev/null || true
sleep 1

# ── start ngrok for LiveKit (:7880) ──────────────────────────────────────────
log "starting ngrok tunnel (port 7880)..."
ngrok http 7880 --log=stdout --log-format=json >/tmp/ngrok-livekit.log 2>&1 &
NGROK_PID=$!

# wait for ngrok API to be ready (up to 15 s)
PUBLIC_URL=""
for i in $(seq 1 30); do
  sleep 0.5
  PUBLIC_URL=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null \
    | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for t in data.get('tunnels', []):
        if t.get('proto') == 'https':
            print(t['public_url'])
            break
except: pass
" 2>/dev/null) || true
  [[ -n "$PUBLIC_URL" ]] && break
done

[[ -n "$PUBLIC_URL" ]] || die "ngrok URL not found — check /tmp/ngrok-livekit.log"

# https:// → wss://
WSS_URL="${PUBLIC_URL/https:\/\//wss://}"
log "tunnel active: $WSS_URL"

# ── update .env ───────────────────────────────────────────────────────────────
if grep -q "^SIMLI_LIVEKIT_URL=" "$ENV_FILE"; then
  sed -i "s|^SIMLI_LIVEKIT_URL=.*|SIMLI_LIVEKIT_URL=$WSS_URL|" "$ENV_FILE"
else
  echo "SIMLI_LIVEKIT_URL=$WSS_URL" >> "$ENV_FILE"
fi
log ".env → SIMLI_LIVEKIT_URL=$WSS_URL"

# ── restart Docker so agent picks up new URL ──────────────────────────────────
log "restarting Docker..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" down --timeout 10
docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d
log "Docker restarted"

echo ""
echo "  Simli LiveKit URL: $WSS_URL"
echo "  Press Ctrl+C to stop tunnel"
echo ""

wait "$NGROK_PID"
