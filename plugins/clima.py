"""El clima, con una tarjeta estilo Apple Weather en el panel de Node: temperatura grande, ícono, próximas horas
y los próximos 5 días con barras de temperatura. Datos de Open-Meteo (gratis, sin clave).
Tu ciudad se detecta una sola vez por tu IP (ip-api.com) y queda en ubicacion.json: edítalo si no es la correcta.
"""
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime

import numpy as np

node = None
SHARP = 3  # los íconos se dibujan 3 veces más grandes y se achican: bordes suaves
N_ = lambda texts: texts  # textos que se traducen al mostrarlos (node.t)
DAYS = N_(['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'])
# Código del tiempo (WMO) -> (cómo se dice, qué ícono)
CODES = N_({0: ('Despejado', 'clear'), 1: ('Mayormente despejado', 'partly'), 2: ('Parcialmente nublado', 'partly'),
         3: ('Nublado', 'cloudy'), 45: ('Niebla', 'fog'), 48: ('Niebla', 'fog'), 51: ('Llovizna', 'rain'),
         53: ('Llovizna', 'rain'), 55: ('Llovizna', 'rain'), 56: ('Llovizna helada', 'rain'),
         57: ('Llovizna helada', 'rain'), 61: ('Lluvia débil', 'rain'), 63: ('Lluvia', 'rain'),
         65: ('Lluvia fuerte', 'rain'), 66: ('Lluvia helada', 'rain'), 67: ('Lluvia helada', 'rain'),
         71: ('Nieve débil', 'snow'), 73: ('Nieve', 'snow'), 75: ('Nieve fuerte', 'snow'), 77: ('Granizo fino', 'snow'),
         80: ('Chaparrones', 'rain'), 81: ('Chaparrones', 'rain'), 82: ('Chaparrones fuertes', 'rain'),
         85: ('Nevadas', 'snow'), 86: ('Nevadas fuertes', 'snow'), 95: ('Tormenta', 'storm'),
         96: ('Tormenta con granizo', 'storm'), 99: ('Tormenta con granizo', 'storm')})
# El cielo de fondo, arriba y abajo, según el tiempo (de día / de noche)
SKY = {'clear': (('#2f80d8', '#7ab8ee'), ('#0a1430', '#24345f')),
       'partly': (('#4a7db8', '#8fb4da'), ('#121b33', '#2f3d5c')),
       'cloudy': (('#64758b', '#97a5b7'), ('#1a2130', '#384356')),
       'fog': (('#7a8591', '#a9b2bc'), ('#22282f', '#454d57')),
       'rain': (('#3c4d63', '#6b7d92'), ('#121a26', '#2b384a')),
       'snow': (('#7d93ae', '#c1cedd'), ('#283350', '#53637e')),
       'storm': (('#2a2e45', '#4b4f6c'), ('#14162a', '#2e3150'))}
TEMPS = [(-5, '#5e9cff'), (5, '#5ac8fa'), (13, '#34c759'), (20, '#ffd60a'), (27, '#ff9f0a'), (35, '#ff453a')]


def get(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'NodeAssistant'})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def home():
    """Tu ubicación: la guardada o, la primera vez, la que dice tu IP."""
    path = node.HERE / 'ubicacion.json'
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    found = get('http://ip-api.com/json/?fields=status,city,regionName,country,lat,lon&lang=es')
    if found.get('status') != 'success':
        raise ConnectionError('no pude averiguar tu ciudad')
    place = {'name': found['city'], 'lat': found['lat'], 'lon': found['lon']}
    path.write_text(json.dumps(place, ensure_ascii=False), encoding='utf-8')
    return place


def find(name):
    found = get('https://geocoding-api.open-meteo.com/v1/search?count=1&language=es&format=json&name='
                + urllib.parse.quote(name))
    if not found.get('results'):
        return None
    result = found['results'][0]
    return {'name': result['name'], 'lat': result['latitude'], 'lon': result['longitude']}


def forecast(place):
    return get('https://api.open-meteo.com/v1/forecast?timezone=auto&forecast_days=6'
               f"&latitude={place['lat']}&longitude={place['lon']}"
               '&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day'
               '&hourly=temperature_2m,weather_code,is_day'
               '&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max')


# ---------- dibujo ----------

def hex_rgb(color):
    return np.array([int(color[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float32)


def disc(x, y, cx, cy, r):
    return np.clip(r - np.hypot(x - cx, y - cy) + 0.5, 0, 1)


def stroke(x, y, ax, ay, bx, by, r):
    t = np.clip(((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2), 0, 1)
    return np.clip(r - np.hypot(x - ax - t * (bx - ax), y - ay - t * (by - ay)) + 0.5, 0, 1)


def triangle(x, y, a, b, c):
    side = lambda p, q: (x - q[0]) * (p[1] - q[1]) - (p[0] - q[0]) * (y - q[1])
    d1, d2, d3 = side(a, b), side(b, c), side(c, a)
    return (~(((d1 < 0) | (d2 < 0) | (d3 < 0)) & ((d1 > 0) | (d2 > 0) | (d3 > 0)))).astype(np.float32)


def over(rgb, alpha, color, cover):
    """Pinta `color` con cobertura `cover` encima de la imagen (rgb, alpha)."""
    cover = cover[..., None] if cover.ndim == 2 else cover
    rgb[:] = rgb * (1 - cover) + color * cover
    alpha[:] = alpha + (1 - alpha) * cover[..., 0]


def icon(kind, size, day):
    """Un ícono del tiempo de size x size píxeles: devuelve (rgb, alpha)."""
    n = size * SHARP
    y, x = np.mgrid[0:n, 0:n].astype(np.float32) + 0.5
    rgb, alpha = np.zeros((n, n, 3), np.float32), np.zeros((n, n), np.float32)

    def sun(cx, cy, r):
        glow = np.exp(-np.clip(np.hypot(x - cx * n, y - cy * n) - r * n, 0, None) / (0.07 * n)) * 0.55
        over(rgb, alpha, hex_rgb('#ffb703'), glow * (1 - disc(x, y, cx * n, cy * n, r * n)))
        over(rgb, alpha, hex_rgb('#ffd84d'), disc(x, y, cx * n, cy * n, r * n))

    def moon(cx, cy, r):
        crescent = disc(x, y, cx * n, cy * n, r * n) * (1 - disc(x, y, (cx + 0.42 * r) * n, (cy - 0.3 * r) * n, r * n))
        over(rgb, alpha, hex_rgb('#f3efd2'), crescent)

    def cloud(cx, cy, w, top='#f7f9fc', bottom='#d3dbe6'):
        parts = [disc(x, y, (cx - 0.2 * w) * n, (cy + 0.03 * w) * n, 0.17 * w * n),
                 disc(x, y, (cx + 0.02 * w) * n, (cy - 0.07 * w) * n, 0.25 * w * n),
                 disc(x, y, (cx + 0.22 * w) * n, (cy + 0.05 * w) * n, 0.16 * w * n),
                 stroke(x, y, (cx - 0.22 * w) * n, (cy + 0.12 * w) * n, (cx + 0.24 * w) * n, (cy + 0.12 * w) * n,
                        0.09 * w * n)]
        shape = np.max(parts, axis=0)
        shade = np.clip((y / n - (cy - 0.3 * w)) / (0.5 * w), 0, 1)[..., None]
        over(rgb, alpha, hex_rgb(top) * (1 - shade) + hex_rgb(bottom) * shade, shape)

    light = sun if day else moon
    if kind == 'clear':
        light(0.5, 0.5, 0.27)
    elif kind == 'partly':
        light(0.38, 0.37, 0.21)
        cloud(0.55, 0.6, 0.78)
    elif kind == 'cloudy':
        cloud(0.62, 0.42, 0.55, '#c9d2de', '#a7b2c1')
        cloud(0.47, 0.58, 0.85)
    elif kind == 'fog':
        for row, (left, right) in enumerate(((0.18, 0.82), (0.26, 0.74), (0.2, 0.8))):
            over(rgb, alpha, hex_rgb('#e3e8ee'),
                 stroke(x, y, left * n, (0.34 + 0.16 * row) * n, right * n, (0.34 + 0.16 * row) * n, 0.045 * n))
    else:
        dark = kind == 'storm'
        cloud(0.5, 0.4, 0.88, '#aeb7c6' if dark else '#eef2f7', '#7f8a9c' if dark else '#c3ccd8')
        if kind == 'rain':
            for drop in (0.33, 0.5, 0.67):
                over(rgb, alpha, hex_rgb('#5ab8ff'),
                     stroke(x, y, (drop + 0.03) * n, 0.68 * n, (drop - 0.03) * n, 0.84 * n, 0.032 * n))
        elif kind == 'snow':
            for sx, sy in ((0.33, 0.72), (0.5, 0.82), (0.67, 0.72), (0.42, 0.9), (0.58, 0.9)):
                over(rgb, alpha, hex_rgb('#ffffff'), disc(x, y, sx * n, sy * n, 0.04 * n))
        else:
            bolt = np.maximum(triangle(x, y, (0.56 * n, 0.55 * n), (0.36 * n, 0.8 * n), (0.52 * n, 0.78 * n)),
                              triangle(x, y, (0.5 * n, 0.72 * n), (0.64 * n, 0.7 * n), (0.42 * n, 0.98 * n)))
            over(rgb, alpha, hex_rgb('#ffd84d'), bolt)
    shrink = lambda image: image.reshape(size, SHARP, size, SHARP, *image.shape[2:]).mean(axis=(1, 3))
    return shrink(rgb), shrink(alpha)


def temp_color(value):
    for (low, a), (high, b) in zip(TEMPS, TEMPS[1:]):
        if value <= high:
            mix = np.clip((value - low) / (high - low), 0, 1)
            return hex_rgb(a) * (1 - mix) + hex_rgb(b) * mix
    return hex_rgb(TEMPS[-1][1])


def rounded(width, height, radius, x0=0, y0=0, w=None, h=None):
    """Cobertura de un rectángulo redondeado (todo el lienzo o una caja dentro)."""
    w, h = w or width, h or height
    y, x = np.mgrid[0:height, 0:width].astype(np.float32) + 0.5
    qx = np.abs(x - x0 - w / 2) - (w / 2 - radius)
    qy = np.abs(y - y0 - h / 2) - (h / 2 - radius)
    depth = radius - np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) - np.minimum(np.maximum(qx, qy), 0)
    return np.clip(depth + 0.5, 0, 1)


def weather_card(place, data):
    """Devuelve la función que dibuja la tarjeta en el panel de Node."""
    def draw(width, px, ink):
        now, daily, hourly = data['current'], data['daily'], data['hourly']
        day = bool(now['is_day'])
        condition, kind = CODES.get(now['weather_code'], ('', 'cloudy'))
        pad, height = px(20), px(414)
        # Fondo: cielo con degradado, esquinas redondeadas y dos cajas de vidrio claro.
        top, bottom = SKY[kind][0 if day else 1]
        shade = (np.arange(height, dtype=np.float32) / height)[:, None, None]
        image = np.repeat(hex_rgb(top) * (1 - shade) + hex_rgb(bottom) * shade, width, axis=1)
        for box_y, box_h in ((px(170), px(92)), (px(272), px(128))):
            glass = rounded(width, height, px(14), pad, box_y, width - 2 * pad, box_h)[..., None] * 0.13
            image = image * (1 - glass) + 255 * glass

        def paste(kind_, size, left, upper, is_day=day):
            rgb, alpha = icon(kind_, size, is_day)
            region = image[upper:upper + size, left:left + size]
            region[:] = region * (1 - alpha[..., None]) + rgb * alpha[..., None]

        paste(kind, px(104), width - pad - px(108), px(12))
        # Próximas horas
        start = next(i for i, moment in enumerate(hourly['time']) if moment[:13] >= datetime.now().isoformat()[:13])
        hours = range(start, start + 7)
        column = (width - 2 * pad) / 7
        for k, i in enumerate(hours):
            paste(CODES.get(hourly['weather_code'][i], ('', 'cloudy'))[1], px(28),
                  int(pad + column * (k + 0.5) - px(14)), px(170) + px(30), bool(hourly['is_day'][i]))
        # Próximos días, con barras de temperatura sobre la escala de toda la semana
        lows, highs = daily['temperature_2m_min'][:5], daily['temperature_2m_max'][:5]
        low_all, high_all = min(lows), max(highs)
        bar_x0, bar_x1 = pad + px(186), width - pad - px(50)
        for k in range(5):
            row_y = px(282) + k * px(23)
            paste(CODES.get(daily['weather_code'][k], ('', 'cloudy'))[1], px(20), pad + px(64), row_y)
            track = rounded(width, height, px(3), bar_x0, row_y + px(8), bar_x1 - bar_x0, px(5))[..., None]
            image = image * (1 - track * 0.25) + 20 * track * 0.25
            left = bar_x0 + (lows[k] - low_all) / max(high_all - low_all, 1) * (bar_x1 - bar_x0)
            right = bar_x0 + (highs[k] - low_all) / max(high_all - low_all, 1) * (bar_x1 - bar_x0)
            fill = rounded(width, height, px(3), int(left), row_y + px(8), max(int(right - left), px(6)), px(5))[..., None]
            spread = np.clip((np.arange(width, dtype=np.float32) - left) / max(right - left, 1), 0, 1)
            colors = np.array([temp_color(lows[k] + (highs[k] - lows[k]) * s) for s in spread])[None]
            image = image * (1 - fill) + colors * fill
        # Los textos, encima (los escribe Windows, suavizados)
        soft = '#e4ecf7'
        text = lambda x, y, value, size, weight='', color='#ffffff', anchor='nw', family=None: \
            ink(image, value, x, y, size, color, weight, anchor, family)
        text(pad, px(16), place['name'], 12, 'bold')
        text(pad - px(3), px(30), f"{round(now['temperature_2m'])}°", 46, family=node.TYPE['light'])
        text(pad, px(100), node.t(condition), 12)
        text(pad, px(121), node.t('Máx {high}°   Mín {low}°', high=round(highs[0]), low=round(lows[0])), 11, color=soft)
        text(pad, px(143), node.t('Sensación {feel}°  ·  Humedad {humidity}%  ·  Viento {wind} km/h',
                                  feel=round(now['apparent_temperature']), humidity=now['relative_humidity_2m'],
                                  wind=round(now['wind_speed_10m'])), 10, color=soft)
        for k, i in enumerate(hours):
            center = pad + column * (k + 0.5)
            text(center, px(180), node.t('Ahora') if k == 0 else f"{hourly['time'][i][11:13]} h", 10, color=soft, anchor='n')
            temp = now['temperature_2m'] if k == 0 else hourly['temperature_2m'][i]
            text(center, px(234), f'{round(temp)}°', 12, 'bold', anchor='n')
        for k in range(5):
            row_y = px(282) + k * px(23) + px(10)
            name = node.t('Hoy') if k == 0 else node.t(DAYS[datetime.fromisoformat(daily['time'][k]).weekday()])
            text(pad + px(12), row_y, name, 11, 'bold', anchor='w')
            rain = daily['precipitation_probability_max'][k]
            if rain and rain >= 20:
                text(pad + px(90), row_y, f'{rain}%', 9, 'bold', color='#8fd3ff', anchor='w')
            text(bar_x0 - px(10), row_y, f'{round(lows[k])}°', 11, color=soft, anchor='e')
            text(width - pad - px(12), row_y, f'{round(highs[k])}°', 11, 'bold', anchor='e')
        return image, rounded(width, height, px(22))  # la imagen y su cobertura (esquinas suaves)
    return draw


def weather(args, where):
    place_name = (args.get('place') or '').strip()
    place = find(place_name) if place_name else home()
    if not place:
        return node.t('No encontré el lugar {place_name}.', place_name=place_name)
    data = forecast(place)
    now, daily = data['current'], data['daily']
    day = min(max(int(args.get('day') or 0), 0), 5)
    condition = node.t(CODES.get(daily['weather_code'][day] if day else now['weather_code'], ('',))[0]).lower()
    rain = daily['precipitation_probability_max'][day] or 0
    high, low = round(daily['temperature_2m_max'][day]), round(daily['temperature_2m_min'][day])
    if day == 0:
        say = node.t('En {place} hay {temp} grados, {condition}. Máxima de {high} y mínima de {low}', place=place['name'],
                     temp=round(now['temperature_2m']), condition=condition, high=high, low=low)
    else:
        weekday = node.DAYS[datetime.fromisoformat(daily['time'][day]).weekday()]
        when = node.t('mañana') if day == 1 else node.t('el {day}', day=weekday)
        say = node.t('En {place}, {when}: {condition}, con máxima de {high} y mínima de {low}', place=place['name'],
                     when=when, condition=condition, high=high, low=low)
    say += node.t(', y {rain} por ciento de probabilidad de lluvia.', rain=rain) if rain >= 30 else '.'
    if where == 'pc':
        node.card(weather_card(place, data))
    else:  # en el celular, también los próximos días en texto
        say += node.t(' Próximos días: ') + ', '.join(
            f"{node.t(DAYS[datetime.fromisoformat(daily['time'][k]).weekday()])} {round(daily['temperature_2m_min'][k])}–"
            f"{round(daily['temperature_2m_max'][k])}°" for k in range(1, 5)) + '.'
    return say


def setup(node_):
    global node
    node = node_
    node.add(node.tool('weather', 'Muestra el clima con una tarjeta (temperatura, próximas horas y días). place: '
                       'la ciudad pedida, o vacío para donde está el usuario. day: 0 hoy, 1 mañana, hasta 5.',
                       place={'type': 'string'}, day={'type': 'integer'}), weather, r'clima|tiempo|llov|lluvia|temperatura|frio|calor|grados|pronostico|paraguas|sol|nubl')
