# AGENTS.md

## Objetivo
Construir un IVR de cobranza para VICIdial/Asterisk usando EAGI y Vosk local.

## Alcance V1
- Un script EAGI principal para clasificar respuestas de voz o DTMF.
- STT local por Vosk Server via WebSocket.
- Configuracion externa en YAML.
- Pruebas locales con archivos WAV antes de conectarlo a Asterisk.
- Logs con enmascarado de numeros telefonicos.

## Reglas funcionales
- Clasificar la respuesta como `SI`, `NO`, `DUDA` o `SILENCIO`.
- Devolver `VOSK_INTENT` como variable de canal.
- No hardcodear destinos reales de Asterisk o VICIdial.
- Permitir un solo reintento desde el dialplan.

## Calidad
Antes de cerrar cambios:
- `ruff check .`
- `ruff format --check .`
- `mypy src`
- `pytest -q`

## Restricciones
- Python 3.10 o superior.
- Sin credenciales reales.
- Mantener el codigo simple, mantenible y documentado.
- Mantener diffs pequenos y por hito.
