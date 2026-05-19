# VICIDIAL / Asterisk setup

## Resumen

La integracion propuesta deja la decision en el dialplan:

- `SI`: transferir a la ruta de abogados definida fuera del codigo.
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
- nombres reales de prompts

## Paso 3: definir la ruta hacia abogados

No esta hardcodeada en Python. Debe resolverse en Asterisk o VICIdial con variables, contexto o una extension puente.

Opciones comunes:

1. `Goto()` a un contexto interno que entregue la llamada al flujo legal.
2. `Dial(Local/...)` hacia una ruta VICIdial.
3. Contexto dedicado que resuelva el ingroup o cola final.

## Paso 4: mapear disposiciones

`config/ivr.yml` ya deja placeholders para:

- `final_disposition_yes`
- `final_disposition_no`
- `final_disposition_unknown`

Puedes usarlos desde AGI futuro o desde el propio dialplan segun tu operacion.

## Paso 5: recargar Asterisk

```bash
asterisk -rx "dialplan reload"
```

## Recomendacion para DTMF

La V1 soporta dos modos:

1. Pasar el digito ya recogido a `EAGI(vosk_cobranza.py,${COBRANZA_DTMF})`.
2. Dejar que el script haga un `WAIT FOR DIGIT` corto si no detecta voz.

El modo 1 es mas estable en VICIdial porque separa la logica de playback y la de captura.
