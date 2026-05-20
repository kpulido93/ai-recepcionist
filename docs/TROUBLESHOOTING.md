# Troubleshooting

## El script no devuelve `VOSK_INTENT`

Revisa:

- permisos de `agi/vosk_cobranza.py`
- que `agi-bin` apunte al archivo correcto
- salida en `/var/log/asterisk/full`
- log de la aplicacion configurado en `LOG_PATH`

## Vosk no responde

Prueba:

```bash
docker compose ps
./scripts/check_vosk.sh
```

Si el puerto no abre:

- confirma que el contenedor esta arriba
- revisa RAM disponible
- revisa si un firewall local bloquea `2700/tcp`

## El transcript sale vacio

Posibles causas:

- WAV en formato incorrecto
- audio demasiado corto
- volumen bajo
- sample rate no alineado con la llamada
- modelo de Vosk no adecuado para tu espanol

## Se oyen prompts pero no hay audio en fd 3

Revisa:

- que la llamada use `EAGI()` y no `AGI()`
- que el canal entregue audio lineal a fd 3
- que el host corra Linux; la captura EAGI de esta V1 no esta pensada para Windows

## Necesito revisar el audio crudo de EAGI

Para diagnostico puntual puedes activar en `config/ivr.yml`:

```yaml
debug:
  audio_dump_enabled: true
  audio_dump_dir: /tmp
```

Con eso el AGI guarda audio raw por llamada con nombre seguro y registra la ruta del archivo en el log.

Para convertir un dump a WAV:

```bash
ffmpeg -f s16le -ar 8000 -ac 1 -i /tmp/eagi-archivo.raw output.wav
```

Al terminar el diagnostico vuelve a `false` para no retener audio innecesario.

## El log muestra datos sensibles completos

Revisa:

- `logging.mask_phone_numbers: true`
- `logging.log_transcript: false` fuera de diagnosticos puntuales
- `config/logging.yml` con filtro `phone_mask`
- que no exista otro proceso escribiendo sin pasar por el logger del proyecto
