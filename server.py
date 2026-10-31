"""HomeView-style dashboard server.

Serves the faces page and a merged /api/data snapshot on 127.0.0.1 (port from config.json), renders the current face to a
1024x768 image with headless Chrome, draws the pop-ups (overlays.py), and maps taps from the iMac G4 onto tiles.

Data sources (all optional except the clock):
  * Open-Meteo      current + hourly weather for the location in config.json (free, no key)
  * Spotify         the Spotify app on this Mac, through AppleScript
  * Calendar        helpers/HomeViewCalendar.app writes <data_dir>/calendar.json from the Mac's Calendar
  * Home Assistant  lights, fans, scenes, shades, speakers, cameras and a doorbell (url + token in config.json)
  * Photos          a folder of your own photos (photos_dir in config.json)
"""
import colorsys, hashlib, io, json, math, re, os, random, subprocess, threading, time, urllib.parse, urllib.request
from datetime import datetime, timezone, date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from homeview_config import CONFIG, openai_key

HERE = Path(__file__).resolve().parent
STATIC = HERE / 'static'
OUT = HERE / 'out'
PORT = CONFIG['ports']['dashboard']
DATA = Path(CONFIG['data_dir'])
PHOTOS = Path(CONFIG['photos_dir'])
CHROME = CONFIG['chrome_path']
LOC = CONFIG['location']
LAT, LON = LOC['latitude'], LOC['longitude']
HA = CONFIG['home_assistant']
FACE_SECONDS = 20
FACES = ['modular']            # just the Home face; the others open from its tiles, by voice or from /remote
EXTRA_FACES = ('weather', 'photo', 'grid', 'muse', 'lyrics', 'nowplaying', 'calendar', 'flow', 'cameras', 'apps', 'cook')
DETAIL_SECONDS = 30            # how long an opened face (e.g. Weather) stays before returning home
NIGHT_START, NIGHT_END = CONFIG['night']['start'], CONFIG['night']['end']
WAKE_SECONDS = 60                # a tap at night shows the normal faces for this long
MASKS = DATA / 'masks'           # person-segmentation masks made by helpers/build/personmask (optional)
DESIGN_W, DESIGN = 1451, 1088   # 4:3 design canvas (width, height)
RENDER_W, RENDER = 1024, 768    # iMac G4 panel

state = {'muse_page': None, 'voice': None, 'changed': {}, 'seen': {}, 'banner': None, 'detail': None, 'awake_until': 0, 'playing': None, 'face_index': 0, 'face_started': time.time(), 'photo': None, 'last_tap': None, 'message': None}
cache = {'weather': (0, None), 'home': (0, None)}
lock = threading.Lock()


def get_json(url, timeout=6, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# ---- Home Assistant: the devices listed in config.json, in the dashboard's own shape ----
HA_GROUPS = {'light': 'lights', 'fan': 'fans', 'scene': 'scenes', 'cover': 'covers', 'media_player': 'media'}


def ha_ready():
    return bool(HA.get('url') and HA.get('token'))


def ha_get(path, raw=False, timeout=6):
    req = urllib.request.Request(HA['url'].rstrip('/') + path, headers={'Authorization': 'Bearer ' + HA['token']})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return body if raw else json.loads(body)


def ha_post(path, body, timeout=10):
    req = urllib.request.Request(HA['url'].rstrip('/') + path, data=json.dumps(body).encode(), method='POST',
                                 headers={'Authorization': 'Bearer ' + HA['token'], 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b'[]')


def home_state():
    """{'lights': [...], 'fans': [...], 'scenes': [...], 'covers': [...], 'media': [...]} for the configured devices, or None."""
    if not ha_ready() or not HA.get('devices'):
        return None
    t, val = cache['home']
    if val and time.time() - t < 3:
        return val
    try:
        states = {st['entity_id']: st for st in ha_get('/api/states', timeout=5)}
    except Exception:
        return val
    out = {g: [] for g in HA_GROUPS.values()}; out['home_online'] = True
    for dev in HA['devices']:
        eid = dev.get('entity_id', ''); domain = eid.split('.', 1)[0]
        if domain not in HA_GROUPS:
            continue
        st = states.get(eid) or {}; at = st.get('attributes', {})
        row = {'id': eid, 'name': dev.get('name') or at.get('friendly_name') or eid, 'room': dev.get('room', ''),
               'available': bool(st) and st.get('state') not in ('unavailable', 'unknown')}
        if domain in ('light', 'fan'):
            row['on'] = st.get('state') == 'on'
            if domain == 'light' and at.get('brightness') is not None:
                row['brightness'] = round(at['brightness'] / 255 * 100)
            if domain == 'fan' and at.get('percentage') is not None:
                row['percentage'] = at['percentage']
        elif domain == 'scene':
            row['available'] = bool(st)
        elif domain == 'cover':
            row['state'] = st.get('state')
        elif domain == 'media_player':
            row.update(state=st.get('state'), title=at.get('media_title'), artist=at.get('media_artist'),
                       volume=at.get('volume_level'))
        out[HA_GROUPS[domain]].append(row)
    cache['home'] = (time.time(), out)
    return out


def weather():
    t, val = cache['weather']
    if val and time.time() - t < 900:
        return val
    try:
        units = 'celsius' if LOC.get('units') == 'celsius' else 'fahrenheit'
        q = urllib.parse.urlencode({'latitude': LAT, 'longitude': LON, 'current': 'temperature_2m,weather_code,is_day',
                                    'hourly': 'temperature_2m,weather_code,is_day', 'daily': 'temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max',
                                    'temperature_unit': units, 'timezone': LOC.get('timezone') or 'auto', 'forecast_days': 6})
        d = get_json('https://api.open-meteo.com/v1/forecast?' + q, timeout=8)
        now = d['current']
        hours = []
        idx = next((i for i, h in enumerate(d['hourly']['time']) if h >= now['time'][:13]), 0)
        for i in range(idx, min(idx + 10, len(d['hourly']['time']))):
            hours.append({'time': d['hourly']['time'][i], 'temp': round(d['hourly']['temperature_2m'][i]),
                          'code': d['hourly']['weather_code'][i], 'day': d['hourly']['is_day'][i]})
        val = {'location': LOC.get('name') or '', 'temp': round(now['temperature_2m']), 'code': now['weather_code'], 'day': now['is_day'],
               'high': round(d['daily']['temperature_2m_max'][0]), 'low': round(d['daily']['temperature_2m_min'][0]),
               'days': [{'date': d['daily']['time'][i], 'high': round(d['daily']['temperature_2m_max'][i]),
                         'low': round(d['daily']['temperature_2m_min'][i]), 'code': d['daily']['weather_code'][i],
                         'rain': d['daily'].get('precipitation_probability_max', [None] * 9)[i]} for i in range(min(6, len(d['daily']['time'])))],
               'hours': hours, 'updated': now['time'], 'source': 'Open-Meteo'}
        cache['weather'] = (time.time(), val)
        return val
    except Exception:
        return val


def photos():
    try:
        return sorted(p.name for p in PHOTOS.iterdir() if p.suffix.lower() in ('.jpg', '.jpeg', '.png'))
    except Exception:
        return []


DEPTH_MAX_COVER = 0.30   # skip the depth effect when people would hide too much of the time


def depth_ok(photo):
    try:
        cover = json.loads((MASKS / 'coverage.json').read_text()).get(photo)
    except Exception:
        return False
    return cover is not None and cover < DEPTH_MAX_COVER and (MASKS / (photo + '.mask.png')).exists()


def screen_dim():
    """1.0 by day, softer in the evening and early morning (the Night face covers the night hours)."""
    h = datetime.now().hour + datetime.now().minute / 60
    if 7 <= h < 19: return 1.0
    if 19 <= h < 21: return 0.85
    if 21 <= h < 23: return 0.65
    return 0.75


def countdown_days():
    """Days until the countdown date in config.json, or None."""
    try:
        return (date.fromisoformat(CONFIG['countdown']['date']) - date.today()).days
    except Exception:
        return None


def is_night():
    h = datetime.now().hour
    return h >= NIGHT_START or h < NIGHT_END


def rotation():
    faces = list(FACES)
    if state.get('playing'):
        faces.insert(1, 'nowplaying')   # Now Playing joins the rotation only while something plays
    return faces


# ---- the Mac's own Calendar (HomeViewCalendar.app writes <data_dir>/calendar.json every 2 minutes) ----
HELPERS = HERE / 'helpers' / 'build'          # helpers/build.sh puts the three helper apps here
CAL_FILE = DATA / 'calendar.json'
CAL_APP = HELPERS / 'HomeViewCalendar.app'


def mac_calendar():
    """Events from the Mac's Calendar in the dashboard's format, or None if the helper hasn't reported recently."""
    try:
        d = json.loads(CAL_FILE.read_text())
        if not d.get('ok') or time.time() - CAL_FILE.stat().st_mtime > 900:
            return None
    except Exception:
        return None
    out = []
    for e in d.get('events', []):
        try:
            st = datetime.fromisoformat(e['start'].replace('Z', '+00:00')).astimezone()
        except Exception:
            continue
        out.append({'title': e.get('title') or 'Event', 'date': st.strftime('%Y-%m-%d'), 'time': '' if e.get('all_day') else st.strftime('%H:%M'),
                    'day': st.strftime('%a, %b %-d'), 'all_day': bool(e.get('all_day')), 'calendar': e.get('calendar', ''), 'location': e.get('location', '')})
    return out


def calendar_keeper():
    if not CONFIG.get('calendar_helper'):
        return
    while True:
        if subprocess.run(['/usr/bin/pgrep', '-f', 'HomeViewCalendar.app/Contents/MacOS/calendard'], capture_output=True).returncode != 0 and CAL_APP.exists():
            subprocess.run(['/usr/bin/open', '-g', str(CAL_APP), '--args', str(CAL_FILE)], capture_output=True)
        time.sleep(120)


# ---- live Spotify from the Mac's Spotify app ----
SPOTIFY_AS = """if application "Spotify" is running then
  tell application "Spotify"
    set t to current track
    return (player state as string) & "\\t" & (name of t) & "\\t" & (artist of t) & "\\t" & (album of t) & "\\t" & (artwork url of t) & "\\t" & (sound volume as string) & "\\t" & ((duration of t) as string) & "\\t" & ((player position) as string)
  end tell
end if
return ""
"""
music = {'spotify': None, 'at': 0}
ART_DIR = OUT / 'sart'
spotify_kick = threading.Event()


def art_palette(url):
    """Save the album cover locally (Chrome then never waits on Spotify's CDN) and pull Apple-Music-style background colors from it."""
    if not url or not url.startswith('https://i.scdn.co/'):
        return None, None
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    meta = ART_DIR / (key + '.json')
    if meta.exists():
        return key, json.loads(meta.read_text())
    from PIL import Image
    ART_DIR.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=6) as r:
        img = Image.open(io.BytesIO(r.read())).convert('RGB')
    img.resize((640, 640)).save(ART_DIR / (key + '.jpg'), 'JPEG', quality=90)
    q = img.resize((48, 48)).quantize(colors=6)
    pal = q.getpalette()
    cols = []
    for n, i in sorted(q.getcolors(), reverse=True):
        h, l, sat = colorsys.rgb_to_hls(*(v / 255 for v in pal[i * 3:i * 3 + 3]))
        r_, g_, b_ = colorsys.hls_to_rgb(h, max(0.20, min(0.58, l)), min(1.0, sat * 1.4 + 0.10))
        cols.append('#%02x%02x%02x' % (int(r_ * 255), int(g_ * 255), int(b_ * 255)))
    meta.write_text(json.dumps(cols))
    old = sorted(ART_DIR.glob('*.jpg'), key=lambda f: f.stat().st_mtime)[:-150]   # keep the newest 150 covers
    for f in old:
        f.unlink(missing_ok=True); f.with_suffix('.json').unlink(missing_ok=True)
    return key, cols


LYR_DIR = OUT / 'lyrics'
UA = 'homeview-g4/1.0 (+https://github.com)'
lyrics = {}      # track key -> [[seconds, line], ...] (empty list: none found)


def lyrics_for(sp):
    """Time-synced lyrics from LRCLIB (free, open lyrics database), cached on disk."""
    key = hashlib.sha1((sp['title'] + '|' + sp['artist']).encode()).hexdigest()[:16]
    if key in lyrics:
        return lyrics[key]
    f = LYR_DIR / (key + '.json')
    if f.exists():
        lyrics[key] = json.loads(f.read_text()); return lyrics[key]
    lines = []
    try:
        q = urllib.parse.urlencode({'track_name': sp['title'], 'artist_name': sp['artist'], 'album_name': sp.get('album', ''),
                                    'duration': int(sp.get('duration') or 0)})
        req = urllib.request.Request('https://lrclib.net/api/get?' + q, headers={'User-Agent': UA})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                d = json.loads(r.read())
        except urllib.error.HTTPError:
            q = urllib.parse.urlencode({'track_name': sp['title'], 'artist_name': sp['artist']})
            with urllib.request.urlopen(urllib.request.Request('https://lrclib.net/api/get?' + q, headers={'User-Agent': UA}), timeout=8) as r:
                d = json.loads(r.read())
        for ln in (d.get('syncedLyrics') or '').splitlines():
            m = re.match(r'\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)', ln)
            if m:
                lines.append([int(m.group(1)) * 60 + float(m.group(2)), m.group(3).strip()])
    except Exception as e:
        print(time.strftime('%T'), 'lyrics:', str(e)[:100], flush=True)
    LYR_DIR.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(lines))
    lyrics[key] = lines
    return lines


def spotify_poll():
    if not CONFIG['spotify'].get('enabled'):
        return None
    r = subprocess.run(['/usr/bin/osascript', '-e', SPOTIFY_AS], capture_output=True, text=True, timeout=8)
    parts = r.stdout.strip().split('\t')
    if not (r.returncode == 0 and len(parts) >= 6 and parts[1]):
        return None
    return {'id': 'spotify', 'name': 'Spotify', 'available': True, 'state': parts[0], 'title': parts[1], 'artist': parts[2],
            'album': parts[3], 'art_remote': parts[4], 'art_url': parts[4], 'volume': int(parts[5] or 0) / 100.0,
            'duration': float(parts[6] or 0) / 1000.0 if len(parts) > 6 else 0,
            'position': float(parts[7] or 0) if len(parts) > 7 else 0, 'polled': time.time()}


def spotify_loop():
    """Check Spotify every 1.5 s (0.2 s of work); redraw the screen the moment the song or play state changes."""
    last = None; art = {}
    while True:
        try:
            sp = spotify_poll()
            if sp:
                remote = sp['art_remote']
                if remote not in art:
                    try:
                        art[remote] = art_palette(remote)
                    except Exception as e:
                        art[remote] = (None, None); print(time.strftime('%T'), 'spotify art:', e, flush=True)
                key, cols = art[remote]
                if key:
                    sp['art_url'] = '/sart/' + key + '.jpg'; sp['colors'] = cols
            music['spotify'] = sp; music['at'] = time.time()
            sig = sp and (sp['title'], sp['artist'], sp['state'])
            if sig != last:
                last = sig
                if sp: threading.Thread(target=lyrics_for, args=(dict(sp),), daemon=True).start()
                threading.Thread(target=render_once, daemon=True).start()
        except Exception:
            music['spotify'] = None
        spotify_kick.wait(1.5); spotify_kick.clear()


def spotify_cmd(cmd, value=None):
    script = {'play': 'play', 'pause': 'pause', 'toggle': 'playpause', 'next': 'next track', 'previous': 'previous track'}.get(cmd)
    if cmd == 'volume' and value is not None:
        script = f'set sound volume to {int(max(0, min(100, value)))}'
    elif cmd in ('louder', 'quieter'):
        script = 'set sound volume to (sound volume ' + ('+' if cmd == 'louder' else '-') + ' 15)'
    if not script:
        return {'ok': False, 'error': 'unknown music command'}
    r = subprocess.run(['/usr/bin/osascript', '-e', f'if application "Spotify" is running then tell application "Spotify" to {script}'],
                       capture_output=True, text=True, timeout=8)
    time.sleep(0.15); spotify_kick.set()      # show the result right away instead of on the next check
    return {'ok': r.returncode == 0, 'error': r.stderr.strip()[:120]}


def media_playing(home):
    sp = music.get('spotify')
    if sp and sp.get('state') == 'playing':
        return sp
    for m in (home or {}).get('media') or []:
        if m.get('available') and m.get('state') == 'playing' and (m.get('title') or '').strip().lower() not in ('', 'tv', 'line-in', 'line in', 'hdmi arc'):
            return m      # (Sonos playing the TV's sound is not "music")
    return None


def current_face():
    sc = demo_scene()
    if sc and not sc.get('free'):
        return sc['face']
    with lock:
        if is_night() and time.time() > state['awake_until']:
            return 'night'
        det = state.get('detail')
        if det and time.time() < det[1]:
            return det[0]
        state['detail'] = None
        faces = rotation()
        if time.time() - state['face_started'] >= FACE_SECONDS:
            state['face_index'] = (state['face_index'] + 1) % len(faces)
            state['face_started'] = time.time()
            p = photos()
            state['photo'] = random.choice(p) if p else None
        if state['photo'] is None:
            p = photos()
            state['photo'] = p[0] if p else None
        return faces[state['face_index'] % len(faces)]


# ---- Demo mode: a 45-second tour of everything, with made-up data only (no personal photos, calendar or devices) ----
DEMO_DIR = STATIC / 'demo'
DEMO_SCENES = [
    {'face': 'modular', 'secs': 4.5}, {'face': 'weather', 'secs': 3.5}, {'face': 'nowplaying', 'secs': 4.0}, {'face': 'lyrics', 'secs': 3.5},
    {'face': 'muse', 'secs': 4.5, 'page': 'fact'}, {'face': 'muse', 'secs': 3.5, 'page': 'list'}, {'face': 'modular', 'secs': 3.5, 'ov': 'timer'},
    {'face': 'flow', 'secs': 3.0, 'ov': 'npbar'}, {'face': 'apps', 'secs': 3.5}, {'face': 'cook', 'secs': 4.0},
    {'face': 'modular', 'secs': 3.5, 'ov': 'door'}, {'face': 'night', 'secs': 3.0}]
# B-roll mode: the same screens, slowly, on a loop (about 2.5 minutes), for filming. No voice pop-ups.
BROLL_SCENES = [
    {'face': 'modular', 'secs': 12}, {'face': 'photo', 'secs': 10, 'photo': 0}, {'face': 'weather', 'secs': 9}, {'face': 'calendar', 'secs': 9},
    {'face': 'nowplaying', 'secs': 10}, {'face': 'lyrics', 'secs': 10}, {'face': 'muse', 'secs': 10, 'page': 'fact'},
    {'face': 'muse', 'secs': 9, 'page': 'list'}, {'face': 'modular', 'secs': 9, 'ov': 'timer'}, {'face': 'flow', 'secs': 9, 'ov': 'npbar'},
    {'face': 'photo', 'secs': 10, 'photo': 1}, {'face': 'apps', 'secs': 9}, {'face': 'cook', 'secs': 10}, {'face': 'modular', 'secs': 9, 'ov': 'door'},
    {'face': 'photo', 'secs': 10, 'photo': 2}, {'face': 'night', 'secs': 8}]


REMOTE_FILE = DATA / 'remote.json'
WALLPAPERS = ['auto', 'green', 'red', 'blue', 'purple', 'gold', 'graphite', 'photo']
remote = {'wallpaper': 'auto', 'photo_pin': None}
try:
    remote.update(json.loads(REMOTE_FILE.read_text()))
except Exception:
    pass


def remote_save():
    try:
        REMOTE_FILE.write_text(json.dumps(remote))
    except Exception as e:
        print('remote save failed:', e, flush=True)


def remote_state():
    sp = music.get('spotify') or {}
    dm = state.get('demo') or {}
    try:
        face = json.loads((OUT / 'shot.json').read_text()).get('face') or current_face()     # what the iMac is actually showing
    except Exception:
        face = current_face()
    return {'face': face, 'demo': (dm.get('mode') or 'tour') if dm else None, 'wallpaper': remote['wallpaper'],
            'photo_pin': remote['photo_pin'], 'photo': state.get('photo'), 'photos': photos(), 'demo_photos': ['demo-' + n for n in demo_photos()],
            'wallpapers': WALLPAPERS, 'song': {'title': sp.get('title'), 'artist': sp.get('artist'), 'state': sp.get('state')} if sp else None,
            'touch': bool(touch.get('H')), 'openai': bool(openai_key()), 'assistant': CONFIG['assistant']['name'],
            'wake_word': CONFIG['assistant']['wake_word'], 'demo_song': CONFIG['demo'].get('song_name') or ''}


def remote_set(q):
    """The control page on the Mac (/remote): demo modes, screens, wallpaper, photos, and 'say it' for testing."""
    g = lambda k: (q.get(k) or [''])[0]
    if g('wallpaper') in WALLPAPERS:
        remote['wallpaper'] = g('wallpaper'); remote_save()
    if 'photo' in q:
        remote['photo_pin'] = None if g('photo') in ('', 'none') else Path(g('photo')).name; remote_save()
    if g('demo'):
        m = g('demo')
        if m == 'talk':
            demo_cmd('script')
        elif m == 'free':
            with lock:
                state['demo'] = {'mode': 'free', 'start': time.time()}; state['detail'] = None
        elif m == 'broll':
            start_demo(broll=True)
        elif m == 'tour':
            start_demo()
        else:
            start_demo(stop=True)
    if g('face'):
        f = g('face'); dm = state.get('demo') or {}
        if dm.get('mode') == 'script':
            demo_cmd('face', f)
        else:
            with lock:
                if dm and dm.get('mode') in (None, 'broll'):
                    state['demo'] = None                      # a screen button takes over from the B-roll loop or tour
                state['detail'] = None if f == 'modular' else (f, time.time() + float(g('seconds') or 300))
                state['awake_until'] = max(state.get('awake_until', 0), time.time() + 300)
    if g('say'):
        try:
            urllib.request.urlopen(urllib.request.Request(VOICE_URL + '/say?' + urllib.parse.urlencode({'text': g('say')}), data=b'', method='POST'), timeout=4)
        except Exception as e:
            return {'ok': False, 'error': 'voice service: %s' % e}
    threading.Thread(target=render_once, daemon=True).start()
    return {'ok': True, 'state': remote_state()}


def demo_photos():
    """The generated placeholder pictures in static/demo/sample-*.jpg (tools/make_demo_images.py)."""
    return sorted(p.name for p in DEMO_DIR.glob('sample-*.jpg'))


DEMO_SONG = CONFIG['demo'].get('song_uri') or ''          # optional: a Spotify track the scripted demo plays
DEMO_FACT = ("The **Golden Gate Bridge** opened in **1937** and spans **4,200 feet** between San Francisco and Marin County. "
             "Its color, International Orange, was chosen so the bridge stands out in the fog.")
DEMO_RECIPE = {'title': 'Banana Bread', 'meta': '1 hour 10 minutes • Serves 8', 'image': '/demo/bread.jpg',
               'ingredients': ['3 ripe bananas, mashed', '1/3 cup melted butter', '3/4 cup sugar', '1 egg, beaten', '1 teaspoon vanilla',
                               '1 teaspoon baking soda', 'Pinch of salt', '1 1/2 cups all-purpose flour'],
               'steps': [{'text': 'Preheat the oven to 350°F and butter a 9 by 5 inch loaf pan.', 'mins': 0},
                         {'text': 'Mash the bananas in a large bowl until smooth.', 'mins': 0},
                         {'text': 'Stir in the melted butter, then the sugar, egg and vanilla.', 'mins': 0},
                         {'text': 'Sprinkle in the baking soda and salt, then fold in the flour until just combined.', 'mins': 0},
                         {'text': 'Pour the batter into the pan and bake until a toothpick comes out clean.', 'mins': 55},
                         {'text': 'Let it cool in the pan for 10 minutes, then slice and enjoy.', 'mins': 10}]}


def demo_scene():
    dm = state.get('demo')
    if not dm:
        return None
    if dm.get('mode') == 'script':                 # spoken demo: stays on until "stop the demo" (or 30 minutes)
        if time.time() - dm['start'] > 1800:
            state['demo'] = None; return None
        return {'face': dm.get('face', 'modular'), 'page': dm.get('page'), 'script': True, 't': time.time() - dm['start']}
    if dm.get('mode') == 'free':                   # free demo: everything works as normal, only the info is demo info
        if time.time() - dm['start'] > 3 * 3600:
            state['demo'] = None; return None
        return {'face': None, 'free': True, 't': time.time() - dm['start']}
    if dm.get('mode') == 'broll':                  # loops until stopped (or 30 minutes)
        el = time.time() - dm['start']
        if el > 1800:
            state['demo'] = None; return None
        total = sum(sc['secs'] for sc in BROLL_SCENES); loop, t = divmod(el, total)
        for i, sc in enumerate(BROLL_SCENES):
            if t < sc['secs']:
                return dict(sc, index=i, t=t, loop=int(loop), broll=True)
            t -= sc['secs']
    t = time.time() - dm['start']
    for i, sc in enumerate(DEMO_SCENES):
        if t < sc['secs']:
            return dict(sc, index=i, t=t)
        t -= sc['secs']
    state['demo'] = None; state['detail'] = None          # tour over: back to Home
    return None


def demo_bounds():
    dm = state.get('demo')
    if not dm:
        return []
    if dm.get('mode') in ('script', 'free'):
        return []
    if dm.get('mode') == 'broll':
        total = sum(sc['secs'] for sc in BROLL_SCENES)
        out, t = [], dm['start'] + ((time.time() - dm['start']) // total) * total
        for _ in range(2):
            for sc in BROLL_SCENES:
                t += sc['secs']; out.append(t + 0.02)
        return out
    out, t = [], dm['start']
    for sc in DEMO_SCENES:
        t += sc['secs']; out.append(t + 0.02)
    return out


def demo_photo(sc):
    if (remote.get('photo_pin') or '').startswith('demo-') and (DEMO_DIR / remote['photo_pin'][5:]).exists():
        return remote['photo_pin']
    pics = demo_photos()
    if not pics:
        return None
    if sc.get('script') or sc.get('free'):
        i = int(sc.get('t', 0) // 20)                  # a new picture every 20 seconds
    elif 'photo' in sc:
        i = sc['photo'] + 3 * sc.get('loop', 0)
    else:
        i = sc.get('index', 0) + 3 * sc.get('loop', 0)
    return 'demo-' + pics[i % len(pics)]


DEMO_HOME = {'home_online': True, 'covers': [], 'media': [],
             'lights': [{'id': 'demo.lamp', 'name': 'Lamp', 'room': 'Living Room', 'available': True, 'on': True, 'brightness': 80},
                        {'id': 'demo.ceiling', 'name': 'Ceiling', 'room': 'Kitchen', 'available': True, 'on': False},
                        {'id': 'demo.strip', 'name': 'Light Strip', 'room': 'Office', 'available': True, 'on': True, 'brightness': 45},
                        {'id': 'demo.bedside', 'name': 'Bedside', 'room': 'Bedroom', 'available': True, 'on': False},
                        {'id': 'demo.porch', 'name': 'Porch', 'room': 'Outside', 'available': True, 'on': True}],
             'fans': [{'id': 'demo.fan', 'name': 'Fan', 'room': 'Bedroom', 'available': True, 'on': False}],
             'scenes': [{'id': 'demo.movie', 'name': 'Movie', 'room': 'Living Room', 'available': True},
                        {'id': 'demo.goodnight', 'name': 'Goodnight', 'room': 'Home', 'available': True}]}


def demo_data(d, sc):
    """Replace everything personal with sample data for the demo."""
    keep = {k: d.get(k) for k in ('muse_page', 'voice', 'banner', 'message')} if sc.get('free') else None
    today = date.today(); iso = lambda k: (today + timedelta(days=k)).isoformat()
    day = lambda k: (today + timedelta(days=k)).strftime('%a, %b %-d')
    cal = [{'title': 'Morning coffee', 'date': iso(0), 'time': '09:30', 'day': day(0), 'all_day': False},
           {'title': 'Dentist appointment', 'date': iso(0), 'time': '14:00', 'day': day(0), 'all_day': False},
           {'title': 'Pick up groceries', 'date': iso(0), 'time': '18:00', 'day': day(0), 'all_day': False},
           {'title': 'Farmers market', 'date': iso(1), 'time': '09:00', 'day': day(1), 'all_day': False},
           {'title': 'Birthday dinner', 'date': iso(2), 'time': '18:30', 'day': day(2), 'all_day': False},
           {'title': 'Anniversary', 'date': iso(4), 'time': '', 'day': day(4), 'all_day': True},
           {'title': 'Book club', 'date': iso(6), 'time': '19:00', 'day': day(6), 'all_day': False}]
    info = {'calendar': cal, 'calendar_live': True, 'countdown': {'label': 'Vacation', 'days': 12}}
    pos = 48 + sc.get('t', 0)
    playing = {'id': 'demo', 'name': 'Living Room', 'available': True, 'state': 'playing', 'title': 'Golden Hour Drive', 'artist': 'The Daylights',
               'album': 'Sample Album', 'art_url': '/demo/art.jpg', 'colors': ['#4a2a8a', '#ff7a45', '#ff4f8f', '#5b5bff'], 'duration': 214, 'position': pos, 'position_now': pos}
    pages = {'fact': {'md': DEMO_FACT, 'image': '/demo/bridge.jpg', 'source': 'Wikipedia', 'question': ''},
             'list': {'md': "Here's what's coming up this week:\n## Today\n- 9:30 AM Morning coffee\n- !Sign for the package\n## " +
                            (today + timedelta(days=3)).strftime('%A, %B %-d') + "\n- Anniversary · all-day\n- 7:00 PM Dinner reservation", 'question': ''}}
    w = dict(d.get('weather') or {}); w['location'] = w.get('location') or LOC.get('name') or 'Home'
    d.update({'info': info, 'home': DEMO_HOME, 'grid': grid_items(DEMO_HOME), 'playing': playing, 'paused': None, 'photo': demo_photo(sc), 'mask': False, 'weather': w, 'banner': None,
              'voice': None, 'muse_page': pages.get(sc.get('page'), pages['fact']), 'message': None, 'dim': 1, 'demo': True,
              'lyrics': [[50, 'Windows down and the city glows'], [55, 'Every light is turning gold'], [60, 'Sing it back, we know the words'],
                         [66, 'Golden hour, here we go'], [71, 'Keep on driving, take it slow'], [76, 'Golden hour, here we go']],
              'cook': {'title': 'Banana Bread', 'meta': '1 hour 10 minutes • Serves 8', 'image': '/demo/bread.jpg', 'view': 'overview', 'step': 0,
                       'ingredients': ['3 ripe bananas'], 'steps': [{'text': 'Preheat the oven to 350°F.', 'mins': 0}]},
              'cams': None, 'changed': {}})
    if sc.get('script') or sc.get('broll') or sc.get('free'):      # the real song from Spotify, its cover, colors and synced lyrics
        sp = music.get('spotify')
        real = sp if sp and sp.get('state') in ('playing', 'paused') and (state['demo'].get('played') or sc.get('free')) else None
        if real:
            real = dict(real, position_now=real.get('position', 0) + (time.time() - real.get('polled', time.time()) if real.get('state') == 'playing' else 0))
        if real or sc.get('script') or sc.get('free'):
            d['playing'] = real if real and real.get('state') == 'playing' else None
            d['paused'] = real if real and real.get('state') == 'paused' else None
            d['lyrics'] = lyrics_for(sp) if real and sc['face'] == 'lyrics' else None
    if keep is not None:                      # free demo: real answers, voice, banners and recipes
        d.update(keep); d['cook'] = state.get('cook')
    if sc.get('script'):
        d['cook'] = state.get('cook') if state.get('cook') and state['cook'].get('demo') else d['cook']
        d['muse_page'] = pages.get(sc.get('page') or 'fact')
    return d


def demo_cmd(cmd, face=None):
    """Scripted demo actions (the voice service matches your lines and calls these)."""
    dm = state.get('demo')
    if cmd == 'script':
        with lock:
            state['demo'] = {'mode': 'script', 'start': time.time(), 'face': 'modular'}; state['detail'] = None
            state['awake_until'] = time.time() + 1800; state['cook'] = None
        sp = music.get('spotify')
        if sp and sp.get('state') == 'playing':
            spotify_cmd('pause')                        # start the demo quiet; "play the demo song" starts the music
    elif cmd == 'status':
        return {'script': bool(dm and dm.get('mode') == 'script')}
    elif not (dm and dm.get('mode') == 'script'):
        return {'ok': False, 'error': 'demo is not on'}
    elif cmd == 'face':
        dm['face'] = face or 'modular'
    elif cmd == 'play':
        r = play_demo_song()
        dm['played'] = True; dm['face'] = 'nowplaying'
        time.sleep(0.6); spotify_kick.set(); time.sleep(0.5)
        if r.returncode != 0:
            return {'ok': False, 'error': r.stderr.strip()[:120]}
    elif cmd == 'lyrics':
        dm['face'] = 'lyrics'
    elif cmd == 'fact':
        dm['face'] = 'muse'; dm['page'] = 'fact'
    elif cmd == 'recipe':
        with lock:
            state['cook'] = dict(json.loads(json.dumps(DEMO_RECIPE)), view='overview', step=0, at=time.time(), demo=True)
        dm['face'] = 'cook'
    threading.Thread(target=render_once, daemon=True).start()
    return {'ok': True}


def play_demo_song():
    """Play the demo song from config.json in Spotify, or just resume Spotify when none is set."""
    play = f'play track "{DEMO_SONG}"' if re.fullmatch(r'spotify:(track|album|playlist):[A-Za-z0-9]+', DEMO_SONG) else 'play'
    return subprocess.run(['/usr/bin/osascript', '-e', 'tell application "Spotify"', '-e', 'set sound volume to 70', '-e',
                           play, '-e', 'end tell'], capture_output=True, text=True, timeout=12)


def start_demo(stop=False, broll=False):
    with lock:
        if stop:
            state['demo'] = None; state['detail'] = None
        elif broll:
            state['demo'] = {'mode': 'broll', 'start': time.time(), 'played': True}; state['detail'] = None; state['cook'] = None
            state['awake_until'] = time.time() + 1800
        else:
            state['demo'] = {'start': time.time()}; state['detail'] = None
            state['awake_until'] = time.time() + 50
    if broll and not stop:
        def go():
            if not DEMO_SONG:
                return                            # no demo song set: B-roll shows the sample song instead
            r = play_demo_song()                  # B-roll plays the real song, so Now Playing and Lyrics are real
            if r.returncode != 0:
                print(time.strftime('%T'), 'demo song:', r.stderr.strip()[:120], flush=True)
            time.sleep(0.6); spotify_kick.set()
        threading.Thread(target=go, daemon=True).start()
    threading.Thread(target=render_once, daemon=True).start()
    return {'ok': True, 'demo': not stop, 'mode': 'broll' if broll and not stop else 'tour',
            'seconds': sum(sc['secs'] for sc in (BROLL_SCENES if broll else DEMO_SCENES))}


def current_face_cached():
    det = state.get('detail')
    return det[0] if det and time.time() < det[1] else None


def next_lyric_at():
    """Wall-clock time the next lyric line starts (for re-rendering the lyrics screen exactly on the line)."""
    sp = music.get('spotify')
    if not sp or sp.get('state') != 'playing':
        return None
    lines = lyrics.get(hashlib.sha1((sp['title'] + '|' + sp['artist']).encode()).hexdigest()[:16]) or []
    pos = sp.get('position', 0) + time.time() - sp.get('polled', time.time())
    nxt = next((t for t, _ in lines if t > pos + 0.05), None)
    return time.time() + (nxt - pos) - 0.25 if nxt is not None else None


def grid_items(home):
    """The Home grid's device tiles, in config.json order (at most 11: the clock takes the first cell)."""
    rows = {}
    for kind, group in (('light', 'lights'), ('fan', 'fans'), ('scene', 'scenes'), ('shade', 'covers'), ('media', 'media')):
        for r in (home or {}).get(group) or []:
            rows[r['id']] = dict(r, kind=kind)
    order = [d.get('entity_id') for d in HA.get('devices') or []]
    items = [rows[i] for i in order if i in rows] + [r for i, r in rows.items() if i not in order]
    return items[:11]


def data():
    home = home_state()
    pl = media_playing(home)
    if pl and pl.get('id') == 'spotify':
        pl = dict(pl, position_now=pl.get('position', 0) + (time.time() - pl.get('polled', time.time()) if pl.get('state') == 'playing' else 0))
    state['playing'] = pl
    cal = mac_calendar()
    cd = countdown_days()
    out = {
        'now': datetime.now().astimezone().isoformat(),
        'face': current_face(),
        'home': home,
        'grid': grid_items(home),
        'playing': state['playing'],
        'paused': music.get('spotify') if not state['playing'] and (music.get('spotify') or {}).get('state') == 'paused' else None,
        'lyrics': lyrics_for(music['spotify']) if music.get('spotify') and current_face_cached() == 'lyrics' else None,
        'cams': {'list': [dict(c, url='/cam/' + c['id'] + '.jpg?v=%d' % cams['stamp']) for c in cams['list'] if (CAM_DIR / (c['id'] + '.jpg')).exists()],
                 'error': cams['error'] or ('no_token' if not ha_ready() else '')} if current_face_cached() == 'cameras' else None,
        'mask': depth_ok(state['photo']),
        'weather': weather(),
        'photo': remote['photo_pin'] if remote.get('photo_pin') and not remote['photo_pin'].startswith('demo-') and (PHOTOS / remote['photo_pin']).exists() else state['photo'],
        'wallpaper': remote['wallpaper'],
        'info': {'calendar': cal or [], 'calendar_live': cal is not None,
                 'countdown': {'label': CONFIG['countdown']['label'], 'days': cd} if CONFIG['countdown'].get('label') and cd is not None else None},
        'owner': CONFIG.get('owner_name') or '',
        'assistant': CONFIG['assistant']['name'],
        'wake': CONFIG['assistant']['wake_word'],
        'message': state['message'],
        'muse_page': state['muse_page'],
        'cook': state.get('cook'),
        'dim': screen_dim(),
        'voice': state['voice'] if state['voice'] and (state['voice'][0] != 'speaking' or time.time() - state['voice'][2] < 40) else None,
        'changed': {k: v for k, v in state['changed'].items() if time.time() - v < 3},
        'banner': state['banner'] if state['banner'] and time.time() < state['banner'][1] else None,
    }
    sc = demo_scene()
    return demo_data(out, sc) if sc else out


# ---- taps -----------------------------------------------------------------------------------------------------
# Tile rectangles in design coordinates (1451x1088). Must match static/faces.js.
M, G, U = 22, 18, 336  # margin, gap, unit
MX = 26.5  # horizontal margin on the 1451-wide canvas


def cell(c, r, w=1, h=1):
    x = MX + c * (U + G); y = M + r * (U + G)
    return (x, y, x + w * U + (w - 1) * G, y + h * U + (h - 1) * G)


# Home Screen (face 'apps') icon grid: must match faces.js APPS / appsFace().
APP_X0, APP_Y0, APP_DX, APP_DY, APP_S = 772, 176, 216, 284, 164
APPS = [('home', 'home'), ('music', 'nowplaying'), ('weather', 'weather'), ('calendar', 'calendar'), ('photos', 'photo'),
        ('lights', 'grid'), ('cameras', 'cameras'), ('lyrics', 'lyrics'), ('flow', 'flow')]
TILES = {
    'modular': [(cell(0, 0, 2, 2), ('open', 'apps')), (cell(2, 0), ('open', 'weather')), (cell(3, 0), ('open', 'calendar')),
                (cell(2, 1), ('photo', None)), (cell(3, 1), ('info', None)),
                (cell(0, 2, 2, 1), ('open', 'calendar')), (cell(2, 2), ('home_tile', None)), (cell(3, 2), ('none', None))],
    'apps': [((APP_X0 + (i % 3) * APP_DX - 20, APP_Y0 + (i // 3) * APP_DY - 10, APP_X0 + (i % 3) * APP_DX + APP_S + 20, APP_Y0 + (i // 3) * APP_DY + APP_S + 60),
              ('home', None) if target == 'home' else ('open', target)) for i, (_, target) in enumerate(APPS)]
            + [((60, 170, 700, 1040), ('open', 'photo'))],
}


def grid_tiles():
    """Tap targets for the Home grid: the clock cell goes home, each device cell toggles its device."""
    out = [(cell(0, 0), ('home', None))]
    for i, dev in enumerate(grid_items(home_state())):
        out.append((cell((i + 1) % 4, (i + 1) // 4), ('device', dev)))
    return out


HOME_VERBS = {'light': ('on', 'off', 'toggle', 'brightness'), 'fan': ('on', 'off', 'toggle', 'speed'), 'scene': ('activate',),
              'shade': ('open', 'close', 'position'), 'media': ('play', 'pause', 'play_pause', 'next', 'previous', 'volume')}
HA_SERVICES = {   # (dashboard kind, action) -> (Home Assistant domain, service, data key for the value)
    ('light', 'on'): ('light', 'turn_on', None), ('light', 'off'): ('light', 'turn_off', None), ('light', 'toggle'): ('light', 'toggle', None),
    ('light', 'brightness'): ('light', 'turn_on', 'brightness_pct'),
    ('fan', 'on'): ('fan', 'turn_on', None), ('fan', 'off'): ('fan', 'turn_off', None), ('fan', 'toggle'): ('fan', 'toggle', None),
    ('fan', 'speed'): ('fan', 'set_percentage', 'percentage'),
    ('scene', 'activate'): ('scene', 'turn_on', None),
    ('shade', 'open'): ('cover', 'open_cover', None), ('shade', 'close'): ('cover', 'close_cover', None),
    ('shade', 'position'): ('cover', 'set_cover_position', 'position'),
    ('media', 'play'): ('media_player', 'media_play', None), ('media', 'pause'): ('media_player', 'media_pause', None),
    ('media', 'play_pause'): ('media_player', 'media_play_pause', None), ('media', 'next'): ('media_player', 'media_next_track', None),
    ('media', 'previous'): ('media_player', 'media_previous_track', None), ('media', 'volume'): ('media_player', 'volume_set', 'volume_level'),
}


def ha_do(kind, rid, action, value=None):
    """One device action through Home Assistant. kind is the dashboard's name (shade = HA cover, media = media_player)."""
    if not ha_ready():
        return {'ok': False, 'error': 'Home Assistant is not set up'}
    home = home_state() or {}
    group = {'light': 'lights', 'fan': 'fans', 'scene': 'scenes', 'shade': 'covers', 'media': 'media'}[kind]
    row = next((r for r in home.get(group, []) if r.get('id') == rid), None)
    if not row:
        return {'ok': False, 'error': 'No device with id ' + rid}
    if not row.get('available'):
        return {'ok': False, 'error': row.get('name', rid) + ' is not responding right now'}
    svc = HA_SERVICES.get((kind, action))
    if not svc:
        return {'ok': False, 'error': 'Unknown action'}
    domain, service, key = svc
    body = {'entity_id': rid}
    if key and value is not None:
        body[key] = value / 100.0 if key == 'volume_level' else int(value)
    try:
        ha_post(f'/api/services/{domain}/{service}', body)
    except Exception as e:
        return {'ok': False, 'error': 'Home Assistant: ' + str(e)[:100]}
    cache['home'] = (0, cache['home'][1])          # read the new state on the next frame
    return {'ok': True, 'payload': {'device': row.get('name', rid), 'action': action, 'value': value, 'sent': True}}


def device_tap(dev):
    kind = dev['kind']
    act = {'light': 'toggle', 'fan': 'toggle', 'scene': 'activate', 'media': 'play_pause'}.get(kind)
    if kind == 'shade':
        act = 'close' if dev.get('state') == 'open' else 'open'
    res = ha_do(kind, dev['id'], act)
    with lock:
        if res.get('ok'): state['changed'][dev['id']] = time.time()
    return 'Sent' if res.get('ok') else 'No Response'


# Now Playing transport buttons (design coords): previous, play/pause, next. Must match faces.js nowplaying().
NP_Y0, NP_Y1 = 880, 1040
NP_BUTTONS = [((450, 635), 'previous'), ((636, 815), 'play_pause'), ((816, 1000), 'next')]


def media_action(rid, act):
    m = state.get('playing') or {}
    if rid == 'spotify':
        if act == 'play_pause':
            act = 'pause' if m.get('state') == 'playing' else 'play'
        return 'Sent' if spotify_cmd(act).get('ok') else 'Not confirmed'
    return 'Sent' if ha_do('media', rid, act).get('ok') else 'Not confirmed'


def tap(x, y):
    """x, y in design coordinates."""
    if time.time() < door['until']:
        door['until'] = 0; door['live_until'] = 0
        return 'door closed'
    face = current_face()
    if face == 'night':
        with lock:
            state['awake_until'] = time.time() + WAKE_SECONDS; state['face_started'] = time.time()
        threading.Thread(target=render_once, daemon=True).start()
        return 'wake'
    if is_night():
        state['awake_until'] = time.time() + WAKE_SECONDS
    if face == 'cook' and state.get('cook'):
        c = state['cook']
        if x < 170 and y < 170: cook_cmd('close'); return 'close recipe'
        if c['view'] == 'overview':
            if 880 <= y <= 1010: cook_cmd('ingredients' if x < 725 else 'start'); return 'cook'
            return 'nothing'
        if c['view'] == 'ingredients': cook_cmd('start'); return 'start cooking'
        st = c['steps'][c['step']]
        if st['mins'] and 840 <= y <= 960 and 90 <= x <= 700: cook_cmd('timer'); return 'step timer'
        cook_cmd('next' if x >= 725 else 'prev'); return 'step'
    if face == 'nowplaying' and 270 <= x <= 380 and 900 <= y <= 1010:
        state['detail'] = ('lyrics', time.time() + 900); threading.Thread(target=render_once, daemon=True).start(); return 'lyrics'
    if face == 'lyrics':
        state['detail'] = ('nowplaying', time.time() + 60); threading.Thread(target=render_once, daemon=True).start(); return 'now playing'
    if face == 'nowplaying' and (state.get('playing') or music.get('spotify')):
        m = state.get('playing') or music['spotify']
        for (x0, x1), act in NP_BUTTONS:
            if x0 <= x <= x1 and NP_Y0 <= y <= NP_Y1:
                result = media_action(m['id'], act)
                state['message'] = (m['id'], result, time.time())
                threading.Thread(target=render_once, daemon=True).start()
                return result
    hit = None
    for (x0, y0, x1, y1), act in (grid_tiles() if face == 'grid' else TILES.get(face, [])):
        if x0 <= x <= x1 and y0 <= y <= y1:
            hit = act; break
    if face in ('weather', 'photo') or (face == 'grid' and hit is None):
        with lock:
            state['detail'] = None; state['face_started'] = time.time()
        hit = ('home', None)
    if hit is not None and hit[0] == 'info':
        hit = ('open', 'nowplaying') if state.get('playing') else ('none', None)
    if hit is not None and hit[0] == 'home_tile':           # the Home face's device tile: toggle it, or open the grid
        first = grid_items(home_state())
        hit = ('device', first[0]) if first else ('open', 'grid')
    if hit is not None and hit[0] == 'open':
        with lock:
            state['detail'] = (hit[1], time.time() + (900 if hit[1] == 'lyrics' else 60 if hit[1] in ('apps', 'cameras', 'calendar', 'flow') else DETAIL_SECONDS))
        result = 'open ' + hit[1]
    elif hit is not None and hit[0] == 'home':
        with lock:
            state['detail'] = None
        result = 'home'
    elif hit is not None and hit[0] == 'none':
        result = 'nothing'
    elif hit is not None and hit[0] == 'photo':
        p = photos()
        with lock:
            if len(p) > 1:
                state['photo'] = random.choice([n for n in p if n != state['photo']])
        result = 'new photo'
    elif hit is None or hit[0] == 'next':
        with lock:
            state['face_index'] = (state['face_index'] + 1) % len(rotation()); state['face_started'] = time.time()
        result = 'next face'
    else:
        result = device_tap(hit[1])
        with lock:
            state['message'] = (hit[1]['id'], result, time.time())
    state['last_tap'] = (x, y, face, result, time.time())
    threading.Thread(target=render_once, daemon=True).start()
    return result


# ---- jobs from the voice service: device control, showing a screen, a banner ----------------------------------
def run_job(job):
    kind = job.get('kind'); p = job.get('params') or {}
    if kind == 'control':
        if p.get('type') not in HOME_VERBS or p.get('action') not in HOME_VERBS[p['type']]:
            return {'ok': False, 'error': 'Unknown device type or action'}
        res = ha_do(p['type'], str(p.get('id', '')), p['action'], p.get('value'))
        with lock:
            if res.get('ok'): state['changed'][str(p.get('id', ''))] = time.time()
        threading.Thread(target=render_once, daemon=True).start()
        return res
    if kind == 'show':
        face = p.get('face', 'home')
        with lock:
            if face in ('home', 'modular'):
                state['detail'] = None; state['demo'] = None
            elif face == 'next_photo':
                ph = photos()
                if len(ph) > 1:
                    state['photo'] = random.choice([n for n in ph if n != state['photo']])
                state['detail'] = ('photo', time.time() + float(p.get('seconds') or DETAIL_SECONDS))
            elif face in EXTRA_FACES:
                state['detail'] = (face, time.time() + float(p.get('seconds') or DETAIL_SECONDS))
            else:
                return {'ok': False, 'error': 'Unknown face ' + str(face)}
            state['awake_until'] = time.time() + WAKE_SECONDS
        threading.Thread(target=render_once, daemon=True).start()
        return {'ok': True, 'payload': {'showing': face}}
    if kind == 'message':
        text = str(p.get('text', '')).strip()[:160]
        with lock:
            state['banner'] = (text, time.time() + float(p.get('seconds') or 30))
        return {'ok': True, 'payload': {'shown': text}}
    return {'ok': False, 'error': 'Unknown job'}


def banner(text, seconds=30):
    with lock:
        state['banner'] = (text, time.time() + seconds)


def home_loop():
    """Watch the configured devices so a tile glows for a moment when one changes (by voice, a tap or anywhere else)."""
    while ha_ready() and HA.get('devices'):
        try:
            cur = {}
            for r in grid_items(home_state()):
                cur[r['id']] = (r.get('on'), r.get('state'), r.get('available'))
            prev = state['seen'].get('devices')
            state['seen']['devices'] = cur
            hits = [k for k, v in cur.items() if prev is not None and k in prev and prev[k] != v]
            if hits:
                now = time.time()
                for k in hits:
                    state['changed'][k] = now
                threading.Thread(target=render_once, daemon=True).start()
                threading.Timer(3.2, render_once).start()
        except Exception as e:
            print(time.strftime('%T'), 'home:', str(e)[:120], flush=True)
        time.sleep(3)


# ---- pop-ups (drawn on the Mac with SF fonts and real glass; the iMac places them) -----------------------------
VOICE_URL = 'http://127.0.0.1:%d' % CONFIG['ports']['voice']
OV_DIR = OUT / 'ov'


def overlay_loop():
    import hashlib
    import overlays as ov
    from PIL import Image
    OV_DIR.mkdir(parents=True, exist_ok=True)
    base_at, base, versions, last_json = None, None, {}, ''
    made = {}          # sid -> (key, img, rect): reuse a pop-up until its content, background or anything under it changes
    big = {'key': None, 'face': None, 'since': 0, 'done': set()}      # the full-screen timer, and timers already shrunk
    while True:
        try:
            try:
                shot = json.loads((OUT / 'shot.json').read_text())
            except Exception:
                shot = {}
            if shot.get('at') != base_at and (OUT / 'shot.png').exists():
                base = Image.open(OUT / 'shot.png').convert('RGB'); base_at = shot.get('at')
            try:
                vs = get_json(VOICE_URL + '/voice-state', timeout=1)
            except Exception:
                vs = {}
            specs = []      # (id, function, args) in stacking order: later ones draw over earlier ones
            y = 14
            tms = vs.get('timers') or []
            fresh = [t for t in tms if t['total'] - t['remaining'] < 60 and t['remaining'] > 0]      # just started: StandBy-style full screen
            if fresh:
                t = min(fresh, key=lambda t: t['total'] - t['remaining'])      # the newest one
                key = (t['label'], t['total'])
                if big['key'] != key:
                    big.update(key=key, face=shot.get('face'), since=time.time())
                elif time.time() - big['since'] < 3:
                    big['face'] = shot.get('face')            # the screen it starts on
                elif shot.get('face') != big['face']:
                    big['done'].add(key)                      # you moved to another screen: shrink to the capsule (like HomeView)
                if key in big['done']:
                    fresh = []
            if fresh and not vs.get('ringing'):
                rem = math.ceil(max(0, t['remaining'])); hh, rr = divmod(rem, 3600); mm, ss = divmod(rr, 60)
                txt = f'{hh}:{mm:02d}:{ss:02d}' if hh else f'{mm}:{ss:02d}'
                tot = int(round(t['total'])); th, tr = divmod(tot, 3600); tmin = tr // 60
                dur = (f'{th} HR ' if th else '') + (f'{tmin} MIN' if tmin else '') if tot >= 60 else f'{tot} SEC'
                name = re.sub(r'\s*timer$', '', t.get('label') or '', flags=re.I).strip()
                lab = (name.upper() + ' · ' if name and not re.fullmatch(r'[\w\s-]*(minute|second|hour)s?', name, re.I) else '') + dur.strip()
                specs.append(('tbig', ov.timer_full, (math.ceil(ov.TICKS * t['remaining'] / max(1, t['total'])),)))
                specs.append(('tdig', ov.timer_digits, (txt, lab)))
                tms = [x for x in tms if x is not t]
            for i, t in enumerate(tms[:2]):
                specs.append(('timer%d' % i, ov.timer_capsule, (t['label'], math.ceil(max(0, t['remaining'])), t['total'], y))); y += 74
            sp = music.get('spotify')
            if sp and sp.get('state') == 'playing' and shot.get('face') not in ('nowplaying', 'modular', 'night', 'lyrics', 'muse') \
                    and not any(sid == 'tbig' for sid, _, _ in specs):
                ap = ART_DIR / Path(sp.get('art_url', '')).name if str(sp.get('art_url', '')).startswith('/sart/') else None
                specs.append(('npbar', ov.np_bar, (sp.get('title', ''), sp.get('artist', ''), str(ap) if ap else None, (sp.get('colors') or [''])[0], y))); y += 70
            b = state.get('banner')
            if b and time.time() < b[1] and shot.get('face') != 'night':
                title, body, kind = ov.split_banner(b[0])
                specs.append(('banner', ov.banner, ('', title, body, kind, y)))
            ph = vs.get('phase'); txt = (vs.get('text') or '').strip(); card = (vs.get('card') or '').strip()
            if not vs.get('ringing'):
                if ph in ('thinking', 'listening') and txt:          # live transcript while you talk, like Siri
                    specs.append(('siri', ov.siri_card, (txt, 'thinking')))
                elif card:
                    specs.append(('siri', ov.siri_card, (card, 'speaking')))
            if vs.get('ringing'):
                specs.append(('alarm', ov.alarm_card, (vs['ringing'],)))
            if time.time() < door['until']:
                specs.append(('door', ov.door_card, (door['title'], door['sub'], str(DOOR_SNAP) if door['stamp'] else None, door['stamp'])))
            dsc = demo_scene()
            if dsc and dsc.get('script'):
                specs = [x for x in specs if x[0] != 'banner' and not (x[0] == 'siri' and ph == 'listening' and txt)]   # hide raw words, keep answers
            elif dsc and not dsc.get('free'):
                specs = []
                if shot.get('face') != dsc['face']:
                    pass          # wait until this scene's screen is up before adding its pop-up
                elif dsc.get('ov') == 'timer':
                    rem = 720 - 28 - dsc['t']; mm, ss = divmod(int(math.ceil(rem)), 60)
                    specs = [('tbig', ov.timer_full, (math.ceil(ov.TICKS * rem / 720),)), ('tdig', ov.timer_digits, (f'{mm}:{ss:02d}', 'PASTA · 12 MIN'))]
                elif dsc.get('ov') == 'npbar':
                    sp = music.get('spotify') or {}
                    if dsc.get('broll') and sp.get('state') == 'playing':
                        ap = ART_DIR / Path(sp.get('art_url', '')).name if str(sp.get('art_url', '')).startswith('/sart/') else None
                        specs = [('npbar', ov.np_bar, (sp.get('title', ''), sp.get('artist', ''), str(ap) if ap else None, (sp.get('colors') or [''])[0], 14))]
                    else:
                        specs = [('npbar', ov.np_bar, ('Golden Hour Drive', 'The Daylights', str(DEMO_DIR / 'art.jpg'), '#ff7a45', 14))]
                elif dsc.get('ov') == 'door':
                    specs = [('door', ov.door_card, ('Front Door', 'Someone is at the door · ' + datetime.now().strftime('%-I:%M %p'),
                                                     str(DOOR_SAMPLE) if DOOR_SAMPLE.exists() else None, 0))]
            if touch['cal'] in ('finger', 'done', 'failed'):
                ct = touch.get('cal_target') or (0, FINGER_TARGETS[0], 0.0)
                specs = [('cal', ov.cal_target, ((int(ct[1][0] * RENDER_W / DESIGN_W), int(ct[1][1] * RENDER / DESIGN)), round(ct[2] * 10) / 10,
                                                 ct[0], len(FINGER_TARGETS), touch['cal']))]
            elif touch['cal']:
                specs = [('cal', ov.cal_dots, ([(int(x * RENDER_W / DESIGN_W), int(y * RENDER / DESIGN)) for x, y in CAL_DOTS] if touch['cal'] == 'dots' else [],))]
            items = []
            if base is not None:
                work = None; chain = (base_at,)
                for sid, fn, args in specs:
                    key = chain + ((sid, repr(args)),)
                    hit = made.get(sid)
                    if hit and hit[0] == key:
                        img, (x, yy, w, h) = hit[1], hit[2]
                    else:
                        if work is None:          # build the stacked background only when something must be redrawn
                            work = base.copy()
                            for psid, _, _ in specs:
                                if psid == sid: break
                                pimg, prect = made[psid][1], made[psid][2]; work.paste(pimg, (prect[0], prect[1]))
                        img, (x, yy, w, h) = fn(work, *args)
                        made[sid] = (key, img, (x, yy, w, h))
                    if work is not None:
                        work.paste(img, (x, yy))
                    chain = key
                    data = img.tobytes()
                    v = hashlib.md5(data + bytes(str((x, yy, w, h)), 'ascii')).hexdigest()[:10]
                    if versions.get(sid) != v:
                        tmp = OV_DIR / (sid + '.tmp.png'); img.save(tmp, 'PNG', optimize=False); os.replace(tmp, OV_DIR / (sid + '.png'))
                        versions[sid] = v
                    items.append({'id': sid, 'x': x, 'y': yy, 'w': w, 'h': h, 'v': v})
            js = json.dumps({'at': base_at, 'items': items})
            if js != last_json:
                (OUT / 'ov.tmp.json').write_text(js); os.replace(OUT / 'ov.tmp.json', OUT / 'ov.json'); last_json = js
        except Exception as e:
            print(time.strftime('%T'), 'overlay:', str(e)[:160], flush=True)
            time.sleep(1)
        time.sleep(0.06 if touch['cal'] else 0.2)


# ---- Doorbell through Home Assistant: a ring shows the Front Door card with the camera picture ----
DOOR_SNAP = OUT / 'door.jpg'
DOOR_SAMPLE = STATIC / 'demo' / 'door.jpg'      # generated placeholder for test rings and the demos
door = {'event': None, 'camera': None, 'last': None, 'until': 0, 'title': '', 'sub': '', 'stamp': 0, 'live_until': 0, 'error': ''}


def door_discover():
    """Find the doorbell's event entity and its camera (or use doorbell_event / doorbell_camera from config.json)."""
    states = ha_get('/api/states', timeout=10)
    def name(st): return (st['entity_id'] + ' ' + str(st.get('attributes', {}).get('friendly_name', ''))).lower()
    ev = HA.get('doorbell_event') or next((st['entity_id'] for st in sorted(states, key=lambda st: not re.search(r'door', name(st)))
                                           if st['entity_id'].startswith('event.') and st.get('attributes', {}).get('device_class') == 'doorbell'), None)
    cams = [st for st in states if st['entity_id'].startswith('camera.')]
    cam = HA.get('doorbell_camera') or next((st['entity_id'] for st in cams if re.search(r'door', name(st))), None) \
        or (cams[0]['entity_id'] if len(cams) == 1 else None)
    door['event'], door['camera'] = ev, cam
    return ev, cam


def door_snapshot(test=False):
    """Save a fresh camera picture for the Front Door card. Returns True when there is a picture to show."""
    from PIL import Image
    try:
        if test and not (ha_ready() and door['camera']):
            if not DOOR_SAMPLE.exists():
                return False
            img = Image.open(DOOR_SAMPLE).convert('RGB')
        else:
            if not door['camera']:
                return False
            img = Image.open(io.BytesIO(ha_get('/api/camera_proxy/' + door['camera'], raw=True, timeout=8))).convert('RGB')
        img.thumbnail((900, 700))
        img.save(OUT / 'door.next.jpg', 'JPEG', quality=88); os.replace(OUT / 'door.next.jpg', DOOR_SNAP)
        door['stamp'] = time.time()
        return True
    except Exception as e:
        door['error'] = str(e)[:120]; print(time.strftime('%T'), 'door snapshot:', e, flush=True)
        return False


def door_show(title, sub, secs, chime=False, test=False, live=0):
    DOOR_SNAP.unlink(missing_ok=True); door['stamp'] = 0
    now = time.time()
    door.update(title=title, sub=sub, until=now + secs, live_until=now + live)
    with lock:
        state['awake_until'] = max(state.get('awake_until', 0), now + secs)    # a ring lights the screen, even at night
    if chime:
        try:
            get_json(VOICE_URL + '/chime', data=b'{}', headers={'Content-Type': 'application/json'}, timeout=2)
        except Exception as e:
            print(time.strftime('%T'), 'door chime:', e, flush=True)
    threading.Thread(target=render_once, daemon=True).start()
    threading.Thread(target=door_snapshot, args=(test,), daemon=True).start()


def door_loop():
    """Watch the doorbell's press event once a second; while the Front Door card is up, refresh its picture every 3 s."""
    prev = None; found_at = 0
    while True:
        if not ha_ready():
            time.sleep(15); continue
        try:
            if not door['event'] and time.time() - found_at > 60:
                found_at = time.time(); door_discover()
            if door['event']:
                st = ha_get('/api/states/' + door['event'], timeout=4).get('state')
                if prev is not None and st != prev and st not in ('unknown', 'unavailable', None):
                    door['last'] = time.time()
                    door_show('Front Door', 'Someone is at the door · ' + datetime.now().strftime('%-I:%M %p'), 45, chime=True, live=45)
                prev = st
            if time.time() < door['live_until'] and time.time() - door['stamp'] > 3 and door['camera']:
                door_snapshot()
            door['error'] = ''
        except Exception as e:
            door['error'] = str(e)[:120]; time.sleep(5)
        time.sleep(1)


# ---- Camera touch (optional): a USB webcam watches the iMac screen, HomeViewTouch.app sends the fingertip, we turn it into taps ----
TOUCH_APP = HELPERS / 'HomeViewTouch.app'
TOUCH_DATA = DATA
TOUCH_CAL = TOUCH_DATA / 'touch-cal.json'
TOUCH_FRAME = TOUCH_DATA / 'touch-frame.jpg'
DWELL_S = 0.55          # hold still this long to tap
SWIPE_FACES = ['modular', 'apps', 'weather', 'calendar', 'flow', 'photo']
touch = {'H': None, 'p': None, 'p_at': 0, 'anchor': None, 'anchor_t': 0, 'fired': False, 'hist': [], 'swipe_at': 0,
         'ripple': None, 'snap': False, 'cam_at': 0, 'cal': None, 'cal_msg': '', 'armed': True, 'swipe_dir': None,
         'raw': None, 'frames': [], 'tap_shot': False, 'cal_raw': [], 'cal_target': None, 'seen_at': 0}
TAP_DIR = TOUCH_DATA / 'taps'


def touch_load():
    try:
        touch['H'] = json.loads(TOUCH_CAL.read_text())['H']
    except Exception:
        touch['H'] = None


def apply_h(H, x, y):
    d = H[2][0] * x + H[2][1] * y + H[2][2]
    return (H[0][0] * x + H[0][1] * y + H[0][2]) / d, (H[1][0] * x + H[1][1] * y + H[1][2]) / d


def touch_active():
    return touch['p'] is not None and time.time() - touch['p_at'] < 0.6


def touch_swipe(left):
    face = current_face()
    print(time.strftime('%T'), 'touch swipe', 'left' if left else 'right', 'on', face, flush=True)
    if face == 'cook':
        cook_cmd('next' if left else 'prev'); return
    if face == 'nowplaying' and left:
        state['detail'] = ('lyrics', time.time() + 900)
    elif face == 'lyrics' and not left:
        state['detail'] = ('nowplaying', time.time() + 120)
    else:
        i = SWIPE_FACES.index(face) if face in SWIPE_FACES else 0
        new = SWIPE_FACES[(i + (1 if left else -1)) % len(SWIPE_FACES)]
        dm = state.get('demo')
        if dm and dm.get('mode') == 'script':
            dm['face'] = new
        else:
            state['detail'] = None if new == 'modular' else (new, time.time() + 60)
    with lock:
        state['awake_until'] = max(state.get('awake_until', 0), time.time() + WAKE_SECONDS)
    threading.Thread(target=render_once, daemon=True).start()


def touch_raw(body):
    now = time.time(); touch['cam_at'] = now
    touch['frames'] = [t for t in touch['frames'] if now - t < 2] + [now]
    snap = touch['snap']; touch['snap'] = False
    idx = body.get('index')
    if touch['cal'] == 'finger':
        if idx:
            touch['cal_raw'].append((now, idx[0], idx[1])); touch['cal_seen'] = touch.get('cal_seen', 0) + 1
            if touch['H']:                                                # show the finger on the calibration screen
                touch['p'] = apply_h(touch['H'], idx[0], idx[1]); touch['p_at'] = now
        touch['cal_raw'] = [e for e in touch['cal_raw'] if now - e[0] < 1.2]
        return {'snap': snap}
    if not idx or not touch['H'] or touch['cal']:
        if now - touch['p_at'] > 0.25 or touch['cal'] or not touch['H']:      # ignore a single missed frame
            touch['p'] = None; touch['anchor'] = None; touch['fired'] = False; touch['hist'] = []; touch['armed'] = True
        return {'snap': snap}
    x, y = apply_h(touch['H'], idx[0], idx[1])
    if not (-30 <= x <= DESIGN_W + 30 and -30 <= y <= DESIGN + 30):
        touch['p'] = None; touch['anchor'] = None; touch['fired'] = False; touch['hist'] = []; touch['armed'] = True
        return {'snap': snap}
    touch['raw'] = (idx[0], idx[1])
    if not touch['p'] or now - touch['p_at'] >= 0.3:
        touch['seen_at'] = now                                        # the hand just came into view
    if touch['p'] and now - touch['p_at'] < 0.3:                      # adaptive smoothing: steady when still, no lag when moving
        dt = max(0.01, now - touch['p_at'])
        speed = math.hypot(x - touch['p'][0], y - touch['p'][1]) / dt
        a = max(0.3, min(0.95, 0.3 + speed / 2500.0))
        x, y = touch['p'][0] + (x - touch['p'][0]) * a, touch['p'][1] + (y - touch['p'][1]) * a
    touch['p'] = (x, y); touch['p_at'] = now
    h = touch['hist']; h.append((now, x, y)); touch['hist'] = h = [e for e in h if now - e[0] < 0.6]
    recent = [e for e in h if now - e[0] < 0.25]
    still = len(recent) >= 3 and max(math.hypot(e[1] - x, e[2] - y) for e in recent) < 45
    if not touch['armed'] and still and now - touch['swipe_at'] > 0.6:
        touch['armed'] = True                                         # hand settled after a swipe: swipes allowed again
    fast = [e for e in h if now - e[0] < 0.45]
    if touch['armed'] and fast:
        t0, x0, y0 = fast[0]
        left = x < x0
        if abs(x - x0) > 0.4 * DESIGN_W and abs(y - y0) < 0.4 * abs(x - x0) and now - t0 > 0.08 and t0 - touch.get('seen_at', now) > 0.35 \
                and not (touch['swipe_dir'] is not None and touch['swipe_dir'] != left and now - touch['swipe_at'] < 1.6):
            touch['swipe_at'] = now; touch['swipe_dir'] = left; touch['armed'] = False
            touch['hist'] = []; touch['anchor'] = None; touch['fired'] = True
            threading.Thread(target=touch_swipe, args=(left,), daemon=True).start()
            return {'snap': snap}
    if not touch['armed']:
        return {'snap': snap}                                         # mid-swipe: no taps either
    a = touch['anchor']
    dist = math.hypot(x - a[0], y - a[1]) if a else 1e9
    if dist < 32:
        if not touch['fired'] and now - touch['anchor_t'] >= DWELL_S and now - touch['swipe_at'] > 0.8:
            touch['fired'] = True; touch['ripple'] = (a, now)
            print(time.strftime('%T'), 'touch tap at', int(a[0]), int(a[1]), 'camera', [int(v) for v in idx[:2]], flush=True)
            threading.Thread(target=tap, args=a, daemon=True).start()
            threading.Thread(target=save_tap_shot, args=(a, (idx[0], idx[1])), daemon=True).start()
    elif not (touch['fired'] and dist < 80):                          # after a tap, move away before the next one
        touch['anchor'] = (x, y); touch['anchor_t'] = now; touch['fired'] = False
    return {'snap': snap or touch.pop('tap_shot', False)}


def save_tap_shot(design_pt, cam_pt):
    """Keep a camera picture of each tap (last 12) with the fingertip marked, to check accuracy."""
    try:
        from PIL import Image, ImageDraw
        TAP_DIR.mkdir(parents=True, exist_ok=True)
        before = TOUCH_FRAME.stat().st_mtime if TOUCH_FRAME.exists() else 0
        touch['tap_shot'] = True
        for _ in range(20):
            time.sleep(0.05)
            if TOUCH_FRAME.exists() and TOUCH_FRAME.stat().st_mtime > before: break
        time.sleep(0.1)
        im = Image.open(TOUCH_FRAME).convert('RGB'); d = ImageDraw.Draw(im)
        cx, cy = cam_pt; d.ellipse((cx - 16, cy - 16, cx + 16, cy + 16), outline=(255, 40, 40), width=5)
        d.text((cx + 22, cy - 10), 'tap %d,%d' % design_pt, fill=(255, 40, 40))
        im.thumbnail((1280, 720)); im.save(TAP_DIR / time.strftime('tap-%H%M%S.jpg'), 'JPEG', quality=80)
        for f in sorted(TAP_DIR.glob('tap-*.jpg'))[:-12]: f.unlink()
    except Exception as e:
        print(time.strftime('%T'), 'tap shot:', e, flush=True)


def touch_progress():
    if not touch_active() or not touch['anchor'] or touch['fired']:
        return 0.0
    return max(0.0, min(1.0, (time.time() - touch['anchor_t'] - 0.12) / (DWELL_S - 0.12)))


def screen_corners(white, black):
    """Find the iMac screen in the camera frame. The camera re-exposes for each flash, so the black frame is used on its
    own: the screen is the big dark area inside the bright bezel. Grow it from the middle, fit a straight line to the middle
    part of each edge, and intersect the lines (so a corner just outside the camera's view still works)."""
    import numpy as np
    k = 4
    hgt, wid = black.shape[0] // k * k, black.shape[1] // k * k
    b = black[:hgt, :wid].reshape(hgt // k, k, wid // k, k).mean(axis=(1, 3))
    hist, edges = np.histogram(b, bins=64, range=(0, 256))          # Otsu: split dark screen from bright bezel
    best, thr = -1, 128.0; tot = hist.sum(); cum = np.cumsum(hist); csum = np.cumsum(hist * (edges[:-1] + 2))
    for n in range(1, 63):
        w0, w1 = cum[n], tot - cum[n]
        if w0 == 0 or w1 == 0: continue
        m0, m1 = csum[n] / w0, (csum[-1] - csum[n]) / w1
        v = w0 * w1 * (m0 - m1) ** 2
        if v > best: best, thr = v, edges[n + 1]
    mask = b < thr
    H_, W_ = mask.shape; cy, cx = H_ // 2, W_ // 2
    if not mask[cy - 2:cy + 3, cx - 2:cx + 3].all():
        raise RuntimeError('could not see the screen: point the camera at the iMac so the whole screen is in view')
    def run(line, start, step):                                    # walk from the middle until the bright bezel
        n = start
        while 0 <= n + step < len(line) and line[n + step]: n += step
        return n
    top_c, bot_c = run(mask[:, cx], cy, -1), run(mask[:, cx], cy, 1)
    lef_c, rig_c = run(mask[cy], cx, -1), run(mask[cy], cx, 1)
    if (bot_c - top_c) < 0.3 * H_ or (rig_c - lef_c) < 0.3 * W_:
        raise RuntimeError('could not see the screen: point the camera at the iMac so the whole screen is in view')
    L, R, T, B = [], [], [], []
    for y in range(top_c + (bot_c - top_c) // 6, bot_c - (bot_c - top_c) // 6):
        L.append((run(mask[y], cx, -1), y)); R.append((run(mask[y], cx, 1) + 1, y))
    for x in range(lef_c + (rig_c - lef_c) // 6, rig_c - (rig_c - lef_c) // 6):
        T.append((x, run(mask[:, x], cy, -1))); B.append((x, run(mask[:, x], cy, 1) + 1))
    def fit(pts, vertical):
        a = np.array(pts, dtype=np.float64)
        for _ in range(3):                                          # least squares, dropping outliers twice
            if vertical: m, c = np.polyfit(a[:, 1], a[:, 0], 1); res = a[:, 0] - (m * a[:, 1] + c)
            else: m, c = np.polyfit(a[:, 0], a[:, 1], 1); res = a[:, 1] - (m * a[:, 0] + c)
            keep = np.abs(res) <= max(1.5, 2.5 * np.std(res))
            a = a[keep] if keep.sum() > 10 else a
        return m, c
    lm, lc = fit(L, True); rm, rc = fit(R, True); tm, tc = fit(T, False); bm, bc = fit(B, False)
    def cross(vm, vc, hm, hc):                                       # x = vm*y + vc ; y = hm*x + hc
        y = (hm * vc + hc) / (1 - hm * vm); x = vm * y + vc
        return (x * k, y * k)
    return cross(lm, lc, tm, tc), cross(rm, rc, tm, tc), cross(rm, rc, bm, bc), cross(lm, lc, bm, bc)


CAL_DOTS = [(200, 160), (1251, 160), (1251, 928), (200, 928)]        # design coords of the four calibration dots


def find_dots(a, b, n=4):
    """Centres of the n spots that lit up between frame a (black) and frame b (black + white dots).
    Only small, round, bright-on-dark spots count, so someone moving in the background can't be mistaken for a dot."""
    import numpy as np
    k = 4
    H_, W_ = a.shape[0] // k * k, a.shape[1] // k * k
    d = (b[:H_, :W_] - a[:H_, :W_]).reshape(H_ // k, k, W_ // k, k).mean(axis=(1, 3))
    bd = b[:H_, :W_].reshape(H_ // k, k, W_ // k, k).mean(axis=(1, 3))
    d = np.clip(d, 0, None); out = []
    for _ in range(60):
        if len(out) == n:
            break
        y, x = np.unravel_index(int(d.argmax()), d.shape)
        peak = d[y, x]
        if peak < 25:
            break
        r = 18
        y0, y1, x0, x1 = max(0, y - r), min(d.shape[0], y + r + 1), max(0, x - r), min(d.shape[1], x + r + 1)
        win = d[y0:y1, x0:x1]; m = win > peak * 0.5
        yy, xx = np.nonzero(m); wts = win[m]
        cx, cy = float((xx * wts).sum() / wts.sum() + x0), float((yy * wts).sum() / wts.sum() + y0)
        d[y0:y1, x0:x1] = 0
        # a dot: compact blob, not touching the search window, and clearly brighter than a dark ring around it
        if len(yy) < 3 or yy.min() == 0 or xx.min() == 0 or yy.max() == m.shape[0] - 1 or xx.max() == m.shape[1] - 1:
            continue
        rad = max(yy.max() - yy.min(), xx.max() - xx.min()) / 2 + 1
        if len(yy) < 0.4 * 3.14 * rad * rad:
            continue
        gy, gx = np.mgrid[0:bd.shape[0], 0:bd.shape[1]]; dist = np.hypot(gy - cy, gx - cx)
        inner = bd[dist <= max(1.0, rad * 0.6)].mean(); ring = bd[(dist > rad * 1.6) & (dist <= rad * 2.6)].mean()
        if inner - ring < 40:
            continue
        out.append(((cx + 0.5) * k, (cy + 0.5) * k))
    if len(out) < n:
        raise RuntimeError('could not see the dots: point the camera at the iMac so the whole screen is in view')
    out.sort(key=lambda p: p[1]); top = sorted(out[:2]); bot = sorted(out[2:])
    return [top[0], top[1], bot[1], bot[0]]                         # TL, TR, BR, BL like CAL_DOTS


def touch_calibrate():
    """Show black, then black with four white dots. Only the dots change, so the camera's auto-exposure doesn't matter.
    The dots' camera positions give the mapping from camera to screen."""
    import numpy as np
    from PIL import Image, ImageDraw
    def grab(name):
        before = TOUCH_FRAME.stat().st_mtime if TOUCH_FRAME.exists() else 0
        touch['snap'] = True
        for _ in range(40):
            time.sleep(0.1)
            if TOUCH_FRAME.exists() and TOUCH_FRAME.stat().st_mtime > before:
                time.sleep(0.2); break
        else:
            raise RuntimeError('the camera helper is not sending frames')
        im = Image.open(TOUCH_FRAME).convert('L'); im.save(TOUCH_DATA / name)
        return np.asarray(im, dtype=np.float32)
    try:
        if time.time() - touch['cam_at'] > 3:
            raise RuntimeError('the camera helper is not running (allow camera access for HomeView Touch)')
        touch['cal'] = 'black'; touch['cal_msg'] = 'calibrating'; time.sleep(3.0)
        a = grab('touch-black.jpg')
        touch['cal'] = 'dots'; time.sleep(1.6)
        b = grab('touch-dots.jpg')
        touch['cal'] = None
        src = find_dots(a, b)
        A = []; bvec = []
        for (x, y), (u, v) in zip(src, CAL_DOTS):
            A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); bvec.append(u)
            A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); bvec.append(v)
        hvec = np.linalg.solve(np.array(A, dtype=np.float64), np.array(bvec, dtype=np.float64))
        H = [[hvec[0], hvec[1], hvec[2]], [hvec[3], hvec[4], hvec[5]], [hvec[6], hvec[7], 1.0]]
        Hi = np.linalg.inv(np.array(H)); corners = []
        for (u, v) in [(0, 0), (DESIGN_W, 0), (DESIGN_W, DESIGN), (0, DESIGN)]:
            q = Hi @ np.array([u, v, 1.0]); corners.append([float(q[0] / q[2]), float(q[1] / q[2])])
        TOUCH_CAL.write_text(json.dumps({'H': H, 'dots': src, 'corners': corners, 'at': time.time(), 'frame': [int(a.shape[1]), int(a.shape[0])]}))
        dbg = Image.open(TOUCH_DATA / 'touch-dots.jpg').convert('RGB'); d = ImageDraw.Draw(dbg)
        d.line([tuple(map(int, c)) for c in corners + [corners[0]]], fill=(255, 40, 40), width=6)
        for (x, y) in src: d.ellipse((x - 14, y - 14, x + 14, y + 14), outline=(40, 255, 40), width=5)
        dbg.save(TOUCH_DATA / 'touch-cal.png')
        touch['H'] = H; touch['cal_msg'] = 'finger'
        threading.Thread(target=finger_calibrate, daemon=True).start()
        return {'ok': True, 'dots': [[int(x), int(y)] for x, y in src], 'finger': True}
    except Exception as e:
        touch['cal'] = None; touch['cal_msg'] = str(e)
        return {'ok': False, 'error': str(e)}
    finally:
        threading.Thread(target=render_once, daemon=True).start()


FINGER_TARGETS = [(260, 210), (1191, 210), (725, 544), (1191, 878), (260, 878)]


def fit_h(src, dst):
    """Least-squares homography (camera -> screen) from 4+ point pairs."""
    import numpy as np
    A = []; bvec = []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); bvec.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); bvec.append(v)
    h = np.linalg.lstsq(np.array(A, dtype=np.float64), np.array(bvec, dtype=np.float64), rcond=None)[0]
    return [[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1.0]]


def near_target(screen, c, tgt):
    """A held fingertip only counts for a target if the screen-dot mapping puts it roughly there (allowing for parallax)."""
    if not screen:
        return True
    x, y = apply_h(screen, c[0], c[1])
    return math.hypot(x - tgt[0], y - tgt[1]) < 420


def finger_calibrate():
    """Touch-and-hold five targets the way you naturally touch: this learns the offset between where the camera sees your
    fingertip and where you mean to touch (viewing angle, finger pad, hovering), like a touchscreen's 'tap the targets'."""
    got = []; used = []; screen = touch['H']                                       # the screen-dot mapping, to sanity-check each touch
    try:
        time.sleep(0.8); touch['cal_seen'] = 0
        for n, tgt in enumerate(FINGER_TARGETS):
            touch['cal_target'] = (n, tgt, 0.0); touch['cal_raw'] = []; touch['cal'] = 'finger'
            t0 = time.time(); held = None
            while time.time() - t0 < 20:
                time.sleep(0.05)
                pts = [e for e in touch['cal_raw'] if time.time() - e[0] < 0.9]
                if len(pts) >= 4:                             # tolerate patchy tracking near the frame edge
                    xs = [e[1] for e in pts]; ys = [e[2] for e in pts]
                    spread = max(max(xs) - min(xs), max(ys) - min(ys))
                    prog = max(0.0, min(1.0, (pts[-1][0] - pts[0][0]) / 0.8)) if spread < 45 else 0.0
                    touch['cal_target'] = (n, tgt, prog)
                    if spread < 45 and pts[-1][0] - pts[0][0] > 0.8:
                        c = (sum(xs) / len(xs), sum(ys) / len(ys))
                        if near_target(screen, c, tgt) and all(math.hypot(c[0] - g[0], c[1] - g[1]) > 120 for g in got):
                            held = c; break
                        touch['cal_target'] = (n, tgt, 0.0)            # still resting on the last target: keep waiting
                else:
                    touch['cal_target'] = (n, tgt, 0.0)
            if not held:
                print(time.strftime('%T'), 'finger calibration: skipped target %d' % (n + 1), flush=True)
                continue                                              # one hard-to-see target is fine; 4 are enough
            got.append(held); used.append(tgt)
            touch['cal_target'] = (n, tgt, 1.0); time.sleep(0.5)      # it turns green
            touch['cal_raw'] = []; t1 = time.time()
            while time.time() - t1 < 3 and [e for e in touch['cal_raw'] if time.time() - e[0] < 0.3
                                            and math.hypot(e[1] - held[0], e[2] - held[1]) < 120]:
                time.sleep(0.05)                                      # wait for you to lift or move your finger
        if len(got) < 4:
            raise RuntimeError('only %d of 5 targets were seen (fingertip seen in %d frames)' % (len(got), touch.get('cal_seen', 0)))
        H = fit_h(got, used)
        cal = json.loads(TOUCH_CAL.read_text()); cal.update(H=H, screen_H=cal.get('H'), finger=got, finger_at=time.time())
        TOUCH_CAL.write_text(json.dumps(cal)); touch['H'] = H; touch['cal_msg'] = 'ok'
        print(time.strftime('%T'), 'finger calibration ok', [[int(a), int(b)] for a, b in got], flush=True)
        touch['cal'] = 'done'; time.sleep(1.5)
    except Exception as e:
        touch['cal_msg'] = str(e); print(time.strftime('%T'), 'finger calibration:', e, flush=True)
        touch['cal'] = 'failed'; time.sleep(2.0)
    finally:
        touch['cal'] = None; touch['cal_target'] = None
        threading.Thread(target=render_once, daemon=True).start()


def touch_keeper():
    touch_load()
    while CONFIG['touch'].get('enabled'):
        if TOUCH_APP.exists() and subprocess.run(['/usr/bin/pgrep', '-f', 'HomeViewTouch.app/Contents/MacOS/touchd'], capture_output=True).returncode != 0:
            subprocess.run(['/usr/bin/open', '-g', str(TOUCH_APP), '--args', str(PORT), str(TOUCH_FRAME)], capture_output=True)
        time.sleep(60)


# ---- Cooking mode (HomeView recipe card -> step by step with timers) ----
def cook_cmd(cmd):
    c = state.get('cook')
    if cmd == 'status':
        return {'on': bool(c) and (current_face_cached() == 'cook' or (demo_scene() or {}).get('face') == 'cook')}
    if not c:
        return {'ok': False, 'say': "There's no recipe open."}
    n = len(c['steps']); say = None
    with lock:
        if cmd == 'close':
            state['cook'] = None; state['detail'] = None; say = 'Okay, enjoy!'
        elif cmd == 'ingredients':
            c['view'] = 'ingredients'
        elif cmd == 'start':
            c['view'] = 'step'; c['step'] = 0
        elif cmd == 'next':
            if c['view'] != 'step': c['view'], c['step'] = 'step', 0
            elif c['step'] < n - 1: c['step'] += 1
            else: say = "That's the last step. Enjoy!"
        elif cmd == 'prev':
            if c['view'] == 'step' and c['step'] > 0: c['step'] -= 1
            elif c['view'] == 'step': c['view'] = 'overview'
            else: c['view'] = 'overview'
        elif cmd == 'timer':
            st = c['steps'][c['step']] if c['view'] == 'step' else None
            if st and st['mins']:
                threading.Thread(target=lambda: get_json(VOICE_URL + '/say?text=' + urllib.parse.quote(f"set a {st['mins']} minute timer for {c['title']}"),
                                                         data=b'', timeout=4), daemon=True).start()
                return {'ok': True, 'say': None}
            return {'ok': False, 'say': "There's no timer on this step."}
        if state.get('cook'):
            state['detail'] = ('cook', time.time() + 3 * 3600)
    threading.Thread(target=render_once, daemon=True).start()
    return {'ok': True, 'say': say}


# ---- Intercom-style announcements: Home Assistant speaks them on your speakers ----
def announce(text):
    text = text.strip().rstrip('.')[:200]
    text = text[:1].upper() + text[1:]
    if not ha_ready():
        banner('Intercom · “' + text + '” (speakers need Home Assistant connected)', 20)
        return {'ok': False, 'reason': 'no_token'}
    try:
        st = ha_get('/api/states', timeout=10)
        tts = HA.get('announce_tts') or next((x['entity_id'] for x in st if x['entity_id'].startswith('tts.')), None)
        players = [x['entity_id'] for x in st if x['entity_id'].startswith('media_player.') and x.get('state') != 'unavailable'
                   and re.search(r'homepod|sonos', x['entity_id'] + ' ' + str(x.get('attributes', {}).get('friendly_name', '')), re.I)]
        if HA.get('announce_players'):
            players = list(HA['announce_players'])
        if not tts or not players:
            banner('Intercom · “' + text + '”', 20)
            return {'ok': False, 'reason': 'no_tts' if not tts else 'no_speakers'}
        ha_post('/api/services/tts/speak', {'entity_id': tts, 'media_player_entity_id': players, 'message': text})
        names = ', '.join(next((str(x.get('attributes', {}).get('friendly_name') or p) for x in st if x['entity_id'] == p), p) for p in players[:3])
        banner('Intercom · Announced to ' + names + ': “' + text + '”', 20)
        return {'ok': True, 'speakers': len(players)}
    except Exception as e:
        banner('Intercom · “' + text + '”', 20)
        return {'ok': False, 'reason': 'error', 'error': str(e)[:120]}


# ---- Home Camera face: up to 9 Home Assistant cameras, refreshed while the face is on screen ----
CAM_DIR = OUT / 'cams'
cams = {'list': [], 'found_at': 0, 'stamp': 0, 'error': ''}


def cam_loop():
    while True:
        if current_face_cached() != 'cameras' and state.get('shown_face') != 'cameras':
            time.sleep(1); continue
        if not ha_ready():
            cams['error'] = 'no_token'; time.sleep(3); continue
        try:
            if time.time() - cams['found_at'] > 120:
                st = ha_get('/api/states', timeout=10)
                cams['list'] = [{'id': x['entity_id'], 'name': x.get('attributes', {}).get('friendly_name') or x['entity_id'][7:]}
                                for x in st if x['entity_id'].startswith('camera.') and x.get('state') != 'unavailable'][:9]
                cams['found_at'] = time.time()
            from PIL import Image
            CAM_DIR.mkdir(parents=True, exist_ok=True)
            def snap(c):
                try:
                    img = Image.open(io.BytesIO(ha_get('/api/camera_proxy/' + c['id'], raw=True, timeout=6))).convert('RGB')
                    img.thumbnail((720, 540)); img.save(CAM_DIR / (c['id'] + '.jpg'), 'JPEG', quality=84)
                except Exception as e:
                    cams['error'] = str(e)[:100]
            ths = [threading.Thread(target=snap, args=(c,)) for c in cams['list']]
            [t.start() for t in ths]; [t.join(8) for t in ths]
            cams['stamp'] = time.time(); cams['error'] = '' if cams['list'] else 'no_cameras'
            threading.Thread(target=render_once, daemon=True).start()
        except Exception as e:
            cams['error'] = str(e)[:100]
        time.sleep(5)


# ---- rendering ------------------------------------------------------------------------------------------------
render_lock = threading.Lock()


CDP_PORT = CONFIG['ports']['chrome_devtools']
WAIT_JS = r"""(async () => {
  const t0 = Date.now();
  while (!(document.getElementById('screen') && document.getElementById('screen').children.length) && Date.now() - t0 < 4000)
    await new Promise(r => setTimeout(r, 20));
  const urls = new Set();
  document.querySelectorAll('[style*="url("]').forEach(e => { const m = (e.getAttribute('style') || '').match(/url\(([^)]+)\)/); if (m) urls.add(m[1].replace(/["']/g, '')); });
  document.querySelectorAll('image').forEach(e => { const h = e.getAttribute('href'); if (h) urls.add(h); });
  await Promise.all([...urls].map(u => new Promise(r => { const i = new Image(); i.onload = i.onerror = r; i.src = u; })));
  await document.fonts.ready;
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  return Date.now() - t0;
})()"""


class WS:
    """Just enough of a WebSocket client (RFC 6455) to drive Chrome's DevTools protocol, with no extra packages."""

    def __init__(self, url, timeout=20):
        import socket, base64 as b64
        u = urllib.parse.urlsplit(url)
        self.s = socket.create_connection((u.hostname, u.port), timeout=timeout)
        key = b64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        resp = b''
        while b'\r\n\r\n' not in resp:
            chunk = self.s.recv(4096)
            if not chunk:
                raise ConnectionError('websocket handshake closed')
            resp += chunk
        head, self.buf = resp.split(b'\r\n\r\n', 1)
        if b' 101 ' not in head.split(b'\r\n')[0]:
            raise ConnectionError('websocket handshake failed: ' + head[:80].decode('latin1'))

    def send(self, text):
        import struct
        data = text.encode(); n = len(data); mask = os.urandom(4)
        hdr = bytearray([0x81])
        if n < 126: hdr.append(0x80 | n)
        elif n < 65536: hdr.append(0x80 | 126); hdr += struct.pack('>H', n)
        else: hdr.append(0x80 | 127); hdr += struct.pack('>Q', n)
        masked = bytes(b ^ mask[k % 4] for k, b in enumerate(data))
        self.s.sendall(bytes(hdr) + mask + masked)

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.s.recv(max(65536, n - len(self.buf)))
            if not chunk:
                raise ConnectionError('websocket closed')
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        import struct
        parts = []
        while True:
            b1, b2 = self._read(2)
            op, n = b1 & 0x0f, b2 & 0x7f
            if n == 126: n = struct.unpack('>H', self._read(2))[0]
            elif n == 127: n = struct.unpack('>Q', self._read(8))[0]
            if b2 & 0x80:
                mk = self._read(4); payload = bytes(c ^ mk[k % 4] for k, c in enumerate(self._read(n)))
            else:
                payload = self._read(n)
            if op == 8:
                raise ConnectionError('websocket closed by peer')
            if op == 9:   # ping
                continue
            parts.append(payload)
            if b1 & 0x80:
                return b''.join(parts).decode('utf-8', 'replace')

    def close(self):
        try: self.s.close()
        except OSError: pass


class Renderer:
    """Keeps one headless Chrome open and screenshots faces through DevTools: about half a second instead of three."""

    def __init__(self):
        self.proc = None; self.ws = None; self.mid = 0

    def start(self):
        self.stop()
        subprocess.run(['pkill', '-f', 'user-data-dir=' + str(HERE / '.chrome-cdp')], capture_output=True)
        self.proc = subprocess.Popen([CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run', '--no-default-browser-check',
                                      '--user-data-dir=' + str(HERE / '.chrome-cdp'), f'--remote-debugging-port={CDP_PORT}',
                                      f'--window-size={DESIGN_W},{DESIGN}', 'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        url = None
        for _ in range(60):
            try:
                pages = get_json(f'http://127.0.0.1:{CDP_PORT}/json/list', timeout=2)
                url = next((p['webSocketDebuggerUrl'] for p in pages if p.get('type') == 'page'), None)
                if url: break
            except Exception:
                pass
            time.sleep(0.25)
        if not url:
            raise RuntimeError('Chrome DevTools did not come up')
        self.ws = WS(url)
        self.call('Page.enable')
        self.call('Emulation.setDeviceMetricsOverride', {'width': DESIGN_W, 'height': DESIGN, 'deviceScaleFactor': RENDER_W / DESIGN_W, 'mobile': False})
        if os.environ.get('TZ'):      # keep Chrome's clock in the same zone as Python's when TZ is set
            try: self.call('Emulation.setTimezoneOverride', {'timezoneId': os.environ['TZ']})
            except Exception as e: print(time.strftime('%T'), 'timezone override:', str(e)[:80], flush=True)

    def stop(self):
        if self.ws: self.ws.close(); self.ws = None
        if self.proc:
            try: self.proc.kill()
            except Exception: pass
            self.proc = None

    def call(self, method, params=None, wait_event=None, timeout=15):
        self.mid += 1; mid = self.mid
        self.ws.send(json.dumps({'id': mid, 'method': method, 'params': params or {}}))
        got, seen = None, wait_event is None
        end = time.time() + timeout
        while time.time() < end:
            msg = json.loads(self.ws.recv())
            if msg.get('id') == mid:
                if 'error' in msg: raise RuntimeError(f"{method}: {msg['error']}")
                got = msg.get('result', {})
            elif wait_event and msg.get('method') == wait_event:
                seen = True
            if got is not None and seen:
                return got
        raise TimeoutError(method)

    def shot(self, url):
        import base64 as b64
        if self.ws is None or self.proc is None or self.proc.poll() is not None:
            self.start()
        self.call('Page.navigate', {'url': url}, wait_event='Page.loadEventFired')
        self.call('Runtime.evaluate', {'expression': WAIT_JS, 'awaitPromise': True, 'returnByValue': True})
        res = self.call('Page.captureScreenshot', {'format': 'png', 'fromSurface': True})
        return b64.b64decode(res['data'])


renderer = Renderer()


def dirty_rects(prev, new):
    """Regions (in 1024x768 px) that changed between two renders; None means most of the screen changed."""
    try:
        from PIL import Image, ImageChops
        a = Image.open(prev).convert('RGB'); b = Image.open(new).convert('RGB')
        if a.size != b.size:
            return None
        d = ImageChops.difference(a, b).convert('L').point(lambda v: 255 if v > 12 else 0)
        B = 32; cols, rows = a.size[0] // B, a.size[1] // B
        cells = {(c, r) for r in range(rows) for c in range(cols) if d.crop((c * B, r * B, c * B + B, r * B + B)).getbbox()}
        if len(cells) > 0.5 * cols * rows:
            return None
        rects, left = [], set(cells)
        while left:
            stack = [left.pop()]; group = []
            while stack:
                c, r = stack.pop(); group.append((c, r))
                for nb in ((c + 1, r), (c - 1, r), (c, r + 1), (c, r - 1)):
                    if nb in left: left.discard(nb); stack.append(nb)
            c0 = min(g[0] for g in group); c1 = max(g[0] for g in group); r0 = min(g[1] for g in group); r1 = max(g[1] for g in group)
            rects.append([max(0, c0 * B - 4), max(0, r0 * B - 4), min(a.size[0], (c1 + 1) * B + 4) - max(0, c0 * B - 4), min(a.size[1], (r1 + 1) * B + 4) - max(0, r0 * B - 4)])
        return rects[:16]
    except Exception as e:
        print(time.strftime('%T'), 'dirty:', e, flush=True)
        return None


def render_once(face=None):
    if not render_lock.acquire(False):
        state['rerender'] = True     # something changed mid-render: render again right after
        return False
    try:
        OUT.mkdir(exist_ok=True)
        face = face or current_face()
        target = OUT / 'next.png'
        url = f'http://127.0.0.1:{PORT}/?face={face}&nohands=1'
        t0 = time.time()
        try:
            target.write_bytes(renderer.shot(url))
        except Exception as e:
            print(time.strftime('%T'), 'fast render failed, using one-shot Chrome:', str(e)[:120], flush=True)
            renderer.stop()
            scale = RENDER / DESIGN
            subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run', '--no-default-browser-check',
                            '--user-data-dir=' + str(HERE / '.chrome-profile'), f'--window-size={DESIGN_W},{DESIGN}',
                            f'--force-device-scale-factor={scale:.5f}', '--virtual-time-budget=4000', '--screenshot=' + str(target), url],
                           capture_output=True, timeout=60)
        if not (target.exists() and target.stat().st_size > 1000):
            return False
        prev = OUT / 'shot.png'
        try:
            old = json.loads((OUT / 'shot.json').read_text())
        except Exception:
            old = {}
        dirty = dirty_rects(prev, target) if prev.exists() and old.get('face') == face else None
        if dirty == []:
            target.unlink(); return True          # nothing visible changed: keep the viewer's current frame
        os.replace(target, prev)
        try:   # a JPEG copy decodes about 5x faster on the G4 than the PNG
            from PIL import Image
            Image.open(prev).convert('RGB').save(OUT / 'shot.next.jpg', 'JPEG', quality=92, subsampling=0, optimize=True)
            os.replace(OUT / 'shot.next.jpg', OUT / 'shot.jpg')
        except Exception as e:
            print(time.strftime('%T'), 'jpeg:', e, flush=True)
        state['shown_face'] = face
        (OUT / 'shot.json').write_text(json.dumps({'face': face, 'at': round(time.time(), 2), 'clocks': clock_geom(face), 'dirty': dirty,
                                                   'ms': round((time.time() - t0) * 1000)}))
        return True
    finally:
        render_lock.release()
        if state.pop('rerender', False):
            threading.Thread(target=render_once, daemon=True).start()


def next_render_delay():
    """Sleep until the next thing that changes the screen: the minute, a face timing out, a banner or glow ending."""
    now = time.time()
    due = [60.2 - now % 60]
    det = state.get('detail')
    if det: due.append(det[1] - now + 0.1)
    b = state.get('banner')
    if b: due.append(b[1] - now + 0.1)
    for v in state.get('changed', {}).values(): due.append(v + 3.1 - now)
    if state.get('awake_until', 0) > now: due.append(state['awake_until'] - now + 0.1)
    return max(0.3, min(d for d in due if d > 0) if any(d > 0 for d in due) else 30)


# Analog clocks the G4 viewer draws live on top of the render (hands are left out of the PNG).
CLOCKS = {'grid': (0, 0, 'light')}


def clock_geom(face):
    c = CLOCKS.get(face)
    if not c:
        return []
    x0, y0, x1, y1 = cell(c[0], c[1]); k = RENDER_W / DESIGN_W
    return [{'cx': round((x0 + x1) / 2 * k, 1), 'cy': round((y0 + y1) / 2 * k, 1), 'r': round((x1 - x0) / 2 * k, 1), 'style': c[2]}]


def clear_stale_chrome():
    """Kill headless Chrome left over from a previous server run (it holds the profile lock)."""
    subprocess.run(['pkill', '-f', 'user-data-dir=' + str(HERE / '.chrome-profile')], capture_output=True)
    time.sleep(1)


def due_times():
    now = time.time(); out = [now - now % 60]
    det = state.get('detail')
    if det: out.append(det[1])
    b = state.get('banner')
    if b: out.append(b[1])
    out += [v + 3.1 for v in state.get('changed', {}).values()]
    if state.get('awake_until'): out.append(state['awake_until'])
    if len(rotation()) > 1: out.append(state['face_started'] + FACE_SECONDS)   # switch Home <-> Now Playing on time
    out += demo_bounds()
    if state.get('shown_face') == 'lyrics' or current_face_cached() == 'lyrics':
        d = state.get('lyric_due')
        if d: out.append(d)
        if not d or d < now:          # that line has been drawn: schedule the next one
            nd = next_lyric_at(); state['lyric_due'] = nd
            if nd: out.append(nd)
    sp = music.get('spotify')
    if sp and sp.get('state') == 'playing' and state.get('shown_face') == 'nowplaying':
        out.append(now - now % 5)
    return out


def render_loop():
    """Render whenever something on screen becomes due: the minute, a face timing out, a banner or glow ending."""
    clear_stale_chrome()
    fails = 0; last = 0.0
    while True:
        now = time.time()
        if last == 0.0 or any(last < t <= now for t in due_times()):
            last = now
            try:
                ok = render_once()
            except Exception:
                ok = False
            fails = 0 if ok else fails + 1
            if fails >= 3:
                clear_stale_chrome(); renderer.stop(); fails = 0
        time.sleep(0.4)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def local_ok(self):
        """Only this Mac, and only first-party requests: a web page open in a browser here must not be able to drive the
        dashboard (CSRF) or read it through DNS rebinding."""
        if self.client_address[0] not in ('127.0.0.1', '::1'):
            return False
        host = (self.headers.get('Host') or '').lower()
        if host not in (f'127.0.0.1:{PORT}', f'localhost:{PORT}', f'[::1]:{PORT}'):
            return False
        origin = (self.headers.get('Origin') or '').rstrip('/').lower()
        if origin and origin not in (f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}'):
            return False
        return (self.headers.get('Sec-Fetch-Site') or '').lower() != 'cross-site'

    def send(self, code, body, ctype):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.local_ok():
            self.send(403, b'forbidden', 'text/plain'); return
        if urllib.parse.urlsplit(self.path).path == '/remote/key':          # only the control page on this Mac may set the key
            n = int(self.headers.get('Content-Length') or 0)
            key = (self.rfile.read(n) if n else b'').decode('utf-8', 'replace').strip()
            if not re.fullmatch(r'sk-[A-Za-z0-9_\-]{20,}', key):
                self.send(400, b'{"ok": false, "error": "That does not look like an OpenAI key (it starts with sk-)."}', 'application/json'); return
            env = Path(CONFIG['openai_key_file'])
            env.parent.mkdir(parents=True, exist_ok=True)
            lines = [l for l in (env.read_text().splitlines() if env.exists() else []) if not l.startswith('OPENAI_API_KEY=')]
            env.write_text('\n'.join(lines + ['OPENAI_API_KEY=' + key]) + '\n'); os.chmod(env, 0o600)
            self.send(200, b'{"ok": true}', 'application/json'); return
        n = int(self.headers.get('Content-Length') or 0)
        try:
            body = json.loads(self.rfile.read(n) or b'{}')
        except ValueError:
            self.send(400, b'bad json', 'text/plain'); return
        if urllib.parse.urlsplit(self.path).path == '/touch-raw':
            self.send(200, json.dumps(touch_raw(body)).encode(), 'application/json'); return
        if urllib.parse.urlsplit(self.path).path == '/cook':
            with lock:
                img = str(body.get('image') or '')
                state['cook'] = {'title': str(body.get('title', ''))[:80], 'meta': str(body.get('meta', ''))[:60],
                                 'ingredients': [str(x)[:90] for x in (body.get('ingredients') or [])][:20],
                                 'steps': [{'text': str(x.get('text', ''))[:260], 'mins': int(x.get('mins') or 0)} for x in (body.get('steps') or [])][:12],
                                 'image': img if img.startswith(('https://upload.wikimedia.org/', 'https://thumb.wikimedia.org/')) else '',
                                 'view': 'overview', 'step': 0, 'at': time.time()}
                state['detail'] = ('cook', time.time() + 3 * 3600)
                state['awake_until'] = time.time() + WAKE_SECONDS
            threading.Thread(target=render_once, daemon=True).start()
            self.send(200, b'{"ok":true}', 'application/json')
        elif urllib.parse.urlsplit(self.path).path == '/muse-page':
            secs = max(10, min(300, float(body.get('seconds') or 60)))
            with lock:
                img = str(body.get('image') or '')
                state['muse_page'] = {'question': str(body.get('question', ''))[:200], 'md': str(body.get('md', ''))[:4000], 'at': time.time(),
                                      'image': img if img.startswith(('https://upload.wikimedia.org/', 'https://thumb.wikimedia.org/')) else '', 'source': str(body.get('source') or '')[:40]}
                state['detail'] = ('muse', time.time() + secs)
                state['awake_until'] = time.time() + WAKE_SECONDS
            threading.Thread(target=render_once, daemon=True).start()
            self.send(200, b'{"ok":true}', 'application/json')
        else:
            self.send(404, b'not found', 'text/plain')

    def do_GET(self):
        if not self.local_ok():
            self.send(403, b'forbidden', 'text/plain'); return
        u = urllib.parse.urlsplit(self.path); path = u.path; q = urllib.parse.parse_qs(u.query)
        if path == '/':
            self.send(200, (STATIC / 'index.html').read_bytes(), 'text/html; charset=utf-8')
        elif path in ('/faces.css', '/faces.js', '/icons.js'):
            self.send(200, (STATIC / path[1:]).read_bytes(), 'text/css' if path.endswith('css') else 'text/javascript')
        elif path == '/api/data':
            self.send(200, json.dumps(data()).encode(), 'application/json')
        elif path.startswith('/photo/'):
            name = Path(urllib.parse.unquote(path[7:])).name
            p = DEMO_DIR / name[5:] if name.startswith('demo-') else PHOTOS / name
            if p.exists():
                self.send(200, p.read_bytes(), 'image/jpeg')
            else:
                self.send(404, b'', 'text/plain')
        elif path == '/voice':
            phase = (q.get('phase') or ['idle'])[0]; text = (q.get('text') or [''])[0]
            with lock:
                state['voice'] = None if phase == 'idle' else (phase, text[:160], time.time())
                if is_night(): state['awake_until'] = time.time() + WAKE_SECONDS
            self.send(200, b'{"ok":true}', 'application/json')
        elif path == '/music':
            cmd = (q.get('cmd') or [''])[0]; val = float(q['value'][0]) if q.get('value') else None
            res = spotify_cmd(cmd, val) if music.get('spotify') else {'ok': False, 'error': 'Spotify is not open'}
            if not res.get('ok') and cmd in ('play', 'pause', 'toggle', 'next', 'previous'):
                home = home_state() or {}
                md = [m for m in home.get('media', []) if m.get('available')]
                if md:
                    res = ha_do('media', (sorted(md, key=lambda m: m.get('state') != 'playing')[0])['id'], {'toggle': 'play_pause'}.get(cmd, cmd))
            self.send(200, json.dumps(res).encode(), 'application/json')
        elif path == '/now-playing':
            self.send(200, json.dumps(state.get('playing') or music.get('spotify') or {}).encode(), 'application/json')
        elif path == '/show':      # local voice commands
            if (q.get('face') or ['home'])[0] == 'home':
                door['until'] = 0; door['live_until'] = 0      # "close it" also closes the Front Door card
            res = run_job({'kind': 'show', 'params': {'face': (q.get('face') or ['home'])[0], 'seconds': float((q.get('seconds') or [DETAIL_SECONDS])[0])}})
            self.send(200, json.dumps(res).encode(), 'application/json')
        elif path == '/remote':
            self.send(200, (STATIC / 'remote.html').read_bytes(), 'text/html; charset=utf-8')
        elif path == '/remote/state':
            self.send(200, json.dumps(remote_state()).encode(), 'application/json')
        elif path == '/remote/set':
            self.send(200, json.dumps(remote_set(q)).encode(), 'application/json')
        elif path == '/remote/shot.jpg' and (OUT / 'shot.jpg').exists():
            self.send(200, (OUT / 'shot.jpg').read_bytes(), 'image/jpeg')
        elif path == '/control':
            p = {'type': (q.get('type') or [''])[0], 'id': (q.get('id') or [''])[0], 'action': (q.get('action') or [''])[0]}
            if q.get('value'): p['value'] = float(q['value'][0])
            self.send(200, json.dumps(run_job({'kind': 'control', 'params': p})).encode(), 'application/json')
        elif path == '/home-state':      # the configured devices, for the voice service
            self.send(200, json.dumps(home_state() or {}).encode(), 'application/json')
        elif path == '/say-banner':
            self.send(200, json.dumps(run_job({'kind': 'message', 'params': {'text': (q.get('text') or [''])[0], 'seconds': 20}})).encode(), 'application/json')
        elif path == '/hv.json' and (OUT / 'shot.json').exists():
            self.send(200, (OUT / 'shot.json').read_bytes(), 'application/json')
        elif path.startswith('/mask/'):
            p = MASKS / (Path(urllib.parse.unquote(path[6:])).name + '.mask.png')
            self.send(*((200, p.read_bytes(), 'image/png') if p.exists() else (404, b'', 'text/plain')))
        elif path == '/door':          # ?test=1 rings like the doorbell; plain shows the camera; ?close=1 hides the card
            if 'close' in q:
                door['until'] = 0; door['live_until'] = 0; res = {'ok': True}
            elif 'test' in q:
                door_show('Front Door', 'Someone is at the door · ' + datetime.now().strftime('%-I:%M %p'), 30, chime=True, test=True); res = {'ok': True, 'test': True}
            elif not ha_ready():
                res = {'ok': False, 'reason': 'no_token'}
            else:
                if not door['camera']:
                    try: door_discover()
                    except Exception as e: door['error'] = str(e)[:120]
                if door['camera']:
                    door_show('Front Door', 'Camera · ' + datetime.now().strftime('%-I:%M %p'), 30, live=30); res = {'ok': True}
                else:
                    res = {'ok': False, 'reason': 'no_camera', 'error': door['error']}
            res.update(event=door['event'], camera=door['camera'], last=door['last'])
            self.send(200, json.dumps(res).encode(), 'application/json')
        elif path == '/touch-cal':
            self.send(200, json.dumps(touch_calibrate()).encode(), 'application/json')
        elif path == '/touch-snap':      # one camera frame, for checking where the webcam points
            before = TOUCH_FRAME.stat().st_mtime if TOUCH_FRAME.exists() else 0
            touch['snap'] = True
            for _ in range(30):
                time.sleep(0.1)
                if TOUCH_FRAME.exists() and TOUCH_FRAME.stat().st_mtime > before: break
            time.sleep(0.2)
            self.send(*((200, TOUCH_FRAME.read_bytes(), 'image/jpeg') if TOUCH_FRAME.exists() else (404, b'', 'text/plain')))
        elif path == '/touch.txt':       # the iMac polls this ~30 times a second and draws the cursor itself
            touch['polls'] = [t for t in touch.get('polls', []) if time.time() - t < 2] + [time.time()]
            if touch_active() and touch['cal'] in (None, 'finger'):
                tx, ty = touch['p']; rp = touch['ripple']
                body = '1 %d %d %.2f %d' % (tx * RENDER_W / DESIGN_W, ty * RENDER / DESIGN, touch_progress(), 1 if rp and time.time() - rp[1] < 0.45 else 0)
            else:
                body = '0'
            self.send(200, body.encode(), 'text/plain')
        elif path == '/touch-state':
            self.send(200, json.dumps({'calibrated': bool(touch['H']), 'camera_seen': round(time.time() - touch['cam_at'], 1), 'finger': touch['p'],
                                       'fps': round(len(touch['frames']) / 2.0, 1), 'cal': touch['cal'], 'cal_target': touch.get('cal_target'), 'imac_polls_per_s': round(len([t for t in touch.get('polls', []) if time.time() - t < 2]) / 2.0, 1),
                                       'message': touch['cal_msg']}).encode(), 'application/json')
        elif path == '/demo':
            if 'free' in q:
                with lock:
                    state['demo'] = {'mode': 'free', 'start': time.time()}; state['detail'] = None
                threading.Thread(target=render_once, daemon=True).start()
                self.send(200, b'{"ok": true, "mode": "free"}', 'application/json')
            elif 'cmd' in q:
                self.send(200, json.dumps(demo_cmd(q['cmd'][0], (q.get('face') or [None])[0])).encode(), 'application/json')
            else:
                self.send(200, json.dumps(start_demo(stop='stop' in q, broll='broll' in q)).encode(), 'application/json')
        elif path.startswith('/demo/'):
            f = DEMO_DIR / Path(urllib.parse.unquote(path[6:])).name
            self.send(*((200, f.read_bytes(), 'image/jpeg') if f.suffix == '.jpg' and f.exists() else (404, b'', 'text/plain')))
        elif path == '/cook':
            self.send(200, json.dumps(cook_cmd((q.get('cmd') or [''])[0])).encode(), 'application/json')
        elif path == '/announce':
            self.send(200, json.dumps(announce((q.get('text') or [''])[0])).encode(), 'application/json')
        elif path.startswith('/cam/'):
            f = CAM_DIR / Path(urllib.parse.unquote(path[5:])).name
            self.send(*((200, f.read_bytes(), 'image/jpeg') if f.suffix == '.jpg' and f.exists() else (404, b'', 'text/plain')))
        elif path.startswith('/sart/'):
            f = ART_DIR / Path(urllib.parse.unquote(path[6:])).name
            self.send(*((200, f.read_bytes(), 'image/jpeg') if f.suffix == '.jpg' and f.exists() else (404, b'', 'text/plain')))
        elif path == '/ov.json' and (OUT / 'ov.json').exists():
            self.send(200, (OUT / 'ov.json').read_bytes(), 'application/json')
        elif path.startswith('/ov/'):
            p = OV_DIR / (Path(path).stem + '.png')
            self.send(*((200, p.read_bytes(), 'image/png') if p.exists() else (404, b'', 'text/plain')))
        elif path == '/shot.jpg' and (OUT / 'shot.jpg').exists():
            self.send(200, (OUT / 'shot.jpg').read_bytes(), 'image/jpeg')
        elif path == '/shot.png' and (OUT / 'shot.png').exists():
            self.send(200, (OUT / 'shot.png').read_bytes(), 'image/png')
        elif path == '/tap':
            # x, y arrive in 768-px render coordinates
            try:
                x = float(q['x'][0]) * DESIGN_W / RENDER_W; y = float(q['y'][0]) * DESIGN / RENDER
                self.send(200, json.dumps({'result': tap(x, y)}).encode(), 'application/json')
            except Exception as e:
                self.send(400, str(e).encode(), 'text/plain')
        else:
            self.send(404, b'not found', 'text/plain')


if __name__ == '__main__':
    import sys
    DATA.mkdir(parents=True, exist_ok=True); OUT.mkdir(exist_ok=True)
    srv = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    srv.daemon_threads = True
    if '--no-render' not in sys.argv:
        threading.Thread(target=render_loop, daemon=True).start()
    threading.Thread(target=home_loop, daemon=True).start()
    threading.Thread(target=overlay_loop, daemon=True).start()
    threading.Thread(target=spotify_loop, daemon=True).start()
    threading.Thread(target=calendar_keeper, daemon=True).start()
    threading.Thread(target=door_loop, daemon=True).start()
    threading.Thread(target=cam_loop, daemon=True).start()
    threading.Thread(target=touch_keeper, daemon=True).start()
    print(f'HomeView dashboard on http://127.0.0.1:{PORT}/  (control page: http://127.0.0.1:{PORT}/remote)', flush=True)
    srv.serve_forever()
