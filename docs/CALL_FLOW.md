# Flujo de llamada

## Flujo nominal

1. El dialplan entra a `ivr-cobranza-vosk`.
2. Asterisk responde, limpia variables defensivas y reproduce `custom/mensaje-cobranza`.
3. Antes de cada intento reproduce `custom/pregunta-abogado`.
4. El dialplan deja una ventana corta de DTMF con `Read(OPCION,,1,,1,1)`.
5. Si no hay DTMF util, el script EAGI escucha audio durante `listen_seconds`.
6. El cliente envia PCM al servidor Vosk por WebSocket.
7. Vosk devuelve texto.
8. El clasificador devuelve una de las intenciones base y, si el YAML lo define, tambien `INFO_COBRO`:
   - `SI`
   - `NO`
   - `DUDA`
   - `SILENCIO`
   - `INFO_COBRO`
9. El script fija `VOSK_INTENT`, `VOSK_TEXT`, `VOSK_CONFIDENCE` y `VOSK_SOURCE`.
10. El dialplan normaliza defaults defensivos si alguna variable vuelve vacia.
11. El dialplan decide como rutear `SI`, `NO` y opcionalmente `INFO_COBRO`, y valida `VOSK_CONFIDENCE` segun la politica del flujo.
12. Si la confianza supera el umbral, deriva al contexto puente `vicidial-cobranza-transfer`.
13. El contexto puente valida placeholders y destino con `DIALPLAN_EXISTS()` antes de anunciar transferencia.

## Flujo Segmentado Optima

El laboratorio ahora puede exponer un flujo segmentado separado para Juridica Optima.

Resumen operativo:

1. `AGI(load_lead_context.py)` carga `IVR_CLIENT_NAME` y `IVR_BANK_NAME`.
2. `AGI(generate_optima_audio.py)` resuelve:
   - `IVR_OPTIMA_SALUDO_NOMBRE_AUDIO`
   - `IVR_OPTIMA_DEUDA_BANCO_AUDIO`
3. El dialplan reproduce los segmentos uno por uno.
4. Entre segmentos usa `IVR_LISTEN_PROFILE=objection_probe`.
5. Si el resultado es `SILENCIO`, continua al siguiente segmento.
6. Si el cliente pide transferencia o el motor devuelve `VOSK_TRANSFER_ELIGIBLE=1` o `VOSK_DECISION=TRANSFER`, transfiere.
7. Si aparece una objecion no transferible, reproduce una sola vez `custom/optima-objecion-unica`.
8. Despues de esa respuesta unica se hace una escucha final con `IVR_LISTEN_PROFILE=first_attempt`.

Los dos audios dinamicos del flujo no se dividen:

- `IVR_OPTIMA_SALUDO_NOMBRE_AUDIO` reproduce `Saludos {nombre}.`
- `IVR_OPTIMA_DEUDA_BANCO_AUDIO` reproduce `Por la deuda que mantiene en {banco}.`

No se debe reemplazar ese esquema con `IVR_NAME_AUDIO`, `IVR_BANK_GREETING_AUDIO` ni `gestion-<bank_slug>`.

## Reintento

- Si la intencion es `DUDA` o `SILENCIO`, el dialplan repite una sola vez.
- Si vuelve a fallar, reproduce mensaje final y cuelga.
- No hay loop infinito: `TRY` arranca en `0`, `MAX_RETRIES` queda en `1` y luego finaliza.

## Perfiles De Escucha

`app.py` soporta estos perfiles:

- `first_attempt`
- `retry_attempt`
- `objection_probe`

Si `IVR_LISTEN_PROFILE` no existe, el comportamiento viejo sigue igual y se decide por `TRY` o
`VOSK_TRY`. Si el valor llega invalido, hace fallback seguro.

`objection_probe` esta pensado para ventanas cortas entre segmentos:

- `initial_timeout_seconds: 1.8`
- `max_listen_seconds: 2`
- `silence_after_speech_ms: 550`
- `min_speech_ms: 250`
- `early_detection_min_audio_ms: 250`

## Modo DTMF

- Si el dialplan ya recogio un digito, lo pasa como `agi_arg_1`.
- El clasificador usa `dtmf_map` antes de intentar STT.
- Si `agi_arg_1` coincide con `dtmf_map`, la llamada no pasa por Vosk.

## Variables de canal utiles

- `VOSK_INTENT`
- `VOSK_TEXT`
- `VOSK_CONFIDENCE`
- `VOSK_SOURCE`
- `VOSK_DECISION`
- `VOSK_TRANSFER_ELIGIBLE`
- `IVR_OPTIMA_SALUDO_NOMBRE_AUDIO`
- `IVR_OPTIMA_DEUDA_BANCO_AUDIO`

## Hard Stops Y Objecion Unica

En el flujo Optima hay intents que no deben recibir respuesta de objecion y deben ir a ruta segura:

- `NUMERO_EQUIVOCADO`
- `NO_ES_PERSONA`
- `TERCERO`
- `AMENAZA_VERBAL`
- `VULGARIDAD`

La respuesta `custom/optima-objecion-unica` solo debe sonar una vez por llamada. Casos tipicos:

- `NO`
- `CALLBACK`
- `DUDA`
- `FRAUDE_O_DESCONFIANZA`
- `DISPUTA_DEUDA`
- `NO_PUEDE_PAGAR`
- `YA_PAGO`
- otras respuestas no transferibles

Si `OBJECTION_PLAYED=1`, ya no se vuelve a reproducir ese prompt.

## Transferencia segura

- No se recomienda `Goto(default,INGROUP_ABOGADOS,1)` como patron principal.
- La recomendacion del repo es usar `[vicidial-cobranza-transfer]`.
- El puente permite:
  - validar que exista ruta configurada
  - preservar `UNIQUEID`, `CALLERID` y variables VICIdial relevantes
  - usar `Dial(Local/...)` con fallback si la entrega falla

## Notas

- El codigo no transfiere por si mismo; solo clasifica y devuelve estado.
- La transferencia real queda en el dialplan o en la integracion VICIdial.
- El sample de laboratorio nuevo vive en `9913` para no romper el flujo previo de `9900` ni el flujo cliente aislado de `9912`.
