# Instalacion

Guia de instalacion para un entorno con:

- VICIdial v12
- Issabel 5
- Asterisk 18
- Vosk Server local en el mismo host o separado en otro host de la red

## 1. Requisitos

Antes de instalar, valida lo siguiente:

- Acceso root o sudo al servidor Asterisk.
- Python 3.10 o superior.
- `pip`, `venv`, `ffmpeg` o `sox` para convertir audios.
- Docker y Docker Compose Plugin si vas a levantar Vosk con el `docker-compose.yml` del proyecto.
- Acceso de escritura a:
  - `/var/lib/asterisk/agi-bin/`
  - `/var/lib/asterisk/sounds/custom/`
  - `/etc/asterisk/extensions_custom.conf` o el archivo equivalente de tu instalacion
- Acceso desde Asterisk al puerto `2700/tcp` del servidor Vosk.
- Audios del IVR en WAV mono, 8 kHz, PCM 16-bit.

Rutas usadas en esta guia:

- Proyecto: `/opt/vicidial-vosk-cobranza-ivr`
- AGI: `/var/lib/asterisk/agi-bin/vosk_cobranza.py`
- Audios: `/var/lib/asterisk/sounds/custom/`
- Dialplan custom: `/etc/asterisk/extensions_custom.conf`

## 2. Instalacion de dependencias Python

Clona o copia el proyecto al servidor:

```bash
cd /opt
git clone <tu-repo> vicidial-vosk-cobranza-ivr
cd vicidial-vosk-cobranza-ivr
cp .env.example .env
```

Crea un entorno virtual e instala el proyecto:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install .
```

Si tambien quieres ejecutar pruebas y validaciones:

```bash
pip install -e .[dev]
```

## 3. Instalacion de Vosk Server

Tienes dos opciones.

### Opcion A: Vosk Server local en el mismo host

Instala Docker y Docker Compose Plugin con el gestor de paquetes de tu distribucion.

Levanta Vosk desde la raiz del proyecto:

```bash
cd /opt/vicidial-vosk-cobranza-ivr
docker compose up -d vosk-server
./scripts/check_vosk.sh
```

`check_vosk.sh` solo valida conectividad al puerto. Para confirmar reconocimiento real,
usa `python scripts/test_audio_file.py /ruta/audio.wav` con un WAV controlado.

### Opcion B: Vosk Server en un host separado

En el host remoto de Vosk:

1. Copia el proyecto o al menos `docker-compose.yml`.
2. Coloca el modelo en `./models/model`.
3. Levanta el contenedor:

```bash
docker compose up -d vosk-server
./scripts/check_vosk.sh
```

Si Vosk corre en un host separado, no abras `2700/tcp` a Internet. Usa al menos una de estas medidas:

- firewall con origenes restringidos al servidor Asterisk
- VPN entre Asterisk y el host Vosk
- red privada o segmento interno sin exposicion publica

En el servidor Asterisk, apunta el proyecto al host remoto editando `.env` o `config/ivr.yml`:

```bash
VOSK_WEBSOCKET_URL=ws://IP_DEL_SERVIDOR_VOSK:2700
```

Si el AGI va a copiarse a `/var/lib/asterisk/agi-bin/` en vez de quedar enlazado al repo,
declara rutas absolutas para `VOSK_COBRANZA_CONFIG`, `VOSK_COBRANZA_INTENTS` y
`VOSK_COBRANZA_LOGGING`. Eso evita depender del `__file__` del AGI para encontrar `config/`
y la logica Python compartida.

## 4. Descarga del modelo espanol

El contenedor no descarga modelos automaticamente. Debes descargar y extraer el modelo antes de arrancar Vosk.

Ejemplo con `vosk-model-small-es-0.42`:

```bash
cd /opt/vicidial-vosk-cobranza-ivr
mkdir -p models
cd models
wget https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip
unzip vosk-model-small-es-0.42.zip
rm vosk-model-small-es-0.42.zip
mv vosk-model-small-es-0.42 model
cd ..
```

La estructura final esperada es:

```text
/opt/vicidial-vosk-cobranza-ivr/models/model/am
/opt/vicidial-vosk-cobranza-ivr/models/model/conf
/opt/vicidial-vosk-cobranza-ivr/models/model/graph
...
```

Antes de salir a produccion, revisa tambien la imagen del servidor Vosk. La referencia oficial
publica ejemplos con `alphacep/kaldi-*:latest`; fija un tag o digest inmutable segun tu proceso
interno antes de trafico real.

## 5. Copia del script a /var/lib/asterisk/agi-bin/

Puedes instalarlo manualmente o usar el script del proyecto.

### Opcion recomendada: script de instalacion

```bash
cd /opt/vicidial-vosk-cobranza-ivr
sudo ./scripts/install_agi.sh
```

### Opcion manual

```bash
cp /opt/vicidial-vosk-cobranza-ivr/agi/vosk_cobranza.py /var/lib/asterisk/agi-bin/vosk_cobranza.py
```

Si el proyecto queda fuera de `/opt/vicidial-vosk-cobranza-ivr`, revisa las rutas de configuracion en `.env`.
Para produccion controlada usa rutas absolutas y define tambien `VOSK_MIN_RMS` si necesitas
subir o bajar el umbral de silencio sin tocar el YAML.
Si vas a copiar el AGI a `/var/lib/asterisk/agi-bin/`, no dependas de rutas relativas:
declara `VOSK_COBRANZA_CONFIG`, `VOSK_COBRANZA_INTENTS` y `VOSK_COBRANZA_LOGGING`
con rutas absolutas del proyecto instalado.

## 5.1 Exportar variables de entorno para Asterisk

El EAGI endurecido soporta overrides por entorno como:

- `VOSK_COBRANZA_CONFIG`
- `VOSK_COBRANZA_INTENTS`
- `VOSK_COBRANZA_LOGGING`
- `VOSK_WEBSOCKET_URL`
- `VOSK_WEBSOCKET_TIMEOUT_SECONDS`
- `VOSK_SAMPLE_RATE`
- `VOSK_MIN_RMS`
- `LOG_PATH`
- `LOG_TRANSCRIPT`

Si Asterisk corre como servicio `systemd`, una forma segura es usar un override:

```bash
mkdir -p /etc/systemd/system/asterisk.service.d
cat >/etc/systemd/system/asterisk.service.d/vosk-cobranza.conf <<'EOF'
[Service]
Environment=VOSK_COBRANZA_CONFIG=/opt/vicidial-vosk-cobranza-ivr/config/ivr.yml
Environment=VOSK_COBRANZA_INTENTS=/opt/vicidial-vosk-cobranza-ivr/config/intents.yml
Environment=VOSK_COBRANZA_LOGGING=/opt/vicidial-vosk-cobranza-ivr/config/logging.yml
Environment=VOSK_WEBSOCKET_URL=ws://127.0.0.1:2700
Environment=VOSK_WEBSOCKET_TIMEOUT_SECONDS=10
Environment=VOSK_MIN_RMS=150.0
Environment=LOG_PATH=/var/log/asterisk/vosk_cobranza.log
Environment=LOG_TRANSCRIPT=false
EOF
systemctl daemon-reload
systemctl restart asterisk
```

Si tu instalacion usa otro mecanismo de arranque, exporta las mismas variables en el wrapper
o script que lanza Asterisk. Lo importante es que el proceso `asterisk` vea esas variables,
no solo tu sesion de shell.

## 6. Permisos chmod +x

El script debe ser ejecutable por Asterisk:

```bash
chmod +x /var/lib/asterisk/agi-bin/vosk_cobranza.py
chown root:asterisk /var/lib/asterisk/agi-bin/vosk_cobranza.py
```

Si usas otra cuenta o grupo para Asterisk, ajusta `asterisk` por el grupo real de tu servidor.

## 6.1 Permisos seguros del log

Si usas `LOG_PATH=/var/log/asterisk/vosk_cobranza.log`, crea el archivo con permisos cerrados:

```bash
touch /var/log/asterisk/vosk_cobranza.log
chown root:asterisk /var/log/asterisk/vosk_cobranza.log
chmod 640 /var/log/asterisk/vosk_cobranza.log
```

Recomendacion adicional:

- deja el directorio `/var/log/asterisk` con permisos acordes a tu politica interna
- valida que solo el grupo de Asterisk y administracion autorizada puedan leer el archivo
- configura `logrotate` o una politica equivalente si no vas a usar la rotacion local del proyecto

## 7. Copia de audios a /var/lib/asterisk/sounds/custom/

Copia tus audios a la carpeta custom:

```bash
mkdir -p /var/lib/asterisk/sounds/custom
cp /ruta/audios/mensaje-cobranza.wav /var/lib/asterisk/sounds/custom/
cp /ruta/audios/pregunta-abogado.wav /var/lib/asterisk/sounds/custom/
cp /ruta/audios/no-entendi.wav /var/lib/asterisk/sounds/custom/
cp /ruta/audios/lo-comunico.wav /var/lib/asterisk/sounds/custom/
cp /ruta/audios/mensaje-final.wav /var/lib/asterisk/sounds/custom/
chown asterisk:asterisk /var/lib/asterisk/sounds/custom/*.wav
chmod 644 /var/lib/asterisk/sounds/custom/*.wav
```

Valida formato de audio:

```bash
soxi /var/lib/asterisk/sounds/custom/mensaje-cobranza.wav
```

Debe ser:

- mono
- 8000 Hz
- PCM 16-bit

## 8. Inclusion del contexto en extensions_custom.conf

Copia el contexto sample del proyecto al dialplan custom:

Archivo base:

- [asterisk/extensions_custom.conf.sample](/D:/repos/ai-recepcionista/asterisk/extensions_custom.conf.sample)

Edita o agrega en `/etc/asterisk/extensions_custom.conf` el contexto:

```ini
[ivr-cobranza-vosk]
exten => s,1,NoOp(Inicio IVR cobranza Vosk)
 same => n,Answer()
 same => n,Set(TRY=0)
 same => n,Set(MAX_RETRIES=1)
 same => n,Set(MIN_CONFIDENCE=${IF($["${MIN_CONFIDENCE}"=""]?0.70:${MIN_CONFIDENCE})})
 same => n,Set(__LAWYER_TRANSFER_CONTEXT=${IF($["${LAWYER_TRANSFER_CONTEXT}"=""]?REEMPLAZAR_CONTEXTO_TRANSFER:${LAWYER_TRANSFER_CONTEXT})})
 same => n,Set(__LAWYER_TRANSFER_EXTEN=${IF($["${LAWYER_TRANSFER_EXTEN}"=""]?REEMPLAZAR_INGROUP_O_EXTENSION:${LAWYER_TRANSFER_EXTEN})})
 same => n,Set(__LAWYER_TRANSFER_PRIORITY=${IF($["${LAWYER_TRANSFER_PRIORITY}"=""]?1:${LAWYER_TRANSFER_PRIORITY})})
 same => n,Playback(custom/mensaje-cobranza)

 same => n(start),Set(OPCION=)
 same => n,Set(VOSK_TEXT=)
 same => n,Set(VOSK_INTENT=)
 same => n,Set(VOSK_CONFIDENCE=)
 same => n,Set(VOSK_SOURCE=)
 same => n,Playback(custom/pregunta-abogado)
 same => n,Read(OPCION,,1,,1,1)
 same => n,GotoIf($["${OPCION}"="1"]?transferir-abogado,1)
 same => n,GotoIf($["${OPCION}"="2"]?finalizar,1)
 same => n,EAGI(vosk_cobranza.py,${OPCION})
 same => n,Set(VOSK_INTENT=${IF($["${VOSK_INTENT}"=""]?DUDA:${VOSK_INTENT})})
 same => n,Set(VOSK_CONFIDENCE=${IF($["${VOSK_CONFIDENCE}"=""]?0.00:${VOSK_CONFIDENCE})})
 same => n,Set(VOSK_SOURCE=${IF($["${VOSK_SOURCE}"=""]?unknown:${VOSK_SOURCE})})
 same => n,NoOp(Vosk intent: ${VOSK_INTENT} confidence: ${VOSK_CONFIDENCE} source: ${VOSK_SOURCE})
 same => n,GotoIf($["${VOSK_INTENT}"="SI"]?validar-si,1)
 same => n,GotoIf($["${VOSK_INTENT}"="NO"]?validar-no,1)
 same => n,GotoIf($["${VOSK_INTENT}"="DUDA"]?manejar-reintento,1)
 same => n,GotoIf($["${VOSK_INTENT}"="SILENCIO"]?manejar-reintento,1)
 same => n,Goto(manejar-reintento,1)

exten => validar-si,1,GotoIf($[${VOSK_CONFIDENCE} >= ${MIN_CONFIDENCE}]?transferir-abogado,1)
 same => n,Goto(manejar-reintento,1)

exten => validar-no,1,GotoIf($[${VOSK_CONFIDENCE} >= ${MIN_CONFIDENCE}]?finalizar,1)
 same => n,Goto(manejar-reintento,1)

exten => manejar-reintento,1,Set(TRY=$[${TRY}+1])
 same => n,GotoIf($[${TRY} <= ${MAX_RETRIES}]?reintento,1)
 same => n,Goto(finalizar,1)

exten => reintento,1,Playback(custom/no-entendi)
 same => n,Goto(s,start)

exten => transferir-abogado,1,Goto(vicidial-cobranza-transfer,s,1)

exten => finalizar,1,Playback(custom/mensaje-final)
 same => n,Hangup()

[vicidial-cobranza-transfer]
exten => s,1,NoOp(Bridge cobranza -> abogados)
 same => n,Set(__VICI_ORIG_UNIQUEID=${UNIQUEID})
 same => n,Set(__VICI_ORIG_CALLERID=${CALLERID(all)})
 same => n,Set(__VICI_ORIG_CALLERID_NUM=${CALLERID(num)})
 same => n,Set(__VICI_ORIG_CHANNEL=${CHANNEL})
 same => n,Set(__VICI_CAMPAIGN_ID=${CAMPAIGN_ID})
 same => n,Set(__VICI_LEAD_ID=${LEAD_ID})
 same => n,Set(__VICI_LIST_ID=${LIST_ID})
 same => n,Set(__VOSK_INTENT=${VOSK_INTENT})
 same => n,Set(__VOSK_CONFIDENCE=${VOSK_CONFIDENCE})
 same => n,Set(__VOSK_SOURCE=${VOSK_SOURCE})
 same => n,GotoIf($["${LAWYER_TRANSFER_CONTEXT}"="REEMPLAZAR_CONTEXTO_TRANSFER"]?transfer-config-error,1)
 same => n,GotoIf($["${LAWYER_TRANSFER_EXTEN}"="REEMPLAZAR_INGROUP_O_EXTENSION"]?transfer-config-error,1)
 same => n,GotoIf($["${DIALPLAN_EXISTS(${LAWYER_TRANSFER_CONTEXT},${LAWYER_TRANSFER_EXTEN},${LAWYER_TRANSFER_PRIORITY})}"="1"]?dial-target,1)
 same => n,Goto(transfer-config-error,1)

exten => dial-target,1,Playback(custom/lo-comunico)
 same => n,Dial(Local/route@vicidial-cobranza-transfer/n,45,g)
 same => n,GotoIf($["${DIALSTATUS}"="ANSWER"]?done,1)
 same => n,Goto(transfer-config-error,1)

exten => route,1,Goto(${LAWYER_TRANSFER_CONTEXT},${LAWYER_TRANSFER_EXTEN},${LAWYER_TRANSFER_PRIORITY})

exten => done,1,Hangup()

exten => transfer-config-error,1,Playback(custom/mensaje-final)
 same => n,Hangup()
```

Puntos que debes adaptar para VICIdial:

- `LAWYER_TRANSFER_CONTEXT`
- `LAWYER_TRANSFER_EXTEN`
- `LAWYER_TRANSFER_PRIORITY`
- `MIN_CONFIDENCE`
- los nombres reales de los audios
- cualquier `Local/` o contexto puente que uses para entregar la llamada al flujo legal

Notas de privacidad para produccion:

- Evita `NoOp(${VOSK_TEXT})` en dialplan productivo.
- `VOSK_TEXT` debe reservarse para decisiones de canal o debug controlado.
- El proyecto deja `logging.log_transcript: false` por defecto.
- `Read(OPCION,,1,,1,1)` agrega una ventana corta de DTMF antes del EAGI. Si tu
  operacion es voice-first puro, reduce aun mas ese timeout o elimina `Read()`.

## 9. Recarga de dialplan

Despues de modificar `extensions_custom.conf`, recarga Asterisk:

```bash
asterisk -rx "dialplan reload"
```

Si tambien cambiaste otros modulos o integracion de audio, revisa:

```bash
asterisk -rx "core show channels"
asterisk -rx "dialplan show ivr-cobranza-vosk"
```

## 10. Prueba desde extension interna

Haz una prueba controlada antes de pasar a VICIdial.

1. Crea una extension temporal o usa `originate`.
2. Enruta la llamada al contexto `ivr-cobranza-vosk`.
3. Verifica los tres casos:
   - DTMF `1`
   - DTMF `2`
   - respuesta por voz

Ejemplo de prueba:

```bash
asterisk -rvvvvv
```

Luego llama a una extension de prueba que haga:

```ini
exten => 9900,1,Goto(ivr-cobranza-vosk,s,1)
```

En consola valida:

- que se reproduzcan los audios
- que se ejecute `EAGI(vosk_cobranza.py)`
- que `VOSK_INTENT` se resuelva correctamente
- que el NoOp solo muestre `VOSK_INTENT`, `VOSK_CONFIDENCE` y `VOSK_SOURCE`
- que la llamada vaya a `transferir-abogado` o `finalizar`

## 11. Prueba desde campana VICIdial

Cuando la prueba interna funcione, integra el flujo con una campana real o de laboratorio.

Pasos sugeridos:

1. Usa una lista de prueba con numeros controlados.
2. Inserta el contexto `ivr-cobranza-vosk` dentro del flujo de llamada de la campana.
3. Verifica que la llamada llegue al IVR antes del transfer.
4. Prueba estos escenarios:
   - cliente pulsa `1`
   - cliente pulsa `2`
   - cliente responde "si"
   - cliente responde "no"
   - cliente guarda silencio
5. Valida que la ruta configurada en `LAWYER_TRANSFER_CONTEXT` y `LAWYER_TRANSFER_EXTEN`
   resuelva correctamente en tu entorno VICIdial.

Durante la prueba, observa:

- `/var/log/asterisk/full`
- el log configurado por el proyecto
- el estado del contenedor Vosk

En las pruebas de transferencia valida tambien:

- que `VOSK_CONFIDENCE` no permita transferencias por voz por debajo de `MIN_CONFIDENCE`
- que el contexto `vicidial-cobranza-transfer` conserve `UNIQUEID` y `CALLERID`
- que `CAMPAIGN_ID`, `LEAD_ID` y `LIST_ID` sigan presentes si tu entorno los expone

## Logs de produccion

Por defecto el proyecto usa `RotatingFileHandler` con:

- `logging.rotate_max_bytes: 10485760`
- `logging.rotate_backup_count: 10`
- `logging.log_transcript: false`

Si necesitas diagnostico temporal, activa `logging.log_transcript: true` solo durante la ventana de prueba y vuelve a desactivarlo despues.

## 12. Troubleshooting

### No audio en EAGI

Posibles causas:

- se esta usando `AGI()` en vez de `EAGI()`
- el canal no entrega audio util al `fd 3`
- el audio llega demasiado bajo o muy tarde
- la llamada entra en un punto del dialplan donde ya no hay media activa

Revision rapida:

```bash
asterisk -rvvvvv
tail -f /var/log/asterisk/full
```

Confirma que el dialplan use exactamente:

```ini
same => n,EAGI(vosk_cobranza.py)
```

### Vosk no responde

Valida conectividad:

```bash
cd /opt/vicidial-vosk-cobranza-ivr
./scripts/check_vosk.sh
docker compose ps
```

Si Vosk esta en otro host:

```bash
./scripts/check_vosk.sh ws://IP_DEL_SERVIDOR_VOSK:2700
```

Revisa:

- puerto `2700/tcp`
- firewall
- URL en `.env` o `config/ivr.yml`
- que el modelo exista en `./models/model`

### Permisos de script

Si Asterisk no ejecuta el AGI:

```bash
ls -l /var/lib/asterisk/agi-bin/vosk_cobranza.py
```

Debe tener permiso de ejecucion:

```bash
chmod +x /var/lib/asterisk/agi-bin/vosk_cobranza.py
chown root:asterisk /var/lib/asterisk/agi-bin/vosk_cobranza.py
```

Tambien revisa el shebang:

```text
#!/usr/bin/env python3
```

### Formato de audio incorrecto

Si Asterisk reproduce mal o Vosk reconoce vacio, revisa el WAV:

```bash
soxi /var/lib/asterisk/sounds/custom/pregunta-abogado.wav
```

Convierte si hace falta:

```bash
ffmpeg -i entrada.mp3 -ac 1 -ar 8000 -sample_fmt s16 /var/lib/asterisk/sounds/custom/pregunta-abogado.wav
```

### No transfiere al ingroup

Si el IVR detecta `SI` pero no transfiere:

- revisa `LAWYER_TRANSFER_CONTEXT`, `LAWYER_TRANSFER_EXTEN` y `LAWYER_TRANSFER_PRIORITY`
- confirma que el contexto puente `vicidial-cobranza-transfer` este cargado
- confirma que la ruta final exista en tu servidor
- confirma que `VOSK_CONFIDENCE` supera `MIN_CONFIDENCE` cuando la fuente es voz
- si tu operacion usa otro puente `Local/`, cambia la ruta del sample por la tuya

Ejemplo alternativo:

```ini
exten => route,1,Goto(${LAWYER_TRANSFER_CONTEXT},${LAWYER_TRANSFER_EXTEN},${LAWYER_TRANSFER_PRIORITY})
```

## Validacion final recomendada

Antes de mover trafico real:

```bash
cd /opt/vicidial-vosk-cobranza-ivr
. .venv/bin/activate
ruff check .
ruff format --check .
mypy src
pytest -q
```
