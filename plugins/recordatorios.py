"""Recordatorios y temporizadores: "avísame en 20 minutos que saque la pizza", "recuérdame a las 18:30 llamar a mamá".
Cuando llega la hora, Node baja la cápsula, suena, lo dice en voz alta y, si está el bot de Telegram, te llega al celular.
Se guardan en recordatorios.json: si Node estaba cerrado a esa hora, te avisa apenas lo abres.
"""
import json
import re
import threading
import time
from datetime import datetime, timedelta

node = None
FILE = None
lock = threading.Lock()


def load():
    return json.loads(FILE.read_text(encoding='utf-8')) if FILE.exists() else []


def save(items):
    FILE.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding='utf-8')


def when_text(moment):
    minutes = max(round((moment - time.time()) / 60), 1)
    clock = f'{datetime.fromtimestamp(moment):%H:%M}'
    if minutes < 60:
        return node.t('en {minutes} minutos (a las {clock})', minutes=minutes, clock=clock) if minutes != 1 else \
            node.t('en 1 minuto (a las {clock})', clock=clock)
    return node.t('a las {clock}', clock=clock) if minutes < 24 * 60 else \
        node.t('el {date} a las {clock}', date=f'{datetime.fromtimestamp(moment):%d/%m}', clock=clock)


def remind(args, where):
    text = (args.get('text') or '').strip() or node.t('tu temporizador terminó')
    minutes, at = float(args.get('minutes') or 0), (args.get('at') or '').strip()
    if match := re.fullmatch(r'(\d{1,2})[:.](\d{2})', at):
        moment = datetime.now().replace(hour=int(match[1]), minute=int(match[2]), second=0, microsecond=0)
        if moment <= datetime.now():  # esa hora ya pasó hoy: mañana
            moment += timedelta(days=1)
        moment = moment.timestamp()
    elif minutes > 0:
        moment = time.time() + minutes * 60
    else:
        return node.t('¿Para cuándo? Dime en cuántos minutos o a qué hora.')
    with lock:
        save(sorted(load() + [{'when': moment, 'text': text}], key=lambda item: item['when']))
    return node.t('Listo, te aviso {dato}.', dato=when_text(moment))


def reminders(args, where):
    with lock:
        items = load()
        if args.get('action') == 'cancel':
            words = (args.get('which') or '').lower().strip()
            keep = [item for item in items if words and words not in item['text'].lower()]
            save(keep)
            gone = len(items) - len(keep)
            return (node.t('Cancelé {gone} recordatorios.', gone=gone) if gone != 1 else node.t('Cancelé 1 recordatorio.')) if gone else node.t('No encontré ese recordatorio.')
    if not items:
        return node.t('No tienes recordatorios pendientes.')
    return node.t('Tienes: ') + '; '.join(f"{item['text']}, {when_text(item['when'])}" for item in items) + '.'


def watch():
    """Revisa cada segundo si llegó la hora de algún recordatorio."""
    while True:
        with lock:
            items = load()
            due = [item for item in items if item['when'] <= time.time()]
            if due:
                save([item for item in items if item['when'] > time.time()])
        for item in due:
            late = time.time() - item['when'] > 120  # Node estaba cerrado a esa hora
            node.notify(node.t('Recordatorio atrasado: {text}.', text=item['text']) if late else
                        node.t('Recordatorio: {text}.', text=item['text']))
            time.sleep(6)  # que dos avisos juntos no se pisen la voz
        time.sleep(1)


def setup(node_):
    global node, FILE
    node, FILE = node_, node_.HERE / 'recordatorios.json'
    node.add(node.tool('remind', 'Pone un temporizador o un recordatorio. Usa minutes para "en X minutos" (horas = '
                       'minutos x 60) o at con la hora HH:MM de 24 horas para "a las X"; el otro, 0 o vacío. text es '
                       'lo que hay que recordar, corto (si es solo un temporizador, vacío).',
                       minutes={'type': 'number'}, at={'type': 'string'}, text={'type': 'string'}), remind, r'avis|recorda|recuerd|temporizador|alarma|minuto|en \d|a las|despert')
    node.add(node.tool('reminders', 'Lista los recordatorios y temporizadores pendientes (action list) o cancela '
                       '(action cancel; which = una palabra del recordatorio, o vacío para no cancelar nada).',
                       action={'type': 'string', 'enum': ['list', 'cancel']}, which={'type': 'string'}), reminders, r'recordatorio|temporizador|alarma|avisos|cancel|pendiente')
    node.STARTERS.append(lambda: threading.Thread(target=watch, daemon=True).start())  # al abrir Node
