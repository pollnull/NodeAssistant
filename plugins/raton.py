"""Mouse: Node encuentra cosas en tu pantalla, las señala y hace clic.
"¿dónde está el botón de guardar?", "señalame la barra de búsqueda", "haz clic en Aceptar", "doble clic en la
carpeta Fotos", "clic derecho en el ícono de Spotify".
Mira la pantalla con la IA de visión (como plugins/pantalla.py), mueve el mouse al centro de lo que encontró y lo hace
girar un instante para que lo veas. Antes de hacer clic pregunta "¿hago clic acá?": respondes "sí" (o "no") en los
próximos 30 segundos, por voz, escribiendo o por Telegram. Con CONFIRM = False hace clic sin preguntar.
Ojo: a veces apunta unos píxeles al costado o elige el elemento equivocado; por eso pregunta primero.
"""
import base64
import ctypes
import ctypes.wintypes
import json
import math
import re
import time

node = None
CONFIRM = True  # preguntar antes de hacer clic
PENDING = {}    # el clic que espera tu "sí": x, y, clic, qué es y hasta cuándo vale
YES = re.compile(r'^(si|sip|dale|ok|okey|hacelo|hazlo|hace clic|haz clic|confirmo|adelante|clic|de una|obvio)\b')
NO = re.compile(r'^(no|nop|cancela|cancelar|deja|dejalo|mejor no|para)\b')
CLICKS = {'click': ((0x02, 0x04),), 'double_click': ((0x02, 0x04), (0x02, 0x04)), 'right_click': ((0x08, 0x10),)}


def locate(target, where):
    """Busca `target` en la pantalla. Devuelve (x, y, None) si lo ve; si está escondido (en un menú, una pestaña),
    (x, y, "qué tocar primero") con el primer paso para llegar; o None si no hay pista."""
    if where == 'pc':  # que la cápsula no tape lo que hay que encontrar
        node.UI['hide']()
        time.sleep(0.45)
    image = node.screenshot()
    if where == 'pc':
        node.UI['appear']()
    user32 = ctypes.windll.user32
    left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)  # el escritorio puede empezar en negativo
    height, width = image.shape[:2]
    small = image[::2, ::2] if width > 2000 else image  # pantallas muy grandes: a la mitad (las coordenadas son 0-1000)
    picture = 'data:image/png;base64,' + base64.b64encode(node.png(small)).decode()
    answer = node.cloud([{'role': 'user', 'content': [
        {'type': 'text', 'text': f'Find this on the screenshot: "{target}" (a button, link, icon, field, option or '
                                 'text the user wants to reach). Answer only JSON, coordinates normalized to 0-1000. '
                                 'If it is visible: {"found": true, "box_2d": [ymin, xmin, ymax, xmax]}. If it is not '
                                 'visible but you know what to click first to get there (a menu, tab, panel or item '
                                 'that reveals it): {"found": false, "step": "<that first step, in Spanish, as an '
                                 'instruction to the user>", "box_2d": [ymin, xmin, ymax, xmax] of that element}. '
                                 'Otherwise: {"found": false}.'},
        {'type': 'image_url', 'image_url': {'url': picture}}]}], vision=True, wait=30, max_tokens=1500,
        only=('Gemini',))  # solo Gemini: las otras apuntan mal  # Gemini 3.5 piensa antes: con menos, la respuesta llega cortada
    found = re.search(r'\{.*\}', answer.get('content') or '', re.S)
    data = json.loads(found.group(0)) if found else {}
    box = data.get('box_2d')
    if not box or len(box) != 4 or not (data.get('found') or data.get('step')):
        return None
    ymin, xmin, ymax, xmax = box
    x, y = left + round((xmin + xmax) / 2000 * width), top + round((ymin + ymax) / 2000 * height)
    return x, y, None if data.get('found') else data['step'].strip().rstrip('.')


GLIDE = 0.45  # segundos que tarda el mouse en deslizarse hasta el objetivo (0 = aparece directo)


def show(x, y):
    """Desliza el mouse hasta ahí (arranca y frena suave, en una curva leve como una mano) y da una vuelta chiquita."""
    user32 = ctypes.windll.user32
    start = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(start))
    distance = math.hypot(x - start.x, y - start.y)
    steps = max(int(GLIDE * 100 * min(1, distance / 600 + 0.4)), 1)  # cerca, más rápido
    bend = min(distance * 0.12, 80)  # cuánto se curva el camino
    for step in range(1, steps + 1):
        t = step / steps
        ease = t * t * (3 - 2 * t)  # suave al arrancar y al frenar
        side = math.sin(math.pi * t) * bend  # la curva: máxima a mitad de camino, cero en las puntas
        nx, ny = (-(y - start.y) / distance, (x - start.x) / distance) if distance else (0, 0)
        user32.SetCursorPos(int(start.x + (x - start.x) * ease + nx * side),
                            int(start.y + (y - start.y) * ease + ny * side))
        time.sleep(0.01)
    for step in range(25):
        angle = step / 24 * 2 * math.pi
        radius = 18 * (1 - step / 24)
        user32.SetCursorPos(int(x + radius * math.cos(angle)), int(y + radius * math.sin(angle)))
        time.sleep(0.012)
    user32.SetCursorPos(x, y)


def click(x, y, kind):
    user32 = ctypes.windll.user32
    user32.SetCursorPos(x, y)
    for down, up in CLICKS[kind]:
        user32.mouse_event(down, 0, 0, 0, 0)
        user32.mouse_event(up, 0, 0, 0, 0)
        time.sleep(0.05)


def point(args, where):
    target, action = (args.get('target') or '').strip(), args.get('action') or 'point'
    if not target:
        return node.t('¿Qué busco en la pantalla?')
    try:
        spot = locate(target, where)
    except ConnectionError:  # Gemini sin cupo por este minuto: mejor esperar que apuntar mal
        if node.OPSEC['on']:
            return node.t('Con /opsec prendido no miro la pantalla: la visión necesita internet.')
        return node.t('La visión precisa (Gemini) está sin cupo por un momento. Pídemelo de nuevo en un minuto.')
    if not spot:
        return node.t('No veo {target} en la pantalla.', target=target)
    *spot, step = spot
    show(*spot)
    if step:  # está escondido: el mouse queda en lo que hay que tocar primero
        if action != 'point' and CONFIRM:
            PENDING.update(x=spot[0], y=spot[1], kind='click', target=target, until=time.time() + 30,
                           done=node.t('Listo. Ahora pídeme de nuevo {target}.', target=target))
            return node.t('Todavía no veo {target}. Primero: {step}. Te dejé el mouse encima: ¿hago clic ahí? Dime sí o no.', target=target, step=step)
        return node.t('Todavía no veo {target}. Primero: {step}. Te dejé el mouse encima; después pídemelo de nuevo.', target=target, step=step)
    if action == 'point':
        return node.t('Ahí está {target}: te dejé el mouse encima.', target=target)
    if not CONFIRM:
        click(*spot, action)
        return node.t('Listo, hice clic en {target}.', target=target)
    PENDING.update(x=spot[0], y=spot[1], kind=action, target=target, until=time.time() + 30)
    return node.t('Encontré {target} y te dejé el mouse encima. ¿Hago {dato}clic{dato2} ahí? Dime sí o no.', target=target, dato="doble " if action == "double_click" else "", dato2=" derecho" if action == "right_click" else "")


def answer(text, where):
    """El "sí" o "no" al clic pendiente (si no hay ninguno, o no es una respuesta, deja pasar la orden)."""
    if not PENDING or PENDING['until'] < time.time():
        PENDING.clear()
        return None
    said = node.plain(text).strip(' .!¡¿?')
    if YES.match(said):
        spot = PENDING.copy()
        PENDING.clear()
        click(spot['x'], spot['y'], spot['kind'])
        return spot.get('done') or node.t('Listo, hice clic en {target}.', target=spot['target'])
    if NO.match(said):
        PENDING.clear()
        return node.t('Ok, no hago nada.')
    PENDING.clear()  # dijo otra cosa: el clic pendiente se olvida y la orden sigue normal
    return None


def setup(node_):
    global node
    node = node_
    node.add(node.tool('mouse', 'Encuentra algo en la pantalla del usuario (botón, link, ícono, campo, texto) y lo '
                       'señala con el mouse; o le hace clic. target: qué buscar, como lo dijo el usuario. action: point '
                       '(solo señalar, "¿dónde está...?"), click, double_click o right_click.',
                       target={'type': 'string'},
                       action={'type': 'string', 'enum': ['point', 'click', 'double_click', 'right_click']}),
             point, r'clic|click|toca|aprieta|presiona|seleccion|donde esta|donde queda|senal|mouse|cursor|encontr')
    node.WAITING.append(answer)
