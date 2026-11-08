"""Bases tipo Notion en Obsidian, con el sistema de la plantilla de kepano (Categories/ y Templates/Bases/).
"agrega Dune a mis películas, le doy 9", "ya vi Arrival", "¿qué películas me faltan ver?",
"anota un gasto de 300 en comida", "¿cuánto gasté este mes?", "¿cuánto gasté en comida?".
Cada cosa es una nota en References/ con sus propiedades arriba, como las de kepano: categories: [[Movies]],
rating (de 1 a 7, como usa kepano: Node convierte tu nota de 1 a 10), last (cuándo la viste o leíste), year...
Así aparece sola en Categories/Movies y en sus vistas (Favoritas, Por ver, Última vista).
Una colección que kepano no trae (Gastos, por ejemplo) se crea sola: Categories/Gastos.md y Templates/Bases/Gastos.base.
"""
import re
from datetime import date

import yaml

node = None
# Lo que dices -> la categoría de la plantilla de kepano
CATEGORIES = {'pelicula': 'Movies', 'peli': 'Movies', 'libro': 'Books', 'videojuego': 'Games', 'juegos? de mesa':
              'Board games', 'juego': 'Games', 'serie': 'Shows', 'receta': 'Recipes', 'persona': 'People', 'contacto':
              'People', 'lugar': 'Places', 'viaje': 'Trips', 'episodio': 'Podcast episodes', 'podcast': 'Podcasts',
              'album': 'Albums', 'disco': 'Albums', 'proyecto': 'Projects', 'empresa': 'Companies', 'evento': 'Events',
              'reunion': 'Meetings', 'producto': 'Products', 'articulo': 'Clippings'}
# Propiedades en español -> las de kepano (las demás quedan como las dijiste)
KEYS = {'puntuacion': 'rating', 'puntaje': 'rating', 'nota': 'rating', 'calificacion': 'rating', 'ano': 'year',
        'fecha': 'date', 'genero': 'genre', 'autor': 'author', 'director': 'director', 'paginas': 'pages',
        'duracion': 'runtime', 'precio': 'price', 'estado': 'status', 'direccion': 'address', 'telefono': 'phone',
        'cumpleanos': 'birthday', 'cocina': 'cuisine', 'ingredientes': 'ingredients'}
DONE = r'vist[oa]s?|leid[oa]s?|jugad[oa]s?|escuchad[oa]s?|terminad[oa]s?|hecho|visitad[oa]'  # -> last: hoy


def category(collection):
    words = node.plain(collection).strip()
    for spanish, english in CATEGORIES.items():
        if re.search(rf'\b{spanish}(?:s|es)?\b', words):
            return english
    for page in (node.VAULT / 'Categories').glob('*.md'):  # "movies", "Gastos": una que ya existe
        if node.plain(page.stem) == words:
            return page.stem
    return re.sub(r'[\\/:*?"<>|#^\[\]]', '', collection).strip().capitalize() or node.t('General')


def file_name(title):
    return re.sub(r'[\\/:*?"<>|#^\[\]]', '', title).strip()


def number(value):
    """'$1.200,50' -> 1200.5; si no es un número, None."""
    text = str(value).strip().replace('$', '').replace(' ', '')
    if re.fullmatch(r'-?\d{1,3}(\.\d{3})+(,\d+)?', text):  # 1.200,50
        text = text.replace('.', '').replace(',', '.')
    try:
        result = float(text.replace(',', '.'))
    except ValueError:
        return None
    return int(result) if result.is_integer() else result


def parse(fields):
    """'puntuación: 9; estado: visto' (o con = y comas) -> {'puntuación': 9, 'estado': 'visto'}."""
    found = {}
    for part in re.split(r'[;\n]|,(?=\s*[^,;:=]+[:=])', fields or ''):  # la coma separa solo si sigue "clave:"
        key, sep, value = re.split(r'([:=])', part, maxsplit=1) if re.search(r'[:=]', part) else (part, '', '')
        key, value = key.strip().lower(), value.strip()
        if key and sep:
            found[key] = number(value) if number(value) is not None else value
    return found


def kepano(props):
    """Las propiedades dichas en español, como las guarda kepano. La puntuación de 1 a 10 pasa a su escala de 1 a 7."""
    result = {}
    for key, value in props.items():
        name = KEYS.get(node.plain(key), key)
        if name == 'rating' and isinstance(value, (int, float)):
            value = max(1, min(7, round(value * 7 / 10)))
        if name == 'status' and re.search(r'por |pendiente|sin ', node.plain(str(value))):
            continue  # "por ver": en kepano es no tener last ni rating (así sale en su vista "To-watch")
        if name == 'status' and re.fullmatch(DONE, node.plain(str(value))):
            name, value = 'last', date.today()
        elif name in ('date', 'last', 'birthday'):
            try:
                value = date.fromisoformat(str(value))
            except ValueError:
                pass
        result[name] = value
    return result


def read(path):
    """Las propiedades de una nota (lo que va entre los --- de arriba) y el resto del texto."""
    text = path.read_text(encoding='utf-8')
    match = re.match(r'---\n(.*?)\n---\n?(.*)', text, re.S)
    if not match:
        return {}, text
    try:
        return yaml.safe_load(match[1]) or {}, match[2]
    except yaml.YAMLError:  # escrito a mano con algún error: se trata como nota sin propiedades
        return {}, text


def write(path, props, body=''):
    head = yaml.safe_dump(props, allow_unicode=True, sort_keys=False, default_flow_style=False).strip()
    path.write_text(f'---\n{head}\n---\n{body}', encoding='utf-8')


def items(name):
    """Las notas de la bóveda con esa categoría (también las de los ejemplos de kepano): [(ruta, propiedades)]."""
    link, found = f'[[{name}]]', []
    for path in node.VAULT.rglob('*.md'):
        if '.obsidian' in path.parts or 'Templates' in path.parts:
            continue
        try:
            props = read(path)[0]
        except (OSError, UnicodeDecodeError):
            continue
        if isinstance(props, dict) and link in (props.get('categories') or []):
            found.append((path, props))
    return sorted(found, key=lambda item: item[0].stem.lower())


def ensure_category(name, keys):
    """Una categoría que kepano no trae (Gastos): su página y su tabla, como las de él."""
    page = node.VAULT / 'Categories' / f'{name}.md'
    if page.exists():
        return
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(f'---\ntags:\n  - categories\n---\n\n![[{name}.base]]\n', encoding='utf-8')
    columns = '\n'.join(f'      - {key}' for key in ['file.name', *keys])
    base = node.VAULT / 'Templates' / 'Bases' / f'{name}.base'
    base.parent.mkdir(parents=True, exist_ok=True)
    base.write_text(f'filters:\n  and:\n    - categories.contains(link("{name}"))\n    - \'!file.name.contains("Template")\'\n'
                    f'views:\n  - type: table\n    name: {name}\n    order:\n{columns}\n', encoding='utf-8')


def matches(props, where):
    """where: 'estado: por ver; categoría: comida' (cada valor, contenido y sin tildes)."""
    plain = {node.plain(key): node.plain(str(value)) for key, value in props.items()}  # "categoria" = "categoría"
    for key, value in parse(where).items():
        name = node.plain(KEYS.get(node.plain(key), key))
        if name == 'status' and re.search(r'por |pendiente|sin ', node.plain(str(value))):  # "por ver": sin ver ni puntuar
            if props.get('last') or props.get('rating'):
                return False
        elif node.plain(str(value)) not in plain.get(name, plain.get(node.plain(key), '')):
            return False
    return True


def show(path, props):
    said = []
    if props.get('rating'):
        said.append(node.t('{rating} de 7', rating=props['rating']))
    if props.get('last'):
        said.append(node.t('última vez {last}', last=props['last']))
    plain = lambda value: re.sub(r'\[\[|\]\]', '', ', '.join(map(str, value)) if isinstance(value, list) else str(value))
    said += [f'{key} {plain(value)}' for key, value in props.items()
             if key not in ('categories', 'created', 'rating', 'last', 'tags', 'cover', 'imdbId', 'via')
             and value not in (None, '', [])]
    return path.stem + (f" ({', '.join(said)})" if said else '')


def base(args, where):
    action, collection = args.get('action') or 'list', (args.get('collection') or '').strip()
    title, filters = file_name(args.get('item') or ''), args.get('where') or ''
    if not collection:
        return node.t('¿En qué colección? Por ejemplo películas, libros o gastos.')
    name = category(collection)
    try:
        found = items(name)
        if action in ('add', 'update'):
            props = kepano(parse(args.get('fields')))
            if not title:
                return node.t('¿Cómo se llama lo que agrego?')
            same = [path for path, _ in found if node.plain(path.stem) == node.plain(title)]
            close = same or [path for path, _ in found if node.plain(title) in node.plain(path.stem)]
            if action == 'update' and not close:
                return node.t('No encontré {title} en {name}.', title=title, name=name)
            if action == 'update' or (same and not props.get('date')):  # "agrega Dune" si ya está: la actualiza
                path = close[0]
            else:  # algo nuevo; un gasto con el mismo nombre es otro gasto, no se pisa
                path, copy = node.VAULT / 'References' / f'{title}.md', 2
                while path.exists():
                    path, copy = node.VAULT / 'References' / f'{title} ({copy}).md', copy + 1
            new = not path.exists()
            old, body = ({'categories': [f'[[{name}]]'], 'created': date.today()}, '') if new else read(path)
            if 'last' in props:  # ya la viste: se va el "por ver" viejo
                old.pop('status', None)
            path.parent.mkdir(parents=True, exist_ok=True)
            write(path, {**old, **props}, body)
            ensure_category(name, list(props))
            changed = ', '.join(f'{key} {value}' for key, value in parse(args.get('fields')).items())  # como lo dijiste
            done = node.t('Agregué {item} en {name}', item=path.stem, name=name) if new else \
                node.t('Actualicé {item} en {name}', item=path.stem, name=name)
            return done + (f': {changed}.' if changed else '.')
        rows = [(path, props) for path, props in found if matches(props, filters)]
        since = (args.get('since') or '').strip()
        if since:  # por fecha: la propiedad date si la tiene, si no, cuándo se creó
            rows = [(path, props) for path, props in rows if str(props.get('date') or props.get('created', '')) >= since]
        if action == 'sum':
            key = node.plain(KEYS.get(node.plain(args.get('field') or ''), args.get('field') or ''))
            values = [number(value) for _, props in rows for prop, value in props.items() if node.plain(prop) == key]
            values = [value for value in values if value is not None]
            if not values:
                return node.t('No encontré valores de {dato} en {name}.', dato=args.get("field"), name=name)
            total = f'{sum(values):.2f}'.rstrip('0').rstrip('.')  # 1950.5, no 1.95e+03
            return (node.t('Suma {total} en {count} registros de {name}.', total=total, count=len(values), name=name)
                    if len(values) != 1 else node.t('Suma {total} en 1 registro de {name}.', total=total, name=name))
    except OSError:
        return node.t('No pude abrir tu bóveda: ¿está conectada la carpeta de tu bóveda?')
    if not rows:
        return node.t('No hay nada en {name}', name=name) + (node.t(' con eso.') if filters or since else node.t(' todavía.'))
    listing = '\n'.join(f'• {show(path, props)}' for path, props in rows[:30])
    return f'{name}, {len(rows)}:\n{listing}' + (node.t('\ny {dato} más.', dato=len(rows) - 30) if len(rows) > 30 else '')


def setup(node_):
    global node
    node = node_
    if not node.VAULT:  # sin memoria (se elige en /setup): sin estas habilidades
        return
    node.add(node.tool(
        'base', 'Bases de datos del usuario en Obsidian, como en Notion: colecciones (películas, libros, juegos, series, '
        'recetas, lugares, gastos...) donde cada cosa tiene propiedades. action: add (agregar item con fields), update '
        '(cambiar fields de algo que ya existe: "ya la vi", "le doy 9 a Dune"), list (mostrar; filtra con where) o sum '
        '(sumar la propiedad field, para "¿cuánto gasté?"). collection: el nombre en plural ("Películas", "Gastos"). '
        'item: el nombre de la cosa; para un gasto, una descripción corta. fields: propiedades "clave: valor; clave: '
        'valor" en español (puntuación de 1 a 10 tal como la dijo, estado como visto, leído, por ver; año, género, '
        'autor, director, monto, categoría, fecha YYYY-MM-DD...); un gasto siempre con monto, categoría y fecha. where: '
        'filtro "clave: valor" ("estado: por ver") o vacío. since: fecha YYYY-MM-DD desde la que cuenta ("este mes" = '
        'el día 1) o vacío. field: la propiedad a sumar, o vacío.',
        action={'type': 'string', 'enum': ['add', 'update', 'list', 'sum']}, collection={'type': 'string'},
        item={'type': 'string'}, fields={'type': 'string'}, where={'type': 'string'}, since={'type': 'string'},
        field={'type': 'string'}), base,
        r'pelicula|serie|libro|juego|gast|pague|compre|cost|coleccion|base|tabla|puntua|le doy|vista|visto|leido|receta|anime|contacto|lugar|viaje|podcast|disco|album')
