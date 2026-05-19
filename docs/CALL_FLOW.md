# Flujo de llamada

## Flujo nominal

1. El dialplan entra a `ivr-cobranza-vosk`.
2. Asterisk reproduce `custom/mensaje-cobranza`.
3. El script EAGI escucha audio durante `listen_seconds`.
4. El cliente envia PCM al servidor Vosk por WebSocket.
5. Vosk devuelve texto.
6. El clasificador devuelve una de cuatro intenciones:
   - `SI`
   - `NO`
   - `DUDA`
   - `SILENCIO`
7. El script fija `VOSK_INTENT`, `VOSK_TEXT`, `VOSK_CONFIDENCE` y `VOSK_SOURCE`.
8. Si la intencion es `SI` por voz, el dialplan valida `VOSK_CONFIDENCE`.
9. Si la confianza supera el umbral, deriva al contexto puente `vicidial-cobranza-transfer`.
10. El contexto puente preserva variables relevantes y hace la entrega final a la ruta legal.

## Reintento

- Si la intencion es `DUDA` o `SILENCIO`, el dialplan repite una sola vez.
- Si vuelve a fallar, reproduce mensaje final y cuelga.

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
