# vicidial-vosk-cobranza-ivr

IVR de cobranza para VICIdial/Asterisk basado en EAGI y Vosk local por WebSocket.

## Que hace

1. Asterisk reproduce un mensaje de cobranza.
2. El llamante responde por voz o, de forma opcional, por DTMF.
3. El script `agi/vosk_cobranza.py` escucha audio EAGI durante 3 a 5 segundos.
4. El audio PCM se envia a Vosk Server por WebSocket.
5. El texto reconocido se clasifica como `SI`, `INFO_COBRO`, `PROMESA_PAGO`, `NO`, `CALLBACK`, `NUMERO_EQUIVOCADO`, `NO_ES_PERSONA`, `DUDA` o `SILENCIO`.
6. El script devuelve `VOSK_INTENT`, `VOSK_CONFIDENCE`, `VOSK_SOURCE` y `VOSK_TEXT`
   para que el dialplan tome la decision final.

## Estructura

- `agi/vosk_cobranza.py`: entrypoint EAGI.
- `src/vicidial_vosk_cobranza_ivr/`: logica reutilizable.
- `config/`: YAML de IVR, intents, logging y ruteo por cartera.
- `asterisk/extensions_custom.conf.sample`: ejemplo de dialplan.
- `scripts/test_audio_file.py`: prueba local con WAV.
- `tests/`: pruebas unitarias del clasificador y del loader de configuracion.
- `docs/`: instalacion, flujo, VICIdial y produccion.

## Requisitos

- Python 3.10+
- Docker y Docker Compose Plugin para levantar Vosk
- Asterisk 18 / Issabel 5 / VICIdial v12 en el despliegue objetivo

## Laboratorio local recomendado

El flujo recomendado hoy para validar el proyecto de forma local es:

- `Ubuntu + Asterisk + Vosk en Docker + Zoiper`
- `1001`: cliente que llama al IVR
- `1002`: agente o abogado de prueba y fallback de laboratorio para transferencias
- `9900`: extension del IVR

## Estado estable actual del laboratorio

- Despliegue estable validado: `2026-05-25 22:31 AST`
- Ruta activa en el servidor local: `/opt/vicidial-vosk-cobranza-ivr`
- Extension de prueba aislada operativa: `9910`
- La transferencia del contexto de prueba ya usa `VOSK_TRANSFER_ELIGIBLE=1` o `VOSK_DECISION=TRANSFER`
- Frases probadas que transfieren: `comunicame`, `quiero pagar`, `cuanto debo`
- Frases probadas que no transfieren: `no`, `numero equivocado`, `no soy esa persona`
- Backup mas reciente usado para el despliegue estable: `/root/backup-vosk-deploy-20260525-223126`

Comandos utiles de monitoreo:

```bash
asterisk -rvvvvv
agi set debug on
agi set debug off
tail -f /var/log/asterisk/vosk_cobranza.log
```

Activos base del laboratorio:

- [Diseño final de Nivel 1 robusto](/D:/repos/ai-recepcionista/docs/NIVEL_1_IVR_ROBUSTO.md)
- [Guia del laboratorio Ubuntu + Asterisk + Vosk](/D:/repos/ai-recepcionista/docs/LAB_ASTERISK_UBUNTU.md)
- [Prompts de audio seguros](/D:/repos/ai-recepcionista/docs/AUDIO_PROMPTS.md)
- [Sample PJSIP de laboratorio](/D:/repos/ai-recepcionista/asterisk/pjsip_lab.conf.sample)
- [Sample de dialplan voice-first](/D:/repos/ai-recepcionista/asterisk/extensions_lab.conf.sample)

## Flujo voice-first

Flujo recomendado en laboratorio:

1. Asterisk reproduce el prompt del IVR.
2. `EAGI(vosk_cobranza.py)` escucha la respuesta por voz.
3. Si el intent es `SI`, `INFO_COBRO` o `PROMESA_PAGO`, el dialplan resuelve `IVR_TRANSFER_TARGET` por cartera y transfiere al destino configurado.
4. Si el intent es `NO`, `CALLBACK`, `NUMERO_EQUIVOCADO` o `NO_ES_PERSONA`, el flujo finaliza o deja una disposición documentada.
5. Si el intent es `DUDA` o `SILENCIO`, el dialplan reintenta una vez.

Ese comportamiento esta sampleado en [asterisk/extensions_lab.conf.sample](/D:/repos/ai-recepcionista/asterisk/extensions_lab.conf.sample) y toma el fallback de laboratorio desde `config/routing.yml`.

## Advertencias de laboratorio

- No hables encima del prompt si todavia no tienes barge-in real en el dialplan.
- Usa auriculares en Zoiper o el softphone para reducir eco.
- Evita prompts que contengan frases exactas de intents como `si`, `no`, `transfierame` o `abogado`.

## Comandos rapidos de laboratorio

```bash
docker compose up -d vosk-server
./scripts/check_vosk.sh
tail -f /var/log/asterisk/vosk_cobranza.log
sudo asterisk -rvvvvv
```

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

`check_vosk.sh` solo valida que el socket TCP responda. Para una prueba funcional
de reconocimiento usa `scripts/test_audio_file.py` con un WAV de prueba.

4. Probar un WAV mono PCM 16-bit:

```bash
python scripts/test_audio_file.py /ruta/al/audio.wav
```

5. Generar prompts de laboratorio seguros para Asterisk (opcional):

```bash
./scripts/generate_lab_prompts.sh /usr/share/asterisk/sounds/custom
```

6. Validar calidad:

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
- `IVR_ROUTING_CONFIG`
- `VOSK_WEBSOCKET_URL`
- `VOSK_WEBSOCKET_TIMEOUT_SECONDS`
- `VOSK_MIN_RMS`
- `LOG_PATH`
- `LOG_TRANSCRIPT`

En produccion usa rutas absolutas en `VOSK_COBRANZA_CONFIG`, `VOSK_COBRANZA_INTENTS` y
`VOSK_COBRANZA_LOGGING`. Si el AGI se copia a `/var/lib/asterisk/agi-bin/`, esas rutas evitan
depender de la ubicacion fisica del script para encontrar `config/` y `src/`.

Para troubleshooting controlado tambien puedes activar en `config/ivr.yml`:

- `debug.audio_dump_enabled: true`
- `debug.audio_dump_dir: /tmp`

Eso guarda el audio EAGI crudo por llamada. Para convertir un dump `.raw` a WAV usa:

```bash
ffmpeg -f s16le -ar 8000 -ac 1 -i input.raw output.wav
```

## Integracion con Asterisk

- El dialplan reproduce el audio.
- Si ya recogio DTMF, lo pasa como `agi_arg_1` con `EAGI(vosk_cobranza.py,${OPCION})`.
- El script evalua primero `agi_arg_1` contra `ivr.dtmf_map` antes de tocar audio o Vosk.
- El script devuelve `VOSK_INTENT`, `VOSK_CONFIDENCE`, `VOSK_SOURCE` y `VOSK_TEXT`.
- El dialplan decide si transfiere, repite o finaliza.
- La recomendacion actual es transferir a traves de `vicidial-cobranza-transfer` usando `LAWYER_TRANSFER_CONTEXT`, `LAWYER_TRANSFER_EXTEN` y `LAWYER_TRANSFER_PRIORITY`.

Valores utiles de `VOSK_SOURCE`:

- `dtmf`: la decision vino de `agi_arg_1`.
- `speech`: la decision vino de reconocimiento de voz.
- `silence`: no hubo audio util o el RMS quedo por debajo del umbral.
- `error`: hubo timeout o fallo de Vosk y el dialplan debe seguir una ruta segura.

Hay un ejemplo completo en [asterisk/extensions_custom.conf.sample](/D:/repos/ai-recepcionista/asterisk/extensions_custom.conf.sample).

## Advertencias de produccion

- El `docker-compose.yml` publica Vosk solo en `127.0.0.1` por defecto.
- Si Vosk corre en otro host, exponlo solo por red privada, VPN o firewall restrictivo.
- La referencia oficial de Vosk sigue usando `alphacep/kaldi-*:latest`; fija tag o digest
  inmutable antes de trafico real.
- No dejes el log dentro del repo en un servidor productivo.
- `logging.log_transcript` viene en `false` por defecto. Activalo solo para diagnostico controlado.
- No hagas `NoOp(${VOSK_TEXT})` ni registres el transcript completo en produccion.
- Trata `VOSK_TEXT` como dato operativo de debug controlado, no como dato de observabilidad permanente.
- Los logs rotan por `RotatingFileHandler` de forma local con el default `10 MB x 10` archivos.
- El masking de logs cubre telefonos, correos, identificaciones largas y montos, pero igual debes restringir acceso al archivo.
- Usa prompts WAV 8 kHz, mono, PCM 16-bit.
- Ajusta el modelo de Vosk al espanol real de tu cartera.
- Valida CPU, RAM y latencia antes de enrutar trafico real.
- No hardcodees ingroups reales en el codigo; usa variables o contexto de dialplan.

## Documentacion

- [Nivel 1 robusto](/D:/repos/ai-recepcionista/docs/NIVEL_1_IVR_ROBUSTO.md)
- [Instalacion](/D:/repos/ai-recepcionista/docs/INSTALL.md)
- [Laboratorio Ubuntu + Asterisk + Vosk](/D:/repos/ai-recepcionista/docs/LAB_ASTERISK_UBUNTU.md)
- [Prompts de audio seguros](/D:/repos/ai-recepcionista/docs/AUDIO_PROMPTS.md)
- [Setup VICIdial](/D:/repos/ai-recepcionista/docs/VICIDIAL_SETUP.md)
- [Flujo de llamada](/D:/repos/ai-recepcionista/docs/CALL_FLOW.md)
- [Troubleshooting](/D:/repos/ai-recepcionista/docs/TROUBLESHOOTING.md)
- [Checklist de produccion](/D:/repos/ai-recepcionista/docs/PRODUCTION_CHECKLIST.md)
