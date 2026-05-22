#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ASTERISK_ETC_DIR="/etc/asterisk"
EXTENSIONS_CONF="${ASTERISK_ETC_DIR}/extensions.conf"
PJSIP_CONF="${ASTERISK_ETC_DIR}/pjsip.conf"
AGI_DIRS=(
  "/usr/share/asterisk/agi-bin"
  "/var/lib/asterisk/agi-bin"
)
SOUND_DIRS=(
  "/var/lib/asterisk/sounds/custom"
  "/usr/share/asterisk/sounds/custom"
)
NAME_CACHE_DIRS=(
  "/var/lib/asterisk/sounds/custom/generated/names"
  "/usr/share/asterisk/sounds/custom/generated/names"
)
BACKUP_ROOT="/var/backups/vicidial-vosk-cobranza-ivr"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${BACKUP_ROOT}/lab-elevenlabs-${TIMESTAMP}"
ENV_FILE="/etc/default/vicidial-vosk-cobranza-ivr"
ASTERISK_GROUP="${ASTERISK_GROUP:-asterisk}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Ejecuta este script como root o con sudo." >&2
  exit 1
fi

require_command() {
  local command_name="$1"

  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "No se encontro ${command_name}." >&2
    exit 1
  fi
}

backup_path() {
  local source_path="$1"
  local target_dir="$2"

  if [[ -e "${source_path}" ]]; then
    cp -a "${source_path}" "${target_dir}/"
  fi
}

install_wrapper() {
  local script_name="$1"
  local target_dir="$2"
  local target_path="${target_dir}/${script_name}"

  cat >"${target_path}" <<EOF
#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR}"
OPTIONAL_ENV_FILE="${ENV_FILE}"

if [[ -f "\${OPTIONAL_ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "\${OPTIONAL_ENV_FILE}"
  set +a
fi

cd "\${PROJECT_DIR}"

export VOSK_COBRANZA_CONFIG="\${PROJECT_DIR}/config/ivr.yml"
export VOSK_COBRANZA_INTENTS="\${PROJECT_DIR}/config/intents.yml"
export VOSK_COBRANZA_LOGGING="\${PROJECT_DIR}/config/logging.yml"
export IVR_ROUTING_CONFIG="\${PROJECT_DIR}/config/routing.yml"
export IVR_LEAD_CONTEXT_CSV="\${PROJECT_DIR}/config/lead_context.sample.csv"
export VOSK_WEBSOCKET_URL="ws://127.0.0.1:2700"
export LOG_PATH="/var/log/asterisk/vosk_cobranza.log"
export LOG_LEVEL="\${LOG_LEVEL:-INFO}"
export IVR_LISTEN_SECONDS="\${IVR_LISTEN_SECONDS:-5}"

exec "\${PROJECT_DIR}/.venv/bin/python" "\${PROJECT_DIR}/agi/${script_name}" "\$@"
EOF

  chmod 755 "${target_path}"
}

render_fixed_prompt() {
  local text="$1"
  local output_base="$2"
  local work_dir="$3"
  local source_file="${work_dir}/$(basename "${output_base}").source.wav"
  local tmp_wav="${work_dir}/$(basename "${output_base}").tmp.wav"

  espeak-ng -v es-la -s 145 -w "${source_file}" -- "${text}"
  ffmpeg -loglevel error -y -i "${source_file}" -ar 8000 -ac 1 -c:a pcm_s16le "${tmp_wav}"
  install -m 644 "${tmp_wav}" "${output_base}.wav"
}

ensure_segmented_assets() {
  local primary_dir="/var/lib/asterisk/sounds/custom"
  local mirror_dir="/usr/share/asterisk/sounds/custom"
  local work_dir
  work_dir="$(mktemp -d)"
  trap 'rm -rf "${work_dir}"' RETURN

  mkdir -p "${primary_dir}" "${mirror_dir}"

  render_fixed_prompt "Hola." "${primary_dir}/hola" "${work_dir}"
  render_fixed_prompt \
    "nos comunicamos de SokaCorp por una gestión pendiente relacionada con Banco Popular. ¿Desea que le comuniquemos ahora? Le escucho." \
    "${primary_dir}/gestion-banco-popular" \
    "${work_dir}"
  render_fixed_prompt \
    "nos comunicamos de SokaCorp por una gestión pendiente relacionada con Banco BHD. ¿Desea que le comuniquemos ahora? Le escucho." \
    "${primary_dir}/gestion-banco-bhd" \
    "${work_dir}"
  render_fixed_prompt \
    "nos comunicamos de SokaCorp por una gestión pendiente relacionada con Banco Reservas. ¿Desea que le comuniquemos ahora? Le escucho." \
    "${primary_dir}/gestion-banco-reservas" \
    "${work_dir}"

  install -m 644 "${primary_dir}/hola.wav" "${mirror_dir}/hola.wav"
  install -m 644 "${primary_dir}/gestion-banco-popular.wav" "${mirror_dir}/gestion-banco-popular.wav"
  install -m 644 "${primary_dir}/gestion-banco-bhd.wav" "${mirror_dir}/gestion-banco-bhd.wav"
  install -m 644 "${primary_dir}/gestion-banco-reservas.wav" "${mirror_dir}/gestion-banco-reservas.wav"
}

replace_asterisk_sections() {
  local source_file="$1"
  local target_file="$2"
  shift 2
  python3 - "$source_file" "$target_file" "$@" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

source_file = Path(sys.argv[1])
target_file = Path(sys.argv[2])
section_names = set(sys.argv[3:])
marker_start = "; BEGIN LAB-VOSK"
marker_end = "; END LAB-VOSK"

sample_text = source_file.read_text(encoding="utf-8").rstrip() + "\n"
target_text = target_file.read_text(encoding="utf-8")
target_text = re.sub(
    rf"(?ms)^\s*{re.escape(marker_start)}.*?^\s*{re.escape(marker_end)}\s*\n?",
    "",
    target_text,
)

lines = target_text.splitlines(keepends=True)
result_lines: list[str] = []
skip_section = False

for line in lines:
    stripped = line.strip()
    match = re.match(r"^\[([^\]]+)\]$", stripped)
    if match:
        section_name = match.group(1)
        skip_section = section_name in section_names
        if skip_section:
            continue
    if skip_section:
        continue
    result_lines.append(line)

result_text = "".join(result_lines).rstrip() + "\n\n"
result_text += f"{marker_start}\n{sample_text}{marker_end}\n"
target_file.write_text(result_text, encoding="utf-8")
PY
}

require_command "python3"
require_command "ffmpeg"
require_command "espeak-ng"
require_command "install"
require_command "asterisk"

mkdir -p "${BACKUP_DIR}"
backup_path "${EXTENSIONS_CONF}" "${BACKUP_DIR}"
backup_path "${PJSIP_CONF}" "${BACKUP_DIR}"

mkdir -p "${BACKUP_DIR}/usr-share-agi-bin" "${BACKUP_DIR}/var-lib-agi-bin"
shopt -s nullglob
for existing_agi in /usr/share/asterisk/agi-bin/*.py; do
  cp -a "${existing_agi}" "${BACKUP_DIR}/usr-share-agi-bin/"
done
for existing_agi in /var/lib/asterisk/agi-bin/*.py; do
  cp -a "${existing_agi}" "${BACKUP_DIR}/var-lib-agi-bin/"
done
shopt -u nullglob

for agi_dir in "${AGI_DIRS[@]}"; do
  mkdir -p "${agi_dir}"
  install_wrapper "vosk_cobranza.py" "${agi_dir}"
  install_wrapper "load_lead_context.py" "${agi_dir}"
  install_wrapper "generate_personalized_prompt.py" "${agi_dir}"
  install_wrapper "generate_name_audio.py" "${agi_dir}"
  install_wrapper "resolve_transfer_target.py" "${agi_dir}"
done

for sound_dir in "${SOUND_DIRS[@]}"; do
  install -d -m 755 "${sound_dir}"
done
for cache_dir in "${NAME_CACHE_DIRS[@]}"; do
  install -d -m 775 "${cache_dir}"
  chown root:"${ASTERISK_GROUP}" "${cache_dir}"
done

ensure_segmented_assets

if [[ ! -f "${ENV_FILE}" ]]; then
  cat >"${ENV_FILE}" <<'EOF'
# Exporta aqui variables opcionales para los AGIs del laboratorio.
# Ejemplo:
# ELEVENLABS_API_KEY=REEMPLAZAR_API_KEY
# ELEVENLABS_VOICE_ID=REEMPLAZAR_VOICE_ID
EOF
  chmod 640 "${ENV_FILE}"
fi

replace_asterisk_sections \
  "${PROJECT_DIR}/asterisk/extensions_lab.conf.sample" \
  "${EXTENSIONS_CONF}" \
  "lab-phones" \
  "ivr-cobranza-vosk" \
  "play-segmented" \
  "play-fallback" \
  "capturar-respuesta" \
  "manejar-reintento" \
  "reintento" \
  "transferir-abogado" \
  "documentar-callback" \
  "documentar-numero-equivocado" \
  "documentar-no-es-persona" \
  "finalizar"

replace_asterisk_sections \
  "${PROJECT_DIR}/asterisk/pjsip_lab.conf.sample" \
  "${PJSIP_CONF}" \
  "transport-lab-udp" \
  "1001" \
  "1002" \
  "1003" \
  "1004"

asterisk -rx "pjsip reload"
asterisk -rx "dialplan reload"

cat <<EOF
Deploy LAB-VOSK completado.
Backup: ${BACKUP_DIR}

Validaciones sugeridas:
  asterisk -rx "pjsip show endpoints"
  asterisk -rx "dialplan show 9901@lab-phones"
  asterisk -rx "dialplan show 9902@lab-phones"
  asterisk -rx "dialplan show 9903@lab-phones"
  python3 ${PROJECT_DIR}/scripts/test_name_cache.py "Juan Perez"
  tail -f /var/log/asterisk/vosk_cobranza.log
EOF
