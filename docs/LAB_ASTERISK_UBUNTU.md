# Laboratorio Ubuntu + Asterisk + Vosk

Guia oficial para montar el laboratorio local del proyecto sin asumir VICIdial instalado.

Este laboratorio sirve para validar el flujo EAGI + Vosk en una PBX Asterisk local usando dos softphones SIP (`1001` y `1002`) y una extension de prueba (`9900`). No reemplaza la configuracion productiva ni la integracion final con VICIdial.

## Estado estable actual

Referencia operativa del ultimo despliegue estable validado en el servidor local:

- Fecha y hora: `2026-05-25 22:31 AST`
- Ruta activa: `/opt/vicidial-vosk-cobranza-ivr`
- Extension de prueba funcionando correctamente: `9910`
- La transferencia del contexto de prueba ya depende de `VOSK_TRANSFER_ELIGIBLE=1` o `VOSK_DECISION=TRANSFER`
- Frases probadas que transfieren: `comunicame`, `quiero pagar`, `cuanto debo`
- Frases probadas que no transfieren: `no`, `numero equivocado`, `no soy esa persona`
- Backup mas reciente usado: `/root/backup-vosk-deploy-20260525-223126`
- Ruta estable activa en servidor: Asterisk actual + Vosk nativo + motor de decision

Comandos utiles de monitoreo:

```bash
asterisk -rvvvvv
agi set debug on
agi set debug off
tail -f /var/log/asterisk/vosk_cobranza.log
```

## 1. Arquitectura

Flujo base del laboratorio:

```text
Softphone 1001 -> Asterisk -> lead context -> saludo personalizado -> EAGI -> Vosk Docker -> intent -> cartera/1002 fallback
```

Descripcion operativa:

1. El usuario registrado como `1001` llama a la extension `9900`.
2. Asterisk carga contexto de lead con `AGI(load_lead_context.py)`.
3. Asterisk puede generar audio de nombre con `AGI(generate_name_audio.py)` y luego resuelve el saludo con `AGI(generate_personalized_prompt.py)`.
4. `EAGI(vosk_cobranza.py)` envia audio a Vosk Server por WebSocket.
5. El texto reconocido se clasifica y el motor devuelve `VOSK_INTENT`, `VOSK_DECISION` y `VOSK_TRANSFER_ELIGIBLE`.
6. Segun la decision y el intent, Asterisk resuelve el destino por cartera con `AGI(resolve_transfer_target.py)`, transfiere con fallback a `1002`, reintenta una vez o finaliza/documenta el resultado en el laboratorio.

## 2. Dependencias Ubuntu

Paquetes base:

- `git`
- `python3`
- `python3-venv`
- `python3-pip`
- `ffmpeg`
- `sox`
- `unzip`
- `wget`
- `asterisk`
- `docker.io`
- soporte para `docker compose`

Instalacion sugerida:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip ffmpeg sox unzip wget asterisk docker.io
sudo apt install -y docker-compose-v2 || sudo apt install -y docker-compose-plugin
```

Notas:

- Si tu usuario no pertenece al grupo `docker`, usa `sudo docker compose ...`.
- El nombre del paquete para habilitar `docker compose` puede variar segun la version de Ubuntu.

## 3. Correccion comun de APT

Si `apt update` falla por una fuente de CD-ROM rota:

```bash
sudo rm -f /etc/apt/sources.list.d/cdrom.sources
sudo apt update
```

Si ves errores `404 Not Found`, revisa el mirror configurado en `sources.list` o `ubuntu.sources`.

Ejemplo con el archivo moderno de Ubuntu:

```bash
sudo editor /etc/apt/sources.list.d/ubuntu.sources
```

Cambia la linea `URIs:` a un mirror valido, por ejemplo:

```text
URIs: http://archive.ubuntu.com/ubuntu
```

Despues vuelve a correr:

```bash
sudo apt update
```

## 4. Clonado del repo

Ruta sugerida del proyecto:

```text
/opt/vicidial-vosk-cobranza-ivr
```

Clonado sobre la rama `dev`:

```bash
cd /opt
sudo git clone --branch dev https://github.com/kpulido93/ai-recepcionist.git vicidial-vosk-cobranza-ivr
sudo chown -R "$USER":"$USER" /opt/vicidial-vosk-cobranza-ivr
cd /opt/vicidial-vosk-cobranza-ivr
```

## 5. Modelo Vosk

La carpeta esperada por el `docker-compose.yml` es:

```text
./models/model
```

Ejemplo de descarga:

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

Valida que al menos existan estos paths:

```bash
test -f models/model/am/final.mdl
test -f models/model/conf/model.conf
test -d models/model/graph
```

Si alguno falla, el contenedor levantara sin reconocer audio de forma util.

## 6. Docker

Levanta Vosk desde la raiz del repo:

```bash
cd /opt/vicidial-vosk-cobranza-ivr
docker compose up -d vosk-server
./scripts/check_vosk.sh
```

Validaciones utiles:

```bash
docker compose ps
docker logs -f vosk-server
```

Notas:

- `scripts/check_vosk.sh` solo valida conectividad TCP al puerto de Vosk.
- Si usas otro host para Vosk, pasa la URL por argumento o por `VOSK_WEBSOCKET_URL`.

## 7. Entorno Python

Prepara el entorno virtual del proyecto:

```bash
cd /opt/vicidial-vosk-cobranza-ivr
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .[dev]
pytest -q
```

Validacion completa recomendada antes de cambios Python:

```bash
ruff check .
ruff format --check .
mypy src agi scripts
pytest -q
```

## 8. AGI

El laboratorio puede usar un wrapper en `agi-bin` para obligar a Asterisk a correr el proyecto con la `.venv` del repo.

Rutas comunes de `agi-bin`:

- `/var/lib/asterisk/agi-bin`
- `/usr/share/asterisk/agi-bin`

Confirma cual usa tu instalacion y crea el wrapper en esa carpeta.

El sample de laboratorio usa estos AGIs:

- `vosk_cobranza.py`
- `load_lead_context.py`
- `generate_personalized_prompt.py`
- `resolve_transfer_target.py`

Ejemplo de wrapper:

```bash
sudo tee /var/lib/asterisk/agi-bin/vosk_cobranza.py >/dev/null <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/opt/vicidial-vosk-cobranza-ivr"
export VOSK_COBRANZA_CONFIG="${PROJECT_DIR}/config/ivr.yml"
export VOSK_COBRANZA_INTENTS="${PROJECT_DIR}/config/intents.yml"
export VOSK_COBRANZA_LOGGING="${PROJECT_DIR}/config/logging.yml"
export LOG_PATH="/var/log/asterisk/vosk_cobranza.log"

exec "${PROJECT_DIR}/.venv/bin/python" "${PROJECT_DIR}/agi/vosk_cobranza.py" "$@"
EOF
sudo chmod 755 /var/lib/asterisk/agi-bin/vosk_cobranza.py
sudo chown root:asterisk /var/lib/asterisk/agi-bin/vosk_cobranza.py
```

Si tu distro usa `/usr/share/asterisk/agi-bin`, cambia solo la ruta de destino del wrapper.

Para `load_lead_context.py`, `generate_personalized_prompt.py` y `resolve_transfer_target.py` puedes repetir el mismo patron o usar symlinks hacia los scripts del repo si ya instalaste el proyecto localmente.

Tambien puedes apoyarte en [scripts/install_agi.sh](/D:/repos/ai-recepcionista/scripts/install_agi.sh) como base de despliegue local, pero el wrapper anterior deja explicito que Asterisk debe usar la `.venv` del laboratorio.

Si usas el sample del laboratorio con saludo personalizado, crea tambien un wrapper gemelo para `generate_personalized_prompt.py` en el mismo `agi-bin`, apuntando a `${PROJECT_DIR}/agi/generate_personalized_prompt.py`.

## 9. Asterisk

Objetivo minimo del laboratorio:

- extension SIP `1001` para originar la llamada
- extension SIP `1002` para recibir la transferencia de prueba
- extension `9900` para entrar al IVR
- audios en `sounds/custom`

Samples incluidos en el repo:

- [asterisk/pjsip_lab.conf.sample](/D:/repos/ai-recepcionista/asterisk/pjsip_lab.conf.sample): endpoints PJSIP locales `1001` y `1002`, transporte UDP en `0.0.0.0:5060` y placeholders seguros.
- [asterisk/extensions_lab.conf.sample](/D:/repos/ai-recepcionista/asterisk/extensions_lab.conf.sample): dialplan del laboratorio con `load_lead_context.py`, `generate_name_audio.py`, `generate_personalized_prompt.py`, `vosk_cobranza.py` y `resolve_transfer_target.py`, prioridad para `VOSK_TRANSFER_ELIGIBLE` y `VOSK_DECISION`, fallback a `PJSIP/1002`, un solo reintento para `DUDA`/`SILENCIO` y compatibilidad por `VOSK_INTENT`.
- [asterisk/extensions_custom.conf.sample](/D:/repos/ai-recepcionista/asterisk/extensions_custom.conf.sample): sample mas cercano al flujo futuro de integracion con VICIdial.

Para el laboratorio local, carga primero `pjsip_lab.conf.sample` y `extensions_lab.conf.sample`. El sample `extensions_custom.conf.sample` queda como referencia para escenarios mas cercanos a produccion o a una integracion posterior con VICIdial.

### 9.1 Flujo del sample

Orden de ejecucion del sample `extensions_lab.conf.sample`:

1. `Answer()` y `Set(TRY=0)`.
2. Variables comentadas de laboratorio para `lead_id`, telefono, cliente, banco y cartera.
3. `AGI(load_lead_context.py)`.
4. `AGI(generate_name_audio.py)`.
5. `AGI(generate_personalized_prompt.py)`.
6. Reproduccion segmentada opcional `custom/hola -> IVR_NAME_AUDIO -> IVR_BANK_GREETING_AUDIO`; si no aplica, `Playback(${IVR_GREETING_AUDIO})` con fallback a `custom/mensaje-cobranza`.
7. `EAGI(vosk_cobranza.py)`.
8. Ruteo priorizando `VOSK_TRANSFER_ELIGIBLE` y `VOSK_DECISION`, con fallback por `VOSK_INTENT`.
9. `AGI(resolve_transfer_target.py)` antes de `Dial(${IVR_TRANSFER_TARGET},20)`.

### 9.2 Como probar con variables hardcodeadas de laboratorio

El sample deja comentadas estas lineas:

```asterisk
; same => n,Set(IVR_LEAD_ID=lab-001)
; same => n,Set(IVR_PHONE_NUMBER=${CALLERID(num)})
; same => n,Set(IVR_CLIENT_NAME=Juan)
; same => n,Set(IVR_BANK_NAME=Banco Popular)
; same => n,Set(IVR_PORTFOLIO_ID=popular_mora_30)
```

Prueba recomendada:

1. Descomenta `IVR_LEAD_ID` y `IVR_PHONE_NUMBER`.
2. Deja activo `AGI(load_lead_context.py)`.
3. Crea una fila matching en `config/lead_context.sample.csv` para que el AGI complete `IVR_CLIENT_NAME`, `IVR_BANK_NAME` e `IVR_PORTFOLIO_ID`.
4. Llama desde `1001` a `9900` y revisa el log de Asterisk para confirmar que el saludo y el ruteo usan esos datos.

Prueba rapida sin CSV:

1. Descomenta tambien `IVR_CLIENT_NAME`, `IVR_BANK_NAME` e `IVR_PORTFOLIO_ID`.
2. Comenta temporalmente `AGI(load_lead_context.py)` en el sample.
3. Recarga el dialplan y llama a `9900`.
4. Esa variante solo sirve para smoke test local; la prueba principal debe dejar `load_lead_context.py` activo.

### 9.3 Como preparar `config/lead_context.sample.csv`

El AGI `load_lead_context.py` espera un CSV con estas columnas:

```text
lead_id,phone_number,client_name,bank_name,portfolio_id,campaign_id,list_id
```

Ejemplo seguro para laboratorio:

```text
lead_id,phone_number,client_name,bank_name,portfolio_id,campaign_id,list_id
lab-001,8095550101,Juan,Banco Popular,popular_mora_30,CAMP_LAB,LIST_LAB
lab-002,8095550102,Ana,Banco BHD,bhd_mora_60,CAMP_LAB,LIST_LAB
```

Notas utiles:

- Si en el dialplan usas `Set(IVR_PHONE_NUMBER=${CALLERID(num)})`, el valor del caller ID debe coincidir con `phone_number`.
- Si prefieres buscar solo por `lead_id`, usa un `IVR_LEAD_ID` unico por prueba y mantelo consistente con el CSV.
- Puedes sobrescribir la ruta del CSV con `IVR_LEAD_CONTEXT_CSV`, pero en el laboratorio basta con editar `config/lead_context.sample.csv`.

### 9.4 Como configurar `routing.yml`

El AGI `resolve_transfer_target.py` usa `config/routing.yml` para decidir el destino final. Ejemplo:

```yaml
default_transfer_target: "PJSIP/1002"
allowed_target_patterns:
  - "^PJSIP/[A-Za-z0-9_-]+$"
  - "^Local/[A-Za-z0-9_-]+@[A-Za-z0-9_-]+$"

portfolios:
  popular_mora_30:
    bank_names:
      - "Banco Popular"
      - "Popular"
    transfer_target: "PJSIP/1002"

  bhd_mora_60:
    bank_names:
      - "Banco BHD"
      - "BHD"
    transfer_target: "PJSIP/1003"
```

Reglas practicas del laboratorio:

- `portfolio_id` tiene prioridad sobre `bank_name`.
- Si no hay match, el AGI usa `default_transfer_target`.
- Si el target no coincide con los patrones permitidos, cae al default seguro.
- Para validar el flujo completo, haz que el `portfolio_id` del CSV coincida con una clave de `portfolios`.

Nota sobre intents:

- `INFO_COBRO` indica interes en conocer el detalle del cobro o de la deuda.
- `PROMESA_PAGO` indica disposicion a pagar o resolver y en laboratorio tambien se transfiere segun la cartera resuelta.
- En el laboratorio, `extensions_lab.conf.sample` transfiere `SI`, `INFO_COBRO` y `PROMESA_PAGO` igual que `SI` hacia `IVR_TRANSFER_TARGET`, con fallback a `1002`.
- El sample prioriza `VOSK_TRANSFER_ELIGIBLE=1` o `VOSK_DECISION=TRANSFER` y conserva fallback por `VOSK_INTENT`.
- Si `IVR_GREETING_AUDIO` queda vacio, el sample cae a `Playback(custom/mensaje-cobranza)`.
- `CALLBACK`, `NUMERO_EQUIVOCADO` y `NO_ES_PERSONA` no transfieren por defecto en el sample; quedan en extensiones documentadas para que luego puedas mapear dispositions reales sin tocar el contrato de `VOSK_INTENT`.
- En produccion puedes rutear `INFO_COBRO` a otro agente, skill o flujo sin cambiar el contrato base de `VOSK_INTENT`.
Nota operativa:

- El saludo personalizado generado desde `config/ivr.yml` ya puede incluir la pregunta de transferencia, por eso el sample no reproduce `custom/pregunta-abogado`.
- Si tu canal, version de Asterisk o softphone no permite barge-in real durante `Playback()`, el caller debe responder justo al terminar el saludo.
- El sample no reproduce un audio adicional tipo "lo comunico" antes del `Dial()` para reducir latencia y evitar sensacion robotica.

Audios sugeridos en `/var/lib/asterisk/sounds/custom/`:

- `mensaje-cobranza.wav`
- `no-entendi.wav`
- `mensaje-final.wav`

Formato recomendado:

- WAV
- mono
- 8000 Hz
- PCM 16-bit

Para generar un set base sin servicios externos, instala `espeak-ng` si aun no lo tienes y ejecuta:

```bash
./scripts/generate_lab_prompts.sh /usr/share/asterisk/sounds/custom
```

Revisa tambien [docs/AUDIO_PROMPTS.md](/D:/repos/ai-recepcionista/docs/AUDIO_PROMPTS.md) para las reglas de wording que ayudan a reducir falsos positivos por eco del propio IVR.

## 10. Zoiper

Configura dos cuentas separadas, una para `1001` y otra para `1002`.

Parametros minimos:

- Host o domain: IP o hostname del servidor Asterisk
- User / extension: `1001` o `1002`
- Auth user: igual a la extension
- Password: `REEMPLAZAR_PASSWORD_1001` o `REEMPLAZAR_PASSWORD_1002`
- Transport: `UDP`
- Puerto SIP: `5060`
- Codecs preferidos: `PCMU` y `PCMA`

Recomendaciones:

- Desactiva video para simplificar la prueba.
- Deja `PCMU/PCMA` arriba en la prioridad de codecs.
- Llama desde `1001` a `9900` y verifica que el saludo use el cliente/banco esperado y que el destino configurado por cartera reciba la transferencia; si no hay match, debe caer en `1002`.

## 11. Troubleshooting

Comandos base:

```bash
asterisk -rvvvvv
pjsip show contacts
pjsip set logger on
tail -f /var/log/asterisk/vosk_cobranza.log
docker logs -f vosk-server
```

Lectura rapida de sintomas SIP:

- `401 Unauthorized`: suele ser normal en el primer `REGISTER`; Asterisk esta pidiendo autenticacion. Si el siguiente intento autentica bien, no es una falla.
- `404 Not Found`: normalmente indica que el endpoint, `auth`, `aor`, contexto o destino marcado no existe como Asterisk espera.
- timeout o ausencia total de respuesta: apunta primero a firewall, IP incorrecta, puerto `5060/UDP` bloqueado, NAT o softphone apuntando al host equivocado.

Chequeos utiles:

- Si `pjsip show contacts` no muestra `1001` o `1002`, el problema esta en registro SIP antes de llegar al IVR.
- Si Zoiper registra pero `9900` devuelve `404`, revisa que el dialplan este cargado y que la extension exista en el contexto correcto.
- Si los prompts se oyen pero no hay clasificacion, revisa `tail -f /var/log/asterisk/vosk_cobranza.log` y `docker logs -f vosk-server`.
- Si `./scripts/check_vosk.sh` responde OK pero no hay reconocimiento, valida el modelo en `./models/model` y el formato de audio del prompt.

## 12. Nota

Este laboratorio sirve para probar el flujo local Ubuntu + Asterisk + Vosk con placeholders y extensiones de prueba. No reemplaza la configuracion productiva, no asume VICIdial instalado y no debe mezclarse con ingroups, credenciales ni telefonos reales.
