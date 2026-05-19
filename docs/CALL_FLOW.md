# Flujo de llamada

## Flujo nominal

1. El dialplan entra a `custom-vosk-cobranza`.
2. Asterisk reproduce `custom/cobranza_intro`.
3. El script EAGI escucha audio durante `listen_seconds`.
4. El cliente envia PCM al servidor Vosk por WebSocket.
5. Vosk devuelve texto.
6. El clasificador devuelve una de cuatro intenciones:
   - `SI`
   - `NO`
   - `DUDA`
   - `SILENCIO`
7. El script fija `VOSK_INTENT`.
8. El dialplan decide la accion siguiente.

## Reintento

- Si la intencion es `DUDA` o `SILENCIO`, el dialplan repite una sola vez.
- Si vuelve a fallar, reproduce mensaje final y cuelga.

## Modo DTMF

- Si el dialplan ya recogio un digito, lo pasa como `agi_arg_1`.
- El clasificador usa `dtmf_map` antes de intentar STT.

## Variables de canal utiles

- `VOSK_INTENT`
- `VOSK_TRANSCRIPT`
- `VOSK_SOURCE`

## Notas

- El codigo no transfiere por si mismo; solo clasifica y devuelve estado.
- La transferencia real queda en el dialplan o en la integracion VICIdial.
