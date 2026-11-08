"""Wikipedia: Resume un artículo de Wikipedia en español sobre lo que pidas. (Issue de prueba de la Action: se cierra sin aceptar.)
Ejemplos: '¿qué dice Wikipedia sobre los agujeros negros?'
Armado con el generador de plugins de Node (tools/crear_plugin.py).
"""
import urllib.parse
import urllib.request

node = None
NAME = 'Wikipedia'
URL = 'https://es.wikipedia.org/api/rest_v1/page/summary/{consulta}'  # {consulta} se reemplaza por lo que pediste
KEY = ''  # la variable de Windows con la clave ('' = no hace falta)


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
            {'role': 'user', 'content': 'Pedido: ' + query + '\n\nLo que devolvió ' + NAME + ':\n' + data[:6000]}],
            wait=15)
        return node.tidy(answer.get('content'))
    except ConnectionError:  # sin nube: los datos tal cual (cortos)
        return data[:300]


def setup(node_):
    global node
    node = node_
    node.add(node.tool('wikipedia', 'Resume un artículo de Wikipedia en español sobre lo que pidas. (Issue de prueba de la Action: se cierra sin aceptar.) query: lo que pidió el usuario, para buscarlo ahí.', query={'type': 'string'}), run, 'wikipedia')
