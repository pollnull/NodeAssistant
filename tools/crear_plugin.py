"""Arma un plugin de Node a partir de unos pocos datos, y avisa si la página probablemente no va a funcionar.

En tu PC (te hace las preguntas y lo deja en plugins/):
    .venv\\Scripts\\python.exe tools\\crear_plugin.py
En GitHub lo corre la Action "Nuevo plugin" con lo que escribiste en el issue (ver .github/workflows/nuevo-plugin.yml):
    python tools/crear_plugin.py --issue issue.md --report informe.md --github-output $GITHUB_OUTPUT

Tres tipos de plugin, sin escribir código:
- api:     consulta una dirección web que devuelve datos (JSON) y la IA te cuenta lo que pediste con esos datos.
- buscar:  abre en el navegador una página con tu búsqueda (por ejemplo, una tienda o un diccionario).
- abrir:   abre siempre lo mismo: un programa, una carpeta o una página.
Lo que escribe la persona solo se guarda como texto dentro del plugin (nunca como código), así que el plugin armado
es siempre esta plantilla. Igual, revisa el pull request antes de aceptarlo.
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path
from string import Template

HERE = Path(__file__).resolve().parent.parent
KINDS = {'api': 'Consultar una API web (devuelve datos JSON)', 'buscar': 'Abrir una página con una búsqueda',
         'abrir': 'Abrir un programa, una carpeta o una página'}
# Sitios que casi siempre fallan si Node los consulta solo: piden iniciar sesión, bloquean robots o no tienen API abierta.
TROUBLE = {
    'instagram.com': 'pide iniciar sesión y bloquea a los programas; su API es solo para cuentas de empresa',
    'facebook.com': 'pide iniciar sesión y bloquea a los programas',
    'x.com': 'pide iniciar sesión; su API es de pago', 'twitter.com': 'pide iniciar sesión; su API es de pago',
    'tiktok.com': 'bloquea a los programas y arma la página con JavaScript',
    'linkedin.com': 'pide iniciar sesión y bloquea a los programas',
    'amazon.': 'bloquea a los programas con captchas', 'netflix.com': 'pide iniciar sesión',
    'google.com/search': 'Google bloquea las búsquedas automáticas (usa el tipo "buscar" para solo abrirla)',
    'reddit.com': 'su API pide una cuenta de desarrollador desde 2023',
    'spotify.com': 'pide iniciar sesión (OAuth); para abrir Spotify ya está el de fábrica',
    'whatsapp.com': 'no tiene una API abierta para cuentas personales',
    'chatgpt.com': 'pide iniciar sesión y bloquea a los programas', 'openai.com': 'pide una clave de API de pago',
    'mercadolibre.': 'su API pide una aplicación registrada y un token',
}


# --- Revisar la página ----------------------------------------------------------------------------------------------

def check(kind, url, key):
    """Avisos de por qué podría no andar. Prueba la página de verdad (con 'test' como búsqueda)."""
    warnings = []
    lower = url.lower()
    for site, why in TROUBLE.items():
        if site in lower:
            warnings.append(f'**{site.strip(".")}**: {why}. Lo más probable es que no funcione.')
    if lower.startswith('http://'):
        warnings.append('Usa **http** sin la s: lo que viaja no va cifrado.')
    if kind != 'api' or not lower.startswith(('http://', 'https://')):  # abrir en el navegador: lo visita una persona
        return warnings
    probe = url.replace('{consulta}', 'test')
    try:  # robots.txt: solo si existe de verdad (si el sitio da error, no se adivina)
        with urllib.request.urlopen(urllib.request.Request(urllib.parse.urljoin(probe, '/robots.txt'), headers={
                'User-Agent': 'NodeAssistant'}), timeout=10) as response:
            robots = urllib.robotparser.RobotFileParser()
            robots.parse(response.read(100_000).decode('utf-8', 'replace').splitlines())
        if not robots.can_fetch('NodeAssistant', probe):
            warnings.append('Su robots.txt **pide que los programas no recorran esa dirección**. Es una regla pensada para buscadores, pero conviene respetarla y revisar los términos del sitio.')
    except (OSError, UnicodeDecodeError):
        pass
    request = urllib.request.Request(probe, headers={'User-Agent': 'NodeAssistant', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            kind_of, final, body = response.headers.get('Content-Type', ''), response.geturl(), response.read(50_000)
    except urllib.error.HTTPError as error:
        server = (error.headers.get('Server') or '').lower()
        if error.headers.get('cf-mitigated') or ('cloudflare' in server and error.code in (403, 503)):
            warnings.append('La protege **Cloudflare** contra robots: es muy probable que bloquee a Node.')
        elif error.code in (401, 403):
            warnings.append(f'Respondió **{error.code}**: pide una clave o iniciar sesión'
                            + ('.' if not key else ', y la prueba se hizo sin tu clave (puede andar con ella).'))
        elif error.code == 429:
            warnings.append('Respondió **429**: limita cuántas consultas aceptas; puede fallar seguido.')
        else:
            warnings.append(f'Respondió con un error **{error.code}** al probarla con "test".')
        return warnings
    except OSError as error:
        warnings.append(f'No pude conectarme para probarla ({getattr(error, "reason", error)}).')
        return warnings
    if re.search(r'/(login|signin|sign-in|accounts?)\b', final.lower()):
        warnings.append('Te **manda a iniciar sesión**: sin cuenta no va a devolver datos.')
    if 'json' not in kind_of.lower():
        text = body.decode('utf-8', 'replace').lower()
        if 'captcha' in text or 'are you a robot' in text:
            warnings.append('Muestra un **captcha**: bloquea a los programas.')
        elif text.count('<script') > 10 and len(re.sub(r'<[^>]+>', '', text).split()) < 200:
            warnings.append('Es una página que se arma con **JavaScript**: Node solo ve el esqueleto, casi sin datos.')
        else:
            warnings.append('Devuelve una **página web**, no datos (JSON). Puede andar, pero la respuesta va a ser '
                            'menos precisa. Si el sitio tiene una API, usa esa dirección.')
    return warnings


# --- Armar el plugin ------------------------------------------------------------------------------------------------

HEADER = Template('''"""$title: $description
Ejemplos: $examples
Armado con el generador de plugins de Node (tools/crear_plugin.py).$key_doc
"""
''')
API = Template('''import urllib.parse
import urllib.request

node = None
NAME = $name
URL = $url  # {consulta} se reemplaza por lo que pediste
KEY = $key  # la variable de Windows con la clave ('' = no hace falta)


def run(args, where):
    query = (args.get('query') or '').strip()
    headers = {'User-Agent': 'NodeAssistant', 'Accept': 'application/json'}
    if KEY:
        if not node.secret(KEY):
            return node.t('Falta la clave {key}: guárdala en las variables de Windows y reinicia Node.', key=KEY)
        headers['Authorization'] = 'Bearer ' + node.secret(KEY)
    request = urllib.request.Request(URL.replace('{consulta}', urllib.parse.quote(query)), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = response.read(200_000).decode('utf-8', 'replace')
    except OSError as error:
        return node.t('No pude consultar {site}: {error}.', site=NAME, error=getattr(error, 'reason', error))
    try:
        answer = node.cloud([
            {'role': 'system', 'content': node.system(' Te paso lo que devolvió una página web. Con eso, responde lo '
                                                      'que pidió el usuario; si no está, dilo.')},
            {'role': 'user', 'content': 'Pedido: ' + query + '\\n\\nLo que devolvió ' + NAME + ':\\n' + data[:6000]}],
            wait=15)
        return node.tidy(answer.get('content'))
    except ConnectionError:  # sin nube: los datos tal cual (cortos)
        return data[:300]


def setup(node_):
    global node
    node = node_
    node.add(node.tool($tool, $tool_description, query={'type': 'string'}), run, $words)
''')
SEARCH = Template('''import urllib.parse
import webbrowser

node = None
NAME = $name
URL = $url  # {consulta} se reemplaza por lo que pediste


def run(args, where):
    query = (args.get('query') or '').strip()
    webbrowser.open(URL.replace('{consulta}', urllib.parse.quote(query)))
    return node.t('Buscando {query} en {site}.', query=query, site=NAME)


def setup(node_):
    global node
    node = node_
    node.add(node.tool($tool, $tool_description, query={'type': 'string'}), run, $words)
''')
OPEN = Template('''import os
import webbrowser

node = None
NAME = $name
TARGET = $url  # lo que se abre: un programa, una carpeta o una página


def run(args, where):
    if TARGET.startswith(('http://', 'https://')):
        webbrowser.open(TARGET)
    else:
        os.startfile(os.path.expandvars(TARGET))
    return node.t('Abriendo {site}.', site=NAME)


def setup(node_):
    global node
    node = node_
    node.add(node.tool($tool, $tool_description), run, $words)
''')


def plain(text):
    import unicodedata
    return unicodedata.normalize('NFD', text.lower()).encode('ascii', 'ignore').decode()


def build(data):
    """data: name, description, examples, kind, url, key, words. Devuelve (nombre del archivo, código)."""
    name = re.sub(r'[^a-z0-9_]', '_', plain(data['name'])).strip('_')[:40] or 'plugin'
    kind = data['kind'] if data['kind'] in KINDS else 'api'
    url = data['url'].strip()
    if kind != 'abrir' and not re.match(r'https?://', url):
        raise ValueError('La dirección tiene que empezar con https://')
    if kind in ('api', 'buscar') and '{consulta}' not in url:
        raise ValueError('La dirección tiene que tener {consulta} donde va lo que pides.')
    key = re.sub(r'[^A-Z0-9_]', '', data.get('key', '').upper())
    words = [plain(w).strip() for w in re.split(r'[,\n]', data.get('words', '')) if plain(w).strip()]
    words_regex = '|'.join(re.escape(w) for w in words)
    description = ' '.join(data['description'].split())[:400]
    examples = ' '.join(data.get('examples', '').split())[:300]
    say = {'api': ' query: lo que pidió el usuario, para buscarlo ahí.', 'buscar': ' query: lo que quiere buscar.',
           'abrir': ''}[kind]
    safe = lambda text: text.replace('\\', '/').replace('"', "'")  # en la explicación de arriba: solo texto
    code = HEADER.substitute(
        title=safe(data['name'].strip())[:60], description=safe(description), examples=safe(examples) or '—',
        key_doc=f'\nNecesita una clave en la variable de Windows {key} (guárdala y reinicia Node).' if key else '')
    code += (API if kind == 'api' else SEARCH if kind == 'buscar' else OPEN).substitute(
        name=repr(data['name'].strip()[:60]), url=repr(url), key=repr(key), tool=repr(name),
        tool_description=repr(description + say), words=repr(words_regex) if words_regex else 'None')
    compile(code, f'{name}.py', 'exec')  # que sea Python válido
    return name, code


# --- Leer los datos: del issue de GitHub o preguntando --------------------------------------------------------------

FIELDS = {'Nombre del plugin': 'name', 'Qué hace': 'description', 'Frases de ejemplo': 'examples', 'Tipo': 'kind',
          'Dirección': 'url', 'Clave': 'key', 'Palabras clave': 'words'}


def from_issue(text):
    """Las respuestas del formulario del issue (### Pregunta, y abajo la respuesta)."""
    data = {}
    for title, answer in re.findall(r'^### (.+?)\n+(.*?)(?=\n### |\Z)', text, re.S | re.M):
        field = next((key for label, key in FIELDS.items() if title.strip().startswith(label)), None)
        if field:
            answer = answer.strip()
            data[field] = '' if answer == '_No response_' else answer
    data['kind'] = next((kind for kind, text_ in KINDS.items() if data.get('kind', '').startswith(text_)), 'api')
    return data


def ask():
    print('Armemos un plugin de Node. Enter deja vacío lo opcional.\n')
    data = {'name': input('Nombre (por ejemplo "Diccionario"): '),
            'description': input('Qué hace, para que la IA sepa cuándo usarlo: '),
            'examples': input('Frases de ejemplo ("¿qué significa X?"): ')}
    for number, (kind, text) in enumerate(KINDS.items(), 1):
        print(f'  {number}. {text}')
    data['kind'] = list(KINDS)[int(input('Tipo (1, 2 o 3): ') or 1) - 1]
    data['url'] = input('Dirección (con {consulta} donde va lo que pides; para "abrir", el programa o la página): ')
    data['key'] = input('Variable de Windows con la clave, si la pide (opcional): ')
    data['words'] = input('Palabras que lo delatan, separadas por comas (opcional, ahorra cupo): ')
    return data


def report(name, data, warnings):
    lines = [f'## Plugin `{name}`', '', f"**Qué hace:** {data['description']}", f"**Tipo:** {KINDS[data['kind']]}",
             f"**Dirección:** `{data['url']}`", '']
    if warnings:
        lines += ['### ⚠️ Puede que no funcione', ''] + [f'- {w}' for w in warnings] + [
            '', 'La prueba se hizo desde los servidores de GitHub (o desde tu PC si lo corriste ahí): algunos sitios '
            'bloquean a esos servidores y no a una PC de casa, y al revés.', '']
    else:
        lines += ['### ✅ La página respondió bien en la prueba', '']
    lines += ['### Cómo instalarlo', '', f'1. Baja `plugins/{name}.py` (o acepta este pull request y actualiza Node).',
              '2. En Node: `/settings` → **Plugins** → **Instalar desde un archivo…** (o pega el enlace del archivo en '
              '**Instalar desde enlace**).', '3. Préndelo y toca **Guardar y reiniciar**.']
    return '\n'.join(lines)


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # la consola de Windows y los emojis
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--issue', help='el texto del issue (formulario "Nuevo plugin")')
    parser.add_argument('--report', help='dónde escribir el informe (Markdown)')
    parser.add_argument('--github-output', help='el archivo $GITHUB_OUTPUT de la Action')
    parser.add_argument('--plugins', default=str(HERE / 'plugins'), help='dónde dejar el plugin')
    args = parser.parse_args()
    data = from_issue(Path(args.issue).read_text(encoding='utf-8')) if args.issue else ask()
    try:
        name, code = build(data)
    except (ValueError, SyntaxError) as error:
        message = f'## No pude armar el plugin\n\n{error}\n\nCorrige el issue (editarlo vuelve a correr esto).'
        if args.report:
            Path(args.report).write_text(message, encoding='utf-8')
        print(message)
        if args.github_output:
            with open(args.github_output, 'a', encoding='utf-8') as out:
                out.write('ok=false\n')
        return 0 if args.issue else 1
    target = Path(args.plugins) / f'{name}.py'
    target.write_text(code, encoding='utf-8', newline='\n')  # LF, como el resto del repo
    warnings = check(data['kind'], data['url'], data.get('key'))
    text = report(name, data, warnings)
    if args.report:
        Path(args.report).write_text(text, encoding='utf-8')
    if args.github_output:
        with open(args.github_output, 'a', encoding='utf-8') as out:
            out.write(f'ok=true\nname={name}\n')
    print(text if args.issue else f'\nListo: {target}\n' + ('\n'.join('⚠️ ' + re.sub(r'\*\*', '', w) for w in warnings)
                                                            or '✅ La página respondió bien.') +
          '\nReinicia Node para usarlo.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
