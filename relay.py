"""The only service the iMac G4 talks to: a tiny HTTP relay on the Mac's Ethernet side.

The dashboard (server.py) and the voice service (voice/voice.py) listen on 127.0.0.1 only. This relay listens on
relay_bind (all interfaces unless you set one) and passes the viewer's requests through to them. Only addresses in
relay_allowed_networks (by default link-local 169.254.x.x, which a direct Ethernet cable uses, and this Mac) may connect;
everyone else gets 403.

It also serves a plain fallback page at / that Safari on the G4 can show without Java (the screen refreshes every
10 seconds and clicks become taps).
"""
import http.server, ipaddress, os, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from homeview_config import CONFIG

PORT = CONFIG['ports']['relay']
DASH = 'http://127.0.0.1:%d' % CONFIG['ports']['dashboard']
VOICE = 'http://127.0.0.1:%d' % CONFIG['ports']['voice']
ALLOWED = [ipaddress.ip_network(n) for n in CONFIG['relay_allowed_networks']]
PAGE = b"""<html><head><title>HomeView</title>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<style>html,body{margin:0;padding:0;background:#000;overflow:hidden}
#face{position:absolute;left:50%;top:0;width:1024px;height:768px;margin-left:-512px;border:0}
a img{border:0} iframe{position:absolute;left:-10px;top:-10px;width:1px;height:1px;border:0}</style>
<script type="text/javascript">
function fit(){try{window.moveTo(0,0);window.resizeTo(screen.width,screen.height);}catch(e){}}
function refresh(){var n=new Image();n.onload=function(){document.getElementById('face').src=n.src;};n.src='/hv.jpg?t='+(new Date()).getTime();}
function tapped(){setTimeout(refresh,1500);setTimeout(refresh,4000);}
window.onload=function(){fit();refresh();setInterval(refresh,10000);};
</script></head><body>
<a href="/hvtap" target="tapframe" onclick="tapped()"><img id="face" ismap src="" alt=""></a>
<iframe name="tapframe" src="about:blank"></iframe>
</body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'HomeViewRelay/1.0'
    VOICE_PATHS = ('/audio', '/voice-state', '/reply.wav', '/voice-done')
    DASH_PATHS = {'/hv.json': '/hv.json', '/hv.png': '/shot.png', '/hv.jpg': '/shot.jpg', '/touch.txt': None, '/ov.json': None}

    def log_message(self, fmt, *args):
        pass

    def allowed(self):
        try:
            client = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        return any(client in n for n in ALLOWED)

    def reply(self, body, ctype):
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.end_headers()
        self.wfile.write(body)

    def fetch(self, url, method='GET', body=b'', timeout=5):
        req = urllib.request.Request(url, data=body if method == 'POST' else None, method=method,
                                     headers={'Content-Type': self.headers.get('Content-Type') or 'application/octet-stream'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), r.headers.get('Content-Type', 'application/octet-stream')

    def do_POST(self):
        if not self.allowed():
            self.send_error(403); return
        path = self.path.split('?', 1)[0]
        n = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(n) if n else b''
        if path not in self.VOICE_PATHS:
            self.send_error(404); return
        try:
            self.reply(*self.fetch(VOICE + self.path, 'POST', body, timeout=15))
        except Exception:
            self.send_error(503)

    def do_GET(self):
        if not self.allowed():
            self.send_error(403); return
        path = self.path.split('?', 1)[0]
        try:
            if path in ('/', '/index.html'):
                self.reply(PAGE, 'text/html; charset=utf-8')
            elif path in self.VOICE_PATHS:
                self.reply(*self.fetch(VOICE + self.path, timeout=15))
            elif path in self.DASH_PATHS:
                self.reply(*self.fetch(DASH + (self.DASH_PATHS[path] or self.path)))
            elif path.startswith('/ov/'):
                self.reply(*self.fetch(DASH + self.path))
            elif path == '/hvtap':
                # The viewer (and Safari's ismap) sends '/hvtap?x,y' in 1024x768 screen coordinates
                q = self.path.split('?', 1)[1] if '?' in self.path else ''
                try:
                    x, y = [int(v) for v in q.split(',')[:2]]
                    body = self.fetch(DASH + '/tap?x=%d&y=%d' % (x, y), timeout=20)[0]
                except Exception as e:
                    body = ('{"error": "%s"}' % type(e).__name__).encode()
                self.reply(body, 'text/plain')
            elif path == '/time':      # UTC as MMDDhhmmYYYY.ss, handy for setting the G4's clock with `date`
                self.reply(time.strftime('%m%d%H%M%Y.%S', time.gmtime()).encode(), 'text/plain')
            else:
                self.send_error(404)
        except Exception:
            self.send_error(503)


if __name__ == '__main__':
    srv = http.server.ThreadingHTTPServer((CONFIG.get('relay_bind') or '0.0.0.0', PORT), Handler)
    srv.daemon_threads = True
    print('HomeView relay on', CONFIG.get('relay_bind') or '0.0.0.0', 'port', PORT, 'for', ', '.join(map(str, ALLOWED)), flush=True)
    srv.serve_forever()
