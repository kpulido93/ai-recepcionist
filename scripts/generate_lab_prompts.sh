#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_DEST_DIR="${REPO_ROOT}/artifacts/lab-prompts"
DEST_DIR="${1:-${PROMPTS_DEST_DIR:-${DEFAULT_DEST_DIR}}}"
ESPEAK_BIN="${ESPEAK_BIN:-espeak-ng}"
FFMPEG_BIN="${FFMPEG_BIN:-ffmpeg}"
ESPEAK_VOICE="${ESPEAK_VOICE:-es}"
ESPEAK_SPEED="${ESPEAK_SPEED:-145}"

MENSAJE_COBRANZA_TEXT="${MENSAJE_COBRANZA_TEXT:-Hola, le llamamos por una gestión pendiente.}"
PREGUNTA_ABOGADO_TEXT="${PREGUNTA_ABOGADO_TEXT:-¿Lo transfiero ahora? Le escucho.}"
NO_ENTENDI_TEXT="${NO_ENTENDI_TEXT:-Disculpe, no le escuché bien.}"
MENSAJE_FINAL_TEXT="${MENSAJE_FINAL_TEXT:-Gracias. Hasta luego.}"

usage() {
  cat <<EOF
Uso:
  ${SCRIPT_NAME} [directorio-destino]

Genera prompts WAV de laboratorio para Asterisk en formato:
  - 8000 Hz
  - mono
  - PCM 16-bit

Ejemplos:
  ./scripts/${SCRIPT_NAME}
  ./scripts/${SCRIPT_NAME} /usr/share/asterisk/sounds/custom

Variables opcionales:
  PROMPTS_DEST_DIR       Directorio destino si no pasas argumento
  ESPEAK_BIN             Binario TTS local, por defecto: espeak-ng
  FFMPEG_BIN             Binario ffmpeg local, por defecto: ffmpeg
  ESPEAK_VOICE           Voz de espeak-ng, por defecto: es
  ESPEAK_SPEED           Velocidad de espeak-ng, por defecto: 145

Notas:
  - El script no usa internet ni TTS cloud.
  - Es solo para laboratorio local; en produccion usa voz humana dominicana grabada.
EOF
}

require_command() {
  local command_name="$1"
  local install_hint="$2"

  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "No se encontro ${command_name}. Instala ${install_hint} y vuelve a intentarlo." >&2
    exit 1
  fi
}

render_prompt() {
  local output_name="$1"
  local prompt_text="$2"
  local source_file="${WORK_DIR}/${output_name}.source.wav"
  local output_file="${DEST_DIR}/${output_name}.wav"

  "${ESPEAK_BIN}" -v "${ESPEAK_VOICE}" -s "${ESPEAK_SPEED}" -w "${source_file}" -- "${prompt_text}"
  "${FFMPEG_BIN}" -loglevel error -y -i "${source_file}" -ar 8000 -ac 1 -c:a pcm_s16le "${output_file}"
  echo "OK: ${output_file}"
}

print_validation_commands() {
  cat <<EOF

Validacion recomendada con soxi:
  soxi "${DEST_DIR}/mensaje-cobranza.wav"
  soxi "${DEST_DIR}/pregunta-abogado.wav"
  soxi "${DEST_DIR}/no-entendi.wav"
  soxi "${DEST_DIR}/mensaje-final.wav"
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

require_command "${ESPEAK_BIN}" "espeak-ng"
require_command "${FFMPEG_BIN}" "ffmpeg"
require_command "mktemp" "coreutils"

mkdir -p "${DEST_DIR}"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "${WORK_DIR}"' EXIT

render_prompt "mensaje-cobranza" "${MENSAJE_COBRANZA_TEXT}"
render_prompt "pregunta-abogado" "${PREGUNTA_ABOGADO_TEXT}"
render_prompt "no-entendi" "${NO_ENTENDI_TEXT}"
render_prompt "mensaje-final" "${MENSAJE_FINAL_TEXT}"

echo "Prompts generados en: ${DEST_DIR}"
print_validation_commands
