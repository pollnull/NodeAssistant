"""La hora y el día con una tarjeta ilustrada: "¿qué hora es?", "¿qué día es hoy?", "¿qué fecha es?".
Un cielo que cambia con la hora (noche, amanecer, día, atardecer) con el sol o la luna en su lugar, un reloj de agujas,
la hora grande, la fecha y la semana con hoy marcado. En Telegram responde solo con texto.
"""
import math
from datetime import datetime

import numpy as np

node = None
# El cielo de fondo (arriba, abajo) según la hora del día.
SKIES = {'night': ('#0a1430', '#24345f'), 'dawn': ('#3a4d8f', '#f0a77a'),
         'day': ('#2f80d8', '#7ab8ee'), 'dusk': ('#3b3f7a', '#f08a5d')}
SUNRISE, SUNSET = 6.5, 19.0  # shortcut: horas fijas aproximadas; para exactas, pedirlas a Open-Meteo como en clima.py


def sky(hour):
    if hour < SUNRISE - 1 or hour >= SUNSET + 1:
        return 'night'
    if hour < SUNRISE + 1.5:
        return 'dawn'
    return 'day' if hour < SUNSET - 1.5 else 'dusk'


def disc(x, y, cx, cy, r):
    return np.clip(r - np.hypot(x - cx, y - cy) + 0.5, 0, 1)


def stroke(x, y, ax, ay, bx, by, r):
    t = np.clip(((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2), 0, 1)
    return np.clip(r - np.hypot(x - ax - t * (bx - ax), y - ay - t * (by - ay)) + 0.5, 0, 1)


def rounded(x, y, x0, y0, w, h, radius):
    qx = np.abs(x - x0 - w / 2) - (w / 2 - radius)
    qy = np.abs(y - y0 - h / 2) - (h / 2 - radius)
    depth = radius - np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) - np.minimum(np.maximum(qx, qy), 0)
    return np.clip(depth + 0.5, 0, 1)


def clock_card(now):
    def draw(width, px, ink):
        height, pad = px(236), px(20)
        y, x = np.mgrid[0:height, 0:width].astype(np.float32) + 0.5
        hour = now.hour + now.minute / 60
        kind = sky(hour)
        top, bottom = SKIES[kind]
        shade = (y / height)[..., None]
        image = node.rgb(top) * (1 - shade) + node.rgb(bottom) * shade
        sky_at = lambda row: node.rgb(top) * (1 - row / height) + node.rgb(bottom) * row / height

        def paint(cover, color, amount=1.0):  # color: '#rrggbb' o un color ya calculado
            color = node.rgb(color) if isinstance(color, str) else color
            image[:] = image * (1 - cover[..., None] * amount) + color * cover[..., None] * amount

        # El sol (de día) o la luna con estrellas (de noche), en un arco de izquierda a derecha.
        if kind == 'night':
            stars = np.random.default_rng(7).random((40, 3))
            for sx, sy, size in stars:
                paint(disc(x, y, sx * width, sy * px(150), px(0.6 + size)), '#ffffff', 0.35 + 0.5 * size)
            night = ((hour - SUNSET - 1) % 24) / (24 - (SUNSET - SUNRISE) - 2)  # 0 al anochecer, 1 al amanecer
            cx, cy = width * (0.66 + 0.26 * night), px(118) - px(80) * math.sin(math.pi * night)
            paint(disc(x, y, cx, cy, px(26)), '#ffffff', 0.08)  # halo
            paint(disc(x, y, cx, cy, px(14)), '#f2f0e6')
            paint(disc(x, y, cx + px(6), cy - px(4), px(12)), sky_at(cy))  # la sombra que la hace creciente
        else:
            day = np.clip((hour - SUNRISE) / (SUNSET - SUNRISE), 0, 1)
            cx, cy = width * (0.66 + 0.26 * day), px(118) - px(80) * math.sin(math.pi * day)
            glow = np.exp(-np.hypot(x - cx, y - cy) / px(30))
            paint(glow, '#fff3c4', 0.5)
            paint(disc(x, y, cx, cy, px(16)), '#ffd75e')

        # El reloj de agujas, a la izquierda.
        cx, cy, r = pad + px(56), px(80), px(56)
        paint(disc(x, y, cx, cy, r), '#ffffff', 0.16)
        paint(disc(x, y, cx, cy, r) - disc(x, y, cx, cy, r - px(1.5)), '#ffffff', 0.5)
        for k in range(12):
            angle = k * math.pi / 6
            inner = r - (px(10) if k % 3 == 0 else px(6))
            paint(stroke(x, y, cx + inner * math.sin(angle), cy - inner * math.cos(angle),
                         cx + (r - px(4)) * math.sin(angle), cy - (r - px(4)) * math.cos(angle),
                         px(1.4 if k % 3 == 0 else 0.8)), '#ffffff', 0.85)
        hand = lambda turn, length, thick, color: paint(stroke(
            x, y, cx, cy, cx + length * math.sin(turn * 2 * math.pi), cy - length * math.cos(turn * 2 * math.pi),
            thick), color)
        hand((hour % 12) / 12, r * 0.5, px(2.6), '#ffffff')
        hand(now.minute / 60, r * 0.76, px(1.8), '#ffffff')
        paint(disc(x, y, cx, cy, px(4)), node.GLOW[0])

        # La semana, abajo, en una caja de vidrio: hoy con un círculo del color de la cápsula.
        box_y, box_h = px(160), px(62)
        paint(rounded(x, y, pad, box_y, width - 2 * pad, box_h, px(14)), '#ffffff', 0.13)
        column = (width - 2 * pad) / 7
        today = now.weekday()
        paint(disc(x, y, pad + column * (today + 0.5), box_y + px(40), px(14)), node.GLOW[0], 0.9)

        # Los textos, encima.
        text = lambda tx, ty, value, size, weight='', color='#ffffff', anchor='nw', family=None: \
            ink(image, value, tx, ty, size, color, weight, anchor, family)
        left = pad + px(136)
        text(left, px(14), f'{now:%H:%M}', 40, family=node.TYPE['light'])
        text(left, px(80), node.DAYS[today].capitalize(), 14, 'bold')
        text(left, px(104), node.t('{day} de {month} de {year}', day=now.day, month=node.MONTHS[now.month - 1],
                                   year=now.year), 11, color='#e4ecf7')
        text(left, px(126), node.t('Semana {week} del año', week=now.isocalendar()[1]), 10, color='#c9d5e6')
        monday = now.toordinal() - today
        for k in range(7):
            center = pad + column * (k + 0.5)
            text(center, box_y + px(8), node.DAYS[k][:1].upper(), 9, color='#e4ecf7', anchor='n')
            text(center, box_y + px(40), str(datetime.fromordinal(monday + k).day), 11, 'bold', anchor='center')
        return image, rounded(x, y, 0, 0, width, height, px(22))
    return draw


def clock(_args, where):
    now = datetime.now()
    if where == 'pc':
        node.card(clock_card(now))
    return node.t('Son las {time} del {weekday} {day} de {month}.', time=f'{now:%H:%M}', weekday=node.DAYS[now.weekday()],
                  day=now.day, month=node.MONTHS[now.month - 1])


def setup(node_):
    global node
    node = node_
    node.PLUGINS['time'] = clock  # la herramienta 'time' ya existe en Node: solo cambia lo que hace
