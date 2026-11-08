"""Portapapeles: "tradúceme lo que copié", "resúmelo", "corrígele la ortografía", "¿qué es esto que copié?".
El resultado te lo dice y te lo deja copiado, listo para pegar.
"""
import ctypes

node = None
LIMIT = 4000  # caracteres: más que esto no entra en el cupo por minuto de la IA gratis
ASK = {
    'translate': 'Traduce este texto {to}. Responde solo con la traducción.',
    'summarize': 'Resume este texto en español en 2 o 3 frases.',
    'fix': 'Corrige la ortografía y la gramática de este texto sin cambiar su sentido ni su idioma. '
           'Responde solo con el texto corregido.',
    'explain': 'Explica en español, simple y en 2 o 3 frases, qué es o qué dice esto.',
}


def win():
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetClipboardData.restype = kernel32.GlobalLock.restype = kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    return user32, kernel32


def read():
    user32, kernel32 = win()
    if not user32.OpenClipboard(None):
        return ''
    try:
        handle = user32.GetClipboardData(13)  # 13 = texto Unicode
        if not handle:
            return ''
        text = ctypes.wstring_at(kernel32.GlobalLock(handle))
        kernel32.GlobalUnlock(handle)
        return text
    finally:
        user32.CloseClipboard()


def write(text):
    user32, kernel32 = win()
    data = (text + '\0').encode('utf-16-le')
    handle = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE: Windows se queda con la memoria
    ctypes.memmove(kernel32.GlobalLock(handle), data, len(data))
    kernel32.GlobalUnlock(handle)
    if user32.OpenClipboard(None):
        user32.EmptyClipboard()
        user32.SetClipboardData(13, handle)
        user32.CloseClipboard()


def clipboard(args, where):
    text = read().strip()
    if not text:
        return node.t('No hay texto copiado.')
    action = args.get('action') or 'read'
    if action == 'read':
        return node.t('Copiaste: {dato}', dato=text[:500]) + ('…' if len(text) > 500 else '')
    cut = len(text) > LIMIT
    language = (args.get('language') or '').strip()
    mine = node.LANGUAGES[node.LANGUAGE][1]  # tu idioma (el de Node)
    to = f'al {language}' if language else (f'al inglés si está en {mine}, o al {mine} si está en otro idioma'
                                         if mine != 'inglés' else 'al español si está en inglés, o al inglés si no')
    answer = node.tidy(node.cloud([{'role': 'user', 'content': ASK[action].format(to=to) + '\n\n' + text[:LIMIT]}],
                                  max_tokens=1500).get('content'))
    if action in ('translate', 'fix'):
        write(answer)
        answer += node.t(' (Te lo dejé copiado.)')
    return answer + (node.t(' Ojo: el texto era largo y usé solo el principio.') if cut else '')


def setup(node_):
    global node
    node = node_
    node.add(node.tool('clipboard', 'Hace algo con el texto que el usuario copió: translate (traducir; language = el '
                       'idioma pedido o vacío), summarize (resumir), fix (corregir ortografía), explain (explicar) o '
                       'read (decir qué copió).', action={'type': 'string', 'enum': list(ASK) + ['read']},
                       language={'type': 'string'}), clipboard, r'copi|portapapeles|traduc|corregi|corrige|ortografia|resum|explica')
