"""Comandos y archivos: Node ejecuta comandos de PowerShell y maneja tus archivos.
"¿qué hay en Descargas?", "busca el archivo factura", "¿qué dice notas.txt del escritorio?", "abre el pdf del
contrato", "mueve las fotos.zip de Descargas a Documentos", "renombra informe.docx a informe final.docx",
"borra captura.png del escritorio", "crea una carpeta Proyectos en Documentos", "¿cuál es mi IP?",
"actualiza mis programas con winget", "¿cuánto pesa la carpeta Videos?".
Mirar (listar, buscar, leer, abrir un documento) lo hace directo. Todo lo que cambia algo (ejecutar un comando,
mover, copiar, renombrar, borrar, crear) te lo muestra y pregunta "¿lo hago?": respondes "sí" o "no" en el próximo
minuto, por voz, escribiendo o por Telegram. Borrar manda a la Papelera (se puede recuperar).
Ojo: el comando lo escribe la IA en la nube; léelo antes de decir que sí. Con /opsec no hay IA en la nube, así que
esto queda en pausa.
"""
import ctypes
import os
import re
import shutil
import subprocess
import time
import winreg
from pathlib import Path

node = None
HIDDEN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
PENDING = {'jobs': [], 'until': 0}  # lo que espera tu "sí": [(qué es, función)], y hasta cuándo vale
YES = re.compile(r'^(si|sip|dale|ok|okey|hacelo|hazlo|ejecutalo|confirmo|adelante|de una|obvio)\b')
NO = re.compile(r'^(no|nop|cancela|cancelar|deja|dejalo|mejor no|para)\b')
# Ni preguntando: rompen Windows o el disco, o bajan y ejecutan código de internet
DANGER = re.compile(r'format-volume|\bformat(\.com)?\s+[a-z]:|diskpart|bcdedit|clear-disk|initialize-disk|'
                    r'remove-partition|vssadmin|cipher\s+/w|reg(\.exe)?\s+delete\s+hklm|set-executionpolicy|'
                    r'invoke-expression|\biex\b|downloadstring|-enc(odedcommand)?\b|takeown|icacls|'
                    r'(remove-item|\brm\b|\bdel\b|\brd\b|rmdir)\b[^|;]*\b[a-z]:\\?(windows|program files|\s|"|\'|$)', re.I)
RUNNABLE = {'.exe', '.bat', '.cmd', '.ps1', '.vbs', '.js', '.msi', '.lnk', '.com', '.scr', '.reg'}
TEXT = {'.txt', '.md', '.csv', '.json', '.log', '.py', '.js', '.html', '.css', '.xml', '.ini', '.yml', '.yaml', '.ps1',
        '.bat', '.cfg', '.toml', '.srt'}


def places():
    """Las carpetas por su nombre en español (siguen a OneDrive si las movió)."""
    found = {}
    for names, csidl in ((('escritorio',), 0x10), (('documentos', 'mis documentos'), 0x05),
                         (('imagenes', 'fotos'), 0x27), (('musica',), 0x0D), (('videos',), 0x0E)):
        buffer = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(0, csidl, 0, 0, buffer)
        found.update(dict.fromkeys(names, buffer.value))
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
            downloads = os.path.expandvars(winreg.QueryValueEx(key, '{374DE290-123F-4565-9164-39C4925E467B}')[0])
    except OSError:
        downloads = str(Path.home() / 'Downloads')
    found['descargas'] = downloads
    found['inicio'] = found['usuario'] = str(Path.home())
    return found


def resolve(path):
    """"Descargas/foto.png", "~/x", "%APPDATA%\\x" o una ruta completa -> Path."""
    path = os.path.expanduser(os.path.expandvars((path or '').strip().strip('"')))
    first, _, rest = path.replace('/', '\\').partition('\\')
    if (folder := places().get(node.plain(first).strip())) is not None:
        return Path(folder, rest)
    return Path(path) if os.path.isabs(path) else Path.home() / path


def guarded(path):
    """Lo que nunca se mueve ni se borra: raíces de disco, Windows, Archivos de programa y la carpeta de Node."""
    path = path.resolve()
    windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    programs = [Path(os.environ.get(name, '-')) for name in ('ProgramFiles', 'ProgramFiles(x86)', 'ProgramData')]
    return path == Path(path.anchor) or path == Path.home() or any(
        path == top or top in path.parents for top in [windows, *programs, node.HERE.resolve()])


def ask(jobs):
    """Deja las acciones esperando tu "sí" (si la IA pidió varias, se juntan)."""
    if PENDING['until'] < time.time():
        PENDING['jobs'] = []
    PENDING['jobs'] += jobs
    PENDING['until'] = time.time() + 60
    return node.t('Voy a: ') + '; '.join(what for what, _ in PENDING['jobs']) + node.t('. ¿Lo hago? Dime sí o no.')


def answer(text, where):
    """El "sí" o "no" a lo pendiente (si no hay nada, o no es una respuesta, deja pasar la orden)."""
    if not PENDING['jobs'] or PENDING['until'] < time.time():
        PENDING['jobs'] = []
        return None
    said = node.plain(text).strip(' .!¡¿?')
    jobs, PENDING['jobs'] = PENDING['jobs'], []
    if YES.match(said):
        results = []
        for _, job in jobs:
            try:
                results.append(job())
            except OSError as error:
                results.append(node.t('No pude: {dato}.', dato=error.strerror or error))
        return ' '.join(results)
    return node.t('Ok, no hago nada.') if NO.match(said) else None  # dijo otra cosa: se olvida y la orden sigue normal


def short(text, request):
    """Lo que devolvió un comando, dicho en una o dos frases (si es corto, tal cual)."""
    text = text.strip()
    if len(text) <= 300:
        return text
    try:
        said = node.tidy(node.cloud([{'role': 'user', 'content': f'El usuario pidió: "{request}". Esto devolvió el '
                                      'comando en su PC. Responde lo que pidió en español, en una o dos frases para '
                                      f'leer en voz alta:\n\n{text[-12000:]}'}], max_tokens=400).get('content'))
    except ConnectionError:
        said = ''
    return said or text[:300] + '…'


def command(args, where):
    script, request = (args.get('command') or '').strip(), (args.get('purpose') or '').strip()
    if not script:
        return node.t('¿Qué comando ejecuto?')
    if DANGER.search(script):
        return node.t('Ese comando puede romper Windows o borrar mucho de golpe, así que no lo ejecuto. Si de verdad lo necesitas, hazlo tú desde PowerShell.')

    def run():
        try:
            done = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                                   '[Console]::OutputEncoding = [Text.Encoding]::UTF8; ' + script],
                                  capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120,
                                  creationflags=HIDDEN, cwd=Path.home())
        except subprocess.TimeoutExpired:
            return node.t('El comando tardó más de 2 minutos y lo corté.')
        out = (done.stdout + ('\n' + done.stderr if done.returncode else '')).strip()
        if done.returncode and not out:
            return node.t('El comando falló (código {returncode}).', returncode=done.returncode)
        return short(out, request or script) if out else node.t('Listo, hecho.')
    return ask([(node.t('ejecutar en PowerShell: {script}', script=script), run)])


def listing(folder):
    if not folder.is_dir():
        return node.t('No encuentro la carpeta {folder}.', folder=folder)
    items = sorted(folder.iterdir(), key=lambda item: (not item.is_dir(), -item.stat().st_mtime))
    if not items:
        return node.t('{dato} está vacía.', dato=folder.name or folder)
    names = [f'{item.name}{"/" if item.is_dir() else ""}' for item in items[:15]]
    more = node.t(' y {count} más', count=len(items) - 15) if len(items) > 15 else ''
    return node.t('En {folder} hay {dato}: ', folder=folder, dato=len(items)) + ', '.join(names) + more + '.'


def find(query, folder):
    """Busca por nombre (sin mirar carpetas ocultas ni AppData), hasta 10 resultados o 8 segundos."""
    wanted, found, start = node.plain(query), [], time.time()
    for root, folders, files in os.walk(folder):
        folders[:] = [name for name in folders if not name.startswith(('.', '$')) and name not in
                      ('AppData', 'node_modules', '.venv', '__pycache__')]
        found += [Path(root, name) for name in folders + files if wanted in node.plain(name)]
        if len(found) >= 10 or time.time() - start > 8:
            break
    if not found:
        return node.t('No encontré nada que se llame {query} en {folder}.', query=query, folder=folder)
    return node.t('Encontré {dato}: ', dato=len(found)) + '; '.join(str(path) for path in found[:10]) + '.'


def read(path, question):
    if path.suffix.lower() not in TEXT:
        return node.t('{name} no es un archivo de texto; puedo abrirlo con su programa.', name=path.name)
    text = path.read_text(encoding='utf-8', errors='replace')
    if not text.strip():
        return node.t('{name} está vacío.', name=path.name)
    try:
        said = node.tidy(node.cloud([{'role': 'user', 'content': f'{question or "Resume este archivo."} Responde en '
                                      'español, breve, para leer en voz alta. Archivo ' + path.name + ':\n\n' +
                                      text[:20000]}], max_tokens=600).get('content'))
    except ConnectionError:
        said = ''
    return said or text[:400]


def trash(path):
    """A la Papelera, como borrar desde el Explorador."""
    subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                    '$p = $env:NODE_TRASH; Add-Type -AssemblyName Microsoft.VisualBasic; '
                    "if (Test-Path -LiteralPath $p -PathType Container) { [Microsoft.VisualBasic.FileIO.FileSystem]::"
                    "DeleteDirectory($p, 'OnlyErrorDialogs', 'SendToRecycleBin') } else { [Microsoft.VisualBasic."
                    "FileIO.FileSystem]::DeleteFile($p, 'OnlyErrorDialogs', 'SendToRecycleBin') }"],
                   env={**os.environ, 'NODE_TRASH': str(path)},  # por variable: la ruta no se mezcla con el comando
                   capture_output=True, creationflags=HIDDEN)
    return node.t('No pude mandar {name} a la Papelera.', name=path.name) if path.exists() else node.t('Mandé {name} a la Papelera.', name=path.name)


def files(args, where):
    action = args.get('action') or 'list'
    path = resolve(args.get('path') or ('' if action in ('list', 'find') else '-'))
    if action == 'list':
        return listing(path)
    if action == 'find':
        return find(args.get('query') or '', path if path.is_dir() else Path.home())
    if action == 'mkdir':
        if path.exists():
            return node.t('Ya existe {path}.', path=path)
        return ask([(node.t('crear la carpeta {path}', path=path),
                     lambda: path.mkdir(parents=True) or node.t('Creé la carpeta {name}.', name=path.name))])
    if not path.exists():
        return node.t('No encuentro {path}. Pídeme que lo busque.', path=path)
    if action == 'read':
        return read(path, args.get('question'))
    if action == 'open':
        if path.suffix.lower() in RUNNABLE:
            return ask([(node.t('abrir el programa {path}', path=path),
                         lambda: os.startfile(path) or node.t('Abriendo {name}.', name=path.name))])
        os.startfile(path)
        return node.t('Abriendo {name}.', name=path.name)
    if guarded(path):
        return node.t('{path} es parte de Windows, de tus programas o de Node: eso no lo toco.', path=path)
    if action == 'delete':
        return ask([(node.t('mandar {path} a la Papelera', path=path), lambda: trash(path))])
    target = args.get('target') or ''
    if not target:
        return node.t('¿A dónde (o con qué nombre)?')
    if action == 'rename':
        new = path.with_name(Path(target).name)
        if new.exists():
            return node.t('Ya hay algo que se llama {name} ahí.', name=new.name)
        return ask([(node.t('renombrar {name} a {new}', name=path.name, new=new.name),
                     lambda: path.rename(new) and node.t('Ahora se llama {new}.', new=new.name))])
    destination = resolve(target)
    destination = destination / path.name if destination.is_dir() else destination
    if destination.exists():
        return node.t('Ya existe {destination}; no lo piso.', destination=destination)
    if action == 'copy':
        copy = shutil.copytree if path.is_dir() else shutil.copy2
        return ask([(node.t('copiar {path} a {destination}', path=path, destination=destination),
                     lambda: copy(path, destination) and node.t('Copié {name} a {folder}.', name=path.name,
                                                                folder=destination.parent))])
    if action == 'move':
        return ask([(node.t('mover {path} a {destination}', path=path, destination=destination),
                     lambda: shutil.move(path, destination) and node.t('Moví {name} a {folder}.', name=path.name,
                                                                       folder=destination.parent))])
    return node.t('Con archivos puedo listar, buscar, leer, abrir, crear carpetas, mover, copiar, renombrar y borrar.')


def setup(node_):
    global node
    node = node_
    node.add(node.tool('files', 'Maneja archivos y carpetas del usuario. action: list (qué hay en una carpeta), find '
                       '(buscar por nombre: query, dentro de path; sin path busca en todo el usuario), read (leer un archivo de texto y responder '
                       'question), open (abrir con su programa), mkdir (crear carpeta), move, copy, rename o delete '
                       '(a la Papelera). path: ruta completa o empezando por Escritorio, Descargas, Documentos, '
                       'Imagenes, Musica o Videos (ej. "Descargas/foto.png"). target: para move y copy, la carpeta o '
                       'ruta de destino; para rename, el nombre nuevo. Si no sabes la ruta exacta, primero find.',
                       action={'type': 'string', 'enum': ['list', 'find', 'read', 'open', 'mkdir', 'move', 'copy',
                                                          'rename', 'delete']},
                       path={'type': 'string'}, target={'type': 'string'}, query={'type': 'string'},
                       question={'type': 'string'}), files,
             r'archivo|carpeta|fichero|documento|descarga|escritorio|imagenes|foto|video|musica|mueve|move|copia|'
             r'renombr|borra|elimin|papelera|busca|encontr|lee|leer|que dice|abri|abre|pdf|txt|docx|zip|que hay en')
    node.add(node.tool('run_command', 'Ejecuta un comando de Windows PowerShell 5.1 en la PC del usuario (se le '
                       'muestra y lo confirma antes). Para lo que ninguna otra herramienta hace: red e IP, instalar o '
                       'actualizar con winget, servicios, tamaños de carpetas, configuración, scripts. Para archivos '
                       'usa files. command: el comando, en una línea, que imprima un resultado corto y no pida nada por teclado (winget con '
                       '--accept-source-agreements --accept-package-agreements). purpose: qué '
                       'pidió el usuario, en sus palabras.', command={'type': 'string'}, purpose={'type': 'string'}),
             command, r'comando|terminal|powershell|consola|\bcmd\b|ejecut|corre |script|instal|desinstal|winget|'
                      r'actualiz|\bip\b|red|wifi|internet|servicio|pesa|tamano|ocupa|puerto|ping|variable|config')
    node.WAITING.append(answer)
