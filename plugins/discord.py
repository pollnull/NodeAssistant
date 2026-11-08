"""Discord: silenciar o ensordecerte por voz, y mandar mensajes a un canal tuyo.

Una sola vez, en Discord:
1. Ajustes de usuario -> Atajos de teclado -> Añadir atajo:
   "Activar/desactivar silencio" = Ctrl + Shift + Alt + M   y   "Activar/desactivar ensordecer" = Ctrl + Shift + Alt + D
2. Para mensajes: en el canal, Editar canal -> Integraciones -> Webhooks -> Nuevo webhook -> Copiar URL, y guárdala
   en Windows (PowerShell):  [Environment]::SetEnvironmentVariable('DISCORD_WEBHOOK_URL', 'LA-URL', 'User')
"""
import json
import urllib.request

node = None
CTRL, SHIFT, ALT = 0x11, 0x10, 0x12
KEYS = {'mute': 0x4D, 'deafen': 0x44}  # M y D


def voice(args, where):
    action = args.get('action')
    if action not in KEYS:
        return node.t('Puedo silenciarte o ensordecerte en Discord.')
    node.press(CTRL, SHIFT, ALT, KEYS[action])
    return node.t({'mute': 'Listo, cambié tu micrófono en Discord.', 'deafen': 'Listo, cambié el ensordecer en Discord.'}[action])


def message(args, where):
    url, text = node.secret('DISCORD_WEBHOOK_URL'), (args.get('text') or '').strip()
    if not url:
        return node.t('Falta el webhook de Discord: guarda su URL en la variable DISCORD_WEBHOOK_URL.')
    if not text:
        return node.t('¿Qué mensaje mando a Discord?')
    body = json.dumps({'content': text, 'username': 'Node', 'allowed_mentions': {'parse': []}}).encode()
    request = urllib.request.Request(url, body, {'Content-Type': 'application/json', 'User-Agent': 'NodeAssistant'})
    urllib.request.urlopen(request, timeout=10).close()
    return node.t('Mandé a Discord: {text}', text=text)


def setup(node_):
    global node
    node = node_
    node.add(node.tool('discord_voice', 'En Discord: mute = silenciar o activar el micrófono del usuario, deafen = '
                       'ensordecerse o volver a escuchar.', action={'type': 'string', 'enum': ['mute', 'deafen']}), voice, r'discord|silenci|microfono|mutea|ensordec')
    node.add(node.tool('discord_message', 'Manda un mensaje al canal de Discord del usuario. Solo si lo pide '
                       'explícitamente ("manda a Discord que..."). text: el mensaje exacto, en primera persona como lo '
                       'escribiría él.', text={'type': 'string'}), message, r'discord|mensaje|avisa(le)? a')
