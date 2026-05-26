# Escenarios de Intencion en Cobranza

## Resumen
El clasificador ahora tiene dos capas locales:

- coincidencia exacta por frases en `config/intents.yml`
- coincidencia fuzzy local en `config/semantic_intents.yml`

Antes de esas capas se evalua un blocklist local. Si el transcript cae en `VULGARIDAD` o `AMENAZA_VERBAL`, nunca se transfiere.

## Matriz de decision
La matriz vive en `config/scenarios.yml`.

Transfieren:

- `SI`
- `TRANSFER_REQUEST`
- `INFO_COBRO`
- `INFO_DEUDA`
- `PROMESA_PAGO`
- `QUIERE_ACUERDO`
- `YA_PAGO`

No transfieren:

- `VULGARIDAD`
- `AMENAZA_VERBAL`
- `NO`
- `NO_ES_PERSONA`
- `NUMERO_EQUIVOCADO`
- `TERCERO`
- `CALLBACK`
- `FRAUDE_O_DESCONFIANZA`
- `DISPUTA_DEUDA`
- `NO_PUEDE_PAGAR`

Reintentan:

- `DUDA` si todavia hay reintento disponible
- `SILENCIO` si todavia hay reintento disponible

Finalizan sin transferir:

- `DUDA` cuando el reintento ya fue agotado
- `SILENCIO` cuando el reintento ya fue agotado

## Prioridad
El orden efectivo es:

1. DTMF
2. blocklist local
3. match exacto
4. fuzzy
5. fallback `DUDA` o `SILENCIO`

Bloqueos fuertes:

- `AMENAZA_VERBAL`
- `VULGARIDAD`
- `NUMERO_EQUIVOCADO`
- `NO_ES_PERSONA`
- `TERCERO`
- `NO`

Eso evita que una palabra positiva dentro de una frase negativa termine en transferencia.

## Configuracion local del blocklist
El sample versionado es `config/blocklist.sample.yml`.

Los terminos reales del entorno deben ir en `config/local/blocklist.yml`. Esa ruta esta ignorada por git.

Ejemplo:

```yaml
abusive_language:
  enabled: true
  terms:
    - "token_local_1"
  phrases: []

verbal_threats:
  enabled: true
  terms:
    - "token_local_2"
  phrases: []
```

Los logs solo registran la categoria y un match sanitizado. No se guarda el termino ofensivo completo.

## Como agregar frases nuevas
Para match exacto:

- editar `config/intents.yml`

Para variantes ASR o equivalentes semanticos:

- editar `config/semantic_intents.yml`

Regla practica:

- poner frases canonicas y estables en `intents.yml`
- poner variantes cortas, errores comunes de ASR y formas alternas en `semantic_intents.yml`

## Variables para dialplan
Se mantienen:

- `VOSK_TEXT`
- `VOSK_INTENT`
- `VOSK_CONFIDENCE`
- `VOSK_SOURCE`

Se agregan:

- `VOSK_DECISION`
- `VOSK_TRANSFER_ELIGIBLE`
- `VOSK_BLOCK_REASON`
- `VOSK_FINAL_DISPOSITION`
- `VOSK_MATCHED_VALUE`

Interpretacion recomendada:

- `VOSK_DECISION=TRANSFER`: puede transferirse
- `VOSK_DECISION=NO_TRANSFER`: no transferir
- `VOSK_DECISION=RETRY`: repetir el prompt
- `VOSK_DECISION=HANGUP`: finalizar

- `VOSK_TRANSFER_ELIGIBLE=1`: el caso es transferible
- `VOSK_TRANSFER_ELIGIBLE=0`: no debe transferirse

En una fase posterior el dialplan puede migrar desde `VOSK_INTENT=SI` hacia `VOSK_TRANSFER_ELIGIBLE=1` o `VOSK_DECISION=TRANSFER`.

## Prueba por consola
Se puede validar una frase sin Asterisk con:

```bash
python scripts/test_intent_matrix.py "comunicame"
```

El script imprime:

- transcript original
- transcript normalizado
- intent
- confidence
- source
- matched_value
- decision
- transfer_eligible
- block_reason
- final_disposition
