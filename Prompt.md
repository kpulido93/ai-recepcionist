# Prompt.md

## Goal
Construir un microservicio local de recepcionista digital para llamadas de cobranza.

## Non-goals
- No negociación automática
- No validación de identidad
- No WhatsApp/SMS en esta V1
- No servicios externos de voz

## Hard constraints
- Python 3.11
- Compatibilidad con Issabel/Asterisk 16/18
- ARI + Stasis + externalMedia RTP
- AMI Redirect para transferencia
- FastAPI solo para admin API
- STT/TTS locales
- Pruebas automatizadas mínimas

## Deliverables
- Worker ARI funcional
- Admin API
- Pipeline RTP->PCM->STT
- Pipeline texto->TTS->audio de retorno
- FSM de diálogo
- Integración con AMI/VICIdial
- Dockerfile + docker-compose + systemd unit
- Tests unitarios e integración mínima

## Done when
- Una llamada entra a Stasis
- El bot reproduce saludo
- El bot escucha y clasifica
- Si hay sí explícito, transfiere
- Si no hay agente, callback
- Si no, cuelga con disposición
- Los checks de lint, tipos y tests pasan