# Production checklist

## Plataforma

- Python 3.10 o superior validado
- Docker operativo en el host
- CPU y RAM medidos con trafico concurrente realista
- Rotacion de logs validada con `RotatingFileHandler` o politica equivalente

## Audio y STT

- Prompts convertidos a 8 kHz mono PCM
- Modelo de Vosk validado con llamadas reales
- Tiempo de escucha ajustado entre 3 y 5 segundos
- Pruebas con ruido, silencio y respuestas cortas

## Seguridad

- Sin secretos dentro del repo
- Puerto de Vosk restringido a red interna
- Permisos minimos en `agi-bin` y logs
- `logging.log_transcript` en `false` fuera de ventanas de diagnostico
- Masking de logs validado para telefonos, correos, identificaciones largas y montos
- Dialplan sin `NoOp(${VOSK_TEXT})` en produccion

## Operacion

- Ruta de transferencia configurada fuera del codigo
- Contexto puente `vicidial-cobranza-transfer` validado
- `LAWYER_TRANSFER_CONTEXT`, `LAWYER_TRANSFER_EXTEN` y `LAWYER_TRANSFER_PRIORITY` poblados por entorno
- `TRANSFER_MIN_CONFIDENCE` ajustado con datos reales
- Reintento unico probado
- Disposiciones finales acordadas con la operacion
- Monitoreo de errores del AGI y del contenedor Vosk
- Retencion y tamano de logs acordes al cumplimiento interno

## Antes de salir a produccion

```bash
ruff check .
ruff format --check .
mypy src
pytest -q
```
