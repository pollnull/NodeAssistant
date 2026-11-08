# Plugins de Node Assistant

Cada archivo `.py` de esta carpeta suma habilidades. Node los carga solo al arrancar; uno roto no lo tumba.

Un plugin tiene una función `setup(node)`. `node` es Node entero; lo que más se usa:

| | |
|---|---|
| `node.add(node.tool(nombre, descripción, **parámetros), función)` | suma una herramienta que la IA puede elegir. `función(argumentos, where)` la hace y devuelve qué decir; `where` es `'pc'` o `'telegram'` |
| `node.notify(texto)` | un aviso que llega solo: baja la cápsula, lo dice en voz alta y lo manda a Telegram |
| `node.card(draw)` | una tarjeta dibujada a mano en el panel: `draw(ancho, px, ink)` devuelve `(imagen, cobertura)` (ver `clima.py`) |
| `node.command('/nombre', 'para qué sirve', función)` | un comando con "/" para la cápsula y Telegram; `función(texto)` devuelve qué mostrar y aparece solo en `/help` |
| `node.WAITING.append(función)` | para esperar una respuesta corta ("¿hago clic acá?" → "sí"): `función(texto, where)` devuelve qué decir, o `None` si no es para ella |
| `node.STARTERS.append(función)` | algo que arranca al abrir Node (un vigilante, un bot) |
| `node.secret('NOMBRE')` | una clave guardada en las variables de Windows |
| `node.cloud(mensajes)`, `node.handle(texto)`, `node.press(*teclas)` | la IA, una orden completa, apretar teclas |
| `node.t('Abriendo {app}.', app=nombre)` | un texto en el idioma de la persona (ver abajo) |

La descripción de la herramienta es lo que la IA lee para decidir cuándo usarla: escríbela clara y corta.

**Ahorro de cupo:** `node.add(herramienta, función, r'palabras|que|la|delatan')`. A la IA solo le llega la herramienta
si lo que dijiste tiene alguna de esas palabras (en minúsculas y sin tildes). Sin palabras, viaja siempre.

Plugins incluidos (cada uno explica arriba cómo se configura; `setup.py` es el asistente `/setup`): `recordatorios.py`, `clima.py`, `discord.py`,
`telegram.py`, `portapapeles.py`, `obsidian.py`, `steam.py`, `obs.py`, `github.py`, `google.py`, `pantalla.py`
(visión), `sistema.py` (estado de la PC), `raton.py` (encontrar, señalar y hacer clic) y `comandos.py` (comandos de
PowerShell y archivos, preguntando antes de cambiar algo), `reloj.py` (tarjeta de la hora y el día), `bases.py`
(colecciones tipo Notion con el sistema de la plantilla de kepano) y `diario.py` (nota del día y resumen de las 20:00).

**Idiomas:** escribe los textos que ve la persona en español y envuélvelos en `node.t(...)`, con los datos aparte
(`node.t('Abriendo {app}.', app=nombre)`, nunca un f-string adentro). Después corre `tools\traducir.py`: los traduce a
los otros idiomas en `idiomas/`. Lo que va para la IA (la descripción de la herramienta, instrucciones) no hace falta
traducirlo.

**¿Sin programar?** `tools\crear_plugin.py` (o el issue "Nuevo plugin" en GitHub) arma uno con unas preguntas.

## Configurar Google (Gmail y Calendar), una sola vez

1. Entra a https://console.cloud.google.com con tu cuenta y crea un proyecto (por ejemplo "Node Assistant").
2. **APIs y servicios -> Biblioteca**: habilita **Gmail API** y **Google Calendar API**.
3. **APIs y servicios -> Pantalla de consentimiento de OAuth** (o "Google Auth Platform"): tipo **Externo**,
   nombre "Node Assistant", tu correo como contacto. En **Público / Usuarios de prueba** agrega tu propio Gmail.
   Después, en **Público**, aprieta **Publicar app** (pasa a "En producción"): si queda "En prueba", Google
   vence el permiso cada 7 días. No hace falta verificarla: es solo para ti.
4. **Credenciales -> Crear credenciales -> ID de cliente de OAuth -> App de escritorio**. Descarga el JSON y
   guárdalo como `google_cliente.json` en la carpeta de Node Assistant.
5. Ejecuta `.venv\Scripts\python.exe plugins\google.py`: se abre el navegador, eliges tu cuenta y aceptas.
   Google avisa "Google no verificó esta app": es la tuya, toca **Configuración avanzada -> Ir a Node Assistant**.
