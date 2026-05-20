#!/usr/bin/env bash
set -euo pipefail

WS_URL="${1:-${VOSK_WEBSOCKET_URL:-ws://127.0.0.1:2700}}"

python3 - "${WS_URL}" <<'PY'
from __future__ import annotations

import socket
import sys
from urllib.parse import urlparse

url = urlparse(sys.argv[1])
host = url.hostname or "127.0.0.1"
port = url.port or 2700

sock = socket.create_connection((host, port), 2)
sock.close()
print(f"OK: socket TCP de Vosk accesible en {host}:{port}")
print("INFO: este check solo valida conectividad al puerto, no reconocimiento real.")
PY
