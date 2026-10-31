"""Fast local understanding of home and screen commands, so they run instantly instead of going to the AI.

parse(text, home) -> None (not a local command: ask the AI) or a dict:
  {'kind': 'show', 'face': ..., 'say': ...}
  {'kind': 'control', 'targets': [device rows], 'action': ..., 'value': ..., 'what': spoken name}
  {'kind': 'say', 'say': ...}       (answered locally: time, weather)
  {'kind': 'unknown_device', 'what': ...}
"""
import difflib, re
from datetime import datetime

NUM = {'zero': 0, 'ten': 10, 'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50, 'sixty': 60, 'seventy': 70, 'eighty': 80,
       'ninety': 90, 'hundred': 100, 'one hundred': 100, 'half': 50, 'full': 100, 'max': 100, 'all the way': 100}
GROUPS = {'light': 'lights', 'fan': 'fans', 'scene': 'scenes', 'shade': 'covers', 'media': 'media'}


def clean(t):
    t = t.lower().replace('’', "'")
    t = re.sub(r"[^a-z0-9%' ]+", ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    for _ in range(3):
        t = re.sub(r"^(please|can you|could you|would you|will you|hey|ok|okay|muse|i want you to|go ahead and|just)\b\s*", '', t)
    t = re.sub(r'\s*\b(please|for me|now|right now|thanks|thank you)$', '', t)
    return t.strip()


def devices(home):
    out = []
    for kind, group in GROUPS.items():
        for r in (home or {}).get(group) or []:
            out.append(dict(r, kind=kind))
    return out


def resolve(x, home, kinds):
    """Device rows the phrase x refers to (may include offline ones)."""
    x = re.sub(r"\b(the|my|our|all|of|in|room)\b", ' ', x)
    x = re.sub(r'\s+', ' ', x).strip()
    devs = [d for d in devices(home) if d['kind'] in kinds]
    if not x or x in ('lights', 'light', 'everything', 'lamps'):
        return [d for d in devs if d['kind'] == 'light']
    rooms = sorted({(d.get('room') or '').lower() for d in devs if d.get('room')}, key=len, reverse=True)
    words = x.split()
    plural = bool(re.search(r'\b(lights|lamps|shades|blinds)\b', x))
    nm = lambda d: (d.get('name') or '').lower().replace('’', "'")
    # 1) exact name, 2) the longest device name contained in the phrase, 3) a phrase whose words all appear in one device's name
    for d in devs:
        if nm(d) == x:
            return [d]
    if not plural:
        inside = sorted([d for d in devs if len(nm(d)) > 3 and nm(d) in x], key=lambda d: -len(nm(d)))
        if inside:
            return [inside[0]]
    GENERIC = {'light', 'lights', 'lamp', 'lamps'}
    key = [w for w in words if w not in GENERIC]
    if key:
        allw = [d for d in devs if all(w.rstrip('s') in nm(d) + ' ' + (d.get('id') or '') for w in key)]
        if len(allw) > 1 and not plural:
            typed = [d for d in allw if d['kind'] in words or d['kind'] + 's' in words]
            allw = typed if len(typed) == 1 else allw
        if len(allw) == 1 or (allw and plural):
            return allw
    for room in rooms:
        if room and room in x:
            rest = x.replace(room, ' ').strip()
            inroom = [d for d in devs if (d.get('room') or '').lower() == room]
            if not rest or rest in ('lights', 'light', 'lamps'):
                return [d for d in inroom if d['kind'] == 'light'] or inroom
            hits = [d for d in inroom if any(w.rstrip('s') in (d.get('name') or '').lower() for w in rest.split())]
            if hits:
                return hits
            return [d for d in inroom if d['kind'] == 'light'] or inroom
    if not key:
        return []
    best, score = None, 0.0
    for d in devs:
        if not any(w.rstrip('s') in (nm(d) + ' ' + (d.get('room') or '').lower()) for w in key):
            continue      # never guess a device that shares no real word with what was said
        for cand in ((d.get('name') or '').lower(), (d.get('id') or '').replace('-', ' '), f"{(d.get('room') or '').lower()} {(d.get('name') or '').lower()}"):
            r = difflib.SequenceMatcher(None, x, cand).ratio()
            if r > score:
                best, score = d, r
    if best and score >= 0.7:
        return [best]
    return []


def spoken(targets, fallback):
    if len(targets) == 1:
        return targets[0].get('name') or fallback
    return fallback


def parse(text, home, weather=None):
    t = clean(text)
    if not t:
        return None
    wx = weather or {}
    # ---- screens ----
    if re.fullmatch(r"(go |go back |back |take me |show )?(home|to home|the home screen|home screen|main screen)|close( it| that| this| the weather| weather)?|go back|never mind|nevermind|dismiss( it)?", t):
        return {'kind': 'show', 'face': 'home', 'say': None}
    if re.search(r'\b(weather|forecast|rain|temperature)\b', t) and not re.search(r'\b(turn|switch|light|lamp)\b', t):
        if re.search(r"^(what|what's|whats|how|how's|hows|is it|will it|is there|do i need)\b", t):
            if re.search(r"\b(jacket|coat|umbrella|wear|shorts|should|weekend|week|tonight|later|hour|sunset|sunrise|snow|wind)\b", t):
                return {'kind': 'show', 'face': 'weather', 'ask_muse': True}      # needs judgment: the AI answers from the forecast
            return {'kind': 'show', 'face': 'weather', 'wx_say': 'tomorrow' if 'tomorrow' in t else 'today'}   # instant, from the forecast
        return {'kind': 'show', 'face': 'weather', 'say': None}
    if re.fullmatch(r"(go to |switch to |turn on |show |show me |start |use )?(the )?(night|red|sleep|bedside)( mode| screen| clock| view)?", t) and re.search(r'\b(night|red|sleep|bedside)\b', t):
        return {'kind': 'show', 'face': 'night', 'say': None}
    if re.fullmatch(r"(show( me)?|open|see)( my| the)? (photos?|pictures?|pics)", t):
        return {'kind': 'show', 'face': 'photo', 'say': None}
    if re.search(r'\b(photo|picture|pic|photos|pictures)\b', t) and re.search(r'\b(next|another|new|change|different|show|open|shuffle)\b', t):
        return {'kind': 'show', 'face': 'next_photo', 'say': None}
    SHOW = r"^(show|open|go to|bring up|pull up|switch to|display|put up|let me see|see)( me)?( the| my)? "
    if re.search(SHOW + r"(lyrics|words|song lyrics)\b", t) or t in ('lyrics', 'show lyrics', 'sing along'):
        return {'kind': 'show', 'face': 'lyrics', 'say': None}
    if re.search(SHOW + r"(calendar|month|calendar face)\b", t):
        return {'kind': 'show', 'face': 'calendar', 'say': None}
    if re.search(SHOW + r"(flow|flow clock|flow face|colorful clock|big clock)\b", t):
        return {'kind': 'show', 'face': 'flow', 'say': None}
    if re.search(SHOW + r"(cameras?|camera feeds?|security cameras?)\b", t):
        return {'kind': 'show', 'face': 'cameras', 'say': None}
    if re.search(SHOW + r"(home screen|apps|app screen|launcher|greeting)\b", t):
        return {'kind': 'show', 'face': 'apps', 'say': None}
    if re.search(SHOW + r"(now playing|music player|player)\b", t):
        return {'kind': 'show', 'face': 'nowplaying', 'say': None}
    if re.search(SHOW + r"(lights|light grid|devices|home grid|accessories)\b", t):
        return {'kind': 'show', 'face': 'grid', 'say': None}

    # ---- camera touch ----
    if re.search(r"\b(calibrate|recalibrate|set up|setup|line up)\b.*\b(touch|screen|camera|touchscreen)\b", t):
        return {'kind': 'touch_cal'}

    # ---- demo tour ----
    if re.fullmatch(r"(start |run |begin |turn on |go into |enter )?(the |a )?demo( mode)?", t):
        return {'kind': 'demo'}
    if re.fullmatch(r"show (me )?(off|what you can do)|what can you do|give me a tour|show me (a )?tour|(start |run )?(the |a )?demo tour", t):
        return {'kind': 'demo', 'tour': True}
    if re.fullmatch(r"(start |run |begin |turn on |go into |enter |use )?(the )?(demo info|demo data|free demo|full demo|open demo)( mode)?", t):
        return {'kind': 'demo', 'free': True}
    if re.fullmatch(r"(start |run |begin |turn on |go into |enter )?(the )?(b[ -]?roll|be roll|slow demo|screensaver)( mode| demo)?", t):
        return {'kind': 'demo', 'broll': True}
    if re.fullmatch(r"(stop|end|exit|cancel|turn off|quit) (the )?demo( mode)?", t):
        return {'kind': 'demo', 'stop': True}

    # ---- cooking ----
    m = re.fullmatch(r"(?:(?:let'?s|lets|let us|i want to|help me|i'm going to|im going to|we're going to) (?:cook|make|bake)|cook|bake) (?:some |a |an |the )?(?P<d>.+?)(?: tonight| for dinner| for lunch| today)?|"
                     r"(?:how (?:do|can|should) (?:i|you|we) (?:make|cook|bake)|(?:give me |show me |find |find me )?(?:a )?recipe for) (?:some |a |an |the )?(?P<d2>.+?)(?: tonight| for dinner)?", t)
    dish = m and (m.group('d') or m.group('d2') or '')
    if dish and not re.search(r"\b(list|call|note|reminder|reservation|appointment|payment|plan|decision|timer|it|that|this|sure|time|money|video|post|email|announcement)\b", dish):
        return {'kind': 'cook', 'dish': dish}

    # ---- intercom announcements ----
    m = re.match(r"(make an announcement|announce|broadcast|intercom|tell everyone|tell the house|tell the whole house)( that| to everyone| to the house)?\s*[,:]?\s*(?P<msg>.+)", t)
    if m and len(m.group('msg').split()) >= 1:
        return {'kind': 'announce', 'text': m.group('msg')}

    # ---- doorbell camera ----
    if re.search(r"\b(door ?bell|front door|porch|door camera|at the door|front step|front steps)\b", t) and not re.search(r'\b(lock|unlock|light|lights|lamp)\b', t):
        return {'kind': 'door'}

    # ---- scenes (any scene in config.json, by name: "movie time", "activate goodnight", "goodnight scene") ----
    scenes = [d for d in devices(home) if d['kind'] == 'scene']
    m = re.fullmatch(r"(activate |run |start |turn on |set |do |it's |its |time for )?(the )?(?P<x>.+?)( scene| mode| time)?", t)
    if m and scenes:
        x = m.group('x').replace(' ', '')
        sc = [d for d in scenes if (d.get('name') or '').lower().replace(' ', '') == x]
        if sc and (m.group(1) or m.group(4) or t == (sc[0].get('name') or '').lower()):
            return {'kind': 'control', 'targets': sc, 'action': 'activate', 'value': None, 'what': sc[0].get('name') + ' scene'}
    # ---- shades ----
    m = re.fullmatch(r"(open|close|raise|lower|shut)( up| down)? (the )?(?P<x>.*?)\b(shades|shade|blinds|blind|curtains)( up| down)?", t)
    if m:
        act = 'open' if m.group(1) in ('open', 'raise') else 'close'
        x = (m.group('x') or '').strip()
        shades = [d for d in devices(home) if d['kind'] == 'shade']
        tg = [d for d in shades if (d.get('room') or '').lower() in x] if x else []
        tg = tg or (shades if not x or x in ('the', 'all', 'all the') else resolve(x + ' shades', home, ('shade',)))
        return {'kind': 'control', 'targets': tg, 'action': act, 'value': None, 'what': 'the shades'}
    # ---- brightness / fan speed ----
    m = re.fullmatch(r"(dim|set|turn|brighten|make|put) (the )?(?P<x>.+?) (to|at) (?P<n>\d{1,3}|" + '|'.join(NUM) + r")( ?%| percent)?( brightness)?", t)
    if m:
        n = m.group('n'); val = int(n) if n.isdigit() else NUM[n]
        tg = resolve(m.group('x'), home, ('light', 'fan'))
        if not tg:
            return {'kind': 'unknown_device', 'what': m.group('x')}
        act = 'speed' if tg[0]['kind'] == 'fan' else 'brightness'
        return {'kind': 'control', 'targets': tg, 'action': act, 'value': max(0, min(100, val)), 'what': spoken(tg, m.group('x'))}
    # ---- on / off ----
    m = (re.fullmatch(r"(turn|switch|shut|put|flip) (?P<a>on|off) (the )?(?P<x>.+)", t) or
         re.fullmatch(r"(turn|switch|shut|put|flip) (the )?(?P<x>.+?) (?P<a>on|off|out)", t) or
         re.fullmatch(r"(?P<a>lights) (?P<b>on|off)", t) or
         re.fullmatch(r"(the )?(?P<x>.+?) (?P<a>on|off)", t))
    if m:
        gd = m.groupdict()
        if gd.get('b'):
            a, x = gd['b'], 'lights'
        else:
            a, x = gd['a'], gd.get('x') or 'lights'
        a = 'off' if a == 'out' else a
        tg = resolve(x, home, ('light', 'fan'))
        if not tg:
            return {'kind': 'unknown_device', 'what': x} if m.re.pattern.startswith('(turn') else None
        return {'kind': 'control', 'targets': tg, 'action': a, 'value': None, 'what': spoken(tg, re.sub(r'^(the|my) ', '', x))}
    # ---- music (Spotify on the Mac first, then a Home Assistant speaker) ----
    if re.fullmatch(r"(what'?s|what is|who'?s|who is)( this| that)?( song| playing| track| singing| this song)?( right now)?|what song is this|what'?s playing", t):
        return {'kind': 'music', 'cmd': 'what'}
    pm = re.fullmatch(r"(press|hit|tap|push|start|resume) (play|pause)|(start|resume|turn on|put on) (the |some )?(music|spotify|songs?)", t)
    if pm:
        return {'kind': 'music', 'cmd': 'pause' if pm.group(2) == 'pause' else 'play'}
    m = re.fullmatch(r"(pause|stop|resume|play|unpause|skip|next|previous|go back|back)( the| this)?( music| song| track| spotify| it)?( please)?", t)
    if m:
        verb = {'pause': 'pause', 'stop': 'pause', 'resume': 'play', 'unpause': 'play', 'play': 'play', 'skip': 'next', 'next': 'next', 'previous': 'previous', 'go back': 'previous', 'back': 'previous'}[m.group(1)]
        return {'kind': 'music', 'cmd': verb}
    if re.fullmatch(r"(next|skip)( this)? (song|track)|play the next (song|track)|skip (it|this)", t):
        return {'kind': 'music', 'cmd': 'next'}
    if re.search(r'\b(turn it|turn the music|turn the volume|volume|music)\b.*\b(up|louder)\b|\blouder\b', t):
        return {'kind': 'music', 'cmd': 'louder'}
    if re.search(r'\b(turn it|turn the music|turn the volume|volume|music)\b.*\b(down|quieter|lower)\b|\bquieter\b', t):
        return {'kind': 'music', 'cmd': 'quieter'}
    m = re.search(r'\b(set|turn|put)?\s*(the )?(volume|music) (to|at) (\d{1,3})( ?%| percent)?', t)
    if m:
        return {'kind': 'music', 'cmd': 'volume', 'value': int(m.group(5))}
    if re.search(r'\b(show|open)\b.*\b(now playing|music|what.?s playing|spotify)\b', t):
        return {'kind': 'show', 'face': 'nowplaying', 'say': None}
    m = re.fullmatch(r"(?:can you |could you |please )?(?:play|put on|queue up|listen to) (?:me )?(?:the song |the track |some )?(?P<q>.+?)(?: on spotify| please| for me)?", t)
    if m and m.group('q') not in ('music', 'it', 'the music', 'something', 'again', 'a song', 'songs', 'spotify'):
        return {'kind': 'play_song', 'q': m.group('q')}            # "play <song> by <artist>": find it on Spotify and play it
    return None


# ---------------- timers and the morning brief ----------------
ONES = {'zero': 0, 'one': 1, 'a': 1, 'an': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9,
        'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15, 'sixteen': 16, 'seventeen': 17,
        'eighteen': 18, 'nineteen': 19, 'couple': 2, 'few': 3}
TENS = {'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50, 'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90}
NUMWORD = r"(?:\d+(?:\.\d+)?|(?:%s)(?:[ -](?:%s))?|%s|a couple of|a few)" % ('|'.join(TENS), '|'.join(k for k in ONES if k not in ('a', 'an')), '|'.join(ONES))
UNIT = {'h': 3600, 'm': 60, 's': 1}


def words_num(w):
    w = w.strip().replace('-', ' ').replace('a couple of', 'couple').replace('a few', 'few')
    try:
        return float(w)
    except ValueError:
        pass
    total = 0
    for part in w.split():
        if part in TENS: total += TENS[part]
        elif part in ONES: total += ONES[part]
        else: return None
    return total


def duration(t):
    """Seconds in phrases like '10 minutes', 'an hour and a half', 'two minutes thirty seconds', 'half an hour'."""
    t = ' ' + t + ' '
    if re.search(r'\bhalf an hour\b|\ba half hour\b', t):
        return 1800
    total = 0
    for m in re.finditer(r'\b(%s) (hours?|hrs?|minutes?|mins?|seconds?|secs?)\b( and a half)?' % NUMWORD, t):
        n = words_num(m.group(1))
        if n is None:
            continue
        unit = UNIT[m.group(2)[0]]
        total += n * unit + (unit / 2 if m.group(3) else 0)
    if not total and re.search(r'\b(\d+|%s) ?(minute|min)\b' % NUMWORD, t):
        m = re.search(r'\b(%s) ?(minute|min)' % NUMWORD, t); n = words_num(m.group(1)); total = (n or 0) * 60
    return int(total) if total else None


def parse_extra(text):
    """Timers and the brief. Returns None when the phrase is about something else."""
    t = clean(text)
    if not t:
        return None
    if re.fullmatch(r"(good morning|morning|morning brief|brief me|my brief|daily brief|what's my day( look like)?|whats my day( look like)?|"
                    r"what does my day look like|what's (on )?(for )?today|what's happening today|give me (my|the|a) (brief|rundown|update)|catch me up)", t):
        return {'kind': 'brief'}
    if re.search(r'\b(cancel|stop|delete|clear|end|remove|turn off|kill)\b.*\b(timers?|alarm)\b', t) or t in ('cancel the timer', 'cancel timer', 'stop timer'):
        return {'kind': 'timer_cancel', 'all': bool(re.search(r'\ball\b', t))}
    if re.search(r"\bhow (much time|long)\b.*\b(left|remaining|timer)\b|\btime left\b|\bhow'?s (my|the) timer\b|\bwhat'?s left on\b", t):
        return {'kind': 'timer_query'}
    if re.search(r'\btimer\b', t) or re.search(r'\b(remind me|alarm) in\b', t):
        secs = duration(t)
        if secs:
            lab = re.search(r'\b(?:for|called|named) (?:the |my )?(?P<l>[a-z][a-z ]*)$', t)
            label = lab.group('l').strip() if lab and not duration(lab.group('l')) and not re.search(r'\b(hours?|minutes?|mins?|seconds?|secs?|half)\b', lab.group('l')) else ''
            return {'kind': 'timer_set', 'seconds': secs, 'label': label}
        if re.search(r'\b(set|start|make)\b', t):
            return {'kind': 'say', 'say': 'How long should the timer be?'}
    return None
