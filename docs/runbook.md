# Runbook

## Estado actual
El workspace actual no contiene todavía el árbol de aplicación (`src/`, `tests/`, `Dockerfile`, `docker-compose.yml`, etc.). Este runbook documenta el procedimiento operativo esperado para la arquitectura acordada del servicio: `admin-api` + `ari-worker`, ARI `externalMedia` por RTP/UDP, STT/TTS locales y transferencia por AMI Redirect.

## Cómo arrancar local
Suposiciones esperadas:
- Python 3.11
- virtualenv local en `.venv`
- archivo `.env` derivado de `.env.example`
- procesos separados `admin-api` y `ari-worker`

Pasos:
1. Crear el entorno:
   - `python -m venv .venv`
   - `.\.venv\Scripts\python.exe -m pip install --upgrade pip`
   - `.\.venv\Scripts\python.exe -m pip install -e ".[dev,stt,tts]"`
2. Crear directorios operativos:
   - `artifacts\health`
   - `artifacts\audit`
   - `artifacts\tts_cache`
   - `models`
   - `voices`
3. Configurar `.env` con ARI, AMI, RTP y rutas de modelos.
4. Arrancar `admin-api`:
   - `.\.venv\Scripts\uvicorn.exe src.ai_recepcionista.api.app:app --host 0.0.0.0 --port 8000`
5. Arrancar `ari-worker`:
   - `.\.venv\Scripts\ari-worker.exe`
6. Verificar salud:
   - `.\.venv\Scripts\python.exe scripts\healthcheck.py http http://127.0.0.1:8000/health`
   - `.\.venv\Scripts\python.exe scripts\healthcheck.py file .\artifacts\health\ari-worker.json 30`

## Cómo configurar ARI
Configurar en Asterisk / Issabel:
1. Habilitar HTTP:
   - `enabled = yes`
   - `bindaddr = 0.0.0.0`
   - `bindport = 8088`
2. Crear usuario ARI con permisos sobre la aplicación Stasis `ai-recepcionista`.
3. Definir en el servicio:
   - `STASIS_APP_NAME=ai-recepcionista`
   - `ARI_BASE_URL=http://PBX:8088/ari`
   - `ARI_USERNAME=...`
   - `ARI_PASSWORD=...`
4. Verificar que `externalMedia` use:
   - `encapsulation=rtp`
   - `transport=udp`
   - `format=ulaw`
5. Confirmar reachability desde Asterisk al host anunciado en:
   - `MEDIA_ADVERTISED_HOST`
   - `MEDIA_RTP_START_PORT` / `MEDIA_RTP_END_PORT`

## Cómo probar una llamada
1. Confirmar que `admin-api` responda `/health` y `/ready`.
2. Confirmar que `ari-worker` escriba heartbeat en `artifacts\health\ari-worker.json`.
3. Enviar una llamada a la app Stasis `ai-recepcionista`.
4. Verificar este flujo esperado:
   - `StasisStart`
   - creación de bridge `mixing`
   - alta de `externalMedia`
   - saludo corto
   - entrada RTP al pipeline STT
   - clasificación `YES_EXPLICIT`, `NO_EXPLICIT` o `UNCLEAR`
   - `AMI Redirect` si hay `YES_EXPLICIT` y agente disponible
   - callback si no hay agente
   - disposición final y auditoría
5. Revisar logs JSON y `artifacts\audit\events.jsonl`.
6. Ejecutar smoke reproducible:
   - `bash scripts/smoke.sh`

## Cómo activar una voz local
1. Guardar una voz femenina de referencia, por ejemplo:
   - `voices\female_reference.wav`
2. Configurar:
   - `TTS_ENGINE=xtts` o `TTS_ENGINE=chatterbox`
   - `TTS_REFERENCE_VOICE_PATH=./voices/female_reference.wav`
3. Si se usa XTTS:
   - `XTTS_CONFIG_PATH`
   - `XTTS_CHECKPOINT_PATH`
   - `XTTS_VOCAB_PATH`
4. Si se usa Chatterbox:
   - `CHATTERBOX_MODEL_PATH`
5. Precachear frases:
   - `.\.venv\Scripts\python.exe scripts\precache_tts.py`

## Cómo hacer rollback
1. Detener `admin-api` y `ari-worker`.
2. Restaurar la última versión estable del workspace.
3. Restaurar el `.env` estable.
4. Limpiar artefactos temporales si corresponde:
   - `artifacts\health`
   - `artifacts\audit`
   - `artifacts\tts_cache`
5. Arrancar primero `admin-api`, luego `ari-worker`.
6. Validar:
   - `/health`
   - heartbeat del worker
   - smoke test

## Riesgo operativo actual
El contenido de aplicación no está presente en este workspace. Antes de usar este runbook en producción, hay que restaurar o clonar el árbol real del microservicio.
