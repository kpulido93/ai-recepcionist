# Nivel 1 IVR Robusto

## Objetivo

El objetivo de este Nivel 1 es clasificar la intención de una llamada de cobranza y tomar una decisión de ruteo en el dialplan sin usar agente LLM.

Este diseño busca:

- operar `100% local`
- evitar costes mensuales por APIs externas
- mantener un flujo simple, auditable y robusto
- servir tanto para laboratorio local como para una integración posterior con VICIdial

## Arquitectura

Arquitectura base:

```text
Asterisk/VICIdial -> EAGI -> Vosk local -> classifier -> dialplan
```

Flujo resumido:

1. Asterisk o VICIdial reproduce el prompt del IVR.
2. `EAGI(vosk_cobranza.py)` captura audio de la llamada.
3. El audio se envía a Vosk local por WebSocket.
4. El clasificador asigna un intent usando reglas locales y configuración YAML.
5. El dialplan decide si transferir, reintentar, finalizar o dejar una disposición documentada.

## Intents

El Nivel 1 robusto trabaja con estos intents:

- `SI`
- `INFO_COBRO`
- `PROMESA_PAGO`
- `NO`
- `CALLBACK`
- `NUMERO_EQUIVOCADO`
- `NO_ES_PERSONA`
- `DUDA`
- `SILENCIO`

## Ruteo Recomendado

- `SI`, `INFO_COBRO` y `PROMESA_PAGO` -> transferir
- `NO` -> finalizar o marcar rechazo
- `CALLBACK` -> disposición callback
- `NUMERO_EQUIVOCADO` -> disposición número equivocado
- `NO_ES_PERSONA` -> disposición tercero o no contacto
- `DUDA` y `SILENCIO` -> reintento controlado

En laboratorio, el sample voice-first actual transfiere a `1002` y limita el reintento a una sola vez.

## Recomendaciones De Audio

- Usa voz humana dominicana para producción.
- Mantén prompts cortos.
- No uses pitido.
- Si tu canal no tiene barge-in real, la persona no debe hablar encima del prompt.
- Cierra con una frase natural de toma de turno, por ejemplo `Le escucho.`
- Usa WAV `8 kHz`, `mono`, `PCM 16-bit`.

## Robustez

La robustez actual del Nivel 1 se apoya en varias capas:

- `early detection`: permite cortar temprano cuando Vosk detecta una intención clara en partials
- `VAD`: corta la captura tras voz seguida de silencio para reducir ruido y latencia
- `prioridad de clasificación`: evita que frases negativas o específicas queden tapadas por coincidencias más débiles
- `logs`: exponen `intent`, `confidence`, `matched_phrase`, `stop_reason` y métricas útiles sin mostrar teléfonos completos por defecto
- `evaluación automática`: el repo incluye un set local de frases RD de cobranza para medir accuracy del clasificador

## No Objetivos

Este Nivel 1 no busca:

- usar LLM
- usar servicios cloud
- sostener conversación abierta
- resolver negociación compleja o multi-turn
- reemplazar todavía una integración completa con VICIdial

## Roadmap Futuro

- prueba A/B con `faster-whisper` local opcional
- barge-in real con `ARI ExternalMedia`
- integración VICIdial real con dispositions y ruteo operativo

## Alcance Actual

Este diseño está pensado para resolver primero el tramo más importante:

- detección de intención de cobranza
- transferencia simple y controlada
- operación local y barata
- observabilidad suficiente para laboratorio y endurecimiento progresivo

Eso permite validar el flujo antes de abrir la puerta a una capa conversacional o a una automatización más compleja.
