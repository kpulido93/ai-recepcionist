# Production checklist

## Plataforma

- Python 3.10 o superior validado
- Docker operativo en el host
- CPU y RAM medidos con trafico concurrente realista
- Rotacion de logs validada con `RotatingFileHandler` o politica equivalente
- Pruebas de concurrencia ejecutadas con la carga esperada de campana
- Latencia medida con percentiles p95 y p99 en escenario realista

## Audio y STT

- Prompts convertidos a 8 kHz mono PCM
- Modelo de Vosk validado con llamadas reales
- Tiempo de escucha ajustado entre 3 y 5 segundos
- Pruebas con ruido, silencio y respuestas cortas
- Errores de WebSocket medidos y observables en logs o monitoreo
- Plan de fallback definido si Vosk queda caido o degradado

## Seguridad

- Sin secretos dentro del repo
- Puerto de Vosk restringido a red interna
- Puerto de Vosk cerrado a red publica
- Permisos minimos en `agi-bin` y logs
- `logging.log_transcript` en `false` fuera de ventanas de diagnostico
- Sin transcript completo en `NoOp()`, `VERBOSE` o logs permanentes
- Masking de logs validado para telefonos, correos, identificaciones largas y montos
- Dialplan sin `NoOp(${VOSK_TEXT})` en produccion
- `logrotate` o politica equivalente validada sobre el archivo final
- Permisos de logs revisados, por ejemplo `640` con grupo de Asterisk

## Operacion

- Ruta de transferencia configurada fuera del codigo
- Contexto puente `vicidial-cobranza-transfer` validado
- `LAWYER_TRANSFER_CONTEXT`, `LAWYER_TRANSFER_EXTEN` y `LAWYER_TRANSFER_PRIORITY` poblados por entorno
- `MIN_CONFIDENCE` ajustado con datos reales
- Reintento unico probado
- Validacion positiva y negativa de transferencia ejecutada
- Flujo cuando `VOSK_SOURCE=error` validado de punta a punta
- Disposiciones finales acordadas con la operacion
- Monitoreo de errores del AGI y del contenedor Vosk
- Retencion y tamano de logs acordes al cumplimiento interno
- Revision legal del flujo de cobranza completada antes de trafico real

## Antes de salir a produccion

```bash
ruff check .
ruff format --check .
mypy src
pytest -q
```
