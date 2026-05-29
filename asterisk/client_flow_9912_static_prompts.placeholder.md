# Client Flow 9912 Static Prompts

Estos son los `Playback()` estáticos esperados por el flujo `9912`.
No se versionan WAV dentro del repo; este archivo deja el inventario y el naming esperado.

Base path activo en Asterisk:

- `custom/cliente-9912/carlo-presentacion`
- `custom/cliente-9912/oferta-acuerdo`
- `custom/cliente-9912/oferta-manana`
- `custom/cliente-9912/oferta-whatsapp`
- `custom/cliente-9912/transfiriendo`
- `custom/cliente-9912/permita-terminar`

Texto sugerido:

- `carlo-presentacion`: `Le habla Carlo Montero, de la oficina de abogados Jurídica Óptima.`
- `oferta-acuerdo`: `Queríamos saber, por favor, si usted estaría interesado en conversar sobre una posible alternativa de acuerdo.`
- `oferta-manana`: `También, si prefiere, puedo llamarle mañana.`
- `oferta-whatsapp`: `O, con mucho gusto, puedo enviarle la información vía WhatsApp.`
- `transfiriendo`: `Muy bien. Permítame un momento, por favor. Ya le transfiero con la persona encargada.`
- `permita-terminar`: `Por favor, permítame terminar.`

Dinámicos generados en `custom/generated/client-flow-9912/`:

- `greeting`
- `bank`
- `deuda-conocida`

Si `custom/cliente-9912/permita-terminar` no existe todavía, el dialplan usa `TryExec(Playback(...))`,
deja `NoOp(...)` con `TRYSTATUS` y continúa el flujo sin romper la llamada.
