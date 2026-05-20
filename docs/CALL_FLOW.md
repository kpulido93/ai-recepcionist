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

## Reintento

- Si la intencion es `DUDA` o `SILENCIO`, el dialplan repite una sola vez.
- Si vuelve a fallar, reproduce mensaje final y cuelga.
- No hay loop infinito: `TRY` arranca en `0`, `MAX_RETRIES` queda en `1` y luego finaliza.

## Modo DTMF

- Si el dialplan ya recogio un digito, lo pasa como `agi_arg_1`.
- El clasificador usa `dtmf_map` antes de intentar STT.
- Si `agi_arg_1` coincide con `dtmf_map`, la llamada no pasa por Vosk.

## Variables de canal utiles

- `VOSK_INTENT`
- `VOSK_TEXT`
- `VOSK_CONFIDENCE`
- `VOSK_SOURCE`

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
