"""Dibuja los íconos de Node Assistant (el orbe) y de Cerrar Node Assistant (las mismas luces en forma de X).
Con el estilo de la cápsula: vidrio oscuro, borde de luz de colores y luces que se mezclan.
Uso: .venv\\Scripts\\python.exe iconos.py   (crea icons\\node.ico e icons\\cerrar.ico)
"""
import math
import struct
import zlib
from pathlib import Path

import numpy as np

GLOW = ['#2d6bff', '#5cc8ff', '#00e5ff']  # los colores de fábrica de la cápsula (combo node)
TOP, BOTTOM, SPHERE = '#181d36', '#07080f', '#140b2a'
SIZES = (16, 24, 32, 48, 64, 128, 256)
SHARP = 4  # se dibuja 4 veces más grande y se achica: bordes suaves


def rgb(color):
    return np.array([int(color[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float32)


def lights(x, y, cx, cy, size):
    """Las tres luces de colores del orbe alrededor del centro (repartidas en la ronda de GLOW)."""
    total = np.zeros(x.shape + (3,), np.float32)
    for i, color in enumerate(GLOW[len(GLOW) * k // 3] for k in range(3)):
        angle = 0.9 + i * 2.1
        bx, by = cx + 0.45 * size * math.cos(angle), cy + 0.45 * size * math.sin(angle)
        total += rgb(color) * np.exp(-((x - bx) ** 2 + (y - by) ** 2) / (2 * (0.5 * size) ** 2))[..., None]
    return total


def segment(x, y, ax, ay, bx, by):
    """Distancia de cada píxel al segmento AB."""
    t = np.clip(((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2), 0, 1)
    return np.hypot(x - ax - t * (bx - ax), y - ay - t * (by - ay))


def draw(size, cross):
    n = size * SHARP
    y, x = np.mgrid[0:n, 0:n].astype(np.float32) + 0.5
    c = n / 2
    # Fondo: cuadrado redondeado de vidrio con un borde de luz que da la vuelta con los colores.
    radius = 0.23 * n
    q = np.abs(np.stack([x - c, y - c])) - (c - radius)
    depth = radius - np.hypot(*np.maximum(q, 0)) - np.minimum(q.max(axis=0), 0)
    alpha = np.clip(depth / SHARP + 0.5, 0, 1)
    shade = (y / n)[..., None]
    image = rgb(TOP) * (1 - shade) + rgb(BOTTOM) * shade
    stops = np.array([rgb(color) for color in GLOW + GLOW[:1]])
    where = (np.arctan2(y - c, x - c) / (2 * math.pi) % 1) * len(GLOW)
    ring = stops[where.astype(int)] * (1 - (where % 1))[..., None] + stops[where.astype(int) + 1] * (where % 1)[..., None]
    inside = depth.clip(0)
    image += ring * (np.exp(-inside / (0.025 * n)) + 0.35 * np.exp(-inside / (0.12 * n)))[..., None] * 0.8
    light = lights(x, y, c, c, 0.3 * n)
    if cross:  # las luces del orbe, pero con forma de X
        arm, width = 0.2 * n, 0.075 * n
        distance = np.minimum(segment(x, y, c - arm, c - arm, c + arm, c + arm),
                              segment(x, y, c + arm, c - arm, c - arm, c + arm))
        shape = np.clip((width - distance) / SHARP + 0.5, 0, 1)[..., None]
        fill = rgb(SPHERE) + light * 0.95 + 35
        halo = np.exp(-np.clip(distance - width, 0, None) / (0.06 * n))[..., None] * 0.6
    else:  # el orbe: una esfera de vidrio con las luces adentro y un reflejo arriba
        distance = np.hypot(x - c, y - c)
        orb = 0.3 * n
        shape = np.clip((orb - distance) / SHARP + 0.5, 0, 1)[..., None]
        shine = 120 * np.exp(-((x - c + 0.35 * orb) ** 2 + (y - c + 0.42 * orb) ** 2) / (2 * (0.2 * orb) ** 2))
        fill = rgb(SPHERE) + light * 0.85 + shine[..., None]
        halo = np.exp(-np.clip(distance - orb, 0, None) / (0.09 * n))[..., None] * 0.5
    image = image * (1 - shape) + fill * shape + light * halo * (1 - shape)
    pixels = np.dstack([image.clip(0, 255), alpha * 255])
    # Achica promediando bloques de SHARP x SHARP (como un antialias).
    return pixels.reshape(size, SHARP, size, SHARP, 4).mean(axis=(1, 3)).round().astype(np.uint8)


def png(pixels):
    height, width = pixels.shape[:2]
    chunk = lambda kind, data: struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    raw = b''.join(b'\x00' + row.tobytes() for row in pixels)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def ico(path, cross):
    images = [png(draw(size, cross)) for size in SIZES]
    offset = 6 + 16 * len(images)
    header = struct.pack('<HHH', 0, 1, len(images))
    for size, image in zip(SIZES, images):
        header += struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(image), offset)
        offset += len(image)
    path.write_bytes(header + b''.join(images))


if __name__ == '__main__':
    folder = Path(__file__).parent / 'icons'
    folder.mkdir(exist_ok=True)
    ico(folder / 'node.ico', cross=False)
    ico(folder / 'cerrar.ico', cross=True)
    for name, cross in (('node', False), ('cerrar', True)):  # vista previa grande, para revisarlos
        (folder / f'{name}.png').write_bytes(png(draw(256, cross)))
    print('Listo: icons\\node.ico e icons\\cerrar.ico')
