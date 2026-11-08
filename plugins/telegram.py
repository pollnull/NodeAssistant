"""Bot de Telegram: usa a Node desde el celular. Escríbele o mándale audios; hace lo mismo que en la PC y te contesta.
Los recordatorios también te llegan ahí, y "mándame una captura" te manda una foto de toda la pantalla.

Una sola vez:
1. En Telegram, habla con @BotFather -> /newbot -> te da un token. Guárdalo en Windows (PowerShell):
   [Environment]::SetEnvironmentVariable('TELEGRAM_BOT_TOKEN', 'EL-TOKEN', 'User')
2. Reinicia Node y escríbele cualquier cosa a tu bot: te responde con tu número de chat. Guárdalo igual:
   [Environment]::SetEnvironmentVariable('TELEGRAM_CHAT_ID', 'EL-NUMERO', 'User')
Desde ahí el bot solo obedece a ese chat: a cualquier otra persona solo le dice su número, nunca hace nada.
Funciona mientras la PC esté prendida y Node abierto.
"""
import json
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


def poll():
    offset, mine = None, node.secret('TELEGRAM_CHAT_ID')
    if mine:
        node.LISTENERS.append(lambda text: send(mine, f'⏰ {text}'))
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
            chat = str(message['chat']['id'])
            try:
                if chat != mine:  # un desconocido (o tú antes de vincular): solo su número, nada más
                    if not mine:
                        send(chat, node.t('Este bot es privado. Para vincularlo con Node, tu número de chat es {chat}.', chat=chat))
                elif time.time() - message['date'] < 120:  # órdenes viejas (con la PC apagada) no se ejecutan
                    answer(message)
            except Exception as error:  # que un error no corte el bot
                try:
                    send(chat, f'Error: {error}')
                except OSError:
                    pass


def setup(node_):
    global node
    node = node_
    if node.secret('TELEGRAM_BOT_TOKEN'):
        node.STARTERS.append(lambda: threading.Thread(target=poll, daemon=True).start())
