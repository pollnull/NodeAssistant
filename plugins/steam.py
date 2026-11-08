"""Steam: "abre el Hustle", "juguemos al Your Only Move", "¿qué juegos tengo?".
Lee tu biblioteca instalada (los appmanifest de cada carpeta de Steam) y abre el juego directo.
"""
import difflib
import os
import re
import winreg
from pathlib import Path

node = None
SKIP = re.compile(r'redistributable|steamworks|proton|runtime|sdk|dedicated server', re.I)


def games():
    """Los juegos instalados: nombre -> número de app."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
            steam = Path(winreg.QueryValueEx(key, 'SteamPath')[0])
    except OSError:
        return {}
    folders = steam / 'steamapps' / 'libraryfolders.vdf'
    libraries = re.findall(r'"path"\s+"([^"]+)"', folders.read_text(encoding='utf-8')) if folders.exists() else []
    found = {}
    for library in libraries or [str(steam)]:
        for manifest in Path(library.replace('\\\\', '\\'), 'steamapps').glob('appmanifest_*.acf'):
            text = manifest.read_text(encoding='utf-8', errors='replace')
            name, app = re.search(r'"name"\s+"([^"]+)"', text), re.search(r'"appid"\s+"(\d+)"', text)
            if name and app and not SKIP.search(name[1]):
                found[name[1]] = app[1]
    return found


def play(args, where):
    wanted, library = (args.get('game') or '').lower().strip(), games()
    if not library:
        return node.t('No encontré juegos de Steam instalados.')
    names = {name.lower(): name for name in library}
    match = next((names[name] for name in names if wanted and (wanted in name or name in wanted)), None)
    match = match or next(iter(difflib.get_close_matches(wanted, names, n=1, cutoff=0.5)), None)
    if not match:
        return node.t('No tengo {dato} en Steam. Tienes: {dato2}.', dato=args.get('game'), dato2=', '.join(sorted(library)))
    match = names.get(match, match)
    os.startfile(f'steam://rungameid/{library[match]}')
    return node.t('Abriendo {match}.', match=match)


def listing(args, where):
    library = games()
    return node.t('Tienes instalados: {dato}.', dato=', '.join(sorted(library))) if library else node.t('No encontré juegos de Steam instalados.')


def setup(node_):
    global node
    node = node_
    node.add(node.tool('steam_play', 'Abre un juego de Steam instalado. game: el nombre como lo dijo el usuario.',
                       game={'type': 'string'}), play, r'steam|jueg|jug|hustle|abre el|abrime')
    node.add(node.tool('steam_games', 'Dice qué juegos de Steam tiene instalados.'), listing, r'steam|juego')
