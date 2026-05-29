# Audio Prompts De Nivel 1

Esta guia define el criterio de audio para el IVR Nivel 1 del laboratorio local y deja claro que en produccion no debe usarse TTS sintetico basico como sustituto de una voz humana.

## Produccion

- Para produccion usa voz humana dominicana grabada.
- No uses `espeak-ng` como audio final de produccion.
- Mantén el tono natural, breve y directo.
- Evita prompts largos porque aumentan latencia, fatiga y riesgo de eco.
- Si usas nombre del cliente, idealmente deja solo el nombre como segmento dinámico.

## Flujo Segmentado Optima

Para el flujo nuevo de Juridica Optima hay dos audios dinamicos que no deben dividirse:

- `custom/generated/optima/optima-01-saludo-nombre-<cache_key>` con el texto completo `Saludos {name}.`
- `custom/generated/optima/optima-04-deuda-banco-<cache_key>` con el texto completo `Por la deuda que mantiene en {bank}.`

No reemplaces este flujo por combinaciones como:

- `custom/optima-01-saludo` + `IVR_NAME_AUDIO`
- `custom/optima-04-deuda-prefijo` + `IVR_BANK_GREETING_AUDIO`
- `custom/gestion-<bank_slug>`

La secuencia segmentada recomendada queda asi:

1. `optima-01-saludo-nombre` dinamico cacheado
2. `optima-02-identificacion`
3. `optima-03-acuerdo`
4. `optima-04-deuda-banco` dinamico cacheado
5. `optima-05-etapa`
6. `optima-06-transferencia`
7. `optima-07-callback`
8. `optima-objecion-unica` solo si aparece una objecion valida

## Reglas De Wording

- Evita decir frases exactas de intents fuertes si esas frases activan acciones.
- No uses prompts como `diga si`, `diga no`, `diga transfierame` o variantes que puedan coincidir con el clasificador.
- Prefiere cierres naturales de toma de turno como `Le escucho.`
- No uses pitidos.
- Si el entorno de pruebas tiene retorno de audio, usa auriculares para reducir eco y falsos positivos.

## Formato De Audio

Los audios del laboratorio y de produccion deben exportarse en:

- `8000 Hz`
- `mono`
- `PCM 16-bit`

Para conversion local el repo normaliza con `ffmpeg`:

```bash
ffmpeg -y -i input -ar 8000 -ac 1 -c:a pcm_s16le output.wav
```

## Prompts Recomendados

- `mensaje-cobranza`: `Hola, le llamamos por una gestión pendiente.`
- `pregunta-abogado`: `¿Lo transfiero ahora? Le escucho.`
- `no-entendi`: `Disculpe, no le escuché bien.`
- `mensaje-final`: `Gracias. Hasta luego.`

## Saludo Con Nombre En Cache

El repo puede usar un modo opcional donde el IVR reproduce:

- `custom/hola`
- audio cacheado del nombre
- `custom/gestion-<banco>`

Ese diseño mantiene fijo el cuerpo principal del saludo y solo deja variable el nombre.

## Cache De Optima

El flujo Optima usa dos variables nuevas de AGI:

- `IVR_OPTIMA_SALUDO_NOMBRE_AUDIO`
- `IVR_OPTIMA_DEUDA_BANCO_AUDIO`

Esas variables apuntan a playback paths reproducibles por Asterisk, por ejemplo:

- `custom/generated/optima/optima-01-saludo-nombre-<cache_key>`
- `custom/generated/optima/optima-04-deuda-banco-<cache_key>`

Rutas esperadas de cache:

- runtime principal: `/var/lib/asterisk/sounds/custom/generated/optima`
- espejo opcional: `/usr/share/asterisk/sounds/custom/generated/optima`
- laboratorio offline: `artifacts/lab-prompts/generated/optima`

El `cache_key` debe ser deterministico y no debe exponer PII. El repo lo deriva del tipo de prompt,
el valor normalizado, la version de plantilla y la configuracion de voz/modelo aplicable.

## Fallbacks De Optima

Si falta el nombre, el AGI debe usar:

- `custom/optima-01-saludo-generico`

Texto:

- `Saludos.`

Si falta el banco o falla la generacion dinamica, el AGI debe usar:

- `custom/optima-04-deuda-generica`

Texto:

- `Por la deuda que mantiene con la entidad correspondiente.`

Si ElevenLabs falla en runtime, la llamada no debe romperse:

- usa el fallback estatico
- registra warning operativo sin exponer nombre completo, banco completo ni API key

## ElevenLabs Como Complemento

ElevenLabs se usa como complemento para generar activos de audio y audios personalizados cacheados:

- La credencial se toma de `ELEVENLABS_API_KEY`.
- El flujo de clasificacion de intencion no debe depender de ElevenLabs para operar.
- Si falta la API key o la llamada al proveedor falla, el IVR debe seguir con el saludo de fallback.
- Para el flujo Optima puedes definir `optima_audio.env_file` en `config/ivr.yml` si el proceso
  AGI no hereda el entorno del usuario que administra Asterisk.

No conviertas ElevenLabs en dependencia funcional del IVR. El camino principal debe seguir operando
con audio local y fallback seguro.

## Env File Protegido Fuera Del Repo

En produccion la key debe vivir fuera del repositorio, por ejemplo en:

- `/etc/asterisk/elevenlabs.env`

Permisos recomendados:

```bash
sudo chown root:root /etc/asterisk/elevenlabs.env
sudo chmod 600 /etc/asterisk/elevenlabs.env
```

Formato esperado:

```text
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...
```

Tambien se aceptan lineas con `export`, por ejemplo:

```text
export ELEVENLABS_API_KEY=...
export ELEVENLABS_VOICE_ID=...
```

El parser del repo:

- no ejecuta el archivo como shell
- no hace `source`
- no evalua command substitution
- solo parsea `KEY=VALUE` de forma segura

## Seguridad Del Nombre

- Sanitiza el nombre antes de generar audio o construir rutas de cache.
- Limita la longitud del nombre para evitar abuso o prompts anómalos.
- No loguees la API key.
- No imprimas ni persistas `ELEVENLABS_API_KEY`.
- Evalúa si es apropiado decir el nombre antes de validar identidad.

## Cache Y Rotacion

Los audios de nombre pueden guardarse en:

- `/var/lib/asterisk/sounds/custom/generated/names`
- espejos opcionales como `/usr/share/asterisk/sounds/custom/generated/names`

Buenas prácticas:

- rota o borra entradas viejas del cache en ventanas de mantenimiento
- cambia `name_audio.version` cuando quieras invalidar audios previos
- evita dejar crecer el cache sin control en ambientes de prueba prolongados

Para el flujo Optima aplica la misma idea usando `optima_audio.version`.

## Script Local

El repo incluye [scripts/generate_lab_prompts.sh](/D:/repos/ai-recepcionista/scripts/generate_lab_prompts.sh) para generar WAVs de laboratorio sin servicios cloud ni acceso a internet.

Ese script:

- usa `espeak-ng` y `ffmpeg` instalados localmente
- genera WAV `8 kHz`, `mono`, `PCM 16-bit`
- sirve solo para laboratorio y validacion local
- no debe considerarse reemplazo de una voz humana dominicana para produccion

Para los prompts segmentados de Optima existe un script separado:

- `python scripts/generate_elevenlabs_optima_prompts.py --dest /var/lib/asterisk/sounds/custom --mirror-dir /usr/share/asterisk/sounds/custom`

Ese script:

- genera los audios estaticos `optima-01` a `optima-07` y `optima-objecion-unica`
- genera cache dinamica para nombres y bancos desde `config/lead_context.sample.csv`
- guarda una copia canonica en `artifacts/lab-prompts`
- valida el WAV final con `ffprobe` o `soxi` cuando alguna de esas herramientas esta disponible

## Validacion Practica

- Revisa el formato final con `soxi`.
- Prueba los audios con auriculares antes de conectarlos al dialplan.
- Si cambias el wording del IVR, vuelve a probar para evitar eco semantico contra `config/intents.yml`.
