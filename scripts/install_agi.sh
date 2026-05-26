#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="vicidial-vosk-cobranza-ivr"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${INSTALL_DIR:-/opt/${PROJECT_NAME}}"
AGI_BIN_DIR="${AGI_BIN_DIR:-/var/lib/asterisk/agi-bin}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
ASTERISK_GROUP="${ASTERISK_GROUP:-asterisk}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Ejecuta este script como root." >&2
  exit 1
fi

command -v "${PYTHON_BIN}" >/dev/null 2>&1 || {
  echo "No se encontro ${PYTHON_BIN}." >&2
  exit 1
}

"${PYTHON_BIN}" - <<'PY'
import sys

if sys.version_info < (3, 10):
    raise SystemExit("Se requiere Python 3.10 o superior.")
PY

mkdir -p "${INSTALL_DIR}" "${AGI_BIN_DIR}" /var/log/asterisk
cp -a "${SOURCE_DIR}/." "${INSTALL_DIR}/"
rm -rf "${INSTALL_DIR}/.git" "${INSTALL_DIR}/.venv" "${INSTALL_DIR}/.pytest_cache"
rm -rf "${INSTALL_DIR}/.mypy_cache" "${INSTALL_DIR}/.ruff_cache"

"${PYTHON_BIN}" -m venv "${INSTALL_DIR}/.venv"
"${INSTALL_DIR}/.venv/bin/pip" install --upgrade pip
"${INSTALL_DIR}/.venv/bin/pip" install "${INSTALL_DIR}"

ln -sf "${INSTALL_DIR}/agi/vosk_cobranza.py" "${AGI_BIN_DIR}/vosk_cobranza.py"
ln -sf "${INSTALL_DIR}/agi/resolve_transfer_target.py" "${AGI_BIN_DIR}/resolve_transfer_target.py"
chmod 755 \
  "${INSTALL_DIR}/agi/vosk_cobranza.py" \
  "${AGI_BIN_DIR}/vosk_cobranza.py" \
  "${INSTALL_DIR}/agi/resolve_transfer_target.py" \
  "${AGI_BIN_DIR}/resolve_transfer_target.py"

touch /var/log/asterisk/vosk_cobranza.log
chown -R root:"${ASTERISK_GROUP}" "${INSTALL_DIR}"
chown root:"${ASTERISK_GROUP}" /var/log/asterisk/vosk_cobranza.log
chmod 664 /var/log/asterisk/vosk_cobranza.log

cat <<EOF
Instalacion base completada.

Proyecto: ${INSTALL_DIR}
AGIs: ${AGI_BIN_DIR}/vosk_cobranza.py, ${AGI_BIN_DIR}/resolve_transfer_target.py
Log: /var/log/asterisk/vosk_cobranza.log

Siguientes pasos:
1. Copiar o ajustar .env y config/ivr.yml
2. Levantar Vosk con docker compose
3. Incluir asterisk/extensions_custom.conf.sample en el dialplan
EOF
