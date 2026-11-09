"""Arma dist/NodeAssistant/NodeAssistant.exe con PyInstaller (lo que después empaqueta el instalador).
Uso, desde la carpeta de Node y con su entorno:  .venv\\Scripts\\python.exe installer\\build.py
Se arma en la misma arquitectura que el Python que lo corre (x64 o ARM64): GitHub Actions lo hace en las dos
(.github/workflows/instaladores.yml). Los plugins se cargan mientras Node corre y PyInstaller no los ve: por eso va
la biblioteca estándar completa y las librerías que usan, así también funcionan los plugins que instale cada uno.
"""
import importlib.util
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / 'dist'
APP = DIST / 'NodeAssistant'
# Lo que va al lado del .exe (se puede editar, y Node lo busca ahí): no adentro del paquete.
BESIDE = ['plugins', 'skills', 'icons', 'idiomas', 'apps.json', 'README.md', 'README.es.md', 'LICENSE']
# Con datos o binarios que PyInstaller no encuentra solo. Las que no existen en esta arquitectura se saltean
# (en ARM64 no hay Whisper local ni Piper).
COLLECT = ['piper', 'espeakng_loader', 'kokoro_onnx', 'phonemizer', 'faster_whisper', 'ctranslate2', 'sounddevice',
           '_sounddevice_data', 'onnxruntime', 'av', 'tokenizers', 'yaml', 'obsws_python', 'numpy']
SKIP_STDLIB = {'antigravity', 'this', 'idlelib', 'test', 'turtledemo', 'lib2to3', 'ensurepip', 'venv', 'pydoc_data',
               'tkinter.test', 'unittest.test', '__phello__', '_testcapi', '_testinternalcapi', '_testbuffer',
               '_testimportmultiple', '_testmultiphase', '_testsinglephase', '_xxtestfuzz', 'xxsubtype', 'xxlimited',
               'xxlimited_35'}


def main():
    present = [name for name in COLLECT if importlib.util.find_spec(name)]
    stdlib = sorted(name for name in sys.stdlib_module_names if name not in SKIP_STDLIB and not name.startswith('_test'))
    args = [sys.executable, '-m', 'PyInstaller', str(ROOT / 'node_assistant.py'), '--name', 'NodeAssistant',
            '--noconsole', '--noconfirm', '--clean', '--icon', str(ROOT / 'icons' / 'node.ico'),
            '--distpath', str(DIST), '--workpath', str(ROOT / 'build'), '--specpath', str(ROOT / 'build')]
    for name in present:
        args += ['--collect-all', name]
    for name in stdlib:
        args += ['--hidden-import', name]
        spec = importlib.util.find_spec(name)
        if spec and spec.submodule_search_locations:  # un paquete (tkinter, email, http…): también sus submódulos
            args += ['--collect-submodules', name]
    print(f'Arquitectura: {platform.machine()} · librerías con datos: {", ".join(present)}')
    subprocess.run(args, check=True)
    for name in BESIDE:  # al lado del .exe
        source = ROOT / name
        target = APP / name
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
        elif source.exists():
            shutil.copy2(source, target)
    size = sum(f.stat().st_size for f in APP.rglob('*') if f.is_file()) / 1e6
    print(f'Listo: {APP / "NodeAssistant.exe"} ({size:.0f} MB)')


if __name__ == '__main__':
    main()
