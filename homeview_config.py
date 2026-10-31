"""Settings for every HomeView service, in one place.

Reads config.json next to this file (or the file named by $HOMEVIEW_CONFIG), on top of the defaults below.
Copy config.example.json to config.json and edit it. Anything you leave out keeps its default.
"""
import copy, json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

DEFAULTS = {
    'ports': {'dashboard': 8878, 'voice': 8879, 'relay': 8090, 'speech': 8880, 'chrome_devtools': 9333},
    # The relay is the only service the iMac connects to. It listens on relay_bind (every interface by default; set the
    # Mac's Ethernet address to limit it to that cable) and only answers addresses in relay_allowed_networks.
    # Link-local 169.254.x.x is what two Macs joined by one cable give themselves.
    'relay_bind': '0.0.0.0',
    'relay_allowed_networks': ['169.254.0.0/16', '127.0.0.0/8'],
    'location': {'name': 'Cupertino', 'latitude': 37.3230, 'longitude': -122.0322, 'timezone': 'auto', 'units': 'fahrenheit'},
    'owner_name': '',                 # shown in the Home Screen greeting ("GOOD MORNING, ALEX"); empty for none
    'assistant': {
        'name': 'Muse',               # what the assistant is called on screen
        'wake_word': 'Hey Apple',     # shown in hints and given to the speech recognizer as a hint
        'wake_names': ['apple'],      # the word(s) after "hey" that wake it; lowercase
        'openai_model': '',           # empty: try gpt-4.1-mini, then gpt-5-mini, then gpt-4o-mini
        'openai_voice': 'marin',
        'mac_voice': '',              # the Mac's own voice when there is no OpenAI key; empty picks the best installed one
    },
    'openai_api_key': '',             # optional; or set OPENAI_API_KEY, or paste it on the /remote page
    'openai_key_file': '~/.config/homeview/openai.env',
    'data_dir': '~/Library/Application Support/HomeView/data',
    'photos_dir': '',                 # a folder of .jpg/.png photos for the Photo face; empty uses <data_dir>/photos
    'chrome_path': '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    'countdown': {'label': '', 'date': ''},     # e.g. {"label": "Vacation", "date": "2027-06-01"}; shown on the Home face
    'night': {'start': 23, 'end': 7},           # hours when the red Night face takes over
    'spotify': {'enabled': True},               # control the Spotify app on this Mac
    'demo': {'song_uri': '', 'song_name': ''},  # optional Spotify track for the scripted demo ("spotify:track:...")
    'home_assistant': {
        'url': '',                    # e.g. "http://homeassistant.local:8123"
        'token': '',                  # a long-lived access token (Home Assistant profile page)
        # Devices shown on the Home grid and controllable by voice. Supported domains: light, fan, scene, cover, media_player.
        'devices': [],                # [{"entity_id": "light.living_room", "name": "Lamp", "room": "Living Room"}, ...]
        'doorbell_event': '',         # e.g. "event.front_door_ding"; empty: look for a doorbell event entity
        'doorbell_camera': '',        # e.g. "camera.front_door"; empty: look for one
        'announce_tts': '',           # e.g. "tts.google_translate_en_com"; empty: the first tts entity
        'announce_players': [],       # media_player entities that speak announcements; empty: HomePods and Sonos
    },
    'calendar_helper': True,          # run helpers/HomeViewCalendar.app to read the Mac's Calendar (if it has been built)
    'touch': {'enabled': False},      # camera touch (helpers/HomeViewTouch.app + a USB webcam pointed at the iMac)
}


def _merge(base, extra):
    for k, v in (extra or {}).items():
        if k.startswith('_'):
            continue
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load():
    path = Path(os.environ.get('HOMEVIEW_CONFIG') or ROOT / 'config.json').expanduser()
    conf = copy.deepcopy(DEFAULTS)
    if path.exists():
        _merge(conf, json.loads(path.read_text()))
    for k in ('data_dir', 'openai_key_file', 'photos_dir'):
        if conf[k]:
            conf[k] = str(Path(conf[k]).expanduser())
    if not conf['photos_dir']:
        conf['photos_dir'] = str(Path(conf['data_dir']) / 'photos')
    return conf


CONFIG = load()


def openai_key():
    """The OpenAI key from $OPENAI_API_KEY, config.json, or the key file the /remote page writes. None if there is none."""
    if os.environ.get('OPENAI_API_KEY'):
        return os.environ['OPENAI_API_KEY'].strip()
    if CONFIG.get('openai_api_key'):
        return CONFIG['openai_api_key'].strip()
    try:
        for line in Path(CONFIG['openai_key_file']).read_text().splitlines():
            if line.startswith('OPENAI_API_KEY='):
                return line.split('=', 1)[1].strip().strip('"\'') or None
    except Exception:
        pass
    return None
