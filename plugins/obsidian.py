"""Obsidian: notas rápidas, listas, tareas con fecha y preguntas a tus notas (bóveda en D:\\Obsidian).
"anota que tengo que comprar cables", "agrega leche y pan a la lista del súper", "ya compré la leche",
"tengo que entregar el informe el viernes", "¿qué tengo pendiente?", "ya entregué el informe",
"¿qué anoté sobre la tesis?", "guárdalo en Obsidian como Receta de pan".
Todo queda en archivos .md normales: los ves y editas en Obsidian.
- Tareas.md: las tareas, con el formato del plugin Tasks de Obsidian ("- [ ] informe 📅 2026-11-13").
- Notas/: lo que le pides guardar. Notas rápidas.md y Listas/: lo de siempre.
Para responder sobre tus notas, Node le pasa las más relacionadas a la IA en la nube; con /opsec solo busca renglones.
"""
import re
from datetime import date, datetime, timedelta

import numpy as np

node = None
TASK = re.compile(r'^- \[([ x])\] (.*?)(?: 📅 (\d{4}-\d{2}-\d{2}))?(?: ✅ (\d{4}-\d{2}-\d{2}))?\s*$')
SKIP = {'sobre', 'anote', 'notas', 'nota', 'tengo', 'dice', 'dicen', 'obsidian', 'algo', 'todo', 'cual', 'cuales',
        'donde', 'cuando', 'como', 'tiene', 'para', 'esta', 'este', 'mis', 'que'}


def clean(name):
    return re.sub(r'[\\/:*?"<>|]', '', name).strip().capitalize() or 'General'


def note(args, where):
    text = (args.get('text') or '').strip()
    if not text:
        return node.t('¿Qué anoto?')
    try:
        node.VAULT.mkdir(parents=True, exist_ok=True)
        with (node.VAULT / 'Notas rápidas.md').open('a', encoding='utf-8') as notes:
            notes.write(f'- {datetime.now():%d/%m %H:%M} — {text}\n')
    except OSError:
        return node.t('No pude anotarlo: ¿está conectada la carpeta de tu bóveda?')
    return node.t('Anotado.')


def lists(args, where):
    action, name = args.get('action') or 'show', clean(args.get('list') or '')
    items = [item.strip() for item in re.split(r',| y ', args.get('items') or '') if item.strip()]
    path = node.VAULT / 'Listas' / f'{name}.md'
    try:
        lines = path.read_text(encoding='utf-8').splitlines() if path.exists() else []
        if action == 'add':
            if not items:
                return node.t('¿Qué agrego?')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('\n'.join(lines + [f'- [ ] {item}' for item in items]) + '\n', encoding='utf-8')
            return node.t('Agregué {dato} a la lista {name}.', dato=', '.join(items), name=name)
        if action == 'done':
            marked = []
            for i, line in enumerate(lines):
                if line.startswith('- [ ] ') and any(item.lower() in line.lower() for item in items):
                    lines[i] = '- [x] ' + line[6:]
                    marked.append(line[6:])
            path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            return node.t('Taché {dato}.', dato=', '.join(marked)) if marked else node.t('No encontré eso en la lista.')
    except OSError:
        return node.t('No pude abrir tus listas: ¿está conectada la carpeta de tu bóveda?')
    left = [line[6:] for line in lines if line.startswith('- [ ] ')]
    return node.t('En la lista {name}: {dato}.', name=name, dato=', '.join(left)) if left else node.t('La lista {name} está vacía.', name=name)


# --- Tareas con fecha -------------------------------------------------------------------------------------------

def tasks_path():
    return node.VAULT / 'Tareas.md'


def read_tasks():
    path = tasks_path()
    return path.read_text(encoding='utf-8').splitlines() if path.exists() else []


def pending():
    """[(texto, vence 'YYYY-MM-DD' o None)] por fecha, las sin fecha al final. También la usa diario.py."""
    items = [(m[2], m[3]) for line in read_tasks() if (m := TASK.match(line)) and m[1] == ' ']
    return sorted(items, key=lambda item: item[1] or '9999')


def done_on(day):
    """Las tareas que tachaste ese día. La usa diario.py."""
    return [m[2] for line in read_tasks() if (m := TASK.match(line)) and m[4] == f'{day:%Y-%m-%d}']


def due_label(due):
    """(texto corto, color) para la fecha de una tarea."""
    if not due:
        return '', '#9aa3b5'
    day = date.fromisoformat(due)
    days = (day - date.today()).days
    if days < 0:
        return node.t('vencida'), '#ff6b6b'
    if days == 0:
        return node.t('hoy'), node.GLOW[0]
    if days == 1:
        return node.t('mañana'), '#ffd479'
    return f'{node.DAYS[day.weekday()][:3]} {day.day}', '#9aa3b5'


def task_card(items):
    def draw(width, px, ink):
        rows, more = items[:8], len(items) - 8
        height = px(56) + px(34) * len(rows) + (px(26) if more > 0 else 0) + px(10)
        glass = node.Glass(width, height, px(18), px(100) / 100)
        image = glass.frame(0.15, 0.3)
        y, x = np.mgrid[0:height, 0:width].astype(np.float32) + 0.5
        ink(image, node.t('Tareas pendientes'), px(20), px(16), 13, '#ffffff', 'bold')
        ink(image, str(len(items)), width - px(20), px(26), 13, node.GLOW[0], 'bold', anchor='e')
        for k, (text, due) in enumerate(rows):
            cy = px(56) + px(34) * k + px(14)
            label, color = due_label(due)
            distance = np.hypot(x - px(30), y - cy)
            ring = (np.clip(px(8) - distance + 0.5, 0, 1) - np.clip(px(6.4) - distance + 0.5, 0, 1))[..., None]
            image[:] = image * (1 - ring) + node.rgb(color if due else '#c9d1e0') * ring  # la casilla
            room = width - px(70) - (ink(None, label, 0, 0, 10, weight='bold')[0] + px(16) if label else 0)
            while len(text) > 1 and ink(None, text, 0, 0, 11)[0] > room:  # que no pise la fecha
                text = text[:-2] + '…'
            ink(image, text, px(48), cy, 11, '#e8ecf4', anchor='w')
            if label:
                ink(image, label, width - px(20), cy, 10, color, 'bold', anchor='e')
        if more > 0:
            ink(image, node.t('y {more} más en Tareas.md', more=more), px(48), height - px(30), 10, '#9aa3b5')
        return image, glass.cover
    return draw


def parse_due(value):
    """'el lunes', 'mañana', 'pasado mañana', 'el 20', '20 de diciembre' o 'YYYY-MM-DD' -> 'YYYY-MM-DD' ('' si no se
    entiende). Lo calcula Node y no la IA, que a veces se equivoca de día."""
    text, today = re.sub(r'^(?:el|para el|para)\s+', '', node.plain(value or '').strip()), date.today()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        pass
    relative = {'hoy': 0, 'manana': 1, 'pasado manana': 2}  # también en tu idioma (today, tomorrow…)
    relative.update({node.plain(node.t('hoy')): 0, node.plain(node.t('mañana')): 1,
                     node.plain(node.t('pasado mañana')): 2})
    shift = relative.get(text)
    for k, name in enumerate(node.DAYS):
        if shift is None and re.search(rf'\b{node.plain(name)}\b', text):
            shift = (k - today.weekday()) % 7 or 7  # "el lunes" siendo lunes = el de la semana que viene
    if shift is not None:
        return (today + timedelta(days=shift)).isoformat()
    if match := re.fullmatch(r'(\d{1,2})(?: de (\w+))?', text):
        months = [node.plain(month) for month in node.MONTHS]
        month = months.index(match[2]) + 1 if match[2] in months else today.month
        try:
            day = date(today.year, month, int(match[1]))
            if day < today:  # ya pasó: el mes (o el año) que viene
                day = date(today.year + 1, month, day.day) if match[2] else \
                    date(today.year + (month == 12), month % 12 + 1, day.day)
            return day.isoformat()
        except ValueError:  # "el 31" en un mes de 30 días
            return ''
    return ''


def spoken(due):
    day = date.fromisoformat(due)
    days = (day - date.today()).days
    if days < 0:
        return node.t('vencida desde el {day}/{month}', day=day.day, month=day.month)
    return {0: node.t('hoy'), 1: node.t('mañana')}.get(days, node.t('el {day} {number}', day=node.DAYS[day.weekday()],
                                                                     number=day.day))


def tasks(args, where):
    action, text = args.get('action') or 'list', (args.get('text') or '').strip()
    try:
        lines = read_tasks()
        if action == 'add':
            if not text:
                return node.t('¿Qué tarea anoto?')
            due = parse_due(args.get('due'))
            tasks_path().parent.mkdir(parents=True, exist_ok=True)
            tasks_path().write_text('\n'.join(lines + [f'- [ ] {text}' + (f' 📅 {due}' if due else '')]) + '\n',
                                    encoding='utf-8')
            when = spoken(due) if due else ''
            if not due:
                return node.t('Anoté la tarea {text}.', text=text)
            if due < f'{date.today()}':
                return node.t('Anoté la tarea {text}, {when}.', text=text, when=when)
            return node.t('Anoté la tarea {text}, para {when}.', text=text, when=when)
        if action == 'done':
            words = node.plain(text)
            for i, line in enumerate(lines):
                if (m := TASK.match(line)) and m[1] == ' ' and words and words in node.plain(m[2]):
                    lines[i] = f'- [x] {m[2]}' + (f' 📅 {m[3]}' if m[3] else '') + f' ✅ {date.today():%Y-%m-%d}'
                    tasks_path().write_text('\n'.join(lines) + '\n', encoding='utf-8')
                    return node.t('Listo, taché {dato}.', dato=m[2])
            return node.t('No encontré esa tarea entre las pendientes.')
        items = pending()
    except OSError:
        return node.t('No pude abrir tus tareas: ¿está conectada la carpeta de tu bóveda?')
    if not items:
        return node.t('No tienes tareas pendientes.')
    if where == 'pc':
        node.card(task_card(items))
    said = [f'{text}, {spoken(due)}' if due else text for text, due in items[:5]]
    return (node.t('Tienes {count} pendientes: ', count=len(items)) if len(items) != 1 else node.t('Tienes 1 pendiente: ')) + '; '.join(said) + \
        (node.t('; y {dato} más.', dato=len(items) - 5) if len(items) > 5 else '.')


# --- Preguntarle a tus notas y guardar respuestas ---------------------------------------------------------------

def notes():
    """Tus notas, sin la configuración de Obsidian ni el registro de cada charla (mucho texto y poco útil)."""
    for path in node.VAULT.rglob('*.md'):
        if '.obsidian' not in path.parts and path.parent.name != 'Conversaciones':
            yield path


def ask(args, where):
    question = (args.get('question') or '').strip()
    if not question:
        return node.t('¿Qué quieres saber de tus notas?')
    words = {word for word in re.findall(r'\w{3,}', node.plain(question)) if word not in SKIP}
    scored = []
    try:
        for path in notes():
            text = path.read_text(encoding='utf-8', errors='replace')
            body, name = node.plain(text), node.plain(path.stem)
            score = sum(body.count(word) for word in words) + 5 * sum(word in name for word in words)
            if score:
                scored.append((score, path.stem, text))
    except OSError:
        return node.t('No pude leer tus notas: ¿está conectada la carpeta de tu bóveda?')
    if not scored:
        return node.t('No encontré nada sobre eso en tus notas.')
    best = sorted(scored, reverse=True)[:5]
    context = ''.join(f'\n### Nota: {name}\n{text[:2500]}\n' for _, name, text in best)
    try:
        answer = node.cloud([
            {'role': 'system', 'content': node.system(' Te paso notas del usuario de su Obsidian. Responde su pregunta '
                                                      'solo con lo que dicen; si no está, dilo. Menciona de qué nota '
                                                      'sale. Si es una lista larga, puedes usar renglones.')},
            {'role': 'user', 'content': f'{context[:8000]}\n\nPregunta: {question}'}],  # 8000: el cupo de la IA gratis
            wait=20, max_tokens=600)
        return node.tidy(answer.get('content'))
    except ConnectionError:  # sin nube (o /opsec): la nota que más tiene que ver, tal cual
        _, name, text = best[0]
        others = ', '.join(other for _, other, _ in best[1:])
        return node.t('En tu nota {name}: {dato}', name=name, dato=text.strip()[:600]) + (node.t('\n(También lo mencionan: {others}.)', others=others) if others else '')


def save_answer(args, where):
    """Guarda la última respuesta de Node como una nota en Notas/."""
    last = next((turn['content'] for turn in reversed(node.HISTORY) if turn['role'] == 'assistant'), '')
    if not last:
        return node.t('No tengo ninguna respuesta reciente para guardar.')
    title = re.sub(r'[\\/:*?"<>|#^\[\]]', '', (args.get('title') or '').strip()) or f'Nota {datetime.now():%Y-%m-%d %H%M}'
    path = node.VAULT / 'Notas' / f'{title}.md'
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as out:
            out.write(f'{last}\n\n_Guardado por Node el {datetime.now():%d/%m/%Y %H:%M}._\n\n')
    except OSError:
        return node.t('No pude guardarlo: ¿está conectada la carpeta de tu bóveda?')
    return node.t('Guardado en Obsidian como {title}.', title=title)


def setup(node_):
    global node
    node = node_
    if not node.VAULT:  # sin memoria (se elige en /setup): sin estas habilidades
        return
    node.add(node.tool('obsidian_note', 'Anota algo rápido en Obsidian ("anota que...", "apunta..."), cuando no es una '
                       'tarea por hacer. text: la nota.', text={'type': 'string'}), note, r'anot|apunt|nota|obsidian')
    node.add(node.tool('obsidian_list', 'Listas de Obsidian (súper, películas por ver...). action: add (agregar items, '
                       'separados por comas), show (decir qué hay) o done (tachar items). list: el nombre de la lista.',
                       action={'type': 'string', 'enum': ['add', 'show', 'done']}, list={'type': 'string'},
                       items={'type': 'string'}), lists, r'lista|agreg|super|compr|tach')
    node.add(node.tool('tasks', 'Tareas del usuario en Obsidian. action: add (una tarea nueva: "tengo que...", "hay que'
                       '..."; text: la tarea corta, sin la fecha; due: cuándo vence con las palabras del usuario, sin '
                       'calcular nada ("el lunes", "mañana", "el 20", "20 de diciembre"), o vacío si no dijo cuándo), '
                       'done (la terminó; text: '
                       'una palabra clave de la tarea) o list ("¿qué tengo pendiente?"; text y due vacíos).',
                       action={'type': 'string', 'enum': ['add', 'done', 'list']}, text={'type': 'string'},
                       due={'type': 'string'}), tasks,
             r'tarea|pendiente|tengo que|hay que|debo|entregar|vence|termine|hice|ya (?:entregue|mande|pague|llame)|tach')
    node.add(node.tool('obsidian_ask', 'Responde con las notas de Obsidian del usuario: "¿qué anoté sobre X?", "¿qué dicen '
                       'mis notas de...?", "busca en mis notas". question: la pregunta tal cual.',
                       question={'type': 'string'}), ask, r'nota|anote|anotado|obsidian|apunte|apuntado')
    node.add(node.tool('obsidian_save', 'Guarda tu respuesta anterior como una nota de Obsidian ("guárdalo en Obsidian", '
                       '"guarda eso como receta"). title: el nombre de la nota, o vacío.',
                       title={'type': 'string'}), save_answer, r'guarda|obsidian|nota')
