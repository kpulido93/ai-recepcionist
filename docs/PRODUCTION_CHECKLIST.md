# Production checklist

## Plataforma

- Python 3.10 o superior validado
- Docker operativo en el host
- CPU y RAM medidos con trafico concurrente realista
- Rotacion de logs definida

## Audio y STT

- Prompts convertidos a 8 kHz mono PCM
- Modelo de Vosk validado con llamadas reales
- Tiempo de escucha ajustado entre 3 y 5 segundos
- Pruebas con ruido, silencio y respuestas cortas

## Seguridad

- Sin secretos dentro del repo
- Puerto de Vosk restringido a red interna
- Permisos minimos en `agi-bin` y logs

## Operacion

- Ruta de transferencia configurada fuera del codigo
- Reintento unico probado
- Disposiciones finales acordadas con la operacion
- Monitoreo de errores del AGI y del contenedor Vosk

## Antes de salir a produccion

```bash
ruff check .
ruff format --check .
mypy src
pytest -q
```
