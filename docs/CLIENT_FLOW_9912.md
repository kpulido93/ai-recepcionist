# CLIENT FLOW 9912

## Objetivo

Agregar un flujo de laboratorio nuevo en `9912` sin tocar `9910` ni `9911`.
El contexto recomendado es `vicidial-vosk-cobranza-ivr-client-flow`.

Datos ficticios de laboratorio:

- `deudor=Kevin`
- `banco=Banco de Prueba`
- `genero=male`
- `destino transferencia=PJSIP/1002`

## Guion

1. `Saludos. ¿Cómo está, señor Kevin?`
2. Escucha `greeting_check`
3. `Le habla Carlo Montero, de la oficina de abogados Jurídica Óptima.`
4. `Le llamo con relación a la deuda que usted mantiene con el Banco de Prueba.`
5. `Queríamos saber, por favor, si usted estaría interesado en conversar sobre una posible alternativa de acuerdo.`
6. `Su caso se encuentra en una etapa avanzada, y por eso nos gustaría orientarle a tiempo.`
7. `Ya anteriormente hemos tenido comunicación con usted.`
8. `Si le parece bien, puedo comunicarle ahora con el abogado encargado, para que le explique las opciones disponibles.`
9. Escucha `agreement_offer`
10. `También, si prefiere, puedo llamarle mañana.`
11. Escucha `callback_offer`
12. `O, con mucho gusto, puedo enviarle la información vía WhatsApp.`
13. Escucha `whatsapp_offer`
14. Si corresponde transferir:
    - `Muy bien. Permítame un momento, por favor.`
    - `Ya le transfiero con la persona encargada.`
    - `Dial(PJSIP/1002)`

Respuestas adicionales del flujo:

- Si el deudor interrumpe en una ventana de escucha: `Por favor, permítame terminar.`
- Si pregunta por la deuda: `Le estamos llamando por la deuda que tiene con Banco de Prueba, que usted ya conoce.`

## Etapas

- `greeting_check`: validación inicial y filtro de contacto correcto.
- `agreement_offer`: oferta principal de conversación / transferencia.
- `callback_offer`: ofrecimiento de llamada mañana.
- `whatsapp_offer`: ofrecimiento de envío por WhatsApp.

Antes de cada `EAGI(vosk_cobranza.py)` se setea `VOSK_FLOW_STAGE=<stage>` y se deja `Wait(0.3)` para no cortar la primera palabra del deudor.

## Decisiones

### greeting_check

- Finaliza: `NO`, `NO_ES_PERSONA`, `NUMERO_EQUIVOCADO`, `TERCERO`, `VULGARIDAD`, `AMENAZA_VERBAL`.
- Salta a `callback_offer`: `CALLBACK`, `CALLBACK_MANANA`, `ESTA_OCUPADO`.
- Responde y continúa el guion: `INTERRUPCION`, `PREGUNTA_DEUDA`.
- Continúa el guion: `DUDA`, `SILENCIO`, `CONFIRMA_PERSONA`, `SI`.
- No transfiere en esta etapa.

### agreement_offer

- Transfiere: `SI`, `TRANSFER_REQUEST`, `PROMESA_PAGO`, `QUIERE_ACUERDO`, `ACEPTA_ACUERDO`, `INFO_DEUDA`, `INFO_COBRO`, `WHATSAPP_INFO`.
- `WHATSAPP_INFO` deja `final_disposition=VOZ_WHATSAPP_TRANSFER`.
- Responde y repite la oferta: `INTERRUPCION`, `PREGUNTA_DEUDA`.
- Salta a `callback_offer`: `CALLBACK`, `CALLBACK_MANANA`, `ESTA_OCUPADO`, `DUDA`, `SILENCIO`.
- Finaliza sin transferir: `NO`, `RECHAZA_ACUERDO`, `VULGARIDAD`, `AMENAZA_VERBAL`, `NO_ES_PERSONA`, `NUMERO_EQUIVOCADO`, `TERCERO`.

### callback_offer

- Finaliza sin transferir con disposición `VOZ_CALLBACK_MANANA`: `SI`, `CALLBACK`, `CALLBACK_MANANA`, `ESTA_OCUPADO`.
- Transfiere: `WHATSAPP_INFO`.
- `WHATSAPP_INFO` deja `final_disposition=VOZ_WHATSAPP_TRANSFER`.
- Responde y repite la oferta: `INTERRUPCION`, `PREGUNTA_DEUDA`.
- Continúa a `whatsapp_offer`: `NO`, `DUDA`, `SILENCIO`, `CONFIRMA_PERSONA`, `RECHAZA_ACUERDO`.
- Finaliza sin transferir: `VULGARIDAD`, `AMENAZA_VERBAL`, `NO_ES_PERSONA`, `NUMERO_EQUIVOCADO`, `TERCERO`.

### whatsapp_offer

- Transfiere: `TRANSFER_REQUEST`, `WHATSAPP_INFO`.
- `WHATSAPP_INFO` deja `final_disposition=VOZ_WHATSAPP_TRANSFER`.
- Responde y repite la oferta: `INTERRUPCION`, `PREGUNTA_DEUDA`.
- Finaliza educadamente sin transferir: `NO`, `DUDA`, `SILENCIO`, `CONFIRMA_PERSONA`, `RECHAZA_ACUERDO`.
- No se envía WhatsApp real. La llamada se transfiere al abogado para que gestione esa opción.

## Intents reforzados

- `CALLBACK_MANANA`
- `WHATSAPP_INFO`
- `INTERRUPCION`
- `PREGUNTA_DEUDA`
- `CONFIRMA_PERSONA`
- `ESTA_OCUPADO`
- `ACEPTA_ACUERDO`
- `RECHAZA_ACUERDO`

## Audios necesarios

Dinámicos por ElevenLabs y caché:

- `custom/generated/client-flow-9912/greeting`
- `custom/generated/client-flow-9912/bank`
- `custom/generated/client-flow-9912/deuda-conocida`

Plantillas activas del saludo dinámico:

- `male`: `Saludos. ¿Cómo está, señor {name}?`
- `female`: `Saludos. ¿Cómo está, señora {name}?`
- `unknown`: `Saludos. ¿Cómo está, {name}?`

La generación agrega `800 ms` de silencio al final y replica el WAV a `/usr/share/asterisk/sounds/custom/generated/client-flow-9912/`.

Estáticos de laboratorio:

- Ver [client_flow_9912_static_prompts.placeholder.md](/home/kevin/code/automatizaciones/ai-recepcionist/asterisk/client_flow_9912_static_prompts.placeholder.md)
- `custom/cliente-9912/permita-terminar` es opcional: si falta, el flujo registra `TRYSTATUS` y sigue.

El flujo usa `Playback(...)` para los WAV existentes de laboratorio y una pausa corta antes de cada escucha real.

## Cómo probar

1. Generar o validar los tres prompts dinámicos:

```bash
.venv/bin/python scripts/test_client_flow_prompts.py --debtor Kevin --bank "Banco de Prueba" --gender male
```

2. Revisar el sample del dialplan:

```bash
rg -n "9912|vicidial-vosk-cobranza-ivr-client-flow|VOSK_FLOW_STAGE" asterisk/extensions_lab.conf.sample
```

3. Validar intents rápidos:

```bash
.venv/bin/python scripts/test_intent_matrix.py "comunicame"
.venv/bin/python scripts/test_intent_matrix.py --flow-stage greeting_check "no"
.venv/bin/python scripts/test_intent_matrix.py --flow-stage greeting_check "que deuda"
.venv/bin/python scripts/test_intent_matrix.py --flow-stage agreement_offer "espere"
.venv/bin/python scripts/test_intent_matrix.py "llameme mañana"
.venv/bin/python scripts/test_intent_matrix.py --flow-stage agreement_offer "comunicame"
.venv/bin/python scripts/test_intent_matrix.py --flow-stage agreement_offer "envíeme por WhatsApp"
.venv/bin/python scripts/test_intent_matrix.py --flow-stage whatsapp_offer "envíeme por WhatsApp"
```

4. En Asterisk:

```bash
asterisk -rx "dialplan reload"
asterisk -rx "dialplan show 9912@lab-phones"
asterisk -rx "dialplan show vicidial-vosk-cobranza-ivr-client-flow"
```

## Comandos de monitoreo

```bash
asterisk -rvvvvv
agi set debug on
tail -f /var/log/asterisk/vosk_cobranza.log
tail -f /var/log/asterisk/vosk_cobranza_events.jsonl
```
