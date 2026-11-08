"""OBS Studio: "empieza a grabar", "pausa la grabación", "corta la grabación", "arranca el directo",
"pasa a la escena Juego", "silencia el micrófono en OBS", "¿estoy grabando?".

Una sola vez, en OBS: Herramientas -> Ajustes del servidor WebSocket -> Habilitar servidor WebSocket ->
Mostrar información de conexión -> copia la contraseña y guárdala en Windows (PowerShell, sin que se vea):
  $t = Read-Host 'Contraseña de OBS' -AsSecureString; [Environment]::SetEnvironmentVariable('OBS_WEBSOCKET_PASSWORD', [Net.NetworkCredential]::new('', $t).Password, 'User'); Remove-Variable t
"""
import difflib
import logging

import obsws_python

node = None
logging.getLogger('obsws_python').setLevel(logging.CRITICAL)  # sin OBS abierto, que no llene la consola de errores
ACTIONS = ['record_start', 'record_stop', 'record_pause', 'record_resume', 'stream_start', 'stream_stop', 'scene',
           'mic', 'status']


def obs(args, where):
    action = args.get('action')
    try:
        client = obsws_python.ReqClient(host='localhost', port=4455, timeout=3,
                                        password=node.secret('OBS_WEBSOCKET_PASSWORD') or '')
    except Exception:  # OBS cerrado o el servidor WebSocket apagado
        app = node.find_app('obs studio')
        if app and action != 'status':
            node.act('open', app, None)
            return node.t('OBS no estaba abierto: lo estoy abriendo. Pídemelo de nuevo en unos segundos.')
        return node.t('OBS no está abierto (o falta activar su servidor WebSocket).')
    try:
        if action == 'record_start':
            client.start_record()
            return node.t('Grabando.')
        if action == 'record_stop':
            client.stop_record()
            return node.t('Grabación terminada.')
        if action == 'record_pause':
            client.pause_record()
            return node.t('Grabación en pausa.')
        if action == 'record_resume':
            client.resume_record()
            return node.t('Sigo grabando.')
        if action == 'stream_start':
            client.start_stream()
            return node.t('Directo iniciado.')
        if action == 'stream_stop':
            client.stop_stream()
            return node.t('Directo terminado.')
        if action == 'scene':
            scenes = [scene['sceneName'] for scene in client.get_scene_list().scenes]
            wanted = (args.get('name') or '').lower()
            lower = {scene.lower(): scene for scene in scenes}
            match = next((lower[s] for s in lower if wanted and wanted in s), None) or \
                next((lower[s] for s in difflib.get_close_matches(wanted, lower, n=1, cutoff=0.4)), None)
            if not match:
                return node.t('No encontré esa escena. Tienes: {dato}.', dato=', '.join(scenes))
            client.set_current_program_scene(match)
            return node.t('Escena {match}.', match=match)
        if action == 'mic':
            mics = [item['inputName'] for item in client.get_input_list().inputs
                    if item['inputKind'] in ('wasapi_input_capture', 'dshow_input')]
            if not mics:
                return node.t('No encontré un micrófono en OBS.')
            muted = client.toggle_input_mute(mics[0]).input_muted
            return node.t('Micrófono de OBS {dato}.', dato='silenciado' if muted else 'activado')
        record, stream = client.get_record_status(), client.get_stream_status()
        scene = client.get_current_program_scene().current_program_scene_name
        doing = []
        if record.output_active:
            doing.append(node.t('grabando (en pausa) hace {time}', time=record.output_timecode[:8]) if record.output_paused
                         else node.t('grabando hace {time}', time=record.output_timecode[:8]))
        if stream.output_active:
            doing.append(node.t('en directo hace {dato}', dato=stream.output_timecode[:8]))
        return node.t('OBS: {state}, escena {scene}.', state=node.t(' y ').join(doing) or node.t('sin grabar ni transmitir'),
                      scene=scene)
    except Exception as error:  # p. ej. "ya está grabando" o una escena que no existe
        return node.t('OBS no pudo: {dato}', dato=getattr(error, "comment", None) or error)
    finally:
        client.disconnect()


def setup(node_):
    global node
    node = node_
    node.add(node.tool('obs', 'Controla OBS Studio. action: record_start, record_stop, record_pause, record_resume, '
                       'stream_start (directo), stream_stop, scene (cambiar a la escena name), mic (silenciar o activar '
                       'el micrófono de OBS) o status (¿está grabando?).', action={'type': 'string', 'enum': ACTIONS},
                       name={'type': 'string'}), obs, r'obs|grab|directo|stream|transmi|escena|en vivo')
