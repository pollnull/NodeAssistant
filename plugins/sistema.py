"""Estado de la PC: "¿cuánta batería me queda?", "¿qué está usando tanta memoria?", "¿cómo está la PC?",
"¿cuánto espacio me queda?", "apaga la PC en una hora", "cancela el apagado", "reinicia la PC", "cierra Chrome".
Apagar y reiniciar esperan al menos 1 minuto (Windows avisa y se puede cancelar). Cerrar una app es como tocar
la X: si tiene algo sin guardar, te pregunta.
"""
import csv
import ctypes
import difflib
import io
import os
import shutil
import subprocess
import time
from ctypes import wintypes

node = None
HIDDEN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
# Nunca se cierran: son partes de Windows (o Node mismo)
PROTECTED = {'system', 'csrss.exe', 'wininit.exe', 'winlogon.exe', 'services.exe', 'lsass.exe', 'svchost.exe',
             'dwm.exe', 'explorer.exe', 'smss.exe', 'fontdrvhost.exe', 'sihost.exe', 'pythonw.exe', 'python.exe', 'NodeAssistant.exe',
             'conhost.exe', 'runtimebroker.exe', 'searchhost.exe', 'startmenuexperiencehost.exe', 'ctfmon.exe'}


class Power(ctypes.Structure):
    _fields_ = [('ac', ctypes.c_byte), ('flag', ctypes.c_byte), ('percent', ctypes.c_byte), ('saver', ctypes.c_byte),
                ('seconds', wintypes.DWORD), ('full', wintypes.DWORD)]


class Memory(ctypes.Structure):
    _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD), ('total', ctypes.c_ulonglong),
                ('free', ctypes.c_ulonglong), ('page_total', ctypes.c_ulonglong), ('page_free', ctypes.c_ulonglong),
                ('virtual_total', ctypes.c_ulonglong), ('virtual_free', ctypes.c_ulonglong),
                ('extended', ctypes.c_ulonglong)]


def battery():
    power = Power()
    ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(power))
    if power.flag & 128 or power.percent < 0:  # 128 = sin batería (PC de escritorio)
        return node.t('No tiene batería: está enchufada.')
    plugged = node.t('enchufada, cargando') if power.ac == 1 else node.t('con batería')
    left = ''
    if power.ac != 1 and power.seconds != 0xFFFFFFFF:
        hours, minutes = divmod(power.seconds // 60, 60)
        left = f', te quedan unas {hours} h {minutes} min' if hours else f', te quedan unos {minutes} minutos'
    return node.t('Batería al {percent} %, {plugged}{left}{dato}.', percent=power.percent, plugged=plugged, left=left, dato=', en ahorro de energía' if power.saver else '')


def memory():
    status = Memory()
    status.length = ctypes.sizeof(Memory)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    used = (status.total - status.free) / 2 ** 30
    return node.t('Memoria: usas {used} de {dato} GB ({load} %).', used=format(used, '.1f'), dato=format(status.total / 2 ** 30, '.0f'), load=status.load)


def processor():
    """El uso del procesador en medio segundo."""
    def times():
        idle, kernel, user = (wintypes.FILETIME() for _ in range(3))
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
        value = lambda t: t.dwHighDateTime << 32 | t.dwLowDateTime
        return value(idle), value(kernel) + value(user)
    idle1, total1 = times()
    time.sleep(0.5)
    idle2, total2 = times()
    return node.t('Procesador al {dato} %.', dato=round(100 * (1 - (idle2 - idle1) / max(total2 - total1, 1))))


def disks():
    found = []
    for drive in 'CDEFG':
        root = f'{drive}:\\'
        if os.path.exists(root):
            usage = shutil.disk_usage(root)
            found.append(node.t('{drive}: {dato} GB libres de {dato2}', drive=drive, dato=format(usage.free / 2 ** 30, '.0f'), dato2=format(usage.total / 2 ** 30, '.0f')))
    return node.t('Espacio: ') + '; '.join(found) + '.'


def processes():
    """Los programas que más memoria usan (sumando sus procesos)."""
    out = subprocess.run(['tasklist', '/fo', 'csv', '/nh'], capture_output=True, text=True, creationflags=HIDDEN,
                         encoding='oem', errors='replace').stdout
    totals = {}
    for row in csv.reader(io.StringIO(out)):
        if len(row) >= 5:
            kilobytes = int(''.join(ch for ch in row[4] if ch.isdigit()) or 0)
            totals[row[0]] = totals.get(row[0], 0) + kilobytes
    top = sorted(totals.items(), key=lambda item: -item[1])[:5]
    return node.t('Lo que más memoria usa: ') + ', '.join(
        f"{name.removesuffix('.exe')} {kb / 2 ** 20:.1f} GB" if kb > 2 ** 20 else f"{name.removesuffix('.exe')} "
        f"{kb // 1024} MB" for name, kb in top) + '.'


def status(args, where):
    what = args.get('what') or 'summary'
    if what == 'battery':
        return battery()
    if what == 'memory':
        return memory() + ' ' + processes()
    if what == 'disk':
        return disks()
    if what == 'processes':
        return processes()
    uptime = ctypes.windll.kernel32.GetTickCount64
    uptime.restype = ctypes.c_ulonglong
    hours = uptime() // 3_600_000
    return ' '.join([processor(), memory(), battery(), node.t('Prendida hace {days} días y {hours} horas.', days=hours // 24, hours=hours % 24)
                     if hours >= 24 else node.t('Prendida hace {hours} horas.', hours=hours)])


def power(args, where):
    action, minutes = args.get('action'), max(int(args.get('minutes') or 1), 1)
    if action == 'cancel':
        done = subprocess.run(['shutdown', '/a'], capture_output=True, creationflags=HIDDEN).returncode == 0
        return node.t('Cancelé el apagado.') if done else node.t('No había ningún apagado programado.')
    flag = {'shutdown': '/s', 'restart': '/r'}.get(action)
    if not flag:
        return node.t('Puedo apagar, reiniciar o cancelar.')
    subprocess.run(['shutdown', flag, '/t', str(minutes * 60), '/c', node.t('Node Assistant: lo pediste tú. Di "cancela el apagado" para frenarlo.')], capture_output=True, creationflags=HIDDEN)
    clock = time.strftime('%H:%M', time.localtime(time.time() + minutes * 60))
    return (node.t('Apago la PC en {minutes} minutos, a las {clock}. Si cambias de idea, dime "cancela el apagado".',
                   minutes=minutes, clock=clock) if action == 'shutdown' else
            node.t('Reinicio la PC en {minutes} minutos, a las {clock}. Si cambias de idea, dime "cancela el apagado".',
                   minutes=minutes, clock=clock))


def close(args, where):
    wanted = (args.get('name') or '').lower().strip().removesuffix('.exe')
    out = subprocess.run(['tasklist', '/fo', 'csv', '/nh'], capture_output=True, text=True, creationflags=HIDDEN,
                         encoding='oem', errors='replace').stdout
    running = {row[0].lower() for row in csv.reader(io.StringIO(out)) if row} - PROTECTED
    names = {name.removesuffix('.exe'): name for name in running}
    match = next((names[n] for n in names if wanted and (n == wanted or n.startswith(wanted))), None) or \
        next((names[n] for n in difflib.get_close_matches(wanted, names, n=1, cutoff=0.6)), None)
    if not match:
        return node.t('No encontré {dato} abierto.', dato=args.get('name'))
    subprocess.run(['taskkill', '/im', match], capture_output=True, creationflags=HIDDEN)  # sin /f: como tocar la X
    return node.t('Cerrando {dato}.', dato=match.removesuffix('.exe'))


def setup(node_):
    global node
    node = node_
    node.add(node.tool('pc_status', 'Estado de la computadora. what: summary (procesador, memoria, batería, tiempo '
                       'prendida), battery, memory (y qué la usa), disk (espacio libre) o processes (qué consume).',
                       what={'type': 'string', 'enum': ['summary', 'battery', 'memory', 'disk', 'processes']}), status,
             r'bateria|carga|memoria|\bram\b|procesador|cpu|disco|espacio|lent|estado|consum|prendida|que esta usando|como esta (?:la )?(?:pc|compu)|battery|storage|status')
    node.add(node.tool('pc_power', 'Apaga (shutdown) o reinicia (restart) la PC dentro de minutes minutos (mínimo 1), '
                       'o cancela (cancel) un apagado programado. Solo si el usuario lo pide claramente.',
                       action={'type': 'string', 'enum': ['shutdown', 'restart', 'cancel']},
                       minutes={'type': 'integer'}), power, r'apag|reinici|cancela|apagado')
    node.add(node.tool('close_app', 'Cierra un programa abierto, como tocar su X (si hay algo sin guardar, el programa '
                       'pregunta). name: el programa, por ejemplo chrome o discord.', name={'type': 'string'}),
             close, r'cerr|cierra|mata|termina|close')
