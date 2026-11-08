"""Google: Gmail y Calendar.
"¿tengo mails sin leer?", "¿algo importante en el correo?", "¿qué dice el último mail de Mercado Libre?",
"¿qué tengo hoy?", "¿qué tengo esta semana?", "agéndame el dentista el martes a las 10".
Solo lee tu correo (no puede mandar ni borrar) y puede leer y crear eventos en tu calendario.

Una sola vez:
1. Crea un cliente OAuth "App de escritorio" en Google Cloud (ver plugins/LEEME.md), descarga el JSON
   y guárdalo como google_cliente.json en la carpeta de Node Assistant.
2. Autoriza:  .venv\\Scripts\\python.exe plugins\\google.py   (se abre el navegador; elige tu cuenta y acepta)
El permiso queda en google_token.json: no lo compartas (es como una contraseña de tu correo).
"""
import base64
import hashlib
import http.server
import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CLIENT, TOKEN = HERE / 'google_cliente.json', HERE / 'google_token.json'
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/calendar.events']
node = None
ACCESS = {'token': None, 'until': 0}


def client():
    data = json.loads(CLIENT.read_text(encoding='utf-8'))
    return data.get('installed') or data.get('web')


def post(url, fields):
    request = urllib.request.Request(url, urllib.parse.urlencode(fields).encode(),
                                     {'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def access():
    """Un permiso de acceso vigente (dura 1 hora; se renueva solo con el guardado)."""
    if ACCESS['until'] > time.time() + 60:
        return ACCESS['token']
    if not TOKEN.exists():
        raise PermissionError(node.t('Falta conectar Google: /settings → Servicios → Conectar Google.'))
    app = client()
    answer = post('https://oauth2.googleapis.com/token', {
        'client_id': app['client_id'], 'client_secret': app['client_secret'], 'grant_type': 'refresh_token',
        'refresh_token': json.loads(TOKEN.read_text(encoding='utf-8'))['refresh_token']})
    ACCESS.update(token=answer['access_token'], until=time.time() + answer['expires_in'])
    return ACCESS['token']


def api(url, body=None):
    request = urllib.request.Request(url, json.dumps(body).encode() if body else None,
                                     {'Authorization': f'Bearer {access()}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


GMAIL = 'https://gmail.googleapis.com/gmail/v1/users/me/messages'


def headers(message):
    found = {item['name'].lower(): item['value'] for item in message['payload'].get('headers', [])}
    sender = re.sub(r'\s*<.*>', '', found.get('from', '')).strip('" ') or found.get('from', '')
    return sender, found.get('subject', '(sin asunto)')


def body_text(part):
    """El texto del mail (la parte de texto plano, o el HTML sin etiquetas)."""
    if part.get('mimeType') == 'text/plain' and part.get('body', {}).get('data'):
        return base64.urlsafe_b64decode(part['body']['data'] + '==').decode('utf-8', 'replace')
    texts = [body_text(child) for child in part.get('parts', [])]
    if any(texts):
        return next(text for text in texts if text)
    if part.get('mimeType') == 'text/html' and part.get('body', {}).get('data'):
        html = base64.urlsafe_b64decode(part['body']['data'] + '==').decode('utf-8', 'replace')
        return re.sub(r'\s+', ' ', re.sub(r'<style.*?</style>|<[^>]+>', ' ', html, flags=re.S))
    return ''


def gmail(args, where):
    action, query = args.get('action') or 'unread', (args.get('query') or '').strip()
    search = {'unread': 'is:unread in:inbox', 'important': 'is:unread is:important'}.get(action, query or 'in:inbox')
    found = api(f'{GMAIL}?maxResults=5&q={urllib.parse.quote(search)}')
    ids = [item['id'] for item in found.get('messages', [])]
    if not ids:
        return {'unread': 'No tienes mails sin leer.', 'important': 'No hay nada importante sin leer.'}.get(
            action, 'No encontré mails así.')
    if action == 'read':  # el primero que coincide, resumido por la IA
        message = api(f'{GMAIL}/{ids[0]}?format=full')
        sender, subject = headers(message)
        text = (body_text(message['payload']) or message.get('snippet', ''))[:3500]
        summary = node.tidy(node.cloud([{'role': 'user', 'content': 'Resume este mail en español en 2 o 3 frases, '
                                         f'para leerlo en voz alta:\n\nDe: {sender}\nAsunto: {subject}\n\n{text}'}]
                                       ).get('content'))
        return node.t('De {sender}, "{subject}": {summary}', sender=sender, subject=subject, summary=summary)
    total = found.get('resultSizeEstimate', len(ids))
    listed = '; '.join('{} — {}'.format(*headers(api(f'{GMAIL}/{i}?format=metadata&metadataHeaders=From'
                                                     f'&metadataHeaders=Subject'))) for i in ids)
    head = {'unread': f'Tienes {total} sin leer', 'important': f'Tienes {total} importantes sin leer'}.get(
        action, 'Encontré')
    return f'{head}: {listed}.'


CALENDAR = 'https://www.googleapis.com/calendar/v3/calendars/primary/events'


def calendar(args, where):
    if args.get('action') == 'add':
        title, start = (args.get('title') or '').strip(), (args.get('start') or '').strip()
        try:
            begin = datetime.fromisoformat(start)
        except ValueError:
            return node.t('¿Para qué día y hora lo agendo?')
        end = begin + timedelta(minutes=int(args.get('minutes') or 60))
        zone = api('https://www.googleapis.com/calendar/v3/users/me/settings/timezone')['value']
        api(CALENDAR, {'summary': title or 'Evento', 'start': {'dateTime': begin.isoformat(), 'timeZone': zone},
                       'end': {'dateTime': end.isoformat(), 'timeZone': zone}})
        return node.t('Agendé {title} el {begin} a las {begin2}.', title=title, begin=format(begin, '%d/%m'), begin2=format(begin, '%H:%M'))
    days = max(int(args.get('days') or 1), 1)
    start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    events = api(f"{CALENDAR}?singleEvents=true&orderBy=startTime&maxResults=15"
                 f"&timeMin={urllib.parse.quote(start.isoformat())}"
                 f"&timeMax={urllib.parse.quote((start + timedelta(days=days)).isoformat())}").get('items', [])
    if not events:
        return node.t('No tienes nada agendado hoy.') if days == 1 else node.t('No tienes nada en los próximos {days} días.', days=days)
    week = [day[:3] for day in node.DAYS]
    said = []
    for event in events:
        when = event['start'].get('dateTime') or event['start'].get('date')
        moment = datetime.fromisoformat(when)
        clock = f'{moment:%H:%M}' if 'T' in when else node.t('todo el día')
        said.append(f"{clock} {event.get('summary', '(sin título)')}" if days == 1 else
                    f"{week[moment.weekday()]} {moment.day} {clock} {event.get('summary', '(sin título)')}")
    return (node.t('Hoy tienes: ') if days == 1 else node.t('Tienes: ')) + '; '.join(said) + '.'


def safe(handler):
    def run(args, where):
        try:
            return handler(args, where)
        except PermissionError as error:
            return str(error)
        except urllib.error.HTTPError as error:
            return node.t('Google respondió con un error ({code}). Si dice 401 o 403, vuelve a autorizar.', code=error.code)
    return run


def setup(node_):
    global node
    node = node_
    node.add(node.tool('gmail', 'Lee el Gmail del usuario (no puede mandar ni borrar). action: unread (mails sin leer), '
                       'important (importantes sin leer), search (buscar con query, sintaxis de Gmail como '
                       '"from:mercadolibre") o read (resumir el primer mail que coincide con query).',
                       action={'type': 'string', 'enum': ['unread', 'important', 'search', 'read']},
                       query={'type': 'string'}), safe(gmail), r'mail|correo|gmail|bandeja')
    node.add(node.tool('calendar', 'Google Calendar. action: agenda (qué tiene; days = 1 hoy, 7 la semana) o add '
                       '(agendar title en start, fecha y hora local "YYYY-MM-DDTHH:MM", que dura minutes).',
                       action={'type': 'string', 'enum': ['agenda', 'add']}, days={'type': 'integer'},
                       title={'type': 'string'}, start={'type': 'string'}, minutes={'type': 'integer'}),
             safe(calendar), r'agenda|calendario|evento|reunion|cita|turno|que tengo|esta semana')


def authorize():
    """Abre el navegador para que aceptes los permisos, y guarda el permiso duradero en google_token.json."""
    app, result = client(), {}
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    state = secrets.token_urlsafe(16)

    class Back(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if query.get('state') == state:
                result.update(query)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write('<h2>Listo, Node Assistant ya tiene permiso. Puedes cerrar esta pestaña.</h2>'.encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(('127.0.0.1', 0), Back)
    redirect = f'http://127.0.0.1:{server.server_port}'
    webbrowser.open('https://accounts.google.com/o/oauth2/v2/auth?' + urllib.parse.urlencode({
        'client_id': app['client_id'], 'redirect_uri': redirect, 'response_type': 'code', 'scope': ' '.join(SCOPES),
        'code_challenge': challenge, 'code_challenge_method': 'S256', 'access_type': 'offline', 'prompt': 'consent',
        'state': state}))
    print('Se abrió el navegador: elige tu cuenta de Google y acepta los permisos…')
    while 'code' not in result and 'error' not in result:
        server.handle_request()
    if 'error' in result:
        raise SystemExit(f"Google no dio permiso: {result['error']}")
    answer = post('https://oauth2.googleapis.com/token', {
        'client_id': app['client_id'], 'client_secret': app['client_secret'], 'code': result['code'],
        'code_verifier': verifier, 'grant_type': 'authorization_code', 'redirect_uri': redirect})
    TOKEN.write_text(json.dumps({'refresh_token': answer['refresh_token']}), encoding='utf-8')
    print('Listo: permiso guardado en google_token.json.')


if __name__ == '__main__':
    authorize()
