r"""Node Assistant: apreta Ctrl+Alt+N, suena un bip, di la orden y haz una pausa: la ejecuta y te contesta en voz alta.

Abre apps y carpetas, busca en Google, maneja el volumen y la música, captura la pantalla, bloquea la PC y dice la hora;
lo que no sea una orden lo responde la IA en la nube (Groq, Gemini, OpenRouter o Cloudflare) o, sin internet, llama3.2.
Una cápsula azul baja desde arriba; también puedes escribir en ella y apretar Enter. La respuesta sale debajo.
Escape o un clic afuera la esconden (sigue esperando el atajo); sola no se esconde.
Para apagarlo del todo y liberar memoria: di o escribe "salir", o usa "Cerrar Node Assistant" del menú Inicio.
Usa el entorno de la carpeta:  .venv\Scripts\pythonw.exe node_assistant.py
Probar sin abrir nada:         .venv\Scripts\python.exe node_assistant.py --dry "pon algo de música"
"""
import collections
import contextlib
import ctypes
import difflib
import glob
import importlib.util
import io
import json
import math
import os
import queue
import re
import struct
import subprocess
import sys
import threading
import time
import unicodedata
import tkinter as tk
import tkinter.font as tkfont
import urllib.parse
import urllib.error
import urllib.request
import wave
import winreg
import webbrowser
import winsound
import zlib
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from piper import PiperVoice

HERE = Path(__file__).parent
SETTINGS = HERE / 'ajustes.json'  # lo que eliges en /setup y con comandos; sigue después de reiniciar


def saved(name, default=False):
    return (json.loads(SETTINGS.read_text(encoding='utf-8')) if SETTINGS.exists() else {}).get(name, default)


def save(name, value):
    settings = json.loads(SETTINGS.read_text(encoding='utf-8')) if SETTINGS.exists() else {}
    SETTINGS.write_text(json.dumps({**settings, name: value}, ensure_ascii=False), encoding='utf-8')


# Lo que se elige en /setup y /settings (se aplica al reiniciar Node).
# Idiomas: código -> (nombre, cómo se dice en español para la IA, cartelitos de la cápsula: esperando/escuchando/pensando)
LANGUAGES = {'es': ('Español', 'español', ('Habla o escribe…', 'Escuchando…', 'Pensando…')),
             'en': ('English', 'inglés', ('Speak or type…', 'Listening…', 'Thinking…')),
             'pt': ('Português', 'portugués', ('Fale ou escreva…', 'Ouvindo…', 'Pensando…')),
             'fr': ('Français', 'francés', ('Parle ou écris…', 'J’écoute…', 'Je réfléchis…')),
             'de': ('Deutsch', 'alemán', ('Sprich oder schreib…', 'Ich höre zu…', 'Ich denke nach…')),
             'it': ('Italiano', 'italiano', ('Parla o scrivi…', 'Ti ascolto…', 'Sto pensando…'))}
def device_language():
    """El idioma de Windows (el de los menús), si Node lo tiene; si no, inglés."""
    buffer = ctypes.create_unicode_buffer(85)
    ctypes.windll.kernel32.LCIDToLocaleName(ctypes.windll.kernel32.GetUserDefaultUILanguage(), buffer, 85, 0)
    code = buffer.value.split('-')[0].lower()  # "es-AR" -> "es"
    return code if code in LANGUAGES else 'en'


# El que elegiste en /setup o /settings; si nunca elegiste, el de Windows. En ese te entiende, responde y muestra todo.
LANGUAGE = saved('language') if saved('language') in LANGUAGES else device_language()
# Los textos fijos de Node (ventanas, avisos, tarjetas) en tu idioma: idiomas/<código>.json, del español a ese idioma.
# Se generan con tools/traducir.py; un texto que falte queda en español.
TRANSLATIONS = json.loads((HERE / 'idiomas' / f'{LANGUAGE}.json').read_text(encoding='utf-8')) \
    if (HERE / 'idiomas' / f'{LANGUAGE}.json').exists() else {}


def N_(texts):
    """Marca textos para traducir que se traducen después, al mostrarlos con t() (listas, opciones de menú)."""
    return texts


def t(text, /, **values):  # "/": un dato también puede llamarse text
    """Un texto fijo en tu idioma. Los datos van aparte: t('Abriendo {app}.', app=nombre)."""
    text = TRANSLATIONS.get(text, text)
    return text.format(**values) if values else text
DECIDE = saved('decide_model', 'laya:322m-multilingual-bf16')  # modelo de decisión: elige entre opciones, no conversa
CHAT = saved('chat_model', 'llama3.2')    # modelo de charla local: el respaldo si no responde ninguna nube
NAME = saved('name', '')                  # tu nombre: así te llama Node
VAULT = Path(saved('vault')) if saved('vault') else None  # la bóveda de Obsidian (memoria); None = sin memoria
VOICE = Path(saved('voice', str(HERE / 'voices' / 'es_MX-claude-high.onnx')))  # la voz de Piper
# La personalidad: se cambia en /settings → Avanzado (es lo que más cambia cómo habla).
CHARACTER = ('Hablas como una persona tranquila y con criterio: cálido y humano, pero sin exagerar el entusiasmo ni '
             'forzar chistes. Vas al punto y dices cosas con sentido; si no sabes algo o no estás seguro, lo dices en '
             'vez de inventar. Puedes dar tu opinión con respeto, sin pasarte de la raya.')
PERSONA = (f'Eres Node, el asistente de {NAME or "quien usa esta computadora"} en su computadora. '
           f'{saved("persona") or CHARACTER} Respondes siempre en {LANGUAGES[LANGUAGE][1]}, en 1 a 3 frases, porque '
           'tus respuestas se leen en voz alta: nada de listas, emojis ni símbolos.')
TEMPERATURE = saved('temperature', 0.5)  # más bajo = respuestas más sensatas; más alto = más creativas (y más disparates)
CONFIDENT = 60                            # % mínimo para hacerle caso a Laya
HOTKEY = (0x0001 | 0x0002 | 0x4000, 0x4E)  # Ctrl + Alt + N (MOD_NOREPEAT: mantenerlo apretado no repite)
HEARING = saved('whisper', 'small')        # modelo de Whisper: tiny, base, small, medium (más grande = entiende mejor, más lento)
RATE = 16000                               # Whisper escucha a 16 kHz
MIC_WARMUP = saved('mic_warmup', 0.9)  # s que tarda el micrófono en captar de verdad al abrirlo (medido en una laptop: 0,9)
QUIET = saved('quiet', 350)               # caracteres: una respuesta más larga se muestra pero no se lee en voz alta
KEEP = '30m'                            # tiempo que los modelos quedan cargados: la primera vez tardan ~30 s

# Tus apps favoritas: nombre del acceso directo -> para qué sirve. Edita apps.json para sumar más.
# Laya acierta mucho más con descripciones cortas en inglés ("music, songs") que con frases en español.
FAVORITES = json.loads((HERE / 'apps.json').read_text(encoding='utf-8'))
# Órdenes claras: se reconocen por palabras clave en español (seguro e instantáneo).
# Laya queda para lo vago ("pon algo de música"): sin entrenar acierta bien entre pocas opciones, no entre muchas.
# Para enseñarle algo nuevo: suma una regla en plan() y lo que hace en act().
KEYS = {'up': 0xAF, 'down': 0xAE, 'mute': 0xAD, 'play_pause': 0xB3, 'next': 0xB0, 'previous': 0xB1}  # teclas multimedia
FOLDERS = {'descarga': 'Downloads', 'documento': 'Personal', 'escritorio': 'Desktop', 'foto': 'My Pictures',
           'imagen': 'My Pictures', 'imágen': 'My Pictures', 'video': 'My Video', 'vídeo': 'My Video', 'música': 'My Music'}
# "busca X en spotify/youtube (y reprodúcelo)", "pon X en youtube": quita las palabras de la orden y deja X.
PLAY = re.compile(r'\b(?:reproduc\w*|pon(?:me|lo|la|le)?|toca\w*|escuch\w*|dale play|play)\b')
FILLER = re.compile(r'\b(?:abr[eií]\w*|b[uú]sca\w*|reproduc\w*|pon(?:me|lo|la|le)?|toca\w*|escuch\w*|dale play|play|en|y|el primero|'
                    r'el primer resultado|lo|la)\b')
SEARCH = re.compile(r'^(?:b[uú]sca\w*|googlea\w*)\s+(?:en (?:google|internet)\s+)?(?:sobre |de |qu[eé] es )?(.+)$')
DAYS = [t(day) for day in N_(('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo'))]  # tu idioma
MONTHS = [t(month) for month in N_(('enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
                                    'septiembre', 'octubre', 'noviembre', 'diciembre'))]
OPEN = re.compile(r'^(?:abr[eií]\w*|inici\w*|ejecut\w*|lanz\w*|open)\s+(?:el |la |los |las |un |una )?(.+)$')


def start_menu_apps():
    """Todos los accesos directos del menú Inicio: nombre en minúsculas -> ruta del .lnk."""
    apps = {}
    for root in (r'%ProgramData%\Microsoft\Windows\Start Menu\Programs', r'%AppData%\Microsoft\Windows\Start Menu\Programs'):
        for lnk in glob.glob(os.path.expandvars(root) + r'\**\*.lnk', recursive=True):
            name = Path(lnk).stem.lower()
            if not re.search(r'uninstall|desinstal', name):
                apps.setdefault(name, lnk)
    # Las apps de la Store (Bloc de notas, Calculadora…) no tienen .lnk: se abren por su AppID.
    out = subprocess.run(['powershell', '-NoProfile', '-Command', 'Get-StartApps | ConvertTo-Json -Compress'],
                         capture_output=True, text=True, encoding='utf-8',
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
    for app in json.loads(out or '[]'):
        if not re.search(r'uninstall|desinstal', app['Name'].lower()):
            apps.setdefault(app['Name'].lower(), 'shell:AppsFolder\\' + app['AppID'])
    return apps


APPS = start_menu_apps()


def find_app(name):
    """Busca una app por nombre: exacto, después contenido, después parecido (tolera errores al dictar)."""
    name = name.lower().strip()
    if name in APPS:
        return name
    # Primero las que tienen esa palabra entera ("obs" -> "obs studio", no "obsidian"), y después las más cortas.
    contains = sorted((app for app in APPS if name in app), key=lambda app: (name not in app.split(), len(app)))
    if contains:
        return contains[0]
    close = difflib.get_close_matches(name, APPS, n=1, cutoff=0.75)
    return close[0] if close else None


def decide(question, text, choices):
    """Le pregunta a Laya cuál opción corresponde. Devuelve (opción, porcentaje)."""
    args = ['ollama', 'run', DECIDE, '--keepalive', KEEP, '--ask', question]
    for key, description in choices.items():
        args += ['--choice', f'{key}={description}']
    try:
        out = subprocess.run(args, input=text, capture_output=True, text=True, encoding='utf-8', timeout=120,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
    except (OSError, subprocess.TimeoutExpired):  # sin Ollama o sin Laya: no decide (lo vago va a la charla)
        return None, 0
    match = re.search(r'(\S+)\s+(\d+)%', out or '')
    return (match.group(1), int(match.group(2))) if match else (None, 0)


def secret(name):
    """Una clave guardada en las variables de entorno de Windows (nunca escrita en el código)."""
    if value := os.environ.get(name):
        return value
    try:  # recién guardada con SetEnvironmentVariable: todavía no está en este proceso, sí en el registro
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as env:
            return winreg.QueryValueEx(env, name)[0]
    except OSError:
        return None


def save_secret(name, value):
    """Guarda una clave como variable de entorno de tu usuario (como SetEnvironmentVariable 'User') y avisa a Windows."""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment', 0, winreg.KEY_SET_VALUE) as env:
        winreg.SetValueEx(env, name, 0, winreg.REG_SZ, value)
    os.environ[name] = value
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, 'Environment', 2, 1000, None)  # WM_SETTINGCHANGE


def delete_secret(name):
    """Borra una clave de las variables de Windows (por ejemplo, para desvincular Telegram)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment', 0, winreg.KEY_SET_VALUE) as env:
            winreg.DeleteValue(env, name)
    except OSError:  # ya no estaba
        pass
    os.environ.pop(name, None)
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, 'Environment', 2, 1000, None)


# Las plataformas en la nube, en orden: si una falla o se queda sin cupo, Node pasa sola a la siguiente.
# Si fallan todas (o no hay internet), decide con las reglas y Laya y charla con llama3.2 local.
PROVIDERS = [
    {'name': 'Groq', 'key': 'GROQ_API_KEY', 'model': 'openai/gpt-oss-120b',
     'url': 'https://api.groq.com/openai/v1/chat/completions', 'extra': {'reasoning_effort': 'low'}},
    {'name': 'Gemini', 'key': 'GEMINI_API_KEY', 'model': 'gemini-flash-lite-latest', 'vision': ['gemini-3.5-flash', 'gemini-flash-lite-latest'],
     'url': 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
     'extra': {'reasoning_effort': 'low'}},
    {'name': 'OpenRouter', 'key': 'OPENROUTER_API_KEY', 'model': 'recursive/flint-v1.0:free',  # uno que no entrena
     'url': 'https://openrouter.ai/api/v1/chat/completions',
     'extra': {'provider': {'data_collection': 'deny'}}},  # solo modelos que no entrenan con lo que les mandas
    {'name': 'Cloudflare', 'key': 'CLOUDFLARE_API_TOKEN', 'model': '@cf/mistralai/mistral-small-3.1-24b-instruct',
     'url': 'https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1/chat/completions', 'extra': {}},
]
BUILT_IN = [dict(provider) for provider in PROVIDERS]  # las de fábrica, para volver a ellas al quitar un cambio tuyo
# Las que agregas o cambias desde el menú de la bandeja (sin claves: esas van a las variables de Windows).
CUSTOM = HERE / 'proveedores.json'


def load_providers():
    """Las de fábrica más las tuyas (una tuya con el mismo nombre reemplaza a la de fábrica, por ejemplo otro modelo)."""
    mine = json.loads(CUSTOM.read_text(encoding='utf-8')) if CUSTOM.exists() else []
    names = {provider['name'] for provider in mine}
    PROVIDERS[:] = [provider for provider in BUILT_IN if provider['name'] not in names] + mine


load_providers()
STATE = {'current': None, 'headers': {}, 'paused': {}}  # la última plataforma usada, sus límites y las que están en pausa
COUNTS = HERE / 'uso.json'  # cuántas consultas y tokens gastó Node hoy en cada plataforma, para /usage
CLOUD_EARS = saved('cloud_ears', True)  # True: tu voz se transcribe en Groq (~0,3 s); False: solo Whisper local (~3 s, nada sale de la PC)


def count(name, tokens):
    today = f'{datetime.now():%Y-%m-%d}'  # shortcut: día local; cada plataforma reinicia su día a otra hora
    data = json.loads(COUNTS.read_text(encoding='utf-8')) if COUNTS.exists() else {}
    if data.get('date') != today:
        data = {'date': today}
    used = data.setdefault(name, {'requests': 0, 'tokens': 0})
    used['requests'] += 1
    used['tokens'] += tokens
    COUNTS.write_text(json.dumps(data), encoding='utf-8')


def counted(name):
    data = json.loads(COUNTS.read_text(encoding='utf-8')) if COUNTS.exists() else {}
    return data.get(name, {'requests': 0, 'tokens': 0}) if data.get('date') == f'{datetime.now():%Y-%m-%d}' else \
        {'requests': 0, 'tokens': 0}


def pause(name, seconds):
    STATE['paused'][name] = time.time() + seconds


def paused(name):
    return STATE['paused'].get(name, 0) > time.time()


def cloud(messages, vision=False, wait=8, only=None, **extra):
    """Pregunta a la primera plataforma disponible y devuelve su mensaje. Si no responde ninguna, lanza ConnectionError.
    vision: los mensajes traen una imagen (prueba los modelos 'vision' de cada plataforma, en orden);
    wait: segundos de espera; only: solo estas plataformas (por ejemplo ('Gemini',) cuando hace falta precisión)."""
    if OPSEC['on']:  # /opsec: nada sale de la PC (quien llama sigue con lo local: reglas, Laya y llama3.2)
        raise ConnectionError('modo /opsec: la nube está apagada')
    choices = [(provider, model_) for provider in PROVIDERS if not only or provider['name'] in only
               for model_ in (provider.get('vision', []) if vision else [provider['model']])]
    for provider, model_ in choices:
        key = secret(provider['key']) if provider.get('key') else 'sin-clave'  # Ollama y otras locales no piden clave
        slot = provider['name'] + (f' {model_}' if vision else '')  # pausa aparte: si falla la visión, la charla sigue
        if not key or paused(slot) or provider['name'] in saved('apagados', []):  # apagada desde la bandeja
            continue
        url = provider['url'].format(account=secret('CLOUDFLARE_ACCOUNT_ID'))
        body = json.dumps({'model': model_, 'temperature': TEMPERATURE,
                           'max_tokens': 300,
                           'messages': messages, **provider.get('extra', {}), **extra}).encode()
        request = urllib.request.Request(url, body, {
            'Content-Type': 'application/json', 'Authorization': f'Bearer {key}', 'User-Agent': 'NodeAssistant'})
        try:
            with urllib.request.urlopen(request, timeout=wait) as response:
                headers, answer = response.headers, json.load(response)
        except urllib.error.HTTPError as error:
            # 429 = sin cupo y 5xx = saturada: en pausa lo que pida la plataforma (o 1 min).
            # Otro error (clave o modelo que ya no existe): 5 min.
            busy = error.code == 429 or error.code >= 500
            pause(slot, float(error.headers.get('retry-after') or 60) if busy else 300)
            continue
        except (OSError, ValueError):  # sin conexión, tardó demasiado o respuesta rara
            pause(slot, 30)
            continue
        STATE.update(current=provider, headers={name.lower(): value for name, value in headers.items()})
        count(provider['name'], (answer.get('usage') or {}).get('total_tokens', 0))
        return answer['choices'][0]['message']
    raise ConnectionError('ninguna plataforma en la nube respondió')


# La memoria vive en tu bóveda de Obsidian (VAULT, arriba): la puedes leer y corregir a mano. Sin bóveda, no recuerda.
NOTES = VAULT / 'Node Assistant' if VAULT else None
FACTS = NOTES / 'Memoria.md' if VAULT else None  # lo que Node sabe de ti, para siempre
HISTORY = []                          # los últimos turnos de esta charla ("¿y eso qué es?", "bájale más")


def memory():
    try:
        return FACTS.read_text(encoding='utf-8').strip() if FACTS else ''
    except OSError:  # el disco no está conectado o todavía no hay memoria
        return ''


def remember(fact):
    if not VAULT:
        return t('No tengo memoria activada: la puedes prender con /setup.')
    try:
        NOTES.mkdir(parents=True, exist_ok=True)
        with FACTS.open('a', encoding='utf-8') as notes:
            notes.write(f'- {fact}\n')
        return t('Listo, lo recuerdo.')
    except OSError:
        return t('No pude guardarlo: ¿está conectada la carpeta de tu bóveda?')


def log(said, reply):
    """Suma el turno a la charla de esta sesión y al diario de hoy en Obsidian."""
    HISTORY[:] = (HISTORY + [{'role': 'user', 'content': said}, {'role': 'assistant', 'content': reply}])[-6:]
    if not VAULT:
        return
    try:
        (NOTES / 'Conversaciones').mkdir(parents=True, exist_ok=True)
        with (NOTES / 'Conversaciones' / f'{datetime.now():%Y-%m-%d}.md').open('a', encoding='utf-8') as diary:
            diary.write(f'**{datetime.now():%H:%M} Tú:** {said}\n**Node:** {reply}\n\n')
    except OSError:  # sin el SSD, Node sigue funcionando: solo no guarda el diario
        pass


def system(extra=''):
    facts, now = memory(), datetime.now()
    today = f' Hoy es {DAYS[now.weekday()]} {now:%Y-%m-%d} y son las {now:%H:%M}.'  # para "el martes a las 10"
    return PERSONA + today + extra + (f'\nLo que sabes de {NAME or "esta persona"} (su memoria, en Obsidian):\n{facts}' if facts else '')


def tool(name, description, /, **params):  # / : un parámetro de la herramienta también puede llamarse name
    return {'type': 'function', 'function': {'name': name, 'description': description, 'parameters': {
        'type': 'object', 'properties': params, 'required': list(params)}}}


# Lo único que la IA puede hacer en la PC: estas acciones fijas, nunca comandos libres de la consola.
# Para enseñarle algo nuevo: suma una herramienta acá y lo que hace en act(). No hay que entrenar nada.
TOOLS = [
    tool('open', 'Abre cualquier app instalada por su nombre de Windows, casi siempre en inglés (notepad, calculator, '
         'settings...). Las favoritas, con para qué sirven: '
         + ', '.join(f'{name} ({use})' for name, use in FAVORITES.items()), name={'type': 'string'}),
    tool('spotify', 'Busca canciones, artistas o discos en la app de Spotify. query vacío solo abre Spotify.',
         query={'type': 'string'}, play={'type': 'boolean', 'description': 'true si pidió reproducir o poner'}),
    tool('youtube', 'Busca videos en YouTube en el navegador. query vacío solo abre YouTube.',
         query={'type': 'string'}, play={'type': 'boolean', 'description': 'true si pidió reproducir o poner'}),
    tool('web_search', 'Busca algo en Google en el navegador.', query={'type': 'string'}),
    tool('volume', 'Sube, baja o silencia el volumen.', direction={'type': 'string', 'enum': ['up', 'down', 'mute']}),
    tool('media', 'Controla lo que está sonando: pausar o reanudar, siguiente, anterior.',
         command={'type': 'string', 'enum': ['play_pause', 'next', 'previous']}),
    tool('folder', 'Abre una carpeta personal en el Explorador (para saber qué hay adentro, usa files).', name={'type': 'string', 'enum': sorted(set(FOLDERS.values()))}),
    tool('screenshot', 'Empieza una captura de pantalla.'),
    tool('lock', 'Bloquea la computadora.'),
    tool('time', 'Dice la hora y la fecha de hoy.'),
    tool('colors', 'Cambia los colores de la cápsula de Node. request es lo que pidió el usuario, tal cual: '
         'nombres de colores ("rojo, azul y verde"), un combo (node, siri, fuego, oceano, bosque, atardecer, neon, aurora, '
         'hielo) o una idea ("colores de atardecer").', request={'type': 'string'}),
    tool('remember', 'Guarda para siempre un dato que el usuario te pide recordar, o algo suyo que conviene '
         'recordar (gustos, nombres, planes). Escríbelo como una frase corta en tercera persona.',
         fact={'type': 'string'}),
]
ARGUMENT = {'web_search': 'query', 'volume': 'direction', 'media': 'command', 'folder': 'name', 'remember': 'fact', 'colors': 'request'}
MANY = re.compile(r'\b(?:y|e|luego|despu[eé]s|tambi[eé]n|adem[aá]s)\b')


SAVE_QUOTA = True  # True: a la IA le llegan solo las herramientas que tienen que ver con lo pedido (gasta mucho menos)
TOOL_HINTS = {}    # herramienta -> palabras que la delatan (sin tildes); sin pistas, va siempre


def hint(name, words):
    TOOL_HINTS[name] = re.compile(words)


def plain(text):
    return unicodedata.normalize('NFD', text.lower()).encode('ascii', 'ignore').decode()


def pick_tools(text):
    """Las herramientas para esta orden (sin las que apagaste en /settings → Herramientas). Mira también lo anterior
    que dijiste ("y bájale más")."""
    off = set(saved('tools_off', []))
    tools = [tool_ for tool_ in TOOLS if tool_['function']['name'] not in off]
    if not SAVE_QUOTA:
        return tools
    said = plain(text + ' ' + ' '.join(turn['content'] for turn in HISTORY[-2:] if turn['role'] == 'user'))
    return [tool_ for tool_ in tools if (found := TOOL_HINTS.get(tool_['function']['name'])) is None
            or found.search(said)]


for name, words in {
        'spotify': r'spotify|cancion|musica|tema|artista|disco|album|playlist',
        'youtube': r'youtube|video', 'web_search': r'busc|googl|internet|que es|quien es|quien fue|investig',
        'volume': r'volumen|sonido|silenci|mute|fuerte|bajit|baja|subi|sube',
        'media': r'pausa|segui|siguiente|anterior|cancion|tema|reanud|play|para la musica',
        'folder': r'carpeta|descarga|documento|escritorio|foto|imagen|video|musica',
        'screenshot': r'captura|pantallazo|screenshot|recorte', 'lock': r'bloque',
        'time': r'hora|dia|fecha|que dia', 'colors': r'color|feeling',
        'remember': r'recorda|acordate|acuerdate|recuerda que|no te olvides|no olvides|guarda que|sabe que'}.items():
    hint(name, words)


# Skills: instrucciones en texto (skills/*.md) que le enseñan a Node cómo y cuándo usar lo que ya sabe hacer: rutinas
# ("modo trabajo"), estilos ("corrígeme el inglés") o datos tuyos. No son código. Arriba de cada una, entre ---:
# nombre, descripcion, palabras (las que la activan, separadas por comas) y siempre (true: va en todas las charlas).
SKILLS_DIR = HERE / 'skills'


def load_skills(every=False):
    """Las skills de skills/ (sin las que apagaste en /settings → Skills, salvo con every=True)."""
    off, found = set(saved('skills_off', [])), []
    for path in sorted(SKILLS_DIR.glob('*.md')) if SKILLS_DIR.exists() else []:
        if path.stem in off and not every:
            continue
        text = path.read_text(encoding='utf-8')
        match = re.match(r'---\s*\n(.*?)\n---\s*\n?(.*)', text, re.S)
        # "clave: valor" por línea, cortando en el primer ":" (así una descripción con ":" no rompe nada, como en YAML)
        meta = {key.strip().lower(): value.strip().strip('"\'') for key, _, value in
                (line.partition(':') for line in (match[1] if match else '').splitlines()) if value.strip()}
        words = str(meta.get('palabras') or meta.get('words') or '')
        found.append({'id': path.stem, 'path': path, 'name': str(meta.get('nombre') or meta.get('name') or path.stem),
                      'about': str(meta.get('descripcion') or meta.get('description') or ''),
                      'words': [plain(word).strip() for word in words.split(',') if plain(word).strip()],
                      'always': (meta.get('siempre') or meta.get('always') or '').lower() in ('true', 'si', 'sí', 'yes'),
                      'body': (match[2] if match else text).strip()[:3000]})
    return found


def skills_for(text):
    """Las skills que tienen que ver con lo que dijiste (o las que van siempre)."""
    said = plain(text)
    return [skill for skill in load_skills() if skill['always'] or any(word in said for word in skill['words'])]


QUICK = {'open', 'spotify', 'youtube', 'web_search', 'volume', 'media', 'folder', 'screenshot', 'lock', 'colors',
         'time', 'remember'}  # sin datos que pensar: con una sola orden de estas, Node contesta sin otra vuelta (más rápido)
ROUNDS = 6  # vueltas máximas: buscar, mirar el resultado, decidir el paso siguiente…


def step_for(call):
    """Lo que pidió la IA (una llamada a herramienta) como (acción, detalle) para act()."""
    action, args = call['function']['name'], json.loads(call['function']['arguments'] or '{}')
    if action == 'open':
        app = find_app(args.get('name', ''))
        return ('open', app) if app else ('say', t('No encontré la app {app}.', app=args.get('name', '')))
    if action in ('spotify', 'youtube'):
        query = args.get('query', '').strip()
        return action, (query, bool(query and args.get('play')))
    if action in ARGUMENT:
        return action, args.get(ARGUMENT[action])
    if action in ('screenshot', 'lock', 'time'):
        return action, None
    return action, args


def agent(text, mood=lambda _: None, where='pc'):
    """La IA decide y Node hace: cada herramienta corre en el momento y la IA ve su resultado, así puede encadenar
    pasos ("busca el informe y ábrelo") y contestar con lo que pasó de verdad. Devuelve (respuesta, pasos)."""
    skills = skills_for(text)
    guide = ''.join(f'\n\nSkill "{skill["name"]}" (síguela si corresponde a lo que pidió):\n{skill["body"]}'
                    for skill in skills)
    messages = [{'role': 'system', 'content': system(
        ' Si te piden hacer algo en la computadora, usa las herramientas: cada una te devuelve qué pasó, y con eso '
        'decides el paso siguiente o le respondes. Cuando termines, responde en 1 a 3 frases con lo que hiciste o '
        'encontraste, sin repetir lo que ya se ve en pantalla.' + guide)},
                *HISTORY, {'role': 'user', 'content': text}]
    # Las herramientas que nombran las skills también viajan (para el ahorro de cupo cuentan como si lo hubieras dicho).
    tools = pick_tools(text + ' ' + ' '.join(skill['body'] for skill in skills))
    steps, results = [], []
    for round_ in range(ROUNDS):
        try:
            message = cloud(messages, tools=tools)
        except ConnectionError:
            if not steps:
                raise  # sin nada hecho: handle() sigue con las reglas y Laya
            return ' '.join(results), steps  # se cortó la nube a mitad de camino: lo que ya se hizo
        calls = message.get('tool_calls') or []
        if not calls:
            return tidy(message.get('content')) or ' '.join(results), steps or [('say', tidy(message.get('content')))]
        messages.append({'role': 'assistant', 'content': message.get('content') or '', 'tool_calls': calls})
        for call in calls:
            action, detail = step_for(call)
            try:
                result = act(action, detail, mood, where) or t('Listo.')
            except Exception as error:  # que la IA se entere del error y decida (avisar, probar otra cosa)
                result = t('Error: {error}', error=error)
            steps.append((action, detail))
            results.append(result)
            messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': str(result)[:3000]})
        quick = all(call['function']['name'] in QUICK for call in calls)
        asked = [skill for skill in skills if not skill['always']]  # las de estilo (siempre) no piden otra vuelta
        if round_ == 0 and quick and not asked and not MANY.search(text.lower()):
            return ' '.join(results), steps  # una orden simple: la confirmación de la herramienta alcanza
    return ' '.join(results), steps


def at(moment):
    return f'{moment.astimezone():%H:%M}'


def usage():
    """/usage: plataforma y modelo actuales, cuánto queda de su plan gratis y cuándo se recupera."""
    if OPSEC['on']:
        return t('Modo /opsec: Node no usa la nube, así que no gasta cupo. Todo corre en tu PC con llama3.2.')
    if not STATE['current']:  # recién abierto: una consulta mínima para saber cuál responde y leer sus límites
        try:
            cloud([{'role': 'user', 'content': 'hola'}], max_tokens=5)
        except ConnectionError:
            return t('Ninguna plataforma en la nube responde (sin claves o sin internet): Node usa llama3.2 local.')
    provider, headers = STATE['current'], STATE['headers']
    name = provider['name']
    used = counted(name)
    lines = [t('Plataforma: {name}, modelo {model}. Plan gratis: no cobra, solo pone límites.', name=name,
               model=provider['model']),
             t('Hoy Node le hizo {requests} consultas y gastó {tokens} tokens (pedazos de palabra).', **used)]

    def when(value):  # "8m38.4s" o "547ms" -> "a las 18:42 (en 9 min)" o "en 1 s"
        units = {'h': 3600, 'm': 60, 's': 1, 'ms': 0.001}
        seconds = sum(float(n) * units[u] for n, u in re.findall(r'([\d.]+)(ms|h|m|s)', value))
        if seconds < 60:
            return t('en {dato} s', dato=max(1, round(seconds)))
        return t('a las {dato} (en {dato2} min)', dato=format(datetime.fromtimestamp(time.time() + seconds), '%H:%M'), dato2=round(seconds / 60))

    midnight_utc = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    if 'x-ratelimit-remaining-requests' in headers:
        h = lambda field: headers.get(f'x-ratelimit-{field}', '?')
        lines.append(t('Consultas: te quedan {dato} de {dato2} por día; se llenan de nuevo {dato3}.', dato=h('remaining-requests'), dato2=h('limit-requests'), dato3=when(h('reset-requests'))))
        if 'x-ratelimit-remaining-tokens' in headers:
            lines.append(t('Tokens: te quedan {dato} de {dato2} por minuto; se llenan {dato3}.', dato=h('remaining-tokens'), dato2=h('limit-tokens'), dato3=when(h('reset-tokens'))))
    if name == 'OpenRouter':
        request = urllib.request.Request('https://openrouter.ai/api/v1/key', headers={
            'Authorization': f"Bearer {secret(provider['key'])}", 'User-Agent': 'NodeAssistant'})
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                key = json.load(response)['data']
            lines.append(t('Créditos gastados: {dato} dólares', dato=key.get('usage', 0))
                         + (t('; te quedan {limit_remaining}.', limit_remaining=key['limit_remaining']) if key.get('limit_remaining') is not None else '.'))
        except (OSError, ValueError, KeyError):
            pass
        lines.append(t('Modelos gratis: 20 consultas por minuto y 50 por día (1000 si cargaste 10 dólares de créditos). El día se reinicia a las {dato}.', dato=at(midnight_utc)))
    elif name == 'Gemini':
        # shortcut: medianoche del Pacífico como UTC-8 (en verano es UTC-7, una hora antes)
        lines.append(t('Google no informa por API cuánto te queda: los límites exactos de tu clave están en Google AI Studio, en Uso. El día se reinicia a las {dato}.', dato=at(midnight_utc + timedelta(hours=8))))
    elif name == 'Cloudflare':
        lines.append(t('Plan gratis: 10.000 neuronas por día; lo gastado exacto está en el panel de Cloudflare, en Workers AI. El día se reinicia a las {dato}.', dato=at(midnight_utc)))
    for other in PROVIDERS:
        if paused(other['name']):
            lines.append(t('{name} está en pausa hasta las {dato} (sin cupo o con error).', name=other['name'], dato=format(datetime.fromtimestamp(STATE['paused'][other['name']]), '%H:%M')))
    backups = [p['name'] for p in PROVIDERS if p is not provider and secret(p['key'])]
    lines.append(t('Si se acaba, sigue con: {dato}.', dato=', '.join(backups + ['llama3.2 local'])))
    return '\n'.join(lines)


def tidy(answer):
    answer = (answer or '').strip()
    # "149\u202f600\u202f000" -> "149600000": la voz lee el número entero y no tres sueltos
    return re.sub(r'(?<=\d)[\u202f\u00a0](?=\d)', '', answer).replace('\u202f', ' ').replace('\u00a0', ' ')


def chat_local(text):
    # Sin num_ctx, Ollama reserva el contexto máximo del modelo (~12 GB de memoria) y falla.
    body = json.dumps({'model': CHAT, 'stream': False, 'keep_alive': KEEP,
                       'options': {'num_ctx': 4096, 'temperature': TEMPERATURE}, 'messages': [
                           {'role': 'system', 'content': system()}, *HISTORY, {'role': 'user', 'content': text}]}).encode()
    request = urllib.request.Request('http://localhost:11434/api/chat', body, {'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.load(response)['message']['content'].strip()
    except (OSError, ValueError, KeyError):  # sin Ollama o sin ese modelo
        return (t('No tengo ninguna IA disponible ahora: ni en la nube ni en tu PC. Escribe /setup para configurar un proveedor gratis o descargar un modelo local.'))


def screenshot():
    """Toda la pantalla (todos los monitores) como imagen numpy RGB, con la API de Windows (sin instalar nada)."""
    user32, gdi32 = gdi()
    left, top, width, height = (user32.GetSystemMetrics(code) for code in (76, 77, 78, 79))  # escritorio virtual
    gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
    gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi32.BitBlt.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 4 + [ctypes.c_void_p] + [ctypes.c_int] * 2 + [wintypes.DWORD]
    gdi32.GetDIBits.argtypes = [ctypes.c_void_p] * 2 + [wintypes.UINT] * 2 + [ctypes.c_void_p] * 2 + [wintypes.UINT]
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    screen = user32.GetDC(None)
    memory = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateCompatibleBitmap(screen, width, height)
    gdi32.SelectObject(memory, bitmap)
    gdi32.BitBlt(memory, 0, 0, width, height, screen, left, top, 0x00CC0020 | 0x40000000)  # SRCCOPY | CAPTUREBLT
    header = struct.pack('<IiiHHIIiiII', 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0)  # de arriba hacia abajo
    info, pixels = ctypes.create_string_buffer(header, 44), ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(memory, bitmap, 0, height, pixels, info, 0)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory)
    user32.ReleaseDC(None, screen)
    return np.frombuffer(pixels, np.uint8).reshape(height, width, 4)[..., 2::-1]  # BGRA -> RGB


def png(rgb):
    """Una imagen numpy RGB como archivo PNG (sin instalar nada)."""
    height, width = rgb.shape[:2]
    chunk = lambda kind, data: struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    raw = b''.join(b'\x00' + row.tobytes() for row in np.ascontiguousarray(rgb))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def multipart(fields, filename, data, mime, field='file'):
    """Un formulario con un archivo adjunto (para Groq y Telegram). Devuelve (cuerpo, Content-Type)."""
    boundary = f'NodeAssistant{time.time_ns()}'
    body = b''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
                    for name, value in fields.items())
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
             f'Content-Type: {mime}\r\n\r\n').encode() + data + f'\r\n--{boundary}--\r\n'.encode()
    return body, f'multipart/form-data; boundary={boundary}'


def transcribe(audio, filename='voz.wav'):
    """Groq transcribe en ~0,3 s y entiende mejor; sin clave, sin internet o con CLOUD_EARS = False, Whisper local.
    audio: lo grabado por el micrófono (numpy) o un archivo de audio en bytes (los audios de Telegram)."""
    if isinstance(audio, np.ndarray):
        wav = io.BytesIO()
        with wave.open(wav, 'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(RATE)
            out.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        data = wav.getvalue()
    else:
        data = audio
    if CLOUD_EARS and not OPSEC['on'] and (key := secret('GROQ_API_KEY')) and not paused('Groq voz'):
        body, kind = multipart({'model': 'whisper-large-v3-turbo', 'language': LANGUAGE, 'response_format': 'text'},
                               filename, data, 'application/octet-stream')
        request = urllib.request.Request('https://api.groq.com/openai/v1/audio/transcriptions', body, {
            'Content-Type': kind, 'Authorization': f'Bearer {key}', 'User-Agent': 'NodeAssistant'})
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                return response.read().decode('utf-8').strip()
        except OSError:  # sin cupo o sin internet (HTTPError también es OSError): un minuto con Whisper local
            pause('Groq voz', 60)
    segments, _ = model('ears').transcribe(audio if isinstance(audio, np.ndarray) else io.BytesIO(data), language=LANGUAGE)
    return ' '.join(segment.text for segment in segments).strip()


_models = {}
LEVEL = {'now': 0.0, 'live': False}  # volumen del micrófono (0 a 1) y si ya está escuchando de verdad


def whisper_ready():
    """Si el modelo de Whisper ya está descargado (la primera vez baja ~460 MB)."""
    return (Path.home() / '.cache' / 'huggingface' / 'hub' / f'models--Systran--faster-whisper-{HEARING}').exists()


def model(name):
    """Carga Whisper y la voz una sola vez (la primera carga tarda unos segundos)."""
    if name not in _models:
        if name == 'ears':
            _models[name] = WhisperModel(HEARING, device='cpu', compute_type='int8')
        elif name == 'kokoro':  # solo si la elegiste: no hace falta tenerla instalada
            import onnxruntime
            from kokoro_onnx import Kokoro
            # 4 hilos: casi igual de rápido que todos con la PC fresca, y 2,5 veces más rápido cuando la laptop se
            # calienta y baja la velocidad (con todos los núcleos, los lentos frenan a los rápidos). Medido.
            options = onnxruntime.SessionOptions()
            options.intra_op_num_threads = 4
            session = onnxruntime.InferenceSession(str(KOKORO_DIR / 'kokoro-v1.0.int8.onnx'), options,
                                                   providers=['CPUExecutionProvider'])
            _models[name] = Kokoro.from_session(session, str(KOKORO_DIR / 'voices-v1.0.bin'))
            _models[name].create('Hola.', voice=kokoro_voices_all(_models[name])[0], lang='es')  # la primera es lenta
        else:
            _models[name] = PiperVoice.load(VOICE)
    return _models[name]


NOISE = {'level': 0.0}  # el ruido del ambiente medido en la grabación anterior (la primera vez, umbral mínimo)


def microphones():
    """Los micrófonos de la PC, por nombre (los de MME: uno por aparato, con el nombre que muestra Windows)."""
    mme = next((i for i, api in enumerate(sd.query_hostapis()) if api['name'] == 'MME'), 0)
    return [d['name'] for d in sd.query_devices() if d['max_input_channels'] > 0 and d['hostapi'] == mme
            and 'Mapper' not in d['name']]


def mic_device():
    """El micrófono elegido en /settings (por su número de ahora: cambia al conectar cosas), o None = el de Windows."""
    name = saved('mic_device')
    if name:
        for index, device in enumerate(sd.query_devices()):
            if device['max_input_channels'] > 0 and device['name'] == name:
                return index
    return None  # el predeterminado de Windows (o el elegido no está conectado ahora)


class Mic:
    """El micrófono siempre abierto (MIC['always']). Guarda en memoria solo el último medio segundo, que se pisa
    todo el tiempo: nada se graba en disco ni sale de la PC hasta que aprietas el atajo. Gasta ~0,1 % de procesador."""

    def __init__(self):
        self.recent, self.queue, self.lock = collections.deque(maxlen=5), None, threading.Lock()
        self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype='float32', blocksize=RATE // 10,
                                     device=mic_device(),
                                     callback=self.heard)
        self.stream.start()

    def heard(self, data, frames, moment, status):
        block = data[:, 0].copy()
        with self.lock:
            self.recent.append(block)
            if self.queue is not None:
                self.queue.put(block)

    def start(self, before=3):
        """Empieza a grabar con los últimos `before` bloques (0,3 s): lo que dijiste mientras apretabas el atajo."""
        with self.lock:
            self.queue = queue.Queue()
            earlier = list(self.recent)[-before:]
        return earlier

    def stop(self):
        with self.lock:
            self.queue = None


# always: el micrófono queda abierto y capta desde que aprietas el atajo (False: se abre al usarlo; /micavailtogg)
MIC = {'open': None, 'off': saved('mic_off'), 'always': saved('mic_always', True)}
OPSEC = {'on': saved('opsec')}  # /opsec: nada sale de la PC (IA, voz y visión solo locales; Telegram en pausa)


def opsec_toggle():
    """/opsec: prende o apaga el modo en que nada sale de tu PC."""
    OPSEC['on'] = not OPSEC['on']
    save('opsec', OPSEC['on'])
    if OPSEC['on']:
        return (t('Modo /opsec prendido: nada sale de tu PC. Charlo con llama3.2 y te entiendo con Whisper local (más lento). Visión, mouse, clima, mails, GitHub, Discord y Telegram quedan en pausa. /opsec de nuevo lo apaga.'))
    return t('Modo /opsec apagado: vuelvo a usar la nube (más rápido y con todas las funciones).')


def mic_ready():
    """Abre o cierra el micrófono permanente según los ajustes."""
    if MIC['always'] and not MIC['off']:
        if not MIC['open']:
            try:
                MIC['open'] = Mic()
            except Exception:  # sin micrófono: se abre al usarlo
                pass
    elif MIC['open']:
        MIC['open'].stream.close()  # Windows deja de mostrar el micrófono en uso
        MIC['open'] = None


def mic_toggle():
    """/mictoggle: apaga el micrófono del todo (modo solo texto) o lo vuelve a prender."""
    MIC['off'] = not MIC['off']
    mic_ready()
    save('mic_off', MIC['off'])
    if MIC['off']:
        return t('Micrófono apagado: modo solo texto. Ctrl+Alt+N abre la cápsula para escribir. /mictoggle lo vuelve a prender.')
    return t('Micrófono prendido: Ctrl+Alt+N vuelve a escucharte.')


def mic_avail_toggle():
    """/micavailtogg: micrófono siempre abierto (capta al instante) o solo mientras usas Ctrl+Alt+N."""
    MIC['always'] = not MIC['always']
    mic_ready()
    save('mic_always', MIC['always'])
    off = t(' (ahora está apagado con /mictoggle; esto vale cuando lo prendas)') if MIC['off'] else ''
    if MIC['always']:
        return t('Micrófono siempre listo: capta desde que aprietas Ctrl+Alt+N, sin perder el principio. Queda abierto (Windows muestra el ícono del micrófono), pero no graba ni manda nada hasta el atajo.{off}', off=off)
    return t('Micrófono solo al usarlo: se abre cuando aprietas Ctrl+Alt+N y se cierra al terminar (tarda unas décimas en arrancar y suena un bip).{off}', off=off)


@contextlib.contextmanager
def microphone():
    """Devuelve (lo de antes de apretar el atajo, función que lee el próximo bloque de 0,1 s)."""
    mic = MIC['open']
    if mic and not mic.stream.active:  # se desconectó o cambió: lo vuelve a abrir
        try:
            mic = MIC['open'] = Mic()
        except Exception:
            mic = MIC['open'] = None
    if mic:
        earlier = mic.start()
        try:
            yield earlier, lambda: mic.queue.get(timeout=2)
        finally:
            mic.stop()
    else:
        with sd.InputStream(samplerate=RATE, channels=1, dtype='float32', device=mic_device()) as stream:
            yield [], lambda: stream.read(RATE // 10)[0][:, 0]


def record(max_seconds=10, wait_seconds=5, pause=0.7):
    """Graba desde el primer instante hasta que hagas una pausa de `pause` segundos. Devuelve None si no hablaste.
    Cuando el micrófono ya capta de verdad, pone LEVEL['live'] (el destello del orbe)."""
    blocks, quiet, heard = [], 0.0, False  # bloques de 0,1 s
    # Sin tirar audio para medir el ruido: si ya estás hablando cuando abre el micrófono, también se graba.
    threshold = max(0.01, NOISE['level'] * 3)
    volumes = []
    start = time.perf_counter()
    with microphone() as (earlier, read):
        warm = bool(earlier)  # el micrófono siempre abierto ya capta: listo desde el primer bloque
        blocks += earlier  # se graban, pero no cuentan como "hablaste": así el clic del teclado no lo dispara
        for _ in range(max_seconds * 10):
            block = read()
            blocks.append(block)
            volume = float(np.sqrt(np.mean(block ** 2)))
            # Recién abierto, el micrófono entrega silencio un rato (MIC_WARMUP); si ya llega tu voz, está listo antes.
            if not LEVEL['live'] and (warm or volume > threshold or time.perf_counter() - start >= MIC_WARMUP):
                LEVEL['live'] = True
            volumes.append(volume)
            LEVEL['now'] = min(1.0, volume * 12)
            if volume > threshold:
                heard, quiet = True, 0.0
            elif heard:
                quiet += 0.1
                if quiet >= pause:
                    break
            elif len(volumes) >= wait_seconds * 10:
                break
    LEVEL['live'] = False
    # El momento más callado = el ruido del ambiente, para la próxima vez (sin los bloques vacíos del arranque).
    NOISE['level'] = min((v for v in volumes if v > 0), default=NOISE['level'])
    return np.concatenate(blocks) if heard else None


CHIME_PEAK = 0.55  # s desde que empieza el sonido hasta que el sable pasa frente a ti (su punto más alto)
CHIME_LEAD = MIC_WARMUP + 0.05 - CHIME_PEAK  # cuándo largarlo para que el pico caiga con el destello (medido)


def chime(rate=44100, length=1.5, peak=CHIME_PEAK):
    """El sonido de "ya te escucho": un sable láser que pasa cerca, como una moto. Entra suave por la izquierda,
    llega al máximo frente a ti (más agudo al acercarse y más grave al alejarse: el efecto Doppler) y se pierde por
    la derecha. Un zumbido grave con armónicos que brillan solo de cerca, un soplo de aire y un poco de eco.
    Se sintetiza acá (estéreo): no hace falta ningún archivo. Devuelve (muestras x 2 canales, rate)."""
    t = np.arange(int(rate * length)) / rate
    near = 1 / (1 + ((t - peak) / 0.22) ** 2)                 # cercanía: 1 frente a ti, cae como la distancia
    doppler = 1 + 0.11 * np.tanh((peak - t) / 0.12)            # más agudo viniendo, más grave yéndose
    hum = np.zeros_like(t)
    for base, detune in ((92.0, 0.0), (92.0, 0.7), (138.0, -0.4)):  # dos voces que laten + una quinta: el zumbido
        phase = 2 * np.pi * np.cumsum((base + detune) * doppler) / rate
        for n in range(1, 9):                                  # armónicos: de lejos apagado, de cerca brillante
            hum += np.sin(n * phase) * (near ** (0.4 * n)) / n ** 1.3
    shimmer = np.sin(2 * np.pi * np.cumsum(1480 * doppler) / rate) * near ** 3 * 0.12  # el filo del sable
    noise = np.convolve(np.random.default_rng(7).standard_normal(len(t)), np.ones(24) / 24, 'same')
    sound = (hum * 0.55 + shimmer + noise * 0.9 * near ** 1.5) * near ** 1.2
    for delay, gain in ((0.045, 0.22), (0.11, 0.12)):          # un poco de espacio alrededor
        shift = int(delay * rate)
        sound[shift:] += gain * sound[:-shift].copy()
    sound *= np.clip(t / 0.03, 0, 1) * np.clip((t[-1] - t) / 0.15, 0, 1)  # sin chasquidos al empezar ni al terminar
    pan = np.clip(0.5 + 0.5 * np.tanh((t - peak) / 0.16), 0, 1)  # de izquierda a derecha al pasar
    stereo = np.stack([sound * np.cos(pan * np.pi / 2), sound * np.sin(pan * np.pi / 2)], axis=1)
    return (0.4 * stereo / np.abs(stereo).max()).astype(np.float32), rate


CHIME = Path(os.environ.get('TEMP', HERE)) / 'node-assistant-sable.wav'  # si cambias chime(), bórralo


def chime_file():
    """El .wav del sable (lo crea la primera vez). Windows lo reproduce sin frenar la grabación; desde memoria no puede."""
    if not CHIME.exists():
        sound, rate = chime()
        with wave.open(str(CHIME), 'wb') as out:
            out.setnchannels(2)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes((sound * 32767).astype('<i2').tobytes())
    return str(CHIME)


def play_chime():
    winsound.PlaySound(chime_file(), winsound.SND_FILENAME | winsound.SND_ASYNC)


def listen():
    audio = record()
    if audio is None:
        return ''
    return transcribe(audio)


# La voz: Piper (local, liviana), Kokoro (local, más natural) o ElevenLabs (en la nube, la más natural; con clave).
# Se elige en /settings → Voz y micrófono, y se aplica al instante. Si la elegida falla, habla con la que haya.
KOKORO_DIR = HERE / 'voices' / 'kokoro'
KOKORO_FILES = {'kokoro-v1.0.int8.onnx': 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/'
                                         'kokoro-v1.0.int8.onnx',
                'voices-v1.0.bin': 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/'
                                   'voices-v1.0.bin'}
KOKORO_LANGS = {'es': ('es', ('ef_', 'em_')), 'en': ('en-us', ('af_', 'am_', 'bf_', 'bm_')), 'fr': ('fr-fr', ('ff_',)),
                'it': ('it', ('if_', 'im_')), 'pt': ('pt-br', ('pf_', 'pm_'))}  # alemán: Kokoro no lo tiene (Piper)
ELEVEN_MODELS = {'eleven_flash_v2_5': 'Flash v2.5', 'eleven_turbo_v2_5': 'Turbo v2.5',
                 'eleven_multilingual_v2': 'Multilingual v2', 'eleven_v3': 'v3'}


def wav(samples, rate):
    """Muestras (numpy float -1..1, o bytes PCM de 16 bits) como un .wav en memoria, para winsound."""
    data = samples if isinstance(samples, bytes) else (np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(data)
    return buffer.getvalue()


def kokoro_ready():
    return LANGUAGE in KOKORO_LANGS and all((KOKORO_DIR / name).exists() for name in KOKORO_FILES)


def kokoro_voices_all(kokoro):
    return sorted(kokoro.get_voices())


def kokoro_voices():
    """Las voces de Kokoro para tu idioma."""
    prefixes = KOKORO_LANGS.get(LANGUAGE, ('', ()))[1]
    return sorted(v for v in model('kokoro').get_voices() if v.startswith(prefixes)) if kokoro_ready() else []


def pieces(text):
    """El texto en pedazos para hablar: por frases y, si una es larga, por comas. El primero, corto: la voz tarda en
    generarlo según su largo, y es lo que se espera antes de oír algo."""
    parts = []
    for sentence in (part for part in re.split(r'(?<=[.!?…;:])\s+', text) if part.strip()):
        limit = 50 if not parts else 140
        while len(sentence) > limit and (cut := sentence.find(', ', 20, limit + 40)) > 0:
            parts.append(sentence[:cut + 1])
            sentence, limit = sentence[cut + 2:], 140
        parts.append(sentence)
    return parts or [text]


def eleven(sentence):
    """Una frase con ElevenLabs (PCM a 22 kHz, sin decodificar MP3)."""
    model_id = saved('eleven_model', 'eleven_flash_v2_5')
    body = {'text': sentence, 'model_id': model_id, 'voice_settings': {
        'stability': saved('eleven_stability', 0.5), 'similarity_boost': saved('eleven_similarity', 0.75),
        'style': saved('eleven_style', 0.0), 'speed': saved('eleven_speed', 1.0), 'use_speaker_boost': True}}
    if model_id.endswith('v2_5'):  # los rápidos aceptan el idioma (pronuncian mejor)
        body['language_code'] = LANGUAGE
    voice = saved('eleven_voice', 'JBFqnCBsd6RMkjVDRZzb')  # George (de las de fábrica) hasta que elijas otra
    request = urllib.request.Request(
        f'https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=pcm_22050', json.dumps(body).encode(),
        {'xi-api-key': secret('ELEVENLABS_API_KEY'), 'Content-Type': 'application/json', 'User-Agent': 'NodeAssistant'})
    with urllib.request.urlopen(request, timeout=20) as response:
        return wav(response.read(), 22050)


def synthesize(sentence):
    """Una frase como .wav con la voz elegida; si no se puede (sin clave, sin internet, sin modelo), con la siguiente."""
    engine = saved('voice_engine', 'piper')
    if engine == 'elevenlabs' and secret('ELEVENLABS_API_KEY') and not OPSEC['on'] and not paused('ElevenLabs'):
        try:
            return eleven(sentence)
        except (OSError, ValueError):  # sin cupo, sin internet o clave mala: un rato con la voz local
            pause('ElevenLabs', 300)
    if engine in ('kokoro', 'elevenlabs') and kokoro_ready():
        try:
            voices = kokoro_voices()
            voice = saved('kokoro_voice') if saved('kokoro_voice') in voices else voices[0]
            samples, rate = model('kokoro').create(sentence, voice=voice, speed=saved('kokoro_speed', 1.0),
                                                   lang=KOKORO_LANGS[LANGUAGE][0])
            return wav(samples, rate)
        except Exception:  # un error de Kokoro no deja a Node mudo: sigue Piper
            pass
    if VOICE.exists():
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as out:
            model('voice').synthesize_wav(sentence, out)
        return buffer.getvalue()
    return None


def speak(text):
    """Lee el texto en voz alta frase por frase: empieza a hablar con la primera mientras prepara las siguientes, en
    vez de esperar a tener todo listo."""
    if saved('voz_off'):  # voz apagada: solo texto
        return
    text = re.sub(r'[*#_`]', '', text)  # sin los símbolos de formato que llama3.2 a veces agrega
    sentences = pieces(text)
    ready = queue.Queue()

    def make():
        try:
            for sentence in sentences:
                if (sound := synthesize(sentence)) is None:
                    break  # sin ninguna voz todavía (/setup): solo texto
                ready.put(sound)
        finally:
            ready.put(None)  # fin (también si algo falló: que no se quede esperando)

    threading.Thread(target=make, daemon=True).start()
    while (sound := ready.get()) is not None:
        winsound.PlaySound(sound, winsound.SND_MEMORY)


def plan(text):
    """Decide qué hacer con lo que dijo el usuario. Devuelve (acción, detalle), por ejemplo ('open', 'spotify')."""
    said = re.sub(r'[.!?¡¿,]', '', text).lower().strip()
    has = lambda pattern: re.search(pattern, said)
    command = OPEN.match(said)
    if command and (app := find_app(command.group(1))):
        return 'open', app
    for service in ('spotify', 'youtube'):
        if service in said:  # sin nada que buscar ("abre youtube") abre la página o la app
            query = re.sub(r'\s+', ' ', FILLER.sub(' ', said.replace(service, ' '))).strip()
            return service, (query, bool(query and PLAY.search(said)))
    if search := SEARCH.match(said):  # "buscar ... en internet" -> busca solo lo del medio
        return 'web_search', re.sub(r'\s+(?:en|por) (?:internet|google|el navegador|la web)$', '', search.group(1))
    if has(r'b[uú]sca(?:lo|la|me)?\b|en (?:google|internet)'):
        return 'web_search', re.sub(r'\s+', ' ', re.sub(r'b[uú]sca\w*|googlea\w*|en (?:google|internet)', '', said)).strip()
    if has(r'silenci|\bmute\b|sin sonido|quita el sonido'):
        return 'volume', 'mute'
    if has(r'volumen|sonido|m[aá]s fuerte|m[aá]s bajito'):
        return 'volume', 'down' if has(r'\bbaj|disminu|menos|bajito') else 'up'
    if has(r'canci[oó]n|tema|m[uú]sica|video|v[ií]deo|^(?:pausa|reanuda|contin[uú]a|play)\b'):
        if has(r'siguiente|pr[oó]xim|salta|adelant'):
            return 'media', 'next'
        if has(r'anterior|atr[aá]s|vuelve'):
            return 'media', 'previous'
        # "para" solo como orden ("para la música"), no en "pon algo para escuchar"
        if has(r'paus|^para\b|\bpara (?:la|el|esa|ese|esta|este|eso)\b|det[eé]n|reanuda|contin[uú]a|\bplay\b'):
            return 'media', 'play_pause'
        if has(r'canci[oó]n|tema|m[uú]sica') and has(r'\b(?:pon|pone|pon[eé]|reproduc|escuch|quiero)'):
            return 'spotify', ('', False)  # pedir música sin decir cuál: abre Spotify
    if has(r'carpeta|descargas|documentos|escritorio'):
        folder = next((name for word, name in FOLDERS.items() if word in said), None)
        if folder:
            return 'folder', folder
    if has(r'captura|pantallazo|screenshot'):
        return 'screenshot', None
    if has(r'bloque[aá]') and has(r'computadora|\bpc\b|compu|pantalla|sesi[oó]n|equipo'):
        return 'lock', None
    if has(r'qu[eé] hora|hora es|qu[eé] d[ií]a|\bfecha\b'):
        return 'time', None
    # Lo vago: Laya decide si es pedir una app ("quiero jugar", "pon una película") o una pregunta.
    kind, sure = decide('What does the user want?', said, {
        'open': 'open or use an app on the computer', 'chat': 'ask a question or talk'})
    if kind == 'open' and sure >= CONFIDENT:
        # Las opciones de Laya no admiten espacios: "obs studio" viaja como "obs_studio".
        favorite, sure = decide('Which app fits what the user wants?', said,
                                {name.replace(' ', '_'): use for name, use in FAVORITES.items()})
        if favorite and sure >= CONFIDENT and (app := find_app(favorite.replace('_', ' '))):
            return 'open', app
    return 'chat', text


def press(*keys):
    for key in keys:
        ctypes.windll.user32.keybd_event(key, 0, 0, 0)
    for key in reversed(keys):
        ctypes.windll.user32.keybd_event(key, 0, 2, 0)  # 2 = soltar la tecla


def act(action, detail, mood, where='pc'):
    """Hace la acción y devuelve qué decir. where: 'pc' (la cápsula) o el canal desde donde se pidió ('telegram')."""
    if action in saved('tools_off', []):  # también si la pidió una regla sin internet
        return t('Eso lo tengo apagado: lo prendes en /settings → Herramientas.')
    if action in PLUGINS:
        return PLUGINS[action](detail, where)
    if action == 'open':
        os.startfile(APPS[detail])
        return t('Abriendo {detail}.', detail=detail)
    if action == 'spotify':
        query, play = detail
        if not query:
            os.startfile('spotify:')
            return t('Abriendo Spotify.')
        os.startfile('spotify:search:' + urllib.parse.quote(query))
        if play:  # reproducir solo necesita la API de Spotify (ver README); por ahora deja los resultados abiertos
            return t('Te dejé {query} en Spotify. Dale play al primero.', query=query)
        return t('Buscando {query} en Spotify.', query=query)
    if action == 'youtube':
        query, play = detail
        if not query:
            webbrowser.open('https://www.youtube.com')
            return t('Abriendo YouTube.')
        results = 'https://www.youtube.com/results?search_query=' + urllib.parse.quote(query)
        if play:
            request = urllib.request.Request(results, headers={'User-Agent': 'Mozilla/5.0 NodeAssistant'})
            page = urllib.request.urlopen(request, timeout=15).read().decode('utf-8', 'replace')
            if first := re.search(r'"videoId":"([\w-]{11})"', page):
                webbrowser.open(f'https://www.youtube.com/watch?v={first.group(1)}')
                return t('Reproduciendo {query} en YouTube.', query=query)
        webbrowser.open(results)
        return t('Buscando {query} en YouTube.', query=query)
    if action == 'web_search':
        webbrowser.open('https://www.google.com/search?q=' + urllib.parse.quote(detail))
        return t('Buscando {detail}.', detail=detail)
    if action == 'volume':
        for _ in range(1 if detail == 'mute' else 5):  # cada toque sube o baja un 2 %
            press(KEYS[detail])
        return t({'up': 'Subiendo el volumen.', 'down': 'Bajando el volumen.', 'mute': 'Silencio activado o quitado.'}[detail])
    if action == 'media':
        press(KEYS[detail])
        return t({'play_pause': 'Listo.', 'next': 'Siguiente canción.', 'previous': 'Canción anterior.'}[detail])
    if action == 'folder':
        os.startfile(f'shell:{detail}')  # encuentra la carpeta aunque esté movida a OneDrive
        return t('Abriendo la carpeta.')
    if action == 'screenshot':
        if where != 'pc':  # desde el celular: el canal manda la captura de toda la pantalla
            return t('Ahí va la captura.')
        mood('hide')  # que la cápsula no salga en la captura
        time.sleep(0.5)
        press(0x5B, 0x10, 0x53)  # Windows + Shift + S
        return t('Elige qué parte de la pantalla capturar.')
    if action == 'lock':
        ctypes.windll.user32.LockWorkStation()
        return t('Bloqueando la computadora.')
    if action == 'time':
        now = datetime.now()
        return t('Son las {time} del {weekday} {day} de {month}.', time=format(now, '%H:%M'), weekday=DAYS[now.weekday()],
                 day=now.day, month=MONTHS[now.month - 1])
    if action == 'colors':
        return feeling(detail)
    if action == 'remember':
        return remember(detail)
    if action == 'say':  # lo que la IA ya respondió
        return detail
    return chat_local(detail)  # sin nube (sin claves, sin internet o sin cupo): charla llama3.2


def handle(text, mood=lambda _: None, where='pc'):
    """Decide y hace lo pedido (desde la cápsula o desde un canal como Telegram). Devuelve (respuesta, pasos)."""
    for answer in WAITING:  # un plugin esperaba una respuesta ("¿hago clic acá?" -> "sí"): sin pasar por la IA
        if (reply := answer(text, where)) is not None:
            log(text, reply)
            return reply, [('say', reply)]
    try:
        reply, steps = agent(text, mood, where)
    except ConnectionError:  # ninguna nube respondió: decide como antes, con las reglas y Laya
        action, detail = plan(text)
        steps = [(action, detail if action != 'chat' else text)]
        reply = ' '.join(act(action, detail, mood, where) for action, detail in steps)
    log(text, reply)
    return reply, steps


def run(text, show, mood=lambda _: None):
    """Ejecuta la orden. `show` muestra la respuesta; `mood` cambia la animación de la cápsula."""
    try:
        mood('think')
        if (answer := slash(text)) is not None:  # un comando (/help, /usage…): se lee en pantalla, no en voz alta
            show(answer)
            return
        reply, _ = handle(text, mood)
        if not UI.pop('card', False):  # si un plugin mostró una tarjeta (el clima), que el texto no la tape
            show(reply)
        if len(reply) <= QUIET:  # lo largo solo se lee en pantalla (con scroll): escucharlo entero cansa
            mood('speak')
            speak(reply)
    except Exception as error:  # que un fallo no cierre la ventana
        show(t('Error: {error}', error=error))
    finally:
        mood('idle')


def unload():
    """Saca llama3.2 y Laya de la memoria de la placa de video ya (si no, se van solos a los 30 min)."""
    for name in (CHAT, DECIDE):
        try:  # si Ollama está trabado, "ollama stop" espera para siempre: que no trabe el cierre de Node
            subprocess.run(['ollama', 'stop', name], capture_output=True, timeout=8,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (subprocess.TimeoutExpired, OSError):
            pass


def stop_others():
    """Cierra cualquier Node Assistant abierto (para el acceso directo "Cerrar Node Assistant")."""
    script = ("Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
              f"Where-Object {{ $_.CommandLine -match 'node_assistant' -and $_.ProcessId -notin {os.getpid()},{os.getppid()} }} | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    try:  # con tope: que cerrar nunca se cuelgue
        subprocess.run(['powershell', '-NoProfile', '-Command', script], capture_output=True, timeout=20,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (subprocess.TimeoutExpired, OSError):
        pass


def listen_hotkey(on_press):
    """Escucha el atajo en todo Windows. Devuelve False si otro programa (u otro Node Assistant) ya lo usa."""
    user32 = ctypes.windll.user32
    ready, result = threading.Event(), {}

    def loop():  # el atajo pertenece al hilo que lo registra, así que registra y espera en el mismo hilo
        result['ok'] = bool(user32.RegisterHotKey(None, 1, *HOTKEY))
        ready.set()
        message = wintypes.MSG()
        while result['ok'] and user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.message == 0x0312:  # WM_HOTKEY
                on_press()

    threading.Thread(target=loop, daemon=True).start()
    ready.wait()
    return result['ok']


# Estilo Siri / Bixby: vidrio oscuro, un borde de luz de colores que gira y un orbe que respira con tu voz.
# Combos de colores para /feeling: suma los tuyos acá.
COMBOS = {
    'node': ['#2d6bff', '#5cc8ff', '#00e5ff'],  # los de Node: azules (los que trae de fábrica)
    'siri': ['#ff3d81', '#ff8a3d', '#b84dff', '#3d7bff', '#2de2ff'],
    'fuego': ['#ff2a00', '#ff7a00', '#ffc400', '#ff0055'],
    'oceano': ['#00e5ff', '#0077ff', '#00ffb3', '#3d4dff'],
    'bosque': ['#2dff6e', '#00b36b', '#c6ff3d', '#0f8f4f'],
    'atardecer': ['#ff5e62', '#ff9966', '#ffcc33', '#c94bff'],
    'neon': ['#ff00e6', '#00fff0', '#faff00', '#7a00ff'],
    'aurora': ['#00ff9d', '#00c3ff', '#8a5cff', '#ff4fd8'],
    'hielo': ['#ffffff', '#9be7ff', '#4da3ff', '#c9d6ff'],
}
NAMES = {  # los nombres de colores que entiende /feeling (sin tildes)
    'rojo': '#ff2d2d', 'azul': '#2d6bff', 'verde': '#2dff6e', 'amarillo': '#ffe13d', 'naranja': '#ff8a1f',
    'rosa': '#ff5fb0', 'fucsia': '#ff1fa6', 'magenta': '#ff00ff', 'violeta': '#8b5cff', 'morado': '#8b3dff',
    'purpura': '#a03dff', 'lila': '#c39bff', 'celeste': '#5cc8ff', 'cian': '#00e5ff', 'turquesa': '#1fe0c8',
    'blanco': '#ffffff', 'gris': '#9aa3b5', 'plateado': '#cfd6e4', 'dorado': '#ffc83d', 'lima': '#b6ff2d',
    'menta': '#5cffb8', 'coral': '#ff6f61', 'indigo': '#4b3dff', 'esmeralda': '#00c878', 'bordo': '#b0123a',
}
COLORS_FILE = HERE / 'colores.json'  # tus colores elegidos, para que sigan después de reiniciar
GLOW = json.loads(COLORS_FILE.read_text(encoding='utf-8')) if COLORS_FILE.exists() else list(COMBOS['node'])
STYLE = {'version': 0}  # sube cada vez que cambian los colores: la cápsula los vuelve a cargar
TOP, BOTTOM = '#181d36', '#07080f'  # el vidrio, arriba y abajo
SPHERE = '#140b2a'                  # el fondo del orbe
TEXT, HINT = '#ffffff', '#8f97b8'   # lo que escribes y el aviso gris
# La fuente de todos los textos (cambia los nombres por otra fuente instalada para probar).
# Ojo: la Cocogoose de prueba (CocogooseProTrial) tapa los números con "TRIAL ONLY": no sirve para horas ni grados.
TYPE = {'regular': 'Segoe UI Variable Text', 'light': 'Segoe UI Variable Display Light',
        'bold': 'Segoe UI Variable Text Semibold'}
FALLBACK = {'regular': 'Segoe UI Variable Text', 'light': 'Segoe UI Variable Display Light',
            'bold': 'Segoe UI Variable Text Semibold'}
TEXT_SIZE = 0.85  # el tamaño de todas las letras (1 = el de antes): más chico, letras más chicas
FONT_SIZE = 13    # la cápsula (los demás textos tienen su tamaño, y todos se multiplican por TEXT_SIZE)
PAGE_KEYS = {'Down': 1, 'Up': -1, 'Next': 4, 'Prior': -4}  # tecla -> pasos para deslizar el texto largo
HINTS = dict(zip(('idle', 'listen', 'think'), LANGUAGES[LANGUAGE][2]), speak='')  # en el idioma elegido
MOODS = {'idle': (0.45, 0.002), 'listen': (0.9, 0.006), 'think': (1.0, 0.02), 'speak': (0.75, 0.008)}  # brillo, giro


def rgb(color):
    return np.array([int(color[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float32)


def palette(steps=256):
    """Los colores de GLOW mezclados en una ronda continua (el último vuelve al primero)."""
    stops = np.array([rgb(color) for color in GLOW + GLOW[:1]])
    where = np.linspace(0, len(GLOW), steps, endpoint=False)
    index, mix = where.astype(int), (where % 1)[:, None]
    return stops[index] * (1 - mix) + stops[index + 1] * mix


def feeling(request):
    """/feeling: cambia los colores. Acepta un combo ("fuego"), nombres ("rojo azul verde"), códigos (#ff0000)
    o cualquier idea ("atardecer en la playa"), que se la pasa a la IA para que elija los colores."""
    words = unicodedata.normalize('NFD', request.lower()).encode('ascii', 'ignore').decode()
    if not words.strip():
        return (t('Colores actuales: {dato}.\nCombos: {dato2}.\nEjemplos: /feeling rojo azul verde · /feeling #ff0000 #00ff88 · /feeling fuego · /feeling atardecer en la playa. Con /feeling node vuelves a los de fábrica.', dato=' '.join(GLOW), dato2=', '.join(COMBOS)))
    combo = next((COMBOS[name] for name in COMBOS if re.search(rf'\b{name}\b', words)), None)
    colors = combo or [color.lower() for color in re.findall(r'#[0-9a-f]{6}\b', words)] + \
        [NAMES[word] for word in re.findall(r'[a-z]+', words) if word in NAMES]
    if not colors:  # una idea en vez de colores: que la IA los elija
        try:
            answer = cloud([{'role': 'user', 'content': f'Dame de 3 a 5 colores vivos en hexadecimal que representen '
                                                        f'"{request}". Responde solo los códigos, separados por espacios.'}])
            colors = re.findall(r'#[0-9a-fA-F]{6}\b', answer.get('content') or '')[:5]
        except ConnectionError:
            pass
    if not colors:
        return t('No entendí esos colores. Prueba con nombres ({dato}…), códigos #rrggbb o un combo.', dato=', '.join(list(NAMES)[:8]))
    GLOW[:] = [color.lower() for color in colors]
    STYLE['version'] += 1
    COLORS_FILE.write_text(json.dumps(GLOW), encoding='utf-8')
    return t('Listo, colores nuevos: {dato}.', dato=' '.join(GLOW))


class Glass:
    """El fondo de vidrio de un rectángulo redondeado (la cápsula o el panel), dibujado píxel a píxel con numpy."""

    def __init__(self, width, height, radius, scale, margin=0):
        """margin: espacio alrededor para que la luz salga un poco hacia afuera (solo en la cápsula)."""
        y, x = np.mgrid[0:height + 2 * margin, 0:width + 2 * margin].astype(np.float32) + 0.5 - margin
        qx = np.abs(x - width / 2) - (width / 2 - radius)
        qy = np.abs(y - height / 2) - (height / 2 - radius)
        depth = radius - np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) - np.minimum(np.maximum(qx, qy), 0)
        self.cover = np.clip(depth + 0.5, 0, 1)[..., None]  # 1 adentro, 0 afuera y un píxel suave en el borde
        self.turn = np.arctan2(y - height / 2, (x - width / 2) * height / width) / (2 * np.pi) % 1  # vuelta al borde
        inside = depth.clip(0)
        self.light = (np.exp(-inside / (1.4 * scale)) + 0.4 * np.exp(-inside / (10 * scale)))[..., None]  # línea + aura
        outside = np.clip(-depth, 0, None)
        self.halo = (np.exp(-outside / (3.5 * scale)) * np.clip(1 - outside / max(margin, 1), 0, 1))[..., None]
        shade = np.clip(y / height, 0, 1)[..., None]
        self.base = rgb(TOP) * (1 - shade) + rgb(BOTTOM) * shade
        self.colors, self.size = palette(), (width + 2 * margin, height + 2 * margin)

    def frame(self, phase, bright):
        index = ((self.turn + phase) * len(self.colors)).astype(int) % len(self.colors)
        self.ring, self.bright = self.colors[index], bright  # para el brillo de afuera en bgra()
        return self.base + self.ring * self.light * bright

    def bgra(self, image):
        """La imagen con transparencia real por píxel (borde suave sobre cualquier fondo y la luz que sale hacia
        afuera), en el formato de UpdateLayeredWindow: azul, verde, rojo, alfa, con el color ya multiplicado por alfa."""
        glow = self.halo * (1 - self.cover) * min(self.bright, 1.2) * 0.5
        color = image.clip(0, 255) * self.cover + self.ring * glow
        alpha = (self.cover + glow) * 255
        return np.dstack([color[..., ::-1], alpha]).clip(0, 255).astype(np.uint8)


def bgra(image, cover):
    """Una imagen y su cobertura (0 afuera, 1 adentro, a medias en el borde) en el formato de UpdateLayeredWindow."""
    cover = cover if cover.ndim == 3 else cover[..., None]
    return np.dstack([(image.clip(0, 255) * cover)[..., ::-1], cover * 255]).clip(0, 255).astype(np.uint8)


def orb(image, cx, cy, radius, clock, level, tint=1.0, flash=0.0):
    """El orbe: tres luces de colores que giran dentro de una esfera de vidrio; crece con tu voz.
    tint: 0 gris (el micrófono todavía arranca), 1 con sus colores. flash: el destello al empezar a escuchar (1 a 0)."""
    size = radius * (1 + 0.35 * level + 0.15 * flash)
    height, width = image.shape[:2]
    x0, x1 = max(0, int(cx - 2 * size)), min(width, int(cx + 2 * size) + 1)
    y0, y1 = max(0, int(cy - 2 * size)), min(height, int(cy + 2 * size) + 1)
    y, x = np.mgrid[y0:y1, x0:x1].astype(np.float32) + 0.5
    inside = np.clip(size - np.hypot(x - cx, y - cy) + 0.5, 0, 1)[..., None]
    light = np.zeros(x.shape + (3,), np.float32)
    for i, color in enumerate(GLOW[len(GLOW) * k // 3] for k in range(3)):  # tres luces repartidas en la ronda
        angle = clock * (1.2 + 0.45 * i) + i * 2.1
        bx, by = cx + 0.45 * size * math.cos(angle), cy + 0.45 * size * math.sin(angle * 1.13)
        shade = rgb(color) * tint + rgb('#8a8f9c') * (1 - tint)  # de gris a su color
        light += shade * np.exp(-((x - bx) ** 2 + (y - by) ** 2) / (2 * (0.5 * size) ** 2))[..., None]
    shine = 110 * np.exp(-((x - cx + 0.35 * size) ** 2 + (y - cy + 0.42 * size) ** 2) / (2 * (0.2 * size) ** 2))
    sphere = rgb(SPHERE) + light * 0.8 + shine[..., None]
    region = image[y0:y1, x0:x1]
    halo = 0.35 + 0.3 * level + 1.4 * flash  # el destello: el halo se enciende y se apaga
    region[:] = region * (1 - inside) + (sphere + light * 0.6 * flash) * inside + light * (1 - inside) * halo


class Layered:
    """Una ventana con transparencia real por píxel (UpdateLayeredWindow): bordes lisos sobre cualquier fondo.
    Windows ya no muestra lo que dibuja Tk en ella: se le pasa la imagen entera cada vez."""

    def __init__(self, window_):
        user32, gdi32 = gdi()
        self.tk, self.dims, self.bitmap = window_, None, None
        self.screen = user32.GetDC(None)
        self.memory = gdi32.CreateCompatibleDC(self.screen)
        self.bits = ctypes.c_void_p()
        self.blend = ctypes.c_uint32(0x01FF0000)  # AC_SRC_OVER, opacidad 255, AC_SRC_ALPHA

    def show(self, image):
        user32, gdi32 = gdi()
        height, width = image.shape[:2]
        if self.dims != (width, height):  # una superficie del tamaño de la imagen
            header = struct.pack('<IiiHHIIiiII', 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0)  # de arriba hacia abajo
            bitmap = gdi32.CreateDIBSection(self.memory, header, 0, ctypes.byref(self.bits), None, 0)
            gdi32.SelectObject(self.memory, bitmap)
            if self.bitmap:
                gdi32.DeleteObject(self.bitmap)
            self.bitmap, self.dims, self.size = bitmap, (width, height), wintypes.SIZE(width, height)
        # Tk vuelve a crear la ventana de Windows al mostrarla: se busca cada vez y se le pone WS_EX_LAYERED.
        window_ = user32.GetParent(self.tk.winfo_id()) or self.tk.winfo_id()
        style = user32.GetWindowLongW(window_, -20)
        if not style & 0x80000:
            user32.SetWindowLongW(window_, -20, style | 0x80000)
        ctypes.memmove(self.bits, np.ascontiguousarray(image).ctypes.data, image.nbytes)
        user32.UpdateLayeredWindow(window_, self.screen, None, ctypes.byref(self.size), self.memory,
                                   ctypes.byref(wintypes.POINT(0, 0)), None, ctypes.byref(self.blend), 2)


GDI = {}


def gdi():
    """Las funciones de Windows para dibujar, con sus tipos (punteros de 64 bits)."""
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    if not GDI:
        for function in (user32.GetDC, user32.GetParent, gdi32.CreateCompatibleDC, gdi32.CreateDIBSection,
                         gdi32.CreateFontW, gdi32.SelectObject):
            function.restype = ctypes.c_void_p
        user32.GetParent.argtypes = gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
        gdi32.DeleteObject.argtypes = gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
        gdi32.SelectObject.argtypes = [ctypes.c_void_p] * 2
        gdi32.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint,
                                           ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint]
        gdi32.SetTextColor.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        gdi32.SetBkMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.DrawTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
        user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
        user32.UpdateLayeredWindow.argtypes = [ctypes.c_void_p] * 9
        GDI['dpi'] = user32.GetDpiForSystem()
    return user32, gdi32


def ink(image, value, x, y, size, color='#ffffff', weight='', anchor='nw', family=None, wrap=0):
    """Escribe texto con Windows (suavizado) sobre una imagen numpy. size en puntos, como en Tk. anchor: nw, n, w, e o
    center. wrap: ancho en píxeles para partir en renglones. Con image None solo mide. Devuelve (ancho, alto).
    family: una fuente de Windows; sin ella, la de TYPE (normal o negrita)."""
    user32, gdi32 = gdi()
    family = family or TYPE['bold' if weight == 'bold' else 'regular']
    size *= TEXT_SIZE
    memory = gdi32.CreateCompatibleDC(None)
    face = gdi32.CreateFontW(-round(size * GDI['dpi'] / 72), 0, 0, 0, 700 if weight == 'bold' else 400, 0, 0, 0, 1,
                             0, 0, 4, 0, family)  # 4 = suavizado en grises
    gdi32.SelectObject(memory, face)
    flags = 0x800 | (0x10 if wrap else 0x20)  # sin "&" especiales, y en renglones o en una sola línea
    box = wintypes.RECT(0, 0, wrap or 10000, 0)
    user32.DrawTextW(memory, value, -1, ctypes.byref(box), flags | 0x400)  # 0x400: solo medir
    width, height = box.right, box.bottom
    if image is not None and width and height:
        bits = ctypes.c_void_p()
        header = struct.pack('<IiiHHIIiiII', 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        bitmap = gdi32.CreateDIBSection(memory, header, 0, ctypes.byref(bits), None, 0)
        gdi32.SelectObject(memory, bitmap)
        gdi32.SetTextColor(memory, 0xFFFFFF)
        gdi32.SetBkMode(memory, 1)  # fondo transparente
        user32.DrawTextW(memory, value, -1, ctypes.byref(wintypes.RECT(0, 0, width, height)), flags)
        mask = np.frombuffer(ctypes.string_at(bits, width * height * 4), np.uint8).reshape(height, width, 4)[..., 1]
        gdi32.DeleteObject(bitmap)
        left = int(x - (width if 'e' in anchor else width / 2 if anchor in ('n', 'center') else 0))
        top = int(y - (height / 2 if anchor in ('w', 'e', 'center') else 0))
        x0, y0 = max(left, 0), max(top, 0)
        x1, y1 = min(left + width, image.shape[1]), min(top + height, image.shape[0])
        if x1 > x0 and y1 > y0:
            alpha = (mask[y0 - top:y1 - top, x0 - left:x1 - left].astype(np.float32) / 255)[..., None]
            region = image[y0:y1, x0:x1]
            region[:] = region * (1 - alpha) + rgb(color) * alpha
    gdi32.DeleteObject(face)
    gdi32.DeleteDC(memory)
    return width, height


def window():
    ctypes.windll.shcore.SetProcessDpiAwareness(1)  # nítido con el zoom de Windows (125 %, 150 %…)
    root = tk.Tk()
    scale = root.winfo_fpixels('1i') / 96
    px = lambda value: int(value * scale)
    width, height = px(480), px(64)
    x, top = (root.winfo_screenwidth() - width) // 2, px(14)
    margin = px(14)  # alrededor de la cápsula, para la luz que sale hacia afuera

    # La cápsula: el orbe a la izquierda y el texto al lado, sobre el vidrio que se redibuja en cada cuadro.
    # Usa transparencia real por píxel (Layered): sin el borde negro que deja el color clave de Tk.
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.geometry(f'{width + 2 * margin}x{height + 2 * margin}+{x - margin}+{-height - 2 * margin}')
    glass = Glass(width, height, height / 2, scale, margin)
    layered = Layered(root)
    if TYPE['regular'] not in tkfont.families():  # Cocogoose no está instalada: la de Windows 11
        TYPE.update(FALLBACK)
    font = tkfont.Font(family=TYPE['regular'], size=round(FONT_SIZE * TEXT_SIZE))  # para medir si el texto entra
    text_width = width - px(92)

    # El panel de respuesta, debajo de la cápsula: también con transparencia real.
    panel = tk.Toplevel(root)
    panel.overrideredirect(True)
    panel.attributes('-topmost', True)
    panel.withdraw()
    panel_layer = Layered(panel)

    state = {'mood': 'idle', 'phase': 0.0, 'clock': 0.0, 'bright': 0.45, 'level': 0.0, 'shown': False, 'text': '', 'caret': True,
             'tint': 1.0, 'flash': 0.0, 'waiting': False}  # tint: 0 orbe gris, 1 con sus colores

    def mood(name):
        root.after(0, lambda: set_mood(name))

    def set_mood(name):
        if name == 'hide':
            return hide()
        state['mood'] = name
        refresh_hint()

    def refresh_hint(_event=None):
        """Muestra lo escrito (con el cursor) o, si no hay nada, el aviso del estado."""
        typed = state['text']
        if not typed:
            hint = t('Micrófono apagado: escribe y aprieta Enter') if MIC['off'] and state['mood'] == 'idle' \
                else HINTS[state['mood']]
            if OPSEC['on'] and state['mood'] == 'idle':
                hint += t('  ·  opsec: todo queda en tu PC')
            return label(hint, HINT)
        shown = typed
        while len(shown) > 1 and font.measure('…' + shown + '|') > text_width:  # si no entra, muestra el final
            shown = shown[1:]
        label(('…' if shown != typed else '') + shown + ('|' if state['caret'] else ' '), TEXT)

    def label(text, color):
        if state.get('label') != (text, color):  # Windows dibuja el texto solo cuando cambia
            state['label'] = (text, color)
            state['ink'] = rgb(color)
            canvas = np.zeros((height, width + 2 * margin, 3), np.float32)
            ink(canvas, text, margin + px(66), height / 2, FONT_SIZE, anchor='w')
            state['mask'] = canvas[..., 1:2] / 255

    def blink():
        state['caret'] = not state['caret']
        if state['text']:
            refresh_hint()
        root.after(530, blink)

    def on_key(event):
        """Escribir en la cápsula: letras, borrar, pegar (Ctrl+V) y Enter."""
        if event.keysym in PAGE_KEYS:  # flechas y Re Pág / Av Pág: deslizan el texto largo del panel
            return scroll(PAGE_KEYS[event.keysym])
        if event.keysym == 'Return':
            return submit(event)
        if event.keysym == 'BackSpace':
            state['text'] = state['text'][:-1]
        elif event.state & 0x4 and event.keysym.lower() == 'v':  # Ctrl+V
            try:
                state['text'] += root.clipboard_get().replace('\n', ' ')
            except tk.TclError:
                pass
        elif event.char and event.char >= ' ' and not event.state & 0x4:
            state['text'] += event.char
        else:
            return
        state['caret'] = True
        refresh_hint()

    def paint():
        if state.get('style') != STYLE['version']:  # cambiaste los colores con /feeling
            state['style'], glass.colors = STYLE['version'], palette()
        image = glass.frame(state['phase'], state['bright'])
        orb(image, margin + px(34), margin + height / 2, px(16), state['clock'], state['level'], state['tint'],
            state['flash'])
        if 'mask' in state:
            text = image[margin:margin + height]
            text[:] = text * (1 - state['mask']) + state['ink'] * state['mask']
        layered.show(glass.bgra(image))

    def animate():
        # El borde de luz gira (rápido al pensar) y brilla más con tu voz; el orbe crece cuando hablas.
        bright, speed = MOODS[state['mood']]
        voice = LEVEL['now'] if state['mood'] == 'listen' else 0.0
        pulse = 0.25 + 0.2 * math.sin(state['clock'] * 5) if state['mood'] == 'speak' else 0.0
        # Gris mientras el micrófono arranca; cuando llega el primer audio, un destello y vuelven los colores.
        if state['waiting'] and LEVEL['live']:
            state['waiting'], state['flash'] = False, 1.0
        state['tint'] += ((0.0 if state['waiting'] else 1.0) - state['tint']) * 0.18
        state['flash'] *= 0.9
        state['bright'] += (bright + 0.8 * voice + 1.2 * state['flash'] - state['bright']) * 0.2
        state['level'] += (voice + pulse - state['level']) * 0.3
        state['phase'] += speed
        state['clock'] += 0.04 + speed * 3
        if state['shown']:  # escondida no dibuja: no gasta procesador
            paint()
        if state['shown'] and clicked_outside():
            hide()
        root.after(33 if state['shown'] else 250, animate)  # escondida: casi sin gastar procesador

    def clicked_outside():
        """True cuando se aprieta el clic izquierdo fuera de la cápsula y del panel (en cualquier programa)."""
        pressed = bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
        was, state['pressed'] = state.get('pressed', False), pressed
        if not pressed or was:  # solo en el instante en que se aprieta
            return False
        cursor = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(cursor))
        for window_ in (root, panel):
            if window_.winfo_viewable() and window_.winfo_rootx() <= cursor.x < window_.winfo_rootx() + window_.winfo_width() \
                    and window_.winfo_rooty() <= cursor.y < window_.winfo_rooty() + window_.winfo_height():
                return False
        return True

    def slide(to, then=None, frame=0, start=None):
        start = root.winfo_y() + margin if start is None else start
        progress = 1 - (1 - (frame + 1) / 10) ** 3  # frena al final
        y = int(start + (to - start) * progress)
        root.geometry(f'+{x - margin}+{y - margin}')
        if frame < 9:
            root.after(16, slide, to, then, frame + 1, start)
        elif then:
            then()

    def appear():
        if not state['shown']:
            state['shown'] = True
            root.geometry(f'+{x - margin}+{-height - 2 * margin}')
            root.deiconify()
            root.update_idletasks()
            paint()  # el primer cuadro ya, sin esperar a la animación
            slide(top)
        root.lift()
        root.focus_force()

    def hide(_event=None):
        panel.withdraw()
        if state['shown']:
            state['shown'] = False
            slide(-height - margin, root.withdraw)

    def show(message):
        root.after(0, lambda: show_now(message))

    def show_now(message):
        """El texto en el panel. Si es largo, el panel queda de alto fijo y se desliza con la rueda o las flechas."""
        wrap = width - px(48)  # a la derecha queda lugar para la barra
        full = ink(None, message, 0, 0, 11, wrap=wrap)[1]
        view = min(full, px(400))  # lo que se ve del texto de una vez
        backdrop = Glass(width, view + px(32), px(18), scale)
        page = np.zeros((full, wrap, 3), np.float32)
        ink(page, message, 0, 0, 11, wrap=wrap)  # el texto entero, una sola vez: deslizar solo lo recorta
        state['page'] = {'glass': backdrop, 'base': backdrop.frame(0.15, 0.3), 'mask': page[..., 1:2] / 255,
                         'view': view, 'offset': 0, 'end': full - view}
        draw_page()

    def draw_page():
        page = state['page']
        image, offset, view = page['base'].copy(), page['offset'], page['view']
        cut = page['mask'][offset:offset + view]
        if page['end']:  # el texto se esfuma en el borde donde sigue, para que se note que hay más
            fade = np.ones((view, 1, 1), np.float32)
            edge = min(px(28), view // 3)
            if offset < page['end']:
                fade[-edge:, 0, 0] = np.linspace(1, 0.1, edge)
            if offset:
                fade[:edge, 0, 0] = np.linspace(0.1, 1, edge)
            cut = cut * fade
            # la barra: su largo es cuánto se ve y su lugar, por dónde vas
            bar_h = max(px(28), view * view // (view + page['end']))
            bar_y = px(16) + (view - bar_h) * offset // page['end']
            r = px(2)
            ys, xs = np.mgrid[0:bar_h, 0:2 * r].astype(np.float32) + 0.5
            bar = np.clip(r - np.hypot(xs - r, ys - np.clip(ys, r, bar_h - r)) + 0.5, 0, 1)[..., None] * 0.4
            region = image[bar_y:bar_y + bar_h, width - px(14):width - px(14) + 2 * r]
            region[:] = region * (1 - bar) + 255 * bar
        region = image[px(16):px(16) + view, px(20):px(20) + cut.shape[1]]
        region[:] = region * (1 - cut) + rgb('#e8ecf4') * cut
        put_panel(page['glass'].bgra(image))

    def scroll(steps):
        """Desliza el texto largo del panel: steps > 0 baja, < 0 sube (un paso = unos 3 renglones)."""
        page = state.get('page')
        if not page or not page['end'] or not panel.winfo_viewable():
            return
        offset = int(min(max(page['offset'] + steps * px(54), 0), page['end']))
        if offset != page['offset']:
            page['offset'] = offset
            draw_page()

    def put_panel(image):
        panel.geometry(f'{width}x{image.shape[0]}+{x}+{top + height + px(8)}')
        panel.deiconify()
        panel.lift()
        panel.update_idletasks()  # que Tk termine de crear la ventana antes de pasarle la imagen
        panel_layer.show(image)

    def put_in_pill(text):
        root.after(0, lambda: (state.update(text=text), refresh_hint()))

    def show_card(draw):
        """Una tarjeta de un plugin (el clima): la dibuja el plugin en el panel, que queda 25 s."""
        def now():
            image, cover = draw(width, px, ink)
            state.pop('page', None)  # la rueda ya no desliza un texto viejo por encima de la tarjeta
            put_panel(bgra(image, cover))
        root.after(0, now)

    def announce(text):
        """Un aviso que llega solo (un recordatorio): baja la cápsula, lo muestra y lo dice en voz alta."""
        def now():
            put_in_pill('')
            appear()
            show_now(text)
            set_mood('speak')
            threading.Thread(target=lambda: (winsound.Beep(1046, 150), winsound.Beep(1318, 200), speak(text),
                                             mood('idle')), daemon=True).start()
        root.after(0, now)

    UI.update(notify=announce, show_card=show_card, hide=lambda: root.after(0, hide), appear=lambda: root.after(0, appear))
    for start in STARTERS:
        start()
    mic_ready()

    def quit_all():
        unload()
        root.destroy()

    busy = threading.Lock()  # una orden a la vez

    def voice_turn():
        if not busy.acquire(blocking=False):
            return
        try:
            mood('listen')
            # El sonido de portal suena cuando el micrófono ya capta (no al apretar el atajo): tu señal para hablar.
            # Con el micrófono siempre abierto no hace falta (y se grabaría).
            if not MIC['open']:  # arranca antes, para que su pico caiga justo con el destello (cuando ya capta)
                threading.Timer(CHIME_LEAD, play_chime).start()
            said = listen()
            LEVEL['now'] = 0.0
            if not said:
                show(t('No te escuché. Apreta Ctrl+Alt+N y vuelve a intentar.'))
                mood('idle')
            elif said.lower().strip('.!') in ('salir', 'cerrar node assistant'):
                root.after(0, quit_all)
            else:
                put_in_pill(said)
                run(said, show, mood)
        except Exception as error:  # micrófono ocupado o desconectado, etc.
            show(t('Error con el micrófono: {error}', error=error))
            mood('idle')
        finally:
            LEVEL['live'] = False
            root.after(0, lambda: state.update(waiting=False))  # si el micrófono falló, el orbe no queda gris
            busy.release()

    def summon():
        panel.withdraw()
        put_in_pill('')
        if not MIC['off'] and not busy.locked():  # va a escuchar: el orbe arranca gris hasta que llegue el audio
            state.update(waiting=True, tint=0.0, flash=0.0)
        appear()
        if MIC['off']:  # modo solo texto: la cápsula espera que escribas
            set_mood('idle')
        else:
            threading.Thread(target=voice_turn, daemon=True).start()

    def submit(_event):
        text = state['text'].strip()
        if text.lower().strip('.!') in ('salir', 'cerrar node assistant'):
            quit_all()
        elif text and not busy.locked():
            threading.Thread(target=run, args=(text, show, mood), daemon=True).start()

    # Para los plugins (como /setup): llamar a Node, mostrar algo, salir, y usar Tk desde su hilo.
    UI.update(summon=lambda: root.after(0, summon), show=show, quit=lambda: root.after(0, quit_all), after=root.after)
    root.bind('<Key>', on_key)
    root.bind_all('<MouseWheel>', lambda event: scroll(-event.delta / 120))  # la rueda con el mouse sobre el panel
    for widget in (root, panel):
        widget.bind('<Escape>', hide)
    set_mood('idle')
    animate()
    blink()
    hotkey = listen_hotkey(lambda: root.after(0, summon))
    if not hotkey:  # otro Node se quedó abierto (o colgado) con el atajo: se cierra y este toma su lugar
        stop_others()
        time.sleep(1)
        hotkey = listen_hotkey(lambda: root.after(0, summon))
    if not hotkey:
        appear()
        show(t('Ctrl+Alt+N ya está en uso: ¿Node Assistant ya está abierto? Este no va a responder al atajo.'))
    else:
        root.withdraw()  # espera escondido hasta el atajo
    # Carga Whisper y la voz en segundo plano para que la primera orden no espere.
    # (Whisper solo si ya está descargado: la descarga la ofrece /setup; la voz, si ya hay una)
    threading.Thread(target=lambda: (chime_file(), whisper_ready() and model('ears'), VOICE.exists() and model('voice'),
                                     saved('voice_engine') == 'kokoro' and kokoro_ready() and model('kokoro')),
                     daemon=True).start()
    root.mainloop()


# Plugins: cada archivo de la carpeta plugins/ suma habilidades. Ver plugins/LEEME.md.
PLUGINS = {}    # nombre de la herramienta -> función(argumentos, where) que la hace y devuelve qué decir
LISTENERS = []  # canales que también reciben los avisos (el bot de Telegram)
STARTERS = []   # lo que los plugins arrancan al abrir Node (no con --stop ni --dry): vigilantes, bots
WAITING = []    # plugins que esperan una respuesta corta: función(texto, where) -> qué decir, o None si no es para ellos
UI = {'notify': lambda text: None, 'show_card': lambda draw: None}  # la ventana los completa al abrirse


def add(tool_, handler, words=None):
    """Para los plugins: suma una herramienta que la IA puede usar y la función que la hace.
    words: palabras (sin tildes, como expresión regular) que la delatan, para el ahorro de cupo; sin ellas va siempre."""
    TOOLS.append(tool_)
    PLUGINS[tool_['function']['name']] = handler
    if words:
        hint(tool_['function']['name'], words)


def notify(text):
    """Para los plugins: un aviso (un recordatorio). Sale en la cápsula, en voz alta y en los canales."""
    UI['notify'](text)
    for send in [] if OPSEC['on'] else LISTENERS:  # con /opsec, los avisos no salen a Telegram
        try:
            send(text)
        except OSError:  # sin internet: el aviso igual salió en la PC
            pass


def card(draw):
    """Para los plugins: muestra una tarjeta dibujada a mano en el panel (el clima). draw(width, px, ink) devuelve
    (imagen numpy alto x ancho x 3, cobertura alto x ancho de 0 a 1); ink() escribe texto sobre la imagen."""
    UI['card'] = True
    UI['show_card'](draw)


# Los comandos que empiezan con "/": funcionan en la cápsula y en Telegram, y /help los lista solos.
COMMANDS = {}  # '/nombre' -> (para qué sirve, función(lo que va después del comando) que devuelve qué mostrar)


def command(name, description, handler):
    """Suma un comando (también para los plugins). Aparece solo en /help."""
    COMMANDS[name.lower()] = (description, handler)


def slash(text):
    """Si el texto es un comando, lo hace y devuelve qué mostrar; si no empieza con "/", None."""
    name, _, rest = text.strip().partition(' ')
    if not name.startswith('/'):
        return None
    if name.lower() not in COMMANDS:
        return t('No conozco {name}. Escribe /help para ver los comandos.', name=name)
    return COMMANDS[name.lower()][1](rest.strip())


def help_text(_rest=''):
    return (t('Comandos:\n') + '\n'.join(f'{name} — {description}' for name, (description, _) in sorted(COMMANDS.items()))
            + t('\nPara cerrar Node: escribe o di "salir".'))


command('/help', t('esta lista de comandos'), help_text)
command('/usage', t('qué plataforma de IA está usando Node y cuánto cupo gratis le queda'), lambda _rest: usage())
command('/feeling', t('cambia los colores de la cápsula: /feeling fuego, /feeling rojo azul verde, /feeling node'),
        feeling)
command('/mictoggle', t('apaga el micrófono (modo solo texto) o lo vuelve a prender'), lambda _rest: mic_toggle())
command('/micavailtogg', t('micrófono siempre listo (capta al instante) o solo al apretar Ctrl+Alt+N'),
        lambda _rest: mic_avail_toggle())
command('/opsec', t('modo privado: nada sale de tu PC (solo IA local) o vuelve a la nube'), lambda _rest: opsec_toggle())


def load_plugins():
    node = sys.modules[__name__]
    off = set(saved('plugins_off', []))  # los que apagaste en /settings → Plugins
    for path in sorted((HERE / 'plugins').glob('*.py')):
        if path.stem in off:
            continue
        try:
            spec = importlib.util.spec_from_file_location(f'plugin_{path.stem}', path)
            plugin = sys.modules[spec.name] = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(plugin)
            plugin.setup(node)
        except Exception as error:  # un plugin roto no tumba a Node
            print(f'Plugin {path.name} no cargó: {error}', file=sys.stderr)


load_plugins()


if __name__ == '__main__':
    if sys.argv[1:2] == ['--stop']:  # apaga todo: el asistente y los modelos en la placa de video
        stop_others()  # primero: sin incluirse (el lanzador del entorno .venv es su proceso padre)
        unload()
    elif sys.argv[1:2] == ['--dry']:
        for phrase in sys.argv[2:]:
            print(f'{phrase!r} -> {plan(phrase)}')
    else:
        window()
    # Termina de verdad: sin esto, un hilo del micrófono o de la voz puede dejar el proceso vivo y sin ventana
    # (y con el atajo tomado: el próximo Node no respondería).
    sys.stdout and sys.stdout.flush()
    os._exit(0)
