# VICIDIAL / Asterisk setup

## Resumen

La integracion propuesta deja la decision en el dialplan:

- `SI`: transferir a la ruta de abogados definida fuera del codigo y validada por confianza.
- `NO`: reproducir mensaje final y colgar.
- `DUDA` o `SILENCIO`: repetir una sola vez y luego finalizar.

## Paso 1: copiar el AGI

El script debe quedar accesible como:

```text
/var/lib/asterisk/agi-bin/vosk_cobranza.py
```

## Paso 2: incluir el dialplan sample

Usa [extensions_custom.conf.sample](/D:/repos/ai-recepcionista/asterisk/extensions_custom.conf.sample) como base y adapta:

- `LAWYER_TRANSFER_CONTEXT`
- `LAWYER_TRANSFER_EXTEN`
- `LAWYER_TRANSFER_PRIORITY`
- `MIN_CONFIDENCE`
- nombres reales de prompts

## Paso 3: definir la ruta hacia abogados

No esta hardcodeada en Python. Debe resolverse en Asterisk o VICIdial con variables, contexto o una extension puente.
La recomendacion principal del repo es usar el contexto `[vicidial-cobranza-transfer]` como puente seguro.
El patron historico `Goto(default,INGROUP_ABOGADOS,1)` debe tratarse solo como placeholder
de laboratorio y no como recomendacion de produccion.

Opciones comunes:

1. Contexto puente que preserve variables y enrute con `Dial(Local/...)`.
2. `Goto()` a un contexto interno solo dentro del canal Local del puente.
3. Contexto dedicado que resuelva el ingroup o cola final.

El contexto puente del sample cumple tres funciones:

1. Validar que `LAWYER_TRANSFER_CONTEXT`, `LAWYER_TRANSFER_EXTEN` y `LAWYER_TRANSFER_PRIORITY`
   hayan sido reemplazados.
2. Verificar con `DIALPLAN_EXISTS()` que el destino exista antes de anunciar transferencia.
3. Preservar variables de VICIdial y del resultado `VOSK_*` al saltar a un canal `Local/`.

## Paso 4: preservar variables de VICIdial

El contexto puente usa variables heredables con prefijo `__` para que no se pierdan al saltar a un canal `Local/`.

Variables recomendadas:

- `__VICI_ORIG_UNIQUEID=${UNIQUEID}`
- `__VICI_ORIG_CALLERID=${CALLERID(all)}`
- `__VICI_ORIG_CALLERID_NUM=${CALLERID(num)}`
- `__VICI_CAMPAIGN_ID=${CAMPAIGN_ID}`
- `__VICI_LEAD_ID=${LEAD_ID}`
- `__VICI_LIST_ID=${LIST_ID}`
- `__VOSK_INTENT=${VOSK_INTENT}`
- `__VOSK_CONFIDENCE=${VOSK_CONFIDENCE}`

Si tu implementacion VICIdial usa mas variables, preservalas del mismo modo antes del `Dial(Local/...)`.

## Paso 5: umbral de confianza

Usa `MIN_CONFIDENCE` en el dialplan para evitar transferencias por voz con baja confianza.

Recomendacion inicial:

- `0.70` como punto de partida conservador
- subirlo si hay mucho ruido o respuestas cortas
- bajarlo solo si validas mejora real en contacto util

DTMF puede seguir transfiriendo aunque no exista STT, porque la fuente queda marcada como `dtmf`.

## Paso 6: mapear disposiciones

`config/ivr.yml` ya deja placeholders para:

- `final_disposition_yes`
- `final_disposition_no`
- `final_disposition_unknown`

Puedes usarlos desde AGI futuro o desde el propio dialplan segun tu operacion.

## Paso 7: recargar Asterisk

```bash
asterisk -rx "dialplan reload"
```

## Recomendacion para DTMF

La V1 soporta dos modos:

1. Pasar el digito ya recogido a `EAGI(vosk_cobranza.py,${COBRANZA_DTMF})`.
2. Dejar que el script haga un `WAIT FOR DIGIT` corto si no detecta voz.

El modo 1 es mas estable en VICIdial porque separa la logica de playback y la de captura.
En el sample actual se usa `Read(OPCION,,1,,1,1)` antes del EAGI para dejar una ventana
corta de DTMF. Si buscas un flujo voice-first puro, reduce ese timeout o elimina `Read()`
y deja que toda la decision la tome `vosk_cobranza.py`.
