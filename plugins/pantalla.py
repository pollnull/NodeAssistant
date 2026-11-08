"""Visión: Node mira tu pantalla y te ayuda con lo que ves.
"¿qué es este error?", "explícame lo que tengo en pantalla", "resúmeme esta página", "¿qué dice este gráfico?".
Saca una captura (sin la cápsula) y se la pasa a una IA que entiende imágenes (Gemini).
Ojo: la captura sale de tu PC hacia esa plataforma; no la uses con contraseñas o datos privados en pantalla.
"""
import base64
import time

node = None


def screen(args, where):
    question = (args.get('question') or '').strip() or 'Describe brevemente qué hay en la pantalla.'
    if where == 'pc':  # que la cápsula no tape lo que hay que ver
        node.UI['hide']()
        time.sleep(0.45)
    image = node.screenshot()
    if where == 'pc':
        node.UI['appear']()
    if image.shape[1] > 2000:  # pantallas muy grandes: a la mitad, para que viaje rápido (se lee igual)
        image = image[::2, ::2]
    picture = 'data:image/png;base64,' + base64.b64encode(node.png(image)).decode()
    answer = node.cloud([
        {'role': 'system', 'content': node.PERSONA + ' Te paso una captura de la pantalla del usuario. Responde lo '
                                                     'que pregunta mirando la imagen; si es un error, di qué significa '
                                                     'y cómo arreglarlo. Breve, porque se lee en voz alta.'},
        {'role': 'user', 'content': [{'type': 'text', 'text': question},
                                     {'type': 'image_url', 'image_url': {'url': picture}}]}],
        vision=True, wait=30, max_tokens=2000)  # Gemini 3.5 piensa antes: con menos, la respuesta llega cortada
    return node.tidy(answer.get('content')) or node.t('No pude ver bien la pantalla.')


def setup(node_):
    global node
    node = node_
    node.add(node.tool('screen', 'Mira la pantalla del usuario (una captura) y responde sobre lo que se ve: errores, '
                       'páginas, gráficos, "¿qué es esto?". question: lo que preguntó, tal cual.',
                       question={'type': 'string'}), screen,
             r'pantalla|esto|este error|esta pagina|ves|mira|que dice|explica|que es eso|grafico|ventana')
