# AGENTS.md

## Fuente de verdad
- La fuente de verdad es este repo en la rama `dev`.
- Si hay diferencias con notas externas o instrucciones viejas, prevalece lo versionado aqui.

## Proyecto
- Clasificador de intencion por voz para IVR de cobranza sobre Asterisk EAGI con Vosk via WebSocket.
- El laboratorio actual usa Asterisk local, Vosk Server en Docker, softphones SIP 1001/1002 y extension 9900.
- La prioridad es mantener compatibilidad con el laboratorio local sin cerrar el camino a una integracion futura con VICIdial.
- El objetivo actual es un Nivel 1 robusto: Asterisk/VICIdial + EAGI + Vosk local + clasificacion de intencion, sin agente LLM, sin APIs externas y sin pagos mensuales.
- La rama objetivo de trabajo es `dev`.

## Stack
- Python 3.10 o superior.
- Asterisk EAGI.
- Vosk Server via WebSocket.
- Configuracion externa en YAML.
- `pytest` para pruebas.

## Alcance V1
- Un script EAGI principal para clasificar respuestas de voz o DTMF.
- STT local por Vosk Server via WebSocket.
- Configuracion externa en YAML.
- Pruebas locales con archivos WAV antes de conectarlo a Asterisk.
- Logs con enmascarado de numeros telefonicos.

## Restricciones de plataforma
- Mantener todo local/offline para este Nivel 1.
- No usar OpenAI API, servicios cloud, APIs pagas ni LLM externo.

## Reglas funcionales
- Clasificar la respuesta como `SI`, `NO`, `DUDA` o `SILENCIO`.
- Devolver `VOSK_INTENT` como variable de canal.
- No hardcodear destinos reales de Asterisk o VICIdial.
- Permitir un solo reintento desde el dialplan.

## Reglas de implementacion
- No hardcodear secretos, credenciales reales, telefonos reales, ingroups reales, IPs privadas obligatorias ni rutas absolutas innecesarias.
- No tocar archivos de configuracion de produccion ni configuraciones reales del sistema Asterisk.
- Para cambios Asterisk, actualizar samples y documentacion; no editar configuraciones operativas del host.
- Si se agregan rutas o valores de laboratorio, deben ser configurables o quedar en documentacion/sample.
- Mantener compatibilidad con el laboratorio local: 1001 cliente, 1002 agente, 9900 IVR.
- Mantener el codigo simple, mantenible y documentado.
- Mantener diffs pequenos y por hito.

## Logging y datos sensibles
- Si `mask_phone_numbers=true`, no exponer telefonos completos en logs, pruebas ni ejemplos.
- Mantener los logs seguros y evitar fugas de datos sensibles en mensajes operativos o de debug.

## Prompts e intents
- Usar espanol de Republica Dominicana orientado a cobranza.
- Preferir frases afirmativas, negativas y ambiguas realistas para llamadas de cobranza.
- Evitar ejemplos artificiales que no suenen naturales para un caller real.

## Calidad
Antes de cerrar cambios Python:
- `ruff check .`
- `ruff format --check .`
- `pytest -q`
- `mypy` si esta configurado

- Si un comando no existe o falla por el entorno, reportarlo claramente en la entrega final.

## Pruebas
- Todo cambio debe incluir pruebas nuevas o actualizadas.
- Si no aplica agregar pruebas, dejar una justificacion explicita en la entrega final.

## Criterio de terminado
- Las pruebas relevantes pasan.
- La documentacion queda actualizada cuando el cambio lo requiere.
- No se introducen secretos ni configuraciones reales sensibles.

## Restricciones
- Sin credenciales reales.
- Sin logica hardcodeada para clientes, campañas o numeros reales.
- No modificar logica funcional salvo que la tarea lo pida de forma explicita.
