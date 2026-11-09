"""Bot de Telegram: usa a Node desde el celular. Escríbele o mándale audios; hace lo mismo que en la PC y te contesta.
Los recordatorios también te llegan ahí, y "mándame una captura" te manda una foto de toda la pantalla.

Cada persona crea su propio bot (el token queda en las variables de Windows de su PC, nunca en el código), y se
vincula en /settings → Servicios → Telegram:
1. Con @BotFather -> /newbot crea tu bot y pega su token.
2. Toca "Vincular": Node muestra un código de 6 dígitos en tu pantalla. Mándaselo a tu bot y queda atado a tu chat.
Solo quien ve tu pantalla puede vincularse, y el código vence a los 10 minutos. Desde ahí el bot solo obedece a ese
chat: a cualquier otra persona no le responde nada. Funciona mientras la PC esté prendida y Node abierto.
"""
import json
import secrets
import threading
import time
import urllib.request

node = None
N_ = lambda texts: texts  # se traduce al mandarlo (node.t)
HELP = N_('Hola, soy Node. Escríbeme o mándame un audio y lo hago en la PC: abrir apps, música, volumen, el clima, '
        'recordatorios ("avísame en 10 minutos que…"), "mándame una captura", "bloquea la compu"… '
        'Escribe /help para ver los comandos.')


def api(method, **params):
    token = node.secret('TELEGRAM_BOT_TOKEN')
    request = urllib.request.Request(f'https://api.telegram.org/bot{token}/{method}', json.dumps(params).encode(),
                                     {'Content-Type': 'application/json', 'User-Agent': 'NodeAssistant'})
    with urllib.request.urlopen(request, timeout=70) as response:
        return json.load(response)['result']


def send(chat, text):
    for start in range(0, len(text), 4000):  # Telegram corta en 4096 caracteres
        api('sendMessage', chat_id=chat, text=text[start:start + 4000])


def send_photo(chat, data):
    token = node.secret('TELEGRAM_BOT_TOKEN')
    body, kind = node.multipart({'chat_id': chat}, 'captura.png', data, 'image/png', field='document')
    request = urllib.request.Request(f'https://api.telegram.org/bot{token}/sendDocument', body,
                                     {'Content-Type': kind, 'User-Agent': 'NodeAssistant'})
    urllib.request.urlopen(request, timeout=60).close()  # como archivo: sin la compresión que achica el texto


def answer(message):
    chat = message['chat']['id']
    text = (message.get('text') or '').strip()
    heard = ''
    if voice := message.get('voice') or message.get('audio'):
        path = api('getFile', file_id=voice['file_id'])['file_path']
        token = node.secret('TELEGRAM_BOT_TOKEN')
        with urllib.request.urlopen(f'https://api.telegram.org/file/bot{token}/{path}', timeout=30) as response:
            text = node.transcribe(response.read(), path.rsplit('/', 1)[-1])
        heard = f'🎙 «{text}»\n'
    if node.OPSEC['on'] and text.lower() not in ('/opsec', '/help'):  # modo privado: el celular no maneja la PC
        return send(chat, node.t('La PC está en modo /opsec: no proceso nada que llegue por Telegram. Mándame /opsec para '
                          'apagarlo.'))
    if not text or text == '/start':
        return send(chat, node.t(HELP))
    if (answer := node.slash(text)) is not None:  # los mismos comandos que en la cápsula (/help los lista)
        return send(chat, answer)
    api('sendChatAction', chat_id=chat, action='typing')
    reply, steps = node.handle(text, where='telegram')
    if any(action == 'screenshot' for action, _ in steps):
        send_photo(chat, node.png(node.screenshot()))
    send(chat, heard + reply)


PAIRING = {'code': None, 'until': 0, 'chat': None}  # el código que muestra /settings para vincular tu chat
STATE = {'running': False}


def pair_code(minutes=10):
    """Un código nuevo de 6 dígitos para vincular el bot con tu chat (lo muestra /settings). Vence solo."""
    PAIRING.update(code=f'{secrets.randbelow(1_000_000):06d}', until=time.time() + minutes * 60, chat=None)
    return PAIRING['code']


def notify_mine(text):
    """Los avisos (recordatorios) también te llegan al celular, al chat vinculado."""
    if mine := node.secret('TELEGRAM_CHAT_ID'):
        send(mine, f'⏰ {text}')


def poll():
    offset = None
    try:  # el botón de menú de Telegram, con los mismos comandos que /help (/tgtoggle, /opsec…)
        api('setMyCommands', commands=[{'command': name[1:], 'description': description[:256]}
                                       for name, (description, _) in sorted(node.COMMANDS.items())])
    except OSError:
        pass
    while True:
        try:
            updates = api('getUpdates', timeout=50, offset=offset, allowed_updates=['message'])
        except OSError:  # sin internet: reintenta en un rato
            time.sleep(10)
            continue
        for update in updates:
            offset = update['update_id'] + 1
            message = update.get('message')
            if not message:
                continue
            chat, fresh = str(message['chat']['id']), time.time() - message['date'] < 120  # viejas: PC apagada
            mine = node.secret('TELEGRAM_CHAT_ID')  # se lee cada vez: cambia al vincular o desvincular
            try:
                if chat == mine:
                    if fresh:
                        answer(message)
                elif fresh and PAIRING['code'] and time.time() < PAIRING['until'] \
                        and (message.get('text') or '').strip() == PAIRING['code']:
                    node.save_secret('TELEGRAM_CHAT_ID', chat)  # el código de tu pantalla: este chat es el tuyo
                    PAIRING.update(code=None, chat=chat)
                    send(chat, node.t('Listo, quedamos vinculados: desde ahora solo te obedezco a ti.') + '\n\n' +
                         node.t(HELP))
                elif not mine and fresh:  # sin vincular todavía: cómo hacerlo (a nadie le hace caso)
                    send(chat, node.t('Este bot es privado. Para vincularlo, abre /settings → Servicios → Telegram en '
                                      'la PC donde está Node y mándame el código que aparece ahí.'))
                # vinculado a otro chat: a un desconocido no se le responde nada
            except Exception as error:  # que un error no corte el bot
                try:
                    send(chat, f'Error: {error}')
                except OSError:
                    pass


def start():
    """Prende el bot si hay token y no está andando (al abrir Node, o al pegar el token en /settings)."""
    if node.secret('TELEGRAM_BOT_TOKEN') and not STATE['running']:
        STATE['running'] = True
        threading.Thread(target=poll, daemon=True).start()


def setup(node_):
    global node
    node = node_
    node.LISTENERS.append(notify_mine)
    node.STARTERS.append(start)
