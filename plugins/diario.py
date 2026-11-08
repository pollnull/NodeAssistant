"""Nota del día y resumen de la noche, en Obsidian (Diario/AAAA-MM-DD.md).
- Al empezar el día, Node crea la nota con el plan: tareas que vencen (de Tareas.md) y tu agenda de Google si está.
- Desde las 8:00 te avisa una vez las tareas de hoy o vencidas.
- A las 20:00 resume el día (lo que hablaste con Node, tareas terminadas, notas rápidas y lo que queda para mañana),
  lo escribe en la nota y te lo manda por Telegram. /tgtoggle apaga o prende el envío; /resumen lo hace ya.
- "¿Qué hice ayer?", "¿qué hice el martes?": lee el resumen de ese día (o lo arma si no hay).
Si Node estaba cerrado a las 20:00, el resumen sale apenas lo abres esa misma noche.
"""
import sys
import threading
import time
from datetime import date, datetime, timedelta

node = None
MORNING, EVENING = 8, 20  # desde qué hora avisa las tareas del día y a qué hora resume


def path(day):
    return node.VAULT / 'Diario' / f'{day:%Y-%m-%d}.md'


def title(day):
    return node.t('{weekday} {day} de {month} de {year}', weekday=node.DAYS[day.weekday()], day=day.day,
                  month=node.MONTHS[day.month - 1], year=day.year)


def plugin(name):
    return sys.modules.get(f'plugin_{name}')


def due_by(day):
    """Las tareas pendientes que vencen ese día o antes: [(texto, fecha)]."""
    tasks = plugin('obsidian')
    return [(text, due) for text, due in tasks.pending() if due and due <= f'{day:%Y-%m-%d}'] if tasks else []


def agenda():
    google = plugin('google')
    if not google or not google.TOKEN.exists():
        return ''
    try:
        return google.calendar({'action': 'agenda', 'days': 1}, 'pc')
    except Exception:  # sin internet o sin permiso: la nota sale igual, sin agenda
        return ''


def ensure(day):
    """Crea la nota del día con el plan, si todavía no existe."""
    note = path(day)
    if note.exists():
        return
    note.parent.mkdir(parents=True, exist_ok=True)
    plan = [node.t('- {task} (vence {due})', task=text, due=due) for text, due in due_by(day)] or [node.t('- Nada vence hoy.')]
    if calendar := agenda():
        plan.append(node.t('- Agenda: {calendar}', calendar=calendar))
    # Como la nota diaria de la plantilla de kepano: la etiqueta daily y la tabla de lo que creaste ese día (Daily.base)
    note.write_text(f'---\ntags:\n  - daily\n---\n# {title(day).capitalize()}\n\n## {node.t("Plan")}\n' +
                    '\n'.join(plan) + f'\n\n## {node.t("Notas del día")}\n\n![[Daily.base]]\n' +
                    f'\n{summary_heading()}\n_' + node.t('Node lo escribe a las {hour}:00.', hour=EVENING) + '_\n',
                    encoding='utf-8')


def summary_heading():
    return f'## {node.t("Resumen")}'


def gather(day):
    """Lo que pasó ese día, en texto, para resumirlo."""
    parts = []
    talk = node.NOTES / 'Conversaciones' / f'{day:%Y-%m-%d}.md'
    if talk.exists():
        parts.append(node.t('Charlas con Node:\n') + talk.read_text(encoding='utf-8')[-6000:])  # lo último, que entre en el cupo
    tasks = plugin('obsidian')
    if tasks and (done := tasks.done_on(day)):
        parts.append(node.t('Tareas terminadas: ') + '; '.join(done))
    quick = node.VAULT / 'Notas rápidas.md'
    if quick.exists():
        notes = [line for line in quick.read_text(encoding='utf-8').splitlines() if line.startswith(f'- {day:%d/%m} ')]
        if notes:
            parts.append(node.t('Notas rápidas:\n') + '\n'.join(notes))
    if day == date.today() and (left := due_by(day + timedelta(days=1))):
        parts.append(node.t('Pendiente para mañana o vencido: ') + '; '.join(text for text, _ in left))
    return '\n\n'.join(parts)


def summarize(day):
    facts = gather(day)
    if not facts:
        return ''
    try:
        answer = node.cloud([
            {'role': 'system', 'content': node.PERSONA + ' Ahora escribes el resumen del día del usuario para leerlo en el '
                                          'celular: de 3 a 6 frases en segunda persona, qué hizo y pidió, qué tareas '
                                          'cerró y qué le queda para mañana. No inventes nada que no esté en los datos.'},
            {'role': 'user', 'content': f'Datos del {title(day)}:\n\n{facts}'}], wait=20, max_tokens=500)
        return node.tidy(answer.get('content'))
    except ConnectionError:  # sin nube (o /opsec): los datos tal cual
        return facts[-1500:]


def write_summary(day, text):
    ensure(day)
    note = path(day)
    head = note.read_text(encoding='utf-8').partition(summary_heading())[0]
    note.write_text(f'{head}{summary_heading()}\n{text}\n', encoding='utf-8')


def evening(day):
    """Resume el día, lo guarda en la nota y lo manda por Telegram (si está activado). Devuelve el resumen."""
    text = summarize(day)
    if not text:
        return node.t('Hoy no hay nada para resumir todavía.')
    write_summary(day, text)
    telegram, chat = plugin('telegram'), node.secret('TELEGRAM_CHAT_ID')
    if telegram and chat and node.saved('tg_resumen', True) and not node.OPSEC['on']:
        try:
            telegram.send(chat, f'🌙 Resumen del {title(day)}\n\n{text}')
        except OSError:  # sin internet: queda en la nota igual
            pass
    return text


def watch():
    while True:
        try:
            now = datetime.now()
            today, stamp = now.date(), f'{now:%Y-%m-%d}'
            if node.VAULT.exists():  # sin el SSD externo no hace nada
                ensure(today)
                if now.hour >= MORNING and node.saved('tareas_avisadas') != stamp:
                    node.save('tareas_avisadas', stamp)
                    if due := due_by(today):
                        node.notify(node.t('Tareas para hoy o vencidas: ') + '; '.join(text for text, _ in due[:5]) + '.')
                if now.hour >= EVENING and node.saved('resumen_hecho') != stamp:
                    node.save('resumen_hecho', stamp)  # antes de resumir: si algo falla, no lo reintenta cada 30 s
                    evening(today)
        except Exception as error:  # que un error no apague el vigilante
            print(f'diario: {error}', file=sys.stderr)
        time.sleep(30)


def diary(args, where):
    try:
        day = date.fromisoformat((args.get('date') or '').strip())
    except ValueError:
        day = date.today()
    try:
        note = path(day)
        if note.exists():
            summary = note.read_text(encoding='utf-8').partition(summary_heading())[2].strip()
            if summary and not summary.startswith('_'):  # "_Node lo escribe a las 20:00._": todavía no hay
                return summary
        return summarize(day) or node.t('No tengo nada guardado del {dato}.', dato=title(day))
    except OSError:
        return node.t('No pude abrir tu diario: ¿está conectada la carpeta de tu bóveda?')


def tg_toggle(_rest=''):
    on = not node.saved('tg_resumen', True)
    node.save('tg_resumen', on)
    return (node.t('Resumen diario por Telegram activado: te llega a las {EVENING}:00.', EVENING=EVENING) if on else
            node.t('Resumen diario por Telegram desactivado. La nota del día se sigue escribiendo en Obsidian.'))


def setup(node_):
    global node
    node = node_
    if not node.VAULT:  # sin memoria (se elige en /setup): sin estas habilidades
        return
    global EVENING
    EVENING = node.saved('resumen_hora', EVENING)  # se cambia en /settings → Memoria
    node.add(node.tool('diary', 'Qué hizo el usuario un día, según su diario ("¿qué hice ayer?", "resúmeme el día"). '
                       'date: el día YYYY-MM-DD (hoy si no dice).', date={'type': 'string'}), diary,
             r'que hice|hice ayer|hice hoy|resum.* (?:dia|hoy|ayer)|diario|como me fue')
    node.command('/tgtoggle', node.t('apaga o prende el resumen del día que llega por Telegram a las 20:00'), tg_toggle)
    node.command('/resumen', node.t('resume el día ahora (lo guarda en Obsidian y lo manda por Telegram)'),
                 lambda _rest: evening(date.today()))
    node.STARTERS.append(lambda: threading.Thread(target=watch, daemon=True).start())
