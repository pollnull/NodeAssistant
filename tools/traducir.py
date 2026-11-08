"""Traduce los textos fijos de Node (los marcados con t() o N_()) a los otros idiomas: idiomas/<código>.json.
Uso:  .venv\\Scripts\\python.exe tools\\traducir.py            (traduce solo lo que falta, en todos los idiomas)
      .venv\\Scripts\\python.exe tools\\traducir.py en fr      (solo esos)
      .venv\\Scripts\\python.exe tools\\traducir.py --todo     (vuelve a traducir todo)
Usa la IA en la nube que tengas configurada en Node. Cada traducción tiene que conservar los datos entre llaves
({name}, {query}…) tal cual; si no, se descarta y ese texto queda en español. Los archivos se pueden corregir a mano.
"""
import ast
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
MARKERS = {'t', 'N_', 'field', 'number', 'tool'}  # funciones cuyos textos se traducen (tool: para /settings)
BATCH = 40


def texts():
    """Todos los textos marcados, en el orden en que aparecen."""
    found = {}
    for path in [HERE / 'node_assistant.py', *sorted((HERE / 'plugins').glob('*.py'))]:
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, 'id', '')
            if name not in MARKERS:
                continue
            keys = {id(k) for d in ast.walk(call) if isinstance(d, ast.Dict) for k in d.keys if k is not None}
            for arg in call.args:
                for item in ast.walk(arg):
                    if isinstance(item, ast.Constant) and isinstance(item.value, str) and id(item) not in keys:
                        text = item.value
                        if re.search(r'[A-Za-zÁÉÍÓÚáéíóúñ]{2}', text) and not re.fullmatch(r'[A-Z0-9_]+', text) \
                                and not text.startswith(('http', '#')) and not (' ' not in text and re.search(r'[_\d]', text)):
                            found.setdefault(text, None)
    for path in sorted((HERE / 'plugins').glob('*.py')):  # la primera línea de cada plugin (sale en /settings → Plugins)
        doc = (ast.get_docstring(ast.parse(path.read_text(encoding='utf-8'))) or '').strip()
        if doc:
            found.setdefault(doc.splitlines()[0], None)
    return list(found)


def placeholders(text):
    return sorted(re.findall(r'\{(\w+)\}', text))


def edges(source, out):
    """Los bordes como en español: los mismos espacios al principio y al final, y punto final solo si lo tiene."""
    core = out.strip()
    if not source.rstrip().endswith('.') and core.endswith('.') and not core.endswith('...'):
        core = core[:-1]
    lead, trail = source[:len(source) - len(source.lstrip())], source[len(source.rstrip()):]
    return lead + core + trail


def translate(node, language, batch):
    name = node.LANGUAGES[language][1]
    numbered = {str(i): text for i, text in enumerate(batch)}
    prompt = (f'Traduce cada texto del español al {name}. Son textos de una app de asistente de voz para Windows: '
              'tono cercano e informal (tuteo), corto y natural, como hablaría una persona. Mantén EXACTOS los datos '
              'entre llaves ({name}, {query}…), los comandos (/setup, /settings…), los atajos (Ctrl + Alt + N), los '
              'nombres de productos (Node, Obsidian, Groq, Whisper, Piper, Ollama, Telegram…), los espacios y la '
              'puntuación de los extremos, y los saltos de línea (\\n). Responde solo un JSON con las mismas claves '
              'y cada texto traducido.')
    answer = node.cloud([{'role': 'system', 'content': prompt},
                         {'role': 'user', 'content': json.dumps(numbered, ensure_ascii=False)}],
                        wait=90, max_tokens=8000, temperature=0.2, response_format={'type': 'json_object'})
    content = re.sub(r'^```(?:json)?|```$', '', (answer.get('content') or '').strip()).strip()
    result = json.loads(content)
    good = {}
    for key, text in numbered.items():
        out = result.get(key)
        if isinstance(out, str) and out.strip() and placeholders(out) == placeholders(text):
            good[text] = edges(text, out)
    return good


def main():
    import node_assistant as node
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    every = texts()
    languages = [a for a in sys.argv[1:] if a in node.LANGUAGES and a != 'es'] or \
        [code for code in node.LANGUAGES if code != 'es']
    folder = HERE / 'idiomas'
    folder.mkdir(exist_ok=True)
    print(f'{len(every)} textos para traducir')
    for language in languages:
        target = folder / f'{language}.json'
        done = {} if '--todo' in sys.argv or not target.exists() else json.loads(target.read_text(encoding='utf-8'))
        missing = [text for text in every if text not in done]
        print(f'{language}: faltan {len(missing)}')
        for start in range(0, len(missing), BATCH):
            batch = missing[start:start + BATCH]
            try:
                got = translate(node, language, batch)
            except (ConnectionError, ValueError, KeyError) as error:
                print(f'  no se pudo traducir un grupo ({error}); queda para la próxima')
                continue
            done.update(got)
            print(f'  {start + len(batch)}/{len(missing)} ({len(batch) - len(got)} descartados)')
            target.write_text(json.dumps({text: done[text] for text in every if text in done}, ensure_ascii=False,
                                         indent=1), encoding='utf-8', newline='\n')
    print('Listo.')


if __name__ == '__main__':
    main()
