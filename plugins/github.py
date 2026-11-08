"""GitHub: "¿cómo va OpenSesame?", "¿hay issues nuevos?", "¿cuántas descargas tiene la última versión?",
"¿tengo notificaciones en GitHub?".
Usa el acceso de GitHub que ya guardó git en tu PC (el administrador de credenciales de Windows): no pide clave.
"""
import difflib
import json
import os
import subprocess
import urllib.request

node = None
TOKEN = {}


def token():
    if 'value' not in TOKEN:
        out = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n',
                             capture_output=True, text=True, timeout=15, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'},
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
        TOKEN['value'] = next((line[9:] for line in out.splitlines() if line.startswith('password=')), None)
    return TOKEN['value']


def api(path):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'NodeAssistant'}
    if key := token():
        headers['Authorization'] = f'Bearer {key}'
    with urllib.request.urlopen(urllib.request.Request(f'https://api.github.com{path}', headers=headers),
                                timeout=15) as response:
        return json.load(response)


def pick(wanted):
    """El repositorio pedido (por nombre aproximado) o, sin nombre, el último que tocaste."""
    repos = api('/user/repos?affiliation=owner&sort=pushed&per_page=50')
    if not repos:
        return None
    if not wanted:
        return repos[0]
    names = {repo['name'].lower(): repo for repo in repos}
    close = difflib.get_close_matches(wanted.lower().replace(' ', ''), names, n=1, cutoff=0.4)
    return next((repo for name, repo in names.items() if wanted.lower() in name), None) or (names[close[0]] if close else None)


def github(args, where):
    action = args.get('action') or 'summary'
    if action == 'notifications':
        unread = api('/notifications')
        if not unread:
            return node.t('No tienes notificaciones nuevas en GitHub.')
        return node.t('Tienes {dato} notificaciones: ', dato=len(unread)) + '; '.join(
            f"{item['repository']['name']}: {item['subject']['title']}" for item in unread[:5]) + '.'
    repo = pick((args.get('repo') or '').strip())
    if not repo:
        return node.t('No encontré ese repositorio.')
    full, name = repo['full_name'], repo['name']
    if action == 'issues':
        items = api(f'/repos/{full}/issues?state=open&per_page=10')
        if not items:
            return node.t('{name} no tiene issues ni pull requests abiertos.', name=name)
        return node.t('En {name} hay {dato} abiertos: ', name=name, dato=len(items)) + '; '.join(
            f"{'PR' if 'pull_request' in item else 'issue'} {item['number']}, {item['title']}" for item in items[:5]) + '.'
    releases = api(f'/repos/{full}/releases?per_page=30')
    total = sum(asset['download_count'] for release in releases for asset in release['assets'])
    if action == 'releases':
        if not releases:
            return node.t('{name} no tiene versiones publicadas.', name=name)
        return node.t('Versiones de {name}: ', name=name) + '; '.join(
            node.t('{tag} con {count} descargas', tag=release['tag_name'],
                   count=sum(a['download_count'] for a in release['assets']))
            for release in releases[:3]) + node.t('. En total, {total} descargas.', total=total)
    latest = node.t(', última versión {tag}', tag=releases[0]['tag_name']) if releases else ''
    return (node.t('{name}: {stargazers_count} estrellas, {forks_count} forks, {open_issues_count} issues o PRs abiertos{latest} y {total} descargas en total.', name=name, stargazers_count=repo['stargazers_count'], forks_count=repo['forks_count'], open_issues_count=repo['open_issues_count'], latest=latest, total=total))


def setup(node_):
    global node
    node = node_
    node.add(node.tool('github', 'Consulta GitHub del usuario. action: summary (cómo va un repositorio: estrellas, '
                       'descargas), issues (issues y pull requests abiertos), releases (versiones y descargas) o '
                       'notifications. repo: el nombre del repositorio, o vacío para el último que tocó.',
                       action={'type': 'string', 'enum': ['summary', 'issues', 'releases', 'notifications']},
                       repo={'type': 'string'}), github, r'github|repo|issue|pull|descarga|version|release|opensesame|estrella|notificacion')
