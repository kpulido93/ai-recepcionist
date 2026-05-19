# vicidial-vosk-cobranza-ivr

IVR de cobranza para VICIdial/Asterisk basado en EAGI y Vosk local por WebSocket.

## Que hace

1. Asterisk reproduce un mensaje de cobranza.
2. El llamante responde por voz o, de forma opcional, por DTMF.
3. El script `agi/vosk_cobranza.py` escucha audio EAGI durante 3 a 5 segundos.
4. El audio PCM se envia a Vosk Server por WebSocket.
5. El texto reconocido se clasifica como `SI`, `NO`, `DUDA` o `SILENCIO`.
6. El script devuelve `VOSK_INTENT` para que el dialplan tome la decision final.

## Estructura

- `agi/vosk_cobranza.py`: entrypoint EAGI.
- `src/vicidial_vosk_cobranza_ivr/`: logica reutilizable.
- `config/`: YAML de IVR, intents y logging.
- `asterisk/extensions_custom.conf.sample`: ejemplo de dialplan.
- `scripts/test_audio_file.py`: prueba local con WAV.
- `tests/`: pruebas unitarias del clasificador y del loader de configuracion.
- `docs/`: instalacion, flujo, VICIdial y produccion.

## Requisitos

- Python 3.10+
- Docker y Docker Compose Plugin para levantar Vosk
- Asterisk 18 / Issabel 5 / VICIdial v12 en el despliegue objetivo

## Inicio rapido local

1. Crear entorno e instalar dependencias:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .[dev]
```

2. Descargar y colocar el modelo local:

El contenedor no descarga modelos por si mismo. Debes dejar el modelo extraido exactamente en:

```text
./models/model
```

Ejemplo con `vosk-model-small-es-0.42`:

```bash
mkdir -p models
cd models
wget https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip
unzip vosk-model-small-es-0.42.zip
rm vosk-model-small-es-0.42.zip
mv vosk-model-small-es-0.42 model
cd ..
```

La ruta final esperada por `docker-compose.yml` es:

```text
./models/model/am
./models/model/conf
./models/model/graph
...
```

3. Levantar Vosk:

```bash
docker compose up -d vosk-server
./scripts/check_vosk.sh
```

4. Probar un WAV mono PCM 16-bit:

```bash
python scripts/test_audio_file.py /ruta/al/audio.wav
```

5. Validar calidad:

```bash
ruff check .
ruff format --check .
mypy src
pytest -q
```

## Variables de entorno utiles

Mira `.env.example`. Las mas importantes:

- `VOSK_COBRANZA_CONFIG`
- `VOSK_COBRANZA_INTENTS`
- `VOSK_COBRANZA_LOGGING`
- `VOSK_WEBSOCKET_URL`
- `LOG_PATH`

## Integracion con Asterisk

- El dialplan reproduce el audio.
- Luego ejecuta `EAGI(vosk_cobranza.py,${COBRANZA_DTMF})`.
- El script devuelve `VOSK_INTENT`.
- El dialplan decide si transfiere, repite o finaliza.

Hay un ejemplo completo en [asterisk/extensions_custom.conf.sample](/D:/repos/ai-recepcionista/asterisk/extensions_custom.conf.sample).

## Advertencias de produccion

- No dejes el log dentro del repo en un servidor productivo.
- Usa prompts WAV 8 kHz, mono, PCM 16-bit.
- Ajusta el modelo de Vosk al espanol real de tu cartera.
- Valida CPU, RAM y latencia antes de enrutar trafico real.
- No hardcodees ingroups reales en el codigo; usa variables o contexto de dialplan.

## Documentacion

- [Instalacion](/D:/repos/ai-recepcionista/docs/INSTALL.md)
- [Setup VICIdial](/D:/repos/ai-recepcionista/docs/VICIDIAL_SETUP.md)
- [Flujo de llamada](/D:/repos/ai-recepcionista/docs/CALL_FLOW.md)
- [Troubleshooting](/D:/repos/ai-recepcionista/docs/TROUBLESHOOTING.md)
- [Checklist de produccion](/D:/repos/ai-recepcionista/docs/PRODUCTION_CHECKLIST.md)
