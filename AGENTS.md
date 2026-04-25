# AGENTS.md

## Objetivo del repo
Construir un microservicio Python para recepcionista digital de cobranza,
integrado con Issabel/Asterisk + VICIdial.

## Arquitectura obligatoria
- Un solo proceso `ari-worker` dueño del app Stasis `ai-recepcionista`
- Un proceso separado `admin-api` con FastAPI
- Media por ARI `externalMedia` usando RTP/UDP
- Transferencia a agentes por AMI Redirect
- Sin servicios cloud para STT/TTS en la V1
- STT principal: Vosk
- STT fallback: faster-whisper
- TTS: XTTS-v2 y Chatterbox-Multilingual detrás de una interfaz común

## Reglas de negocio
- Guion corto
- Una sola repregunta
- Transferir solo con sí explícito
- Si no hay agente, crear callback
- Guardar disposición final
- No negociar dentro del bot

## Calidad
Antes de cerrar cada hito:
- correr `ruff check .`
- correr `ruff format --check .`
- correr `mypy src`
- correr `pytest -q`

## Restricciones
- No romper compatibilidad con Asterisk 16/18
- No usar chan_websocket para media
- No meter el cliente ARI dentro de FastAPI workers
- Mantener diffs pequeños y por hito