"""/setup: deja a Node listo desde cero, en una ventana con pasos. Se abre sola la primera vez.
1. Tu nombre.
2. IA en la nube: elige proveedores gratis (o cualquiera compatible con OpenAI), pega la clave, busca y prueba modelos.
   La clave va a las variables de Windows de tu usuario, nunca a un archivo; el resto, a proveedores.json.
3. Modelos en tu PC (Ollama): instalar Ollama, descargar modelos abiertos con un botón, descargar cualquier otro por su
   nombre o importar tu propio archivo GGUF, y elegir con cuál charla Node sin internet.
4. Voz: descargar voces de Piper o importar la tuya (.onnx), y Whisper para entenderte sin internet.
5. Memoria (opcional): crea una bóveda de Obsidian en la carpeta que elijas, encuentra Obsidian solo y la registra
   para que aparezca al abrirlo; si quieres, con la plantilla de kepano. Sin memoria, Node no recuerda nada.
6. Preferencias: iniciar con Windows, leer en voz alta, micrófono, modo privado, resumen por Telegram y colores.
Es también la pantalla de ajustes: /setup la vuelve a abrir cuando quieras. Al terminar, Node se reinicia.
"""
import ctypes
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import winreg
import zipfile
from pathlib import Path
from tkinter import filedialog, ttk

N_ = lambda texts: texts  # marca textos de listas para traducir: se traducen al mostrarlos (node.t)

node = None
WINDOW = {}
BG, FIELD, FG, SOFT, GOOD, BAD = '#101320', '#1a1f33', '#e8ecf4', '#8f97b8', '#7ee0a8', '#ff8a8a'
FONT, SMALL, TINY, TITLE = ('Segoe UI Variable Text', 10), ('Segoe UI Variable Text', 9), \
    ('Segoe UI Variable Text', 8), ('Segoe UI Variable Display', 17)
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
OLLAMA_API = 'http://localhost:11434/api'
# Proveedores con API compatible con OpenAI: (dirección, variable de la clave, modelo sugerido, dónde sacar la clave)
PRESETS = {
    'Groq': ('https://api.groq.com/openai/v1', 'GROQ_API_KEY', 'openai/gpt-oss-120b', 'https://console.groq.com/keys'),
    'Gemini': ('https://generativelanguage.googleapis.com/v1beta/openai', 'GEMINI_API_KEY', 'gemini-flash-lite-latest',
               'https://aistudio.google.com/apikey'),
    'OpenRouter': ('https://openrouter.ai/api/v1', 'OPENROUTER_API_KEY', '', 'https://openrouter.ai/settings/keys'),
    'NVIDIA': ('https://integrate.api.nvidia.com/v1', 'NVIDIA_API_KEY', '', 'https://build.nvidia.com'),
    'Mistral': ('https://api.mistral.ai/v1', 'MISTRAL_API_KEY', 'mistral-small-latest', 'https://console.mistral.ai'),
    'SambaNova': ('https://api.sambanova.ai/v1', 'SAMBANOVA_API_KEY', '', 'https://cloud.sambanova.ai'),
    'Hugging Face': ('https://router.huggingface.co/v1', 'HF_TOKEN', '', 'https://huggingface.co/settings/tokens'),
    'DeepSeek': ('https://api.deepseek.com', 'DEEPSEEK_API_KEY', 'deepseek-chat', 'https://platform.deepseek.com'),
    'Ollama (local)': ('http://localhost:11434/v1', '', 'llama3.2', 'https://ollama.com'),
    'Otro': ('', '', '', ''),
}
# Modelos abiertos para Ollama: (nombre, tamaño, para qué)
LOCAL_MODELS = N_([
    ('llama3.2', '2 GB', 'Rápido, para charlar sin internet. Anda en casi cualquier PC.'),
    ('qwen2.5:7b', '4,7 GB', 'Mejor español. Pide unos 6 GB de memoria de video o RAM.'),
    ('gpt-oss:20b', '14 GB', 'El más capaz que corre en una PC común. Pide unos 16 GB entre video y RAM.'),
    ('laya:322m-multilingual-bf16', '0,7 GB', 'Decide órdenes vagas ("pon algo de música") sin internet.'),
])
# Voces de Piper por idioma: (id, de dónde y calidad)
VOICES = N_({
    'es': [('es_MX-claude-high', 'México · alta calidad'), ('es_MX-ald-medium', 'México'),
           ('es_AR-daniela-high', 'Argentina · alta calidad'), ('es_ES-davefx-medium', 'España'),
           ('es_ES-sharvard-medium', 'España')],
    'en': [('en_US-ryan-high', 'EE. UU. · alta calidad'), ('en_US-lessac-medium', 'EE. UU.'),
           ('en_GB-alan-medium', 'Reino Unido')],
    'pt': [('pt_BR-faber-medium', 'Brasil')],
    'fr': [('fr_FR-siwis-medium', 'Francia'), ('fr_FR-tom-medium', 'Francia')],
    'de': [('de_DE-thorsten-high', 'Alemania · alta calidad'), ('de_DE-kerstin-low', 'Alemania')],
    'it': [('it_IT-paola-medium', 'Italia'), ('it_IT-riccardo-x_low', 'Italia')],
})
# Lo que se guarda al apretar Guardar (y se aplica al reiniciar Node). Lo demás se aplica al instante.
SAVED_ON_RESTART = ('name', 'language', 'chat_model', 'voice', 'persona', 'temperature', 'whisper', 'quiet',
                    'mic_warmup', 'cloud_ears', 'resumen_hora')
KEPANO = 'https://codeload.github.com/kepano/kepano-obsidian/zip/refs/heads/main'


# --- Lo que hace cada botón (sin ventana) ---------------------------------------------------------------------------

def get_json(url, key='', body=None, timeout=20):
    headers = {'User-Agent': 'NodeAssistant', 'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = f'Bearer {key}'
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=timeout) as response:
        return json.load(response)


def problem(error):
    if isinstance(error, urllib.error.HTTPError):
        return {401: 'la clave no es válida', 403: 'la clave no tiene permiso', 404: 'esa dirección o modelo no existe',
                429: 'sin cupo por ahora'}.get(error.code, f'error {error.code}')
    return str(getattr(error, 'reason', error))


def save_key(name, value):
    node.save_secret(name, value)  # en las variables de Windows de tu usuario, nunca en un archivo


def mine():
    return json.loads(node.CUSTOM.read_text(encoding='utf-8')) if node.CUSTOM.exists() else []


def ollama_installed():
    return bool(shutil.which('ollama')) or (Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Ollama' /
                                            'ollama.exe').exists()


def ollama_models():
    """Los modelos que ya tienes en Ollama, o None si Ollama no está corriendo."""
    try:
        return sorted(model['name'] for model in get_json(f'{OLLAMA_API}/tags', timeout=3).get('models', []))
    except (OSError, ValueError):
        return None


def ollama_pull(name, progress):
    """Descarga un modelo de Ollama. progress(texto) va contando."""
    request = urllib.request.Request(f'{OLLAMA_API}/pull', json.dumps({'name': name, 'stream': True}).encode(),
                                     {'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        for line in response:
            step = json.loads(line)
            if step.get('error'):
                raise OSError(step['error'])
            if step.get('total'):
                progress(f"{step.get('completed', 0) / step['total']:.0%} de {step['total'] / 1e9:.1f} GB")


def ollama_import(gguf, name):
    """Tu propio modelo (un archivo .gguf) como modelo de Ollama."""
    folder = Path(tempfile.mkdtemp())
    (folder / 'Modelfile').write_text(f'FROM "{gguf}"\n', encoding='utf-8')
    done = subprocess.run(['ollama', 'create', name, '-f', str(folder / 'Modelfile')], capture_output=True, text=True,
                          creationflags=NO_WINDOW)
    shutil.rmtree(folder, ignore_errors=True)
    if done.returncode:
        raise OSError(done.stderr.strip().splitlines()[-1] if done.stderr.strip() else 'ollama create falló')


def download(url, target, progress):
    """Baja un archivo de a pedazos (para ver el avance) y lo guarda recién al terminar."""
    request = urllib.request.Request(url, headers={'User-Agent': 'NodeAssistant'})
    partial = target.with_name(target.name + '.parte')
    with urllib.request.urlopen(request, timeout=60) as response, partial.open('wb') as out:
        total, done = int(response.headers.get('Content-Length') or 0), 0
        while chunk := response.read(1 << 16):
            out.write(chunk)
            done += len(chunk)
            if total:
                progress(f'{done / total:.0%} de {total / 1e6:.0f} MB')
    partial.replace(target)


def voice_url(voice_id):
    locale, speaker, quality = voice_id.split('-')
    return (f'https://huggingface.co/rhasspy/piper-voices/resolve/main/{locale.split("_")[0]}/{locale}/{speaker}/'
            f'{quality}/{voice_id}.onnx')


def find_obsidian():
    """Dónde está Obsidian instalado, o None."""
    for place in (Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Obsidian' / 'Obsidian.exe',
                  Path(os.environ.get('PROGRAMFILES', '')) / 'Obsidian' / 'Obsidian.exe'):
        if place.exists():
            return place
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_CLASSES_ROOT):  # el que abre los enlaces obsidian://
        try:
            sub = r'Software\Classes\obsidian\shell\open\command' if root == winreg.HKEY_CURRENT_USER else \
                r'obsidian\shell\open\command'
            with winreg.OpenKey(root, sub) as key:
                command = winreg.QueryValueEx(key, '')[0]
            exe = Path(re.match(r'"?([^"]+\.exe)', command)[1])
            if exe.exists():
                return exe
        except (OSError, TypeError):
            continue
    return None


def register_vault(folder):
    """Suma la carpeta a la lista de bóvedas de Obsidian, para que aparezca al abrirlo."""
    config = Path(os.environ.get('APPDATA', '')) / 'obsidian' / 'obsidian.json'
    data = json.loads(config.read_text(encoding='utf-8')) if config.exists() else {}
    vaults = data.setdefault('vaults', {})
    if any(Path(v.get('path', '')).resolve() == folder.resolve() for v in vaults.values()):
        return
    vaults[secrets.token_hex(8)] = {'path': str(folder), 'ts': int(time.time() * 1000)}
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps(data), encoding='utf-8')


def kepano_template(folder):
    """Las categorías, plantillas y vistas de la bóveda de kepano (MIT), sin pisar nada tuyo."""
    work = Path(tempfile.mkdtemp())
    try:
        download(KEPANO, work / 'kepano.zip', lambda _text: None)
        with zipfile.ZipFile(work / 'kepano.zip') as archive:
            archive.extractall(work)
        source = next(work.glob('kepano-obsidian-*'))
        for part in ('Categories', 'Templates'):
            shutil.copytree(source / part, folder / part, dirs_exist_ok=True,
                            copy_function=lambda a, b: None if Path(b).exists() else shutil.copy2(a, b))
        settings = folder / '.obsidian'
        settings.mkdir(exist_ok=True)
        for name in ('templates.json', 'types.json'):
            if not (settings / name).exists():
                shutil.copy2(source / '.obsidian' / name, settings / name)
        if not (settings / 'daily-notes.json').exists():  # las notas del día, en la misma carpeta que usa Node
            (settings / 'daily-notes.json').write_text(json.dumps(
                {'folder': 'Diario', 'template': 'Templates/Daily Note Template'}), encoding='utf-8')
    finally:
        shutil.rmtree(work, ignore_errors=True)


def restart():
    """Abre un Node nuevo (con los ajustes nuevos) y cierra este."""
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    subprocess.Popen(f'cmd /c timeout /t 3 /nobreak >nul & start "" "{pythonw}" "{node.HERE / "node_assistant.py"}"',
                     creationflags=NO_WINDOW)
    node.UI['quit']()


# --- Piezas de la ventana -------------------------------------------------------------------------------------------

def dark(win):
    """Ícono de Node y barra de título oscura, como la cápsula."""
    try:
        win.iconbitmap(str(node.HERE / 'icons' / 'node.ico'))
        win.update_idletasks()
        ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.windll.user32.GetParent(win.winfo_id()), 20,
                                                   ctypes.byref(ctypes.c_int(1)), 4)
    except (tk.TclError, OSError, AttributeError):
        pass
    style = ttk.Style(win)
    style.theme_use('clam')
    style.configure('TCombobox', fieldbackground=FIELD, background=FIELD, foreground=FG, arrowcolor=FG,
                    bordercolor=FIELD, lightcolor=FIELD, darkcolor=FIELD, selectbackground=FIELD, selectforeground=FG)
    style.map('TCombobox', fieldbackground=[('readonly', FIELD)], foreground=[('readonly', FG)])


def label(parent, text, color=SOFT, font=SMALL, **pack):
    widget = tk.Label(parent, text=text, bg=BG, fg=color, font=font, anchor='w', justify='left', wraplength=500)
    widget.pack(fill='x', **pack)
    return widget


def entry(parent, **kw):
    return tk.Entry(parent, bg=FIELD, fg=FG, insertbackground=FG, relief='flat', font=FONT, **kw)


def button(parent, text, command, accent=False, **kw):
    return tk.Button(parent, text=text, command=command, relief='flat', font=SMALL, padx=12, pady=4, cursor='hand2',
                     bg=node.GLOW[0] if accent else FIELD, fg='#ffffff' if accent else FG, activebackground=FIELD,
                     activeforeground=FG, disabledforeground=SOFT, **kw)


def in_background(widget, work, done):
    """Corre work() en otro hilo y después done(resultado, error) en la ventana (Tk no se usa desde otros hilos)."""
    def run():
        try:
            result, error = work(), None
        except (OSError, ValueError, KeyError, IndexError) as problem_:
            result, error = None, problem_
        try:
            widget.after(0, done, result, error)
        except (tk.TclError, RuntimeError):  # cerraron la ventana mientras tanto
            pass
    threading.Thread(target=run, daemon=True).start()


def scrollable(holder):
    """Un panel que se desliza con la rueda cuando el contenido no entra. Devuelve el marco donde va el contenido."""
    canvas = tk.Canvas(holder, bg=BG, highlightthickness=0, bd=0)
    canvas.pack(fill='both', expand=True)
    body = tk.Frame(canvas, bg=BG)
    inside = canvas.create_window(0, 0, window=body, anchor='nw')
    body.bind('<Configure>', lambda _e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda e: canvas.itemconfigure(inside, width=e.width))

    def wheel(event):
        if canvas.winfo_exists() and body.winfo_height() > canvas.winfo_height():  # solo si hay algo que deslizar
            canvas.yview_scroll(int(-event.delta / 120) * 3, 'units')
    # en la ventana (vale para todo lo de adentro) y no en toda la app: la cápsula tiene su propia rueda
    holder.winfo_toplevel().bind('<MouseWheel>', wheel)
    return body


def row(parent):
    frame = tk.Frame(parent, bg=BG)
    frame.pack(fill='x', pady=3)
    return frame


# --- La ventana para agregar o cambiar un proveedor -----------------------------------------------------------------

def provider_dialog(parent, chosen='Groq', on_save=lambda: None):
    win = tk.Toplevel(parent)
    win.title(node.t('Proveedor de IA'))
    win.configure(bg=BG, padx=22, pady=18)
    win.resizable(False, False)
    win.transient(parent)
    dark(win)
    values = {}

    def field(text, widget, hint=''):
        label(win, node.t(text), pady=(8, 2))
        widget.pack(fill='x', ipady=5)
        if hint:
            label(win, node.t(hint), font=TINY)
        return widget

    preset = field('Proveedor', ttk.Combobox(win, values=list(PRESETS), state='readonly', font=FONT))
    name = field('Nombre', entry(win, width=46))
    url = field('Dirección de la API (compatible con OpenAI)', entry(win), 'Termina en /v1; Node le agrega '
                '/chat/completions.')
    model = field('Modelo', ttk.Combobox(win, font=FONT), 'Escríbelo o toca "Buscar modelos" para ver los que ofrece.')
    key_name = field('Variable de Windows para la clave', entry(win))
    key = field('Clave API', entry(win, show='•'), 'Se guarda en las variables de Windows de tu usuario, nunca en un '
                'archivo. Déjala vacía si ya está guardada o si es local (Ollama).')
    status = label(win, '', pady=(10, 0))
    bar = tk.Frame(win, bg=BG)
    bar.pack(fill='x', pady=(12, 0))

    def put(widget, value):
        widget.delete(0, 'end')
        widget.insert(0, value)

    def pick(_event=None):
        base, env, default, page = PRESETS.get(preset.get(), PRESETS['Otro'])
        current = next((p for p in node.PROVIDERS if p['name'] == preset.get()), None)  # ya está: muestra lo de ahora
        put(name, '' if preset.get() == 'Otro' else preset.get().replace(' (local)', ''))
        put(url, current['url'].rsplit('/chat/completions', 1)[0] if current else base)
        model.set(current['model'] if current else default)
        put(key_name, current.get('key', env) if current else env)
        values['page'] = page
        has = env and node.secret(env)
        status.config(text=(node.t('Ya tienes una clave guardada en {env}. ', env=env) if has else '') +
                      (node.t('Consigue una clave gratis en {page}', page=page) if page and env and not has else ''), fg=SOFT)

    def credentials():
        return key.get().strip() or (node.secret(key_name.get().strip()) if key_name.get().strip() else '') or ''

    def find_models():
        status.config(text=node.t('Buscando modelos…'), fg=SOFT)

        def done(result, error):
            if error:
                return status.config(text=node.t('No pude listar los modelos: {dato}.', dato=problem(error)), fg=BAD)
            ids = sorted(item['id'] for item in result.get('data', []))
            free = [i for i in ids if i.endswith(':free')]  # en OpenRouter, los gratis primero
            model.config(values=free + [i for i in ids if i not in free])
            status.config(text=node.t('{dato} modelos: despliega la lista de Modelo para elegir.', dato=len(ids)), fg=SOFT)
        in_background(win, lambda: get_json(url.get().strip().rstrip('/') + '/models', credentials()), done)

    def test():
        status.config(text=node.t('Probando…'), fg=SOFT)

        def done(result, error):
            if error:
                return status.config(text=node.t('No funcionó: {dato}.', dato=problem(error)), fg=BAD)
            answer = (result['choices'][0]['message'].get('content') or '').strip()
            status.config(text=node.t('Funciona.') + (node.t(' Respondió: «{dato}»', dato=answer[:80]) if answer else ''), fg=GOOD)
        in_background(win, lambda: get_json(url.get().strip().rstrip('/') + '/chat/completions', credentials(), {
            'model': model.get().strip(), 'max_tokens': 300,  # los que razonan gastan tokens antes de contestar
            'messages': [{'role': 'user', 'content': 'Di "hola" y nada más.'}]}), done)

    def keep():
        title, base, chosen_model = name.get().strip(), url.get().strip().rstrip('/'), model.get().strip()
        env = re.sub(r'[^A-Z0-9_]', '', key_name.get().strip().upper())
        if not (title and base and chosen_model):
            return status.config(text=node.t('Faltan el nombre, la dirección o el modelo.'), fg=BAD)
        if key.get().strip():
            if not env:
                return status.config(text=node.t('Falta la variable de Windows para guardar la clave.'), fg=BAD)
            save_key(env, key.get().strip())
        old = next((p for p in node.PROVIDERS if p['name'] == title), {})
        provider = {'name': title, 'key': env, 'model': chosen_model, 'url': base + '/chat/completions',
                    'extra': old.get('extra', {})}
        if old.get('vision'):
            provider['vision'] = old['vision']
        node.CUSTOM.write_text(json.dumps([p for p in mine() if p['name'] != title] + [provider], ensure_ascii=False,
                                          indent=1), encoding='utf-8')
        node.load_providers()
        win.destroy()
        on_save()

    button(bar, node.t('Buscar modelos'), find_models).pack(side='left')
    button(bar, node.t('Probar'), test).pack(side='left', padx=6)
    button(bar, node.t('Guardar'), keep, accent=True).pack(side='right')
    button(bar, node.t('Cancelar'), win.destroy).pack(side='right', padx=6)
    preset.bind('<<ComboboxSelected>>', pick)
    preset.set(chosen if chosen in PRESETS else 'Otro')
    pick()
    if chosen not in PRESETS:  # uno agregado a mano: muestra lo suyo
        current = next((p for p in node.PROVIDERS if p['name'] == chosen), None)
        if current:
            put(name, current['name'])
            put(url, current['url'].rsplit('/chat/completions', 1)[0])
            model.set(current['model'])
            put(key_name, current.get('key', ''))
    win.bind('<Escape>', lambda _e: win.destroy())
    win.grab_set()


# --- Los pasos del asistente ----------------------------------------------------------------------------------------

def page_welcome(body, choice):
    label(body, node.t('Hola, soy Node.'), FG, TITLE, pady=(0, 6))
    label(body, node.t('Te ayudo con la PC por voz: aprietas Ctrl + Alt + N, esperas el destello del orbe y me hablas. Vamos a dejarme listo en unos pasos. Puedes volver a esta ventana cuando quieras escribiendo /setup en la cápsula.'), pady=(0, 16))
    name_and_language(body, choice)


def name_and_language(body, choice):
    """El nombre y el idioma (en la bienvenida y en /settings → General)."""
    label(body, node.t('¿Cómo te llamo?'), pady=(0, 3))
    text = tk.StringVar(body, choice['name'])
    text.trace_add('write', lambda *_: choice.update(name=text.get().strip()))  # al escribir, pegar o borrar
    name = entry(body, textvariable=text)
    name.pack(fill='x', ipady=5)
    name.focus_set()
    label(body, node.t('Idioma en el que te entiendo y te respondo'), pady=(14, 3))
    names = {code: info[0] for code, info in node.LANGUAGES.items()}
    language = ttk.Combobox(body, values=list(names.values()), state='readonly', font=FONT)
    language.set(names[choice['language']])

    def chose(_event=None):
        code = next(code for code, shown in names.items() if shown == language.get())
        choice['language'] = code
        if not Path(choice['voice']).name.startswith(code):  # una voz de ese idioma (la descargas en Voz)
            choice['voice'] = str(node.HERE / 'voices' / f'{VOICES[code][0][0]}.onnx')
    language.bind('<<ComboboxSelected>>', chose)
    language.pack(fill='x', ipady=4)
    label(body, node.t('Las respuestas, la voz y las ventanas salen en ese idioma (se aplica al reiniciar).'), font=TINY)


def page_cloud(body, choice):
    label(body, node.t('IA en la nube'), FG, TITLE, pady=(0, 6))
    label(body, node.t('Es lo que me hace inteligente y rápido. Con una sola alcanza; con varias, si una se queda sin cupo paso sola a la siguiente. Groq es gratis, rapidísima y no guarda lo que le mandas: es la que recomiendo para empezar. Gemini es gratis y además ve imágenes (para mirar tu pantalla).'),
          pady=(0, 10))
    off = set(node.saved('apagados', []))
    for provider in node.PROVIDERS:
        line = row(body)
        ready = not provider.get('key') or node.secret(provider['key'])
        on = tk.BooleanVar(value=provider['name'] not in off)
        tk.Checkbutton(line, variable=on, bg=BG, activebackground=BG, selectcolor=FIELD, fg=FG, relief='flat',
                       command=(lambda name, var: lambda: toggle_provider(name, var.get()))(provider['name'], on)
                       ).pack(side='left')
        text = tk.Frame(line, bg=BG)
        text.pack(side='left', fill='x', expand=True)
        tk.Label(text, text=provider['name'], bg=BG, fg=FG, font=FONT, anchor='w').pack(fill='x')
        tk.Label(text, text=f"{provider['model']}  ·  " + (node.t('lista') if ready else node.t('falta la clave')), bg=BG,
                 fg=GOOD if ready else SOFT, font=TINY, anchor='w').pack(fill='x')
        button(line, node.t('Configurar'), (lambda name: lambda: provider_dialog(
            body.winfo_toplevel(), name, lambda: WINDOW['show']()))(provider['name'])).pack(side='right')
        if provider['name'] in {p['name'] for p in mine()} and not any(p['name'] == provider['name'] for p in node.BUILT_IN):
            button(line, node.t('Quitar'), (lambda name: lambda: remove_provider(name))(provider['name'])).pack(side='right',
                                                                                                         padx=4)
    button(body, node.t('+ Agregar otro proveedor'), lambda: provider_dialog(body.winfo_toplevel(), 'Groq',
                                                                     lambda: WINDOW['show']())).pack(anchor='w',
                                                                                                    pady=(10, 0))


def toggle_provider(name, on):
    off = set(node.saved('apagados', []))
    (off.discard if on else off.add)(name)
    node.save('apagados', sorted(off))


def remove_provider(name):
    node.CUSTOM.write_text(json.dumps([p for p in mine() if p['name'] != name], ensure_ascii=False, indent=1),
                           encoding='utf-8')
    node.load_providers()
    WINDOW['show']()


def page_local(body, choice):
    label(body, node.t('Modelos en tu PC'), FG, TITLE, pady=(0, 6))
    label(body, node.t('Opcional. Con Ollama, unos modelos abiertos corren en tu PC: sirven sin internet, cuando la nube se queda sin cupo y en el modo privado (/opsec). Ocupan disco y memoria.'), pady=(0, 10))
    installed = ollama_models()
    if installed is None:
        found = ollama_installed()
        label(body, node.t('Ollama está instalado pero no está abierto: ábrelo (queda en la bandeja) y toca Revisar.') if found
              else node.t('Ollama no está instalado.'), FG, pady=(0, 6))
        line = row(body)
        if not found:
            button(line, node.t('Descargar Ollama'), lambda: webbrowser.open('https://ollama.com/download'), accent=True
                   ).pack(side='left')
        button(line, node.t('Revisar de nuevo'), WINDOW['show']).pack(side='left', padx=6)
        return
    status = label(body, '', pady=(0, 4))
    for name, size, use in LOCAL_MODELS:
        line = row(body)
        text = tk.Frame(line, bg=BG)
        text.pack(side='left', fill='x', expand=True)
        tk.Label(text, text=f'{name}  ({size})', bg=BG, fg=FG, font=FONT, anchor='w').pack(fill='x')
        tk.Label(text, text=node.t(use), bg=BG, fg=SOFT, font=TINY, anchor='w', wraplength=360, justify='left').pack(fill='x')
        have = any(model == name or model == f'{name}:latest' for model in installed)
        pull_button = button(line, node.t('Instalado') if have else node.t('Descargar'), None, state='disabled' if have else 'normal')
        pull_button.config(command=(lambda n, b: lambda: pull(body, n, b, status))(name, pull_button))
        pull_button.pack(side='right')
    label(body, node.t('Tu propio modelo'), FG, FONT, pady=(12, 2))
    line = row(body)
    other = entry(line, width=26)
    other.pack(side='left', ipady=4)
    other_button = button(line, node.t('Descargar de Ollama'), None)
    other_button.config(command=lambda: other.get().strip() and pull(body, other.get().strip(), other_button, status))
    other_button.pack(side='left', padx=6)
    button(line, node.t('Importar GGUF…'), lambda: import_gguf(body, status)).pack(side='left')
    label(body, node.t('Cualquier nombre de ollama.com/library, o un archivo .gguf tuyo (por ejemplo de Hugging Face).'),
          font=TINY)
    label(body, node.t('Con cuál charlo sin internet'), FG, FONT, pady=(12, 2))
    pick = ttk.Combobox(body, values=installed, state='readonly', font=FONT)
    same = [m for m in installed if m in (choice['chat_model'], f"{choice['chat_model']}:latest")]  # llama3.2 = :latest
    pick.set(same[0] if same else installed[0] if installed else '')
    choice['chat_model'] = pick.get() or choice['chat_model']
    pick.bind('<<ComboboxSelected>>', lambda _e: choice.update(chat_model=pick.get()))
    pick.pack(fill='x', ipady=4)


def pull(body, name, widget, status):
    widget.config(state='disabled', text=node.t('Bajando…'))
    progress = lambda text: body.after(0, lambda: status.config(text=f'{name}: {text}', fg=SOFT))

    def done(_result, error):
        if error:
            widget.config(state='normal', text=node.t('Reintentar'))
            return status.config(text=node.t('No pude bajar {name}: {dato}.', name=name, dato=problem(error)), fg=BAD)
        WINDOW['show']()
    in_background(body, lambda: ollama_pull(name, progress), done)


def import_gguf(body, status):
    path = filedialog.askopenfilename(parent=body.winfo_toplevel(), title=node.t('Tu modelo GGUF'),
                                      filetypes=[(node.t('Modelo GGUF'), '*.gguf')])
    if not path:
        return
    name = re.sub(r'[^a-z0-9._-]', '-', Path(path).stem.lower())[:40]
    status.config(text=node.t('Importando {name}… (puede tardar un rato)', name=name), fg=SOFT)

    def done(_result, error):
        if error:
            return status.config(text=node.t('No pude importarlo: {dato}.', dato=problem(error)), fg=BAD)
        WINDOW['show']()
    in_background(body, lambda: ollama_import(path, name), done)


def page_voice(body, choice):
    label(body, node.t('Voz'), FG, TITLE, pady=(0, 6))
    label(body, node.t('Mi voz sale de tu PC con Piper, sin internet. Voces en {dato}: elige una (o importa la tuya); sin voz, te respondo solo con texto.', dato=node.LANGUAGES[choice["language"]][0]), pady=(0, 10))
    voices = node.HERE / 'voices'
    status = label(body, '', pady=(0, 4))
    for voice_id, about in VOICES[choice['language']]:
        line = row(body)
        path = voices / f'{voice_id}.onnx'
        chosen = Path(choice['voice']).name == path.name
        tk.Label(line, text=f'{voice_id}', bg=BG, fg=FG, font=FONT, anchor='w').pack(side='left')
        tk.Label(line, text=f'  {node.t(about)}', bg=BG, fg=SOFT, font=TINY, anchor='w').pack(side='left')
        if path.exists():
            button(line, node.t('En uso') if chosen else node.t('Usar'), (lambda p: lambda: (choice.update(voice=str(p)),
                                                                             WINDOW['show']()))(path),
                   accent=chosen).pack(side='right')
        else:
            get = button(line, node.t('Descargar'), None)
            get.config(command=(lambda v, b: lambda: fetch_voice(body, v, b, status, choice))(voice_id, get))
            get.pack(side='right')
    button(body, node.t('Importar una voz (.onnx)…'), lambda: import_voice(body, choice, status)).pack(anchor='w', pady=(8, 0))
    label(body, node.t('Más voces en huggingface.co/rhasspy/piper-voices (bajas el .onnx y su .onnx.json).'), font=TINY)
    label(body, node.t('Entenderte sin internet'), FG, FONT, pady=(14, 2))
    groq = node.secret('GROQ_API_KEY')
    if node.whisper_ready():
        label(body, node.t('Whisper ya está descargado.'), GOOD)
    else:
        label(body, (node.t('Con la clave de Groq te entiendo en la nube en 0,3 s; Whisper es el respaldo sin internet.') if groq
                     else node.t('Sin clave de Groq, necesito Whisper para entenderte.')), pady=(0, 4))
        get = button(body, node.t('Descargar Whisper ({HEARING}, unos 460 MB)', HEARING=node.HEARING), None)
        get.config(command=lambda: fetch_whisper(body, get, status))
        get.pack(anchor='w')


def fetch_voice(body, voice_id, widget, status, choice):
    widget.config(state='disabled', text=node.t('Bajando…'))
    folder = node.HERE / 'voices'
    folder.mkdir(exist_ok=True)
    progress = lambda text: body.after(0, lambda: status.config(text=f'{voice_id}: {text}', fg=SOFT))

    def work():
        download(voice_url(voice_id) + '.json', folder / f'{voice_id}.onnx.json', lambda _t: None)
        download(voice_url(voice_id), folder / f'{voice_id}.onnx', progress)

    def done(_result, error):
        if error:
            widget.config(state='normal', text=node.t('Reintentar'))
            return status.config(text=node.t('No pude bajar la voz: {dato}.', dato=problem(error)), fg=BAD)
        choice['voice'] = str(folder / f'{voice_id}.onnx')
        WINDOW['show']()
    in_background(body, work, done)


def import_voice(body, choice, status):
    path = filedialog.askopenfilename(parent=body.winfo_toplevel(), title=node.t('Tu voz de Piper'),
                                      filetypes=[(node.t('Voz de Piper'), '*.onnx')])
    if not path:
        return
    source = Path(path)
    config = source.with_name(source.name + '.json')
    if not config.exists():
        return status.config(text=node.t('Falta {name} al lado de la voz (Piper lo necesita).', name=config.name), fg=BAD)
    folder = node.HERE / 'voices'
    folder.mkdir(exist_ok=True)
    shutil.copy2(source, folder / source.name)
    shutil.copy2(config, folder / config.name)
    choice['voice'] = str(folder / source.name)
    WINDOW['show']()


def fetch_whisper(body, widget, status):
    widget.config(state='disabled', text=node.t('Bajando Whisper… (unos minutos)'))

    def done(_result, error):
        if error:
            widget.config(state='normal', text=node.t('Reintentar'))
            return status.config(text=node.t('No pude bajar Whisper: {dato}.', dato=problem(error)), fg=BAD)
        WINDOW['show']()
    in_background(body, lambda: node.model('ears'), done)


def page_memory(body, choice):
    label(body, node.t('Memoria'), FG, TITLE, pady=(0, 6))
    label(body, node.t('Con memoria, recuerdo lo que me cuentas, llevo tu diario y tus tareas, y armo bases tipo Notion. Todo queda en una bóveda de Obsidian: archivos de texto en tu PC que puedes leer y editar.'), pady=(0, 10))
    use = tk.BooleanVar(value=choice['memory'])
    for value, text in N_(((True, 'Usar memoria'), (False, 'Sin memoria (no recuerdo nada entre charlas)'))):
        tk.Radiobutton(body, text=node.t(text), variable=use, value=value, bg=BG, fg=FG, selectcolor=FIELD, font=FONT,
                       activebackground=BG, activeforeground=FG, anchor='w',
                       command=lambda: (choice.update(memory=use.get()), WINDOW['show']())).pack(fill='x')
    if not choice['memory']:
        return
    label(body, node.t('Carpeta de la bóveda'), FG, FONT, pady=(12, 2))
    line = row(body)
    text = tk.StringVar(body, choice['folder'])
    text.trace_add('write', lambda *_: choice.update(folder=text.get().strip()))
    entry(line, textvariable=text).pack(side='left', fill='x', expand=True, ipady=4)

    def browse():
        path = filedialog.askdirectory(parent=body.winfo_toplevel(), title=node.t('¿Dónde creo tu bóveda?'),
                                       initialdir=str(Path(choice['folder']).parent))
        if path:
            choice['folder'] = str(Path(path))
            WINDOW['show']()
    button(line, node.t('Elegir…'), browse).pack(side='left', padx=(6, 0))
    label(body, node.t('Si la carpeta ya es una bóveda, la uso tal cual (no borro nada).'), font=TINY)
    obsidian = find_obsidian()
    label(body, node.t('Obsidian'), FG, FONT, pady=(12, 2))
    if obsidian:
        label(body, node.t('Lo encontré en {obsidian}. Voy a sumar la bóveda a su lista para que la veas al abrirlo.', obsidian=obsidian), GOOD)
    else:
        label(body, node.t('No encontré Obsidian. No hace falta para que yo recuerde, pero sirve para ver y editar tus notas.'),
              pady=(0, 4))
        line = row(body)
        button(line, node.t('Descargar Obsidian'), lambda: webbrowser.open('https://obsidian.md/download'), accent=True
               ).pack(side='left')
        button(line, node.t('Revisar de nuevo'), WINDOW['show']).pack(side='left', padx=6)
    kepano = tk.BooleanVar(value=choice['kepano'])
    tk.Checkbutton(body, text=node.t('Sumar la plantilla de kepano (categorías y tablas para películas, libros, recetas…)'),
                   variable=kepano, bg=BG, fg=FG, selectcolor=FIELD, activebackground=BG, activeforeground=FG,
                   font=SMALL, anchor='w', wraplength=500, justify='left',
                   command=lambda: choice.update(kepano=kepano.get())).pack(fill='x', pady=(10, 0))


RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'


def starts_with_windows():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return bool(winreg.QueryValueEx(key, 'NodeAssistant')[0])
    except OSError:
        return False


def set_startup(on):
    """Que Windows abra Node al iniciar sesión (como un programa más en Inicio de la Configuración de Windows)."""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            pythonw = Path(sys.executable).with_name('pythonw.exe')
            winreg.SetValueEx(key, 'NodeAssistant', 0, winreg.REG_SZ,
                              f'"{pythonw}" "{node.HERE / "node_assistant.py"}"')
        elif starts_with_windows():
            winreg.DeleteValue(key, 'NodeAssistant')


def options():
    """Los interruptores que se aplican al instante: clave -> (texto, explicación, si está prendido, qué hacer)."""
    return N_({
        'startup': ('Iniciar con Windows', 'Me abro solo al prender la PC y espero el atajo, sin ventana.',
                    starts_with_windows, set_startup),
        'voice': ('Leer las respuestas en voz alta', 'Apagado, solo te respondo con texto.',
                  lambda: not node.saved('voz_off'), lambda on: node.save('voz_off', not on)),
        'mic': ('Micrófono', 'Apagado, solo me escribes (Ctrl + Alt + N abre la cápsula para escribir).',
                lambda: not node.MIC['off'], lambda on: on == node.MIC['off'] and node.mic_toggle()),
        'always': ('Micrófono siempre listo', 'Capta al instante, sin la espera del arranque. Queda abierto (Windows '
                   'muestra el ícono del micrófono), pero no graba nada hasta que aprietas el atajo.',
                   lambda: node.MIC['always'], lambda on: on != node.MIC['always'] and node.mic_avail_toggle()),
        'opsec': ('Modo privado', 'Nada sale de tu PC: solo modelos locales. Visión, clima, mails y Telegram quedan '
                  'en pausa.', lambda: node.OPSEC['on'], lambda on: on != node.OPSEC['on'] and node.opsec_toggle()),
        'telegram': ('Resumen del día por Telegram', 'Lo que hiciste hoy, en tu celular.',
                     lambda: node.saved('tg_resumen', True),
                     lambda on: on != node.saved('tg_resumen', True) and node.slash('/tgtoggle')),
    })


def switches(body, keys):
    for key in keys:
        if key == 'telegram' and '/tgtoggle' not in node.COMMANDS:  # sin memoria no hay diario que resumir
            continue
        text, about, current, change = options()[key]
        text, about = node.t(text), node.t(about)
        on = tk.BooleanVar(value=bool(current()))
        tk.Checkbutton(body, text=text, variable=on, bg=BG, fg=FG, selectcolor=FIELD, font=FONT, anchor='w',
                       activebackground=BG, activeforeground=FG,
                       command=(lambda var, act: lambda: act(var.get()))(on, change)).pack(fill='x', pady=(6, 0))
        tk.Label(body, text=about, bg=BG, fg=SOFT, font=TINY, anchor='w', justify='left', wraplength=460
                 ).pack(fill='x', padx=(24, 0))


def colors_picker(body):
    label(body, node.t('Colores de la cápsula'), FG, FONT, pady=(14, 2))
    current = next((name for name, colors in node.COMBOS.items() if list(colors) == node.GLOW), '')
    colors = ttk.Combobox(body, values=[name.capitalize() for name in node.COMBOS], state='readonly', font=FONT)
    colors.set(current.capitalize() if current else 'Personalizados')
    colors.bind('<<ComboboxSelected>>', lambda _e: node.feeling(colors.get().lower()))
    colors.pack(fill='x', ipady=4)
    label(body, node.t('O escribe /feeling con lo que quieras ("/feeling atardecer en la playa").'), font=TINY)


def number(body, choice, key, text, about, low, high, step):
    """Un número que se guarda al apretar Guardar."""
    line = row(body)
    tk.Label(line, text=node.t(text), bg=BG, fg=FG, font=FONT, anchor='w').pack(side='left')
    value = tk.StringVar(line, str(choice[key]))

    def keep(*_):
        try:
            choice[key] = min(high, max(low, type(low)(float(value.get().replace(',', '.')))))
        except ValueError:  # a medio escribir
            pass
    value.trace_add('write', keep)
    tk.Spinbox(line, from_=low, to=high, increment=step, textvariable=value, width=7, font=FONT, bg=FIELD, fg=FG,
               buttonbackground=FIELD, insertbackground=FG, relief='flat').pack(side='right', ipady=3)
    label(body, node.t(about), font=TINY)


def page_prefs(body, choice):
    label(body, node.t('Preferencias'), FG, TITLE, pady=(0, 6))
    label(body, node.t('Se aplican al instante. Todo esto (y más) lo cambias después con /settings.'), pady=(0, 10))
    switches(body, ('startup', 'voice', 'mic', 'always', 'opsec', 'telegram'))
    colors_picker(body)


# --- /settings: los ajustes, por secciones --------------------------------------------------------------------------

def section_general(body, choice):
    label(body, node.t('General'), FG, TITLE, pady=(0, 10))
    name_and_language(body, choice)
    switches(body, ('startup',))
    colors_picker(body)


def section_voice(body, choice):
    page_voice(body, choice)
    label(body, node.t('Micrófono y voz'), FG, FONT, pady=(16, 0))
    switches(body, ('voice', 'mic', 'always'))
    number(body, choice, 'quiet', 'No leer en voz alta respuestas de más de', 'caracteres (las largas se leen en el '
           'panel, con scroll).', 50, 5000, 50)
    number(body, choice, 'mic_warmup', 'Espera del micrófono al abrirse', 'segundos: lo que tarda en captar de verdad '
           '(el orbe queda gris ese rato). Súbelo si se come el principio de lo que dices.', 0.0, 3.0, 0.1)
    voice_engine_block(body, choice)


ENGINES = N_((('piper', 'Piper: local y liviana'), ('kokoro', 'Kokoro: local y más natural'),
               ('elevenlabs', 'ElevenLabs: en la nube, la más natural (con clave)')))
ELEVEN_STYLE = N_((('eleven_stability', 'Estabilidad', 0.0, 1.0, 0.5, 'más baja: más expresiva; más alta: más pareja'),
                   ('eleven_similarity', 'Parecido a la voz original', 0.0, 1.0, 0.75, ''),
                   ('eleven_style', 'Estilo (exagera la forma de hablar de la voz)', 0.0, 1.0, 0.0, ''),
                   ('eleven_speed', 'Velocidad', 0.7, 1.2, 1.0, '')))


def slider(body, key, text, low, high, default, about=''):
    """Un control deslizable que se guarda al instante (la voz lo usa en la próxima frase)."""
    label(body, node.t(text), FG, SMALL, pady=(6, 0))
    scale = tk.Scale(body, from_=low, to=high, resolution=0.05, orient='horizontal', bg=BG, fg=FG, troughcolor=FIELD,
                     highlightthickness=0, bd=0, activebackground=node.GLOW[0], showvalue=True, font=TINY,
                     command=lambda value: node.save(key, float(value)))
    scale.set(node.saved(key, default))
    scale.pack(fill='x')
    if about:
        label(body, node.t(about), font=TINY)


def try_voice():
    threading.Thread(target=node.speak, args=(node.t('Así sueno. Todos los sistemas en orden.'),), daemon=True).start()


def voice_engine_block(body, choice):
    """Elegir con qué voz habla Node (se aplica al instante) y, abajo, la voz, el modelo y el estilo de ese motor."""
    label(body, node.t('Motor de voz'), FG, FONT, pady=(16, 2))
    engine = tk.StringVar(body, node.saved('voice_engine', 'piper'))
    for value, text in ENGINES:
        tk.Radiobutton(body, text=node.t(text), variable=engine, value=value, bg=BG, fg=FG, selectcolor=FIELD,
                       font=SMALL, activebackground=BG, activeforeground=FG, anchor='w',
                       command=lambda: (node.save('voice_engine', engine.get()), WINDOW['show']())).pack(fill='x')
    status = label(body, '')
    chosen = engine.get()
    if chosen == 'kokoro':
        if node.LANGUAGE not in node.KOKORO_LANGS:
            label(body, node.t('Kokoro no tiene voces en este idioma: se usa Piper.'), BAD)
        elif not node.kokoro_ready():
            get = button(body, node.t('Descargar Kokoro (unos 120 MB)'), None, accent=True)

            def fetch():
                get.config(state='disabled', text=node.t('Bajando…'))
                node.KOKORO_DIR.mkdir(parents=True, exist_ok=True)

                def work():
                    for name, url in node.KOKORO_FILES.items():
                        download(url, node.KOKORO_DIR / name,
                                 lambda text, n=name: body.after(0, lambda: status.config(text=f'{n}: {text}', fg=SOFT)))
                in_background(body, work, lambda _r, error: status.config(
                    text=node.t('No pude bajar Kokoro: {error}.', error=problem(error)), fg=BAD) if error else
                    WINDOW['show']())
            get.config(command=fetch)
            get.pack(anchor='w', pady=(4, 0))
        else:
            voices = node.kokoro_voices()
            label(body, node.t('Voz'), FG, SMALL, pady=(6, 2))
            pick = ttk.Combobox(body, values=voices, state='readonly', font=FONT)
            pick.set(node.saved('kokoro_voice') if node.saved('kokoro_voice') in voices else voices[0])
            pick.bind('<<ComboboxSelected>>', lambda _e: node.save('kokoro_voice', pick.get()))
            pick.pack(fill='x', ipady=3)
            label(body, node.t('La letra del medio dice si es femenina (f) o masculina (m): ef_dora, em_alex…'), font=TINY)
            slider(body, 'kokoro_speed', N_('Velocidad'), 0.7, 1.3, 1.0)
    elif chosen == 'elevenlabs':
        label(body, node.t('Lo que dice Node viaja a ElevenLabs. El plan gratis trae unos 10.000 caracteres por mes; si '
                           'se acaba o no hay internet (o con /opsec), habla con la voz local.'), font=TINY)
        label(body, node.t('Clave API'), FG, SMALL, pady=(6, 2))
        line = row(body)
        key = entry(line, show='•')
        key.pack(side='left', fill='x', expand=True, ipady=4)
        has = node.secret('ELEVENLABS_API_KEY')
        button(line, node.t('Guardar'), lambda: key.get().strip() and (
            save_key('ELEVENLABS_API_KEY', key.get().strip()), WINDOW['show']())).pack(side='left', padx=(6, 0))
        label(body, node.t('Ya hay una clave guardada.') if has else
              node.t('Consigue una en elevenlabs.io → Developers → API Keys.'), GOOD if has else SOFT, TINY)
        if has:
            label(body, node.t('Voz'), FG, SMALL, pady=(6, 2))
            line = row(body)
            names = {}
            pick = ttk.Combobox(line, state='readonly', font=FONT)
            pick.set(node.saved('eleven_voice_name', 'George'))
            pick.pack(side='left', fill='x', expand=True, ipady=3)
            pick.bind('<<ComboboxSelected>>', lambda _e: (node.save('eleven_voice', names[pick.get()]),
                                                          node.save('eleven_voice_name', pick.get())))

            def find_voices():
                status.config(text=node.t('Buscando tus voces…'), fg=SOFT)

                def done(result, error):
                    if error:
                        return status.config(text=node.t('No pude: {error}.', error=problem(error)), fg=BAD)
                    names.clear()
                    names.update({v['name']: v['voice_id'] for v in result.get('voices', [])})
                    pick.config(values=sorted(names))
                    status.config(text=node.t('{count} voces: elige una.', count=len(names)), fg=SOFT)
                in_background(body, lambda: get_eleven('/v1/voices'), done)
            button(line, node.t('Buscar mis voces'), find_voices).pack(side='left', padx=(6, 0))
            label(body, node.t('Modelo'), FG, SMALL, pady=(6, 2))
            models = {name: code for code, name in node.ELEVEN_MODELS.items()}
            model = ttk.Combobox(body, values=list(models), state='readonly', font=FONT)
            model.set(node.ELEVEN_MODELS.get(node.saved('eleven_model', 'eleven_flash_v2_5'), 'Flash v2.5'))
            model.bind('<<ComboboxSelected>>', lambda _e: node.save('eleven_model', models[model.get()]))
            model.pack(fill='x', ipady=3)
            label(body, node.t('Flash y Turbo responden más rápido; Multilingual v2 suena más natural; v3 es el más '
                               'expresivo.'), font=TINY)
            for key_, text, low, high, default, about in ELEVEN_STYLE:
                slider(body, key_, text, low, high, default, about)
    button(body, node.t('Probar voz'), try_voice).pack(anchor='w', pady=(10, 0))


def get_eleven(path):
    request = urllib.request.Request('https://api.elevenlabs.io' + path, headers={
        'xi-api-key': node.secret('ELEVENLABS_API_KEY'), 'User-Agent': 'NodeAssistant'})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def section_memory(body, choice):
    page_memory(body, choice)
    if choice['memory']:
        label(body, node.t('Resumen del día'), FG, FONT, pady=(16, 0))
        switches(body, ('telegram',))
        number(body, choice, 'resumen_hora', 'Hora del resumen', 'de 0 a 23: se escribe en tu diario y llega por '
               'Telegram.', 0, 23, 1)
        if node.VAULT:
            button(body, node.t('Abrir mi bóveda'), lambda: os.startfile(node.VAULT)).pack(anchor='w', pady=(10, 0))


SERVICES = N_([  # (servicio, variable de Windows, dónde se consigue, si es secreta)
    ('Discord: webhook', 'DISCORD_WEBHOOK_URL', 'En el canal: Editar canal → Integraciones → Webhooks → Copiar URL.',
     True),
    ('OBS: contraseña del WebSocket', 'OBS_WEBSOCKET_PASSWORD', 'En OBS: Herramientas → Ajustes del servidor '
     'WebSocket.', True),
    ('Cloudflare: Account ID', 'CLOUDFLARE_ACCOUNT_ID', 'En dash.cloudflare.com, al lado de Workers AI.', False),
])


def telegram_block(body):
    """Tu propio bot, atado a tu PC: crearlo con @BotFather, pegar su token y vincular tu chat con un código."""
    label(body, node.t('Telegram'), FG, FONT, pady=(6, 2))
    bot = sys.modules.get('plugin_telegram')
    if not bot:
        return label(body, node.t('El plugin telegram está apagado (/settings → Plugins).'), font=TINY)
    label(body, node.t('Cada persona usa su propio bot: el tuyo queda atado a tu PC y solo te obedece a ti.'), font=TINY)
    if node.secret('TELEGRAM_CHAT_ID') and node.secret('TELEGRAM_BOT_TOKEN'):
        label(body, node.t('Vinculado: tu bot solo te obedece a ti.'), GOOD)

        def unlink():
            node.delete_secret('TELEGRAM_CHAT_ID')
            WINDOW['show']()
        return button(body, node.t('Desvincular'), unlink).pack(anchor='w', pady=(4, 0))
    line = row(body)
    tk.Label(line, text=node.t('1. Crea tu bot:'), bg=BG, fg=FG, font=SMALL).pack(side='left')
    button(line, node.t('Abrir @BotFather'), lambda: webbrowser.open('https://t.me/BotFather')).pack(side='left', padx=6)
    label(body, node.t('Escríbele /newbot, elige un nombre y copia el token que te da.'), font=TINY)
    label(body, node.t('2. Pega el token:'), FG, SMALL, pady=(8, 2))
    line = row(body)
    token = entry(line, show='•')
    token.pack(side='left', fill='x', expand=True, ipady=4)
    if node.secret('TELEGRAM_BOT_TOKEN'):
        label(body, node.t('Ya hay un token guardado.'), GOOD, TINY)

    def keep():
        if token.get().strip():
            save_key('TELEGRAM_BOT_TOKEN', token.get().strip())
            bot.start()  # sin reiniciar: el bot empieza a escuchar ya
            WINDOW['show']()
    button(line, node.t('Guardar'), keep).pack(side='left', padx=(6, 0))
    label(body, node.t('3. Vincula tu chat:'), FG, SMALL, pady=(8, 2))
    shown = label(body, '', FG, TITLE)
    status = label(body, '')

    def link():
        if not node.secret('TELEGRAM_BOT_TOKEN'):
            return status.config(text=node.t('Primero guarda el token de tu bot.'), fg=BAD)
        bot.start()
        code = bot.pair_code()
        shown.config(text=code)
        status.config(text=node.t('Mándale este código a tu bot en Telegram. Vence en 10 minutos.'), fg=SOFT)

        def wait():
            if not shown.winfo_exists():
                return
            if bot.PAIRING['chat']:
                return WINDOW['show']()
            if bot.PAIRING['code'] != code or time.time() > bot.PAIRING['until']:
                shown.config(text='')
                return status.config(text=node.t('El código venció. Toca Vincular otra vez.'), fg=BAD)
            shown.after(1000, wait)
        wait()
    button(body, node.t('Vincular'), link, accent=True).pack(anchor='w', pady=(2, 0))


def section_services(body, choice):
    label(body, node.t('Servicios'), FG, TITLE, pady=(0, 6))
    label(body, node.t('Para que use tus cuentas. Las claves van a las variables de Windows de tu usuario, nunca a un archivo, y se aplican al reiniciar.'), pady=(0, 4))
    telegram_block(body)
    status = label(body, '')
    for title, env, hint, hidden in SERVICES:
        label(body, node.t(title), FG, FONT, pady=(6, 2))
        line = row(body)
        field = entry(line, show='•' if hidden else '')
        field.pack(side='left', fill='x', expand=True, ipady=4)
        has = node.secret(env)
        if has and not hidden:
            field.insert(0, has)

        def keep(name=env, widget=field, title_=title):
            if widget.get().strip():
                save_key(name, widget.get().strip())
                status.config(text=node.t('{title}: guardado. Se aplica al reiniciar.', title=title_), fg=GOOD)
        button(line, node.t('Guardar'), keep).pack(side='left', padx=(6, 0))
        label(body, (node.t('Ya está guardado. ') if has else '') + node.t(hint), GOOD if has else SOFT, TINY)
    label(body, node.t('Google (Gmail y Calendar)'), FG, FONT, pady=(12, 2))
    google = sys.modules.get('plugin_google')
    if google and google.TOKEN.exists():
        label(body, node.t('Conectado.'), GOOD)
    elif google and google.CLIENT.exists():
        connect = button(body, node.t('Conectar Google'), None)

        def done(_result, error):
            connect.config(state='normal', text=node.t('Conectar Google'))
            status.config(text=node.t('No se pudo: {dato}.', dato=problem(error)) if error else node.t('Google conectado.'),
                          fg=BAD if error else GOOD)
        connect.config(command=lambda: (connect.config(state='disabled', text=node.t('Esperando al navegador…')),
                                        in_background(body, google.authorize, done)))
        connect.pack(anchor='w')
    else:
        label(body, node.t('Primero hay que crear tu acceso en Google Cloud (unos minutos, una sola vez).'), pady=(0, 4))
        button(body, node.t('Ver cómo'), lambda: os.startfile(node.HERE / 'plugins' / 'LEEME.md')).pack(anchor='w')


def section_advanced(body, choice):
    label(body, node.t('Avanzado'), FG, TITLE, pady=(0, 6))
    label(body, node.t('Personalidad'), FG, FONT, pady=(4, 2))
    text = tk.Text(body, height=5, wrap='word', bg=FIELD, fg=FG, insertbackground=FG, relief='flat', font=SMALL,
                   padx=8, pady=6)
    text.insert('1.0', choice['persona'])
    text.bind('<KeyRelease>', lambda _e: choice.update(persona=text.get('1.0', 'end').strip()))
    text.pack(fill='x')
    label(body, node.t('Cómo habla Node. El idioma y el largo de las respuestas los pone Node solo.'), font=TINY)
    button(body, node.t('Volver a la de fábrica'), lambda: (choice.update(persona=node.CHARACTER), WINDOW['show']())
           ).pack(anchor='w', pady=(4, 0))
    number(body, choice, 'temperature', 'Creatividad (temperatura)', 'de 0 a 1: más bajo, más sensato y predecible; '
           'más alto, más creativo (y más disparates).', 0.0, 1.0, 0.1)
    label(body, node.t('Whisper (entenderte sin internet)'), FG, FONT, pady=(12, 2))
    size = ttk.Combobox(body, values=['tiny', 'base', 'small', 'medium'], state='readonly', font=FONT)
    size.set(choice['whisper'])
    size.bind('<<ComboboxSelected>>', lambda _e: choice.update(whisper=size.get()))
    size.pack(fill='x', ipady=4)
    label(body, node.t('Más grande entiende mejor pero es más lento (tiny 75 MB, small 460 MB, medium 1,5 GB).'), font=TINY)
    ears = tk.BooleanVar(value=choice['cloud_ears'])
    tk.Checkbutton(body, text=node.t('Transcribir mi voz con Groq (0,3 s) cuando hay clave'), variable=ears, bg=BG, fg=FG,
                   selectcolor=FIELD, font=FONT, anchor='w', activebackground=BG, activeforeground=FG,
                   command=lambda: choice.update(cloud_ears=ears.get())).pack(fill='x', pady=(10, 0))
    switches(body, ('opsec',))


CORE_PLUGINS = {'setup'}  # sin este no hay /setup ni /settings: no se puede apagar ni quitar
WARNING = N_('Un plugin es código que corre con los mismos permisos que Node: puede leer tus archivos y usar internet. '
           'Instala solo los de alguien en quien confíes, y si puedes, revisa el código antes.')


def plugin_about(path):
    """La primera línea de la explicación de arriba del plugin (sin ejecutarlo)."""
    import ast
    try:
        doc = ast.get_docstring(ast.parse(path.read_text(encoding='utf-8'))) or ''
    except (SyntaxError, UnicodeDecodeError, OSError):
        return node.t('No se puede leer: tiene un error.')
    return node.t(doc.strip().splitlines()[0]) if doc.strip() else ''  # traducida por tools/traducir.py


def install_plugin(source_name, code, status):
    """Guarda un plugin nuevo en plugins/ (si es Python válido y tiene setup), apagado hasta que lo revises."""
    import ast
    name = re.sub(r'[^a-z0-9_]', '_', Path(source_name).stem.lower()).strip('_') or 'plugin'
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        return status.config(text=node.t('No es un plugin válido: tiene un error en la línea {lineno}.', lineno=error.lineno), fg=BAD)
    if not any(isinstance(item, ast.FunctionDef) and item.name == 'setup' for item in tree.body):
        return status.config(text=node.t('No es un plugin de Node: le falta la función setup(node).'), fg=BAD)
    target = node.HERE / 'plugins' / f'{name}.py'
    if target.exists():
        return status.config(text=node.t('Ya hay un plugin llamado {name}. Quita el viejo primero.', name=name), fg=BAD)
    target.write_text(code, encoding='utf-8')
    off = set(node.saved('plugins_off', []))
    off.add(name)  # entra apagado: lo prendes después de revisarlo
    node.save('plugins_off', sorted(off))
    WINDOW['show']()
    WINDOW['status'].config(text=node.t('Instalé {name}, apagado. Revísalo, préndelo y guarda para reiniciar.', name=name), fg=GOOD)


def raw_link(url):
    """Un enlace de GitHub a un archivo (github.com/…/blob/…) como su versión descargable."""
    match = re.match(r'https://github\.com/([^/]+)/([^/]+)/blob/(.+)', url)
    return f'https://raw.githubusercontent.com/{match[1]}/{match[2]}/{match[3]}' if match else url


def section_plugins(body, choice):
    label(body, node.t('Plugins'), FG, TITLE, pady=(0, 6))
    label(body, node.t('Cada plugin suma habilidades. Los cambios se aplican al reiniciar.'), pady=(0, 4))
    label(body, node.t(WARNING), '#ffd479', TINY, pady=(0, 8))
    off = set(node.saved('plugins_off', []))
    for path in sorted((node.HERE / 'plugins').glob('*.py')):
        line = row(body)
        on = tk.BooleanVar(value=path.stem not in off)

        def flip(name=path.stem, var=on):
            now = set(node.saved('plugins_off', []))
            (now.discard if var.get() else now.add)(name)
            node.save('plugins_off', sorted(now))
        tk.Checkbutton(line, variable=on, bg=BG, activebackground=BG, selectcolor=FIELD, relief='flat', command=flip,
                       state='disabled' if path.stem in CORE_PLUGINS else 'normal').pack(side='left')
        text = tk.Frame(line, bg=BG)
        text.pack(side='left', fill='x', expand=True)
        tk.Label(text, text=path.stem, bg=BG, fg=FG, font=FONT, anchor='w').pack(fill='x')
        tk.Label(text, text=plugin_about(path)[:110], bg=BG, fg=SOFT, font=TINY, anchor='w', justify='left',
                 wraplength=380).pack(fill='x')
        if path.stem not in CORE_PLUGINS:
            button(line, node.t('Quitar'), (lambda p: lambda: remove_plugin(p))(path)).pack(side='right')
        button(line, node.t('Ver código'), (lambda p: lambda: os.startfile(p, 'edit'))(path)).pack(side='right', padx=4)
    label(body, node.t('Instalar un plugin'), FG, FONT, pady=(14, 2))
    status = label(body, '')
    line = row(body)
    link = entry(line)
    link.pack(side='left', fill='x', expand=True, ipady=4)

    def from_link():
        url = raw_link(link.get().strip())
        if not url.startswith('https://'):
            return status.config(text=node.t('Pega un enlace https a un archivo .py (por ejemplo de GitHub).'), fg=BAD)
        status.config(text=node.t('Bajando…'), fg=SOFT)

        def work():
            request = urllib.request.Request(url, headers={'User-Agent': 'NodeAssistant'})
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.read(512_000).decode('utf-8')
        in_background(body, work, lambda code, error: status.config(text=node.t('No pude bajarlo: {dato}.', dato=problem(error)),
                                                                     fg=BAD) if error else
                      install_plugin(urllib.parse.urlparse(url).path, code, status))
    button(line, node.t('Instalar desde enlace'), from_link).pack(side='left', padx=(6, 0))

    def from_file():
        path = filedialog.askopenfilename(parent=body.winfo_toplevel(), title=node.t('Un plugin de Node'),
                                          filetypes=[(node.t('Plugin de Node'), '*.py')])
        if path:
            install_plugin(path, Path(path).read_text(encoding='utf-8'), status)
    button(body, node.t('Instalar desde un archivo…'), from_file).pack(anchor='w', pady=(6, 0))
    label(body, node.t('Entra apagado: revisa el código, préndelo y toca "Guardar y reiniciar". ¿Quieres crear uno? En GitHub, abre un issue "Nuevo plugin" en el repositorio de Node, o corre tools\\crear_plugin.py.'), font=TINY,
          pady=(4, 0))


def remove_plugin(path):
    """Lo saca de plugins/ a plugins_quitados/ (no lo borra, por si te arrepientes)."""
    target = node.HERE / 'plugins_quitados'
    target.mkdir(exist_ok=True)
    shutil.move(str(path), str(target / path.name))
    WINDOW['show']()
    WINDOW['status'].config(text=node.t('Quité {stem} (quedó en plugins_quitados). Se aplica al reiniciar.', stem=path.stem), fg=GOOD)


def section_tools(body, choice):
    """Cada herramienta (lo que Node puede hacer en la PC), agrupada por el plugin que la trae, para prenderla o apagarla."""
    label(body, node.t('Herramientas'), FG, TITLE, pady=(0, 6))
    label(body, node.t('Lo que Node puede hacer en tu PC. Apaga lo que no quieras que haga: la IA deja de verlo y, si '
                       'igual se lo pides, te avisa que está apagado. Se aplica al instante.'), pady=(0, 6))
    groups = {}
    for tool_ in node.TOOLS:
        handler = node.PLUGINS.get(tool_['function']['name'])
        group = handler.__module__.replace('plugin_', '') if handler else 'Node'
        groups.setdefault(group, []).append(tool_['function'])
    for group, tools in groups.items():
        label(body, group, FG, FONT, pady=(10, 0))
        for function in tools:
            about = node.t(function['description'])
            about = re.split(r'(?<=[.:])\s', about, maxsplit=1)[0].rstrip('.:')  # la primera frase
            on = tk.BooleanVar(value=function['name'] not in node.saved('tools_off', []))

            def flip(name=function['name'], var=on):
                off = set(node.saved('tools_off', []))
                (off.discard if var.get() else off.add)(name)
                node.save('tools_off', sorted(off))
            tk.Checkbutton(body, text=f"{function['name']}  ·  {about[:140]}", variable=on, command=flip, bg=BG,
                           fg=FG, selectcolor=FIELD, font=SMALL, anchor='w', justify='left', wraplength=520,
                           activebackground=BG, activeforeground=FG).pack(fill='x', padx=(8, 0))


SKILL_WARNING = N_('Una skill no es código, pero le da instrucciones a la IA. Instala solo las de alguien en quien '
                   'confíes y léela antes de prenderla; lo que cambia cosas en tu PC igual te pide confirmación.')
# Las claves de la cabecera quedan en inglés (Node entiende name/description/words y nombre/descripcion/palabras):
# solo se traducen los valores, así la plantilla sirve en cualquier idioma.
SKILL_TEMPLATE = '---\nname: {name}\ndescription: {about}\nwords: {words}\n---\n{body}\n'
SKILL_PARTS = N_(('Mi skill', 'Para qué sirve, en una frase.', 'palabras que la activan, separadas por comas',
                  'Cuando el usuario pida …, haz esto, usando una herramienta por paso:\n\n1. …\n2. …\n\n'
                  'Al final, dile en una frase cómo salió.'))


def edit(path):
    subprocess.Popen(['notepad.exe', str(path)])  # el Bloc de notas: está en todas las PC y edita texto sin vueltas


def install_skill(source_name, text, status):
    """Guarda una skill nueva en skills/ (si tiene la cabecera entre ---), apagada hasta que la leas."""
    name = re.sub(r'[^a-z0-9_-]', '-', Path(source_name).stem.lower()).strip('-') or 'skill'
    if not re.match(r'---\s*\n.*?\n---', text, re.S):
        return status.config(text=node.t('No parece una skill: le falta la cabecera entre --- (nombre, descripcion, '
                                         'palabras).'), fg=BAD)
    target = node.SKILLS_DIR / f'{name}.md'
    if target.exists():
        return status.config(text=node.t('Ya hay una skill llamada {name}. Quita la vieja primero.', name=name), fg=BAD)
    node.SKILLS_DIR.mkdir(exist_ok=True)
    target.write_text(text, encoding='utf-8')
    off = set(node.saved('skills_off', []))
    off.add(name)
    node.save('skills_off', sorted(off))
    WINDOW['show']()
    WINDOW['status'].config(text=node.t('Instalé la skill {name}, apagada. Léela y préndela.', name=name), fg=GOOD)


def new_skill():
    node.SKILLS_DIR.mkdir(exist_ok=True)
    number = 1
    while (node.SKILLS_DIR / f'mi-skill-{number}.md').exists():
        number += 1
    path = node.SKILLS_DIR / f'mi-skill-{number}.md'
    name, about, words, body = (node.t(part) for part in SKILL_PARTS)
    path.write_text(SKILL_TEMPLATE.format(name=name, about=about, words=words, body=body), encoding='utf-8')
    edit(path)
    WINDOW['show']()
    WINDOW['status'].config(text=node.t('Escribe tu skill en el Bloc de notas y guarda: queda prendida.'), fg=GOOD)


def remove_skill(path):
    target = node.HERE / 'skills_quitadas'
    target.mkdir(exist_ok=True)
    shutil.move(str(path), str(target / path.name))
    WINDOW['show']()
    WINDOW['status'].config(text=node.t('Quité {name} (quedó en skills_quitadas).', name=path.stem), fg=GOOD)


def section_skills(body, choice):
    label(body, node.t('Skills'), FG, TITLE, pady=(0, 6))
    label(body, node.t('Instrucciones en texto que le enseñan a Node cómo y cuándo usar lo que ya sabe hacer: rutinas '
                       '("modo trabajo"), estilos ("corrígeme el inglés") o datos tuyos. Una skill se activa cuando '
                       'dices alguna de sus palabras. Se aplica al instante.'), pady=(0, 4))
    label(body, node.t(SKILL_WARNING), '#ffd479', TINY, pady=(0, 8))
    off = set(node.saved('skills_off', []))
    for skill in node.load_skills(every=True):
        line = row(body)
        on = tk.BooleanVar(value=skill['id'] not in off)

        def flip(name=skill['id'], var=on):
            now = set(node.saved('skills_off', []))
            (now.discard if var.get() else now.add)(name)
            node.save('skills_off', sorted(now))
        tk.Checkbutton(line, variable=on, bg=BG, activebackground=BG, selectcolor=FIELD, relief='flat',
                       command=flip).pack(side='left')
        text = tk.Frame(line, bg=BG)
        text.pack(side='left', fill='x', expand=True)
        tk.Label(text, text=skill['name'], bg=BG, fg=FG, font=FONT, anchor='w').pack(fill='x')
        words = ', '.join(skill['words'][:4]) if not skill['always'] else node.t('siempre')
        tk.Label(text, text=f"{skill['about']}  ·  {words}"[:140], bg=BG, fg=SOFT, font=TINY, anchor='w',
                 justify='left', wraplength=380).pack(fill='x')
        button(line, node.t('Quitar'), (lambda p: lambda: remove_skill(p))(skill['path'])).pack(side='right')
        button(line, node.t('Editar'), (lambda p: lambda: edit(p))(skill['path'])).pack(side='right', padx=4)
    button(body, node.t('+ Nueva skill'), new_skill, accent=True).pack(anchor='w', pady=(12, 0))
    label(body, node.t('Instalar una skill'), FG, FONT, pady=(14, 2))
    status = label(body, '')
    line = row(body)
    link = entry(line)
    link.pack(side='left', fill='x', expand=True, ipady=4)

    def from_link():
        url = raw_link(link.get().strip())
        if not url.startswith('https://'):
            return status.config(text=node.t('Pega un enlace https a un archivo .md (por ejemplo de GitHub).'), fg=BAD)
        status.config(text=node.t('Bajando…'), fg=SOFT)

        def work():
            request = urllib.request.Request(url, headers={'User-Agent': 'NodeAssistant'})
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.read(64_000).decode('utf-8')

        def done(text, error):
            if error:
                return status.config(text=node.t('No pude bajarla: {error}.', error=problem(error)), fg=BAD)
            install_skill(urllib.parse.urlparse(url).path, text, status)
        in_background(body, work, done)
    button(line, node.t('Instalar desde enlace'), from_link).pack(side='left', padx=(6, 0))

    def from_file():
        path = filedialog.askopenfilename(parent=body.winfo_toplevel(), title=node.t('Una skill de Node'),
                                          filetypes=[(node.t('Skill de Node'), '*.md')])
        if path:
            install_skill(path, Path(path).read_text(encoding='utf-8'), status)
    button(body, node.t('Instalar desde un archivo…'), from_file).pack(anchor='w', pady=(6, 0))


SECTIONS = N_([('General', section_general), ('IA en la nube', page_cloud), ('Modelos locales', page_local),
               ('Voz y micrófono', section_voice), ('Memoria', section_memory), ('Herramientas', section_tools),
               ('Plugins', section_plugins), ('Skills', section_skills), ('Servicios', section_services), ('Avanzado', section_advanced)])


def page_done(body, choice):
    label(body, node.t('Listo'), FG, TITLE, pady=(0, 6))
    cloud = [p['name'] for p in node.PROVIDERS if p['name'] not in node.saved('apagados', [])
             and (not p.get('key') or node.secret(p['key']))]
    voice = Path(choice['voice'])
    lines = [node.t('Nombre: {name}', name=choice['name'] or node.t('(sin nombre)')),
             node.t('Idioma: {language}', language=node.LANGUAGES[choice['language']][0]),
             node.t('IA en la nube: {cloud}', cloud=', '.join(cloud) if cloud else node.t('ninguna todavía')),
             node.t('Modelo local: {model}', model=choice['chat_model'] if ollama_models() else
                    node.t('ninguno (Ollama no está)')),
             node.t('Voz: {voice}', voice=voice.stem if voice.exists() else node.t('ninguna (respondo con texto)')),
             node.t('Memoria: {memory}', memory=choice['folder'] if choice['memory'] else node.t('apagada'))]
    for text in lines:
        label(body, text, FG, FONT, pady=2)
    if not cloud and not ollama_models():
        label(body, node.t('Ojo: sin IA en la nube ni modelo local no puedo responder. Vuelve al paso 2 o 3.'), BAD, pady=(10, 0))
    label(body, node.t('Al terminar me reinicio para aplicar todo (tarda unos segundos). Lo cambias cuando quieras con /settings.'), pady=(14, 0))
    WINDOW['status'] = label(body, '', pady=(6, 0))


def finish(choice):
    """Guarda todo, crea la bóveda si hace falta y reinicia Node."""
    status = WINDOW['status']
    for key in SAVED_ON_RESTART:
        node.save(key, choice[key])
    if not choice['memory']:
        node.save('vault', '')
        node.save('setup_done', True)
        return restart()
    folder = Path(choice['folder']).expanduser()
    status.config(text=node.t('Creando la bóveda…'), fg=SOFT)

    def work():
        (folder / 'Node Assistant').mkdir(parents=True, exist_ok=True)
        (folder / '.obsidian').mkdir(exist_ok=True)
        if choice['kepano']:
            kepano_template(folder)
        if find_obsidian():
            register_vault(folder)

    def done(_result, error):
        if error:
            return status.config(text=node.t('No pude crear la bóveda: {dato}.', dato=problem(error)), fg=BAD)
        node.save('vault', str(folder))
        node.save('setup_done', True)
        restart()
    in_background(status, work, done)


PAGES = [page_welcome, page_cloud, page_local, page_voice, page_memory, page_prefs, page_done]


def current_choice():
    """Lo que está configurado ahora (el punto de partida de /setup y /settings)."""
    vault = node.saved('vault')
    return {'name': node.saved('name', ''), 'language': node.LANGUAGE, 'chat_model': node.CHAT,
            'voice': str(node.VOICE), 'memory': bool(vault) or not node.saved('setup_done'),
            'folder': vault or str(Path.home() / 'Documents' / 'Node'), 'kepano': not vault,
            'persona': node.saved('persona') or node.CHARACTER, 'temperature': node.TEMPERATURE,
            'whisper': node.HEARING, 'quiet': node.QUIET, 'mic_warmup': node.MIC_WARMUP,
            'cloud_ears': node.CLOUD_EARS, 'resumen_hora': node.saved('resumen_hora', 20)}


def new_window(title, size):
    """Una sola ventana de configuración a la vez (/setup o /settings)."""
    if WINDOW.get('win') and WINDOW['win'].winfo_exists():
        WINDOW['win'].destroy()
    win = WINDOW['win'] = tk.Toplevel()
    win.title(title)
    win.configure(bg=BG)
    win.geometry(size)
    dark(win)
    win.bind('<Escape>', lambda _e: win.destroy())
    return win


def on_top(win):
    win.attributes('-topmost', True)  # que aparezca arriba de todo (sobre todo la primera vez) y después normal
    win.after(800, lambda: win.attributes('-topmost', False))
    win.focus_force()


def wizard():
    choice = current_choice()
    win = new_window('Node Assistant · ' + node.t('Configuración'), '600x740')
    win.minsize(560, 640)
    steps = tk.Label(win, bg=BG, fg=SOFT, font=TINY, anchor='w')
    steps.pack(fill='x', padx=28, pady=(18, 0))
    bar = tk.Frame(win, bg=BG)
    bar.pack(side='bottom', fill='x', padx=28, pady=18)  # antes que el contenido: los botones siempre se ven
    holder = tk.Frame(win, bg=BG)
    holder.pack(fill='both', expand=True, padx=28, pady=(8, 0))
    back = button(bar, node.t('Atrás'), lambda: go(-1))
    back.pack(side='left')
    ahead = button(bar, node.t('Siguiente'), lambda: go(1), accent=True)
    ahead.pack(side='right')
    state = {'page': 0}
    names = [node.t(name) for name in N_(['Bienvenida', 'IA en la nube', 'Modelos', 'Voz', 'Memoria', 'Preferencias',
                                          'Listo'])]

    def show():
        for child in holder.winfo_children():
            child.destroy()
        body = scrollable(holder)
        PAGES[state['page']](body, choice)
        steps.config(text='   ›   '.join(f'[{n}]' if i == state['page'] else n for i, n in enumerate(names)))
        back.config(state='normal' if state['page'] else 'disabled')
        ahead.config(text=node.t('Terminar') if state['page'] == len(PAGES) - 1 else node.t('Siguiente'))

    def go(step):
        if state['page'] == len(PAGES) - 1 and step > 0:
            return finish(choice)
        state['page'] = max(0, min(len(PAGES) - 1, state['page'] + step))
        show()

    WINDOW['show'] = show
    show()
    on_top(win)


def settings():
    """Los ajustes: secciones a la izquierda; los interruptores se aplican al instante, lo demás con Guardar."""
    choice = current_choice()
    choice['memory'] = bool(node.saved('vault'))
    win = new_window('Node Assistant · ' + node.t('Ajustes'), '820x780')
    win.minsize(760, 660)
    side = tk.Frame(win, bg='#0b0d16', width=190)
    side.pack(side='left', fill='y')
    side.pack_propagate(False)
    tk.Label(side, text=node.t('Ajustes'), bg='#0b0d16', fg=FG, font=('Segoe UI Variable Display', 15), anchor='w'
             ).pack(fill='x', padx=18, pady=(20, 14))
    bar = tk.Frame(win, bg=BG)
    bar.pack(side='bottom', fill='x', padx=28, pady=16)
    holder = tk.Frame(win, bg=BG)
    holder.pack(side='left', fill='both', expand=True, padx=28, pady=(20, 0))
    WINDOW['status'] = tk.Label(bar, text='', bg=BG, fg=SOFT, font=SMALL, anchor='w')
    WINDOW['status'].pack(side='left', fill='x', expand=True)
    button(bar, node.t('Guardar y reiniciar'), lambda: finish(choice), accent=True).pack(side='right')
    button(bar, node.t('Cerrar'), win.destroy).pack(side='right', padx=6)
    state = {'section': 0}
    tabs = []

    def show():
        for child in holder.winfo_children():
            child.destroy()
        body = scrollable(holder)
        SECTIONS[state['section']][1](body, choice)
        for i, tab in enumerate(tabs):
            tab.config(bg=FIELD if i == state['section'] else '#0b0d16', fg=FG if i == state['section'] else SOFT)

    for i, (title, _page) in enumerate(SECTIONS):
        tab = tk.Button(side, text=node.t(title), anchor='w', relief='flat', font=FONT, padx=18, pady=7, cursor='hand2',
                        bd=0, activebackground=FIELD, activeforeground=FG,
                        command=(lambda k: lambda: (state.update(section=k), show()))(i))
        tab.pack(fill='x')
        tabs.append(tab)
    WINDOW['show'] = show
    show()
    on_top(win)


def open_window(function, what):
    def handler(_rest=''):
        node.UI['after'](0, function)
        return node.t('Abrí {what} en la PC.', what=node.t(what))
    return handler


def setup(node_):
    global node
    node = node_
    node.command('/setup', node.t('configura Node desde cero, paso a paso: idioma, IA, modelos, voz y memoria'),
                 open_window(wizard, N_('la configuración')))
    node.command('/settings', node.t('los ajustes de Node: idioma, IA, modelos, voz, micrófono, memoria, servicios y más'),
                 open_window(settings, N_('los ajustes')))
    # La primera vez (o si nunca se terminó): se abre solo. Tk ya existe cuando corren los STARTERS.
    node.STARTERS.append(lambda: node.saved('setup_done') or tk._default_root.after(800, wizard))
