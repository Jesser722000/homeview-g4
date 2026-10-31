/* HomeView-style faces. Renders one face (from ?face=) from /api/data. Tile geometry matches server.py TILES. */
(function () {
  var W = 'stroke="currentColor" fill="none" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round"';
  var F = 'fill="currentColor"';
  var ICON = {};   // Framework7 Icons / Phosphor / Lucide, from static/icons.js (tools/icons.py)
  ['sun', 'lock', 'ceiling', 'bulb', 'fan', 'house', 'intercom', 'blinds', 'moon', 'film', 'car', 'dollar', 'box', 'football', 'heart',
   'printer', 'cal', 'list', 'chevDown', 'chevUp', 'bell', 'timer', 'camera', 'clock', 'check', 'envelope', 'chat'].forEach(function (n) { ICON[n] = sf(n); });

  var WXN = 0;
  function wxIcon(code, day, size) {
    // Apple-style multicolour weather: Framework7 glyphs layered (yellow sun, white cloud, blue rain, yellow bolt).
    function g(n, color, extra) { var i = SF[n]; return '<g color="' + color + '"' + (extra || '') + '>' + i.g + '</g>'; }
    function split(n, top, bottom, cut) {     // one glyph, cloud part white and precipitation coloured
      var id = 'wxc' + (++WXN);
      return '<defs><clipPath id="' + id + 'a"><rect width="56" height="' + cut + '"/></clipPath><clipPath id="' + id + 'b"><rect y="' + cut + '" width="56" height="' + (56 - cut) + '"/></clipPath></defs>' +
        g(n, top, ' clip-path="url(#' + id + 'a)"') + g(n, bottom, ' clip-path="url(#' + id + 'b)"');
    }
    var body;
    if (code === 0 || code === 1) body = day ? g('wx_sun', '#ffd60a') : g('wx_moonstars', '#fff');
    else if (code === 2) body = (day ? '<g transform="translate(17 -3) scale(.62)">' + g('wx_sun', '#ffd60a') + '</g>' : '<g transform="translate(20 0) scale(.55)">' + g('wx_moon', '#fff') + '</g>') +
      '<g transform="translate(-2 8) scale(.86)">' + g('wx_cloud', '#fff') + '</g>';
    else if (code === 45 || code === 48) body = g('wx_fog', '#fff');
    else if (code >= 51 && code <= 57) body = split('wx_drizzle', '#fff', '#5ac8fa', 37);
    else if (code >= 61 && code <= 67 || code >= 80 && code <= 82) body = split(code === 65 || code === 82 ? 'wx_heavyrain' : 'wx_rain', '#fff', '#5ac8fa', 37);
    else if (code >= 71 && code <= 77 || code === 85 || code === 86) body = g('wx_snow', '#fff');
    else if (code >= 95) body = split('wx_bolt', '#fff', '#ffd60a', 37);
    else body = g('wx_cloud', '#fff');
    return '<svg viewBox="0 0 56 56" width="' + size + '" height="' + size + '">' + body + '</svg>';
  }
  function wxName(code) {
    if (code === 0) return 'Clear'; if (code === 1) return 'Mostly Clear'; if (code === 2) return 'Partly Cloudy'; if (code === 3) return 'Cloudy';
    if (code === 45 || code === 48) return 'Foggy'; if (code >= 51 && code <= 57) return 'Drizzle'; if (code >= 61 && code <= 67) return 'Rain';
    if (code >= 71 && code <= 77) return 'Snow'; if (code >= 80 && code <= 82) return 'Showers'; if (code >= 95) return 'Thunderstorms'; return 'Cloudy';
  }

  // ?nohands=1: the G4 viewer draws the hands itself so they move smoothly.
  var NOHANDS = /nohands=1/.test(location.search);
  function clockSVG(now, light) {
    var h = now.getHours() % 12, m = now.getMinutes(), s = now.getSeconds();
    var face = light ? '#e4e4e9' : 'none', hand = light ? '#1c1c1e' : '#ffffff';
    var out = '<svg viewBox="0 0 300 300"><circle cx="150" cy="150" r="146" fill="' + face + '"/>';
    if (light) {
      for (var i = 0; i < 60; i++) { var a = i * 6 * Math.PI / 180, r1 = i % 5 ? 140 : 133;
        out += '<line x1="' + (150 + r1 * Math.sin(a)).toFixed(1) + '" y1="' + (150 - r1 * Math.cos(a)).toFixed(1) + '" x2="' + (150 + 143 * Math.sin(a)).toFixed(1) + '" y2="' + (150 - 143 * Math.cos(a)).toFixed(1) + '" stroke="' + (i % 5 ? '#cdcae2' : '#7a74ab') + '" stroke-width="' + (i % 5 ? 1.5 : 2.5) + '"/>'; }
      for (var n = 1; n <= 12; n++) { var b = n * 30 * Math.PI / 180;
        out += '<text x="' + (150 + 108 * Math.sin(b)).toFixed(1) + '" y="' + (150 - 108 * Math.cos(b) + 11).toFixed(1) + '" text-anchor="middle" font-size="34" font-weight="500" fill="#57508c" style="font-family:-apple-system,system-ui,sans-serif">' + n + '</text>'; }
    } else {
      for (var j = 0; j < 12; j++) { var c = j * 30 * Math.PI / 180;
        out += '<line x1="' + (150 + 104 * Math.sin(c)).toFixed(1) + '" y1="' + (150 - 104 * Math.cos(c)).toFixed(1) + '" x2="' + (150 + 138 * Math.sin(c)).toFixed(1) + '" y2="' + (150 - 138 * Math.cos(c)).toFixed(1) + '" stroke="#ffffff" stroke-width="7" stroke-linecap="round" opacity="0.95"/>'; }
    }
    if (NOHANDS) return out + '</svg>';
    var ha = (h + m / 60) * 30, ma = (m + s / 60) * 6, sa = s * 6;
    function hand2(len, w, ang) {
      return '<g transform="rotate(' + ang + ' 150 150)"><line x1="150" y1="150" x2="150" y2="132" stroke="' + hand + '" stroke-width="3" stroke-linecap="round"/>' +
        '<line x1="150" y1="132" x2="150" y2="' + (150 - len) + '" stroke="' + hand + '" stroke-width="' + w + '" stroke-linecap="round"/></g>';
    }
    out += hand2(76, light ? 10 : 11, ha) + hand2(137, light ? 8 : 9, ma);
    out += '<line x1="150" y1="174" x2="150" y2="9" stroke="' + (light ? '#6c64b0' : 'rgba(255,255,255,0.9)') + '" stroke-width="3" stroke-linecap="round" transform="rotate(' + sa + ' 150 150)"/>';
    out += light ? '<circle cx="150" cy="150" r="3.5" fill="#fff" stroke="#6c64b0" stroke-width="2"/>' : '<circle cx="150" cy="150" r="6" fill="#fff"/>';
    return out + '</svg>';
  }

  function el(cls, html, style) { return '<div class="' + cls + '"' + (style ? ' style="' + style + '"' : '') + '>' + (html || '') + '</div>'; }
  function find(list, id) { if (!list) return null; for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i]; return null; }
  function hm12(t) { var p = (t || '').split(':'); if (p.length < 2) return t; var h = +p[0]; return ((h % 12) || 12) + ':' + p[1] + (h < 12 ? ' AM' : ' PM'); }
  var CHANGED = {};
  function accTile(pos, icon, name, room, on, id, offline) {
    var cls = 'tile glass acc glass-text ' + pos + (on === false ? ' off' : '') + (offline ? ' offline' : '') + (id && CHANGED[id] ? ' changed' : '');
    return el(cls, el('icon', ICON[icon]) + el('name', esc(name == null ? '' : name)) + el('room', esc(room == null ? '' : room)));
  }
  function homeState(row, kind) {
    if (!row) return 'Not Set Up';
    if (!row.available) return 'No Response';
    if (kind === 'fan') return row.on ? (row.percentage ? row.percentage + '%' : 'On') : 'Off';
    return row.on ? (row.brightness ? row.brightness + '%' : 'On') : 'Off';
  }

  function lightAcc(pos, row, icon, name, room) {
    return accTile(pos, icon, row ? row.name : name, row ? (row.available ? (row.room || room) : 'No Response') : room, row ? !!row.on : false,
      row && row.id, !row || !row.available);
  }
  function sceneAcc(pos, row, icon, name) {
    return accTile(pos, icon, row ? row.name : name, row && row.available ? 'Scene' : 'No Response', row ? !!row.available : false, row && row.id, !row || !row.available);
  }
  function hm(t) { var p = (t || '').split(':'); if (p.length < 2) return t || ''; var h = +p[0]; return ((h % 12) || 12) + (p[1] === '00' ? '' : ':' + p[1]) + (h < 12 ? ' AM' : ' PM'); }
  function upcoming(d) {
    var o = d.info || {}, today = new Date(d.now), iso = today.getFullYear() + '-' + ('0' + (today.getMonth() + 1)).slice(-2) + '-' + ('0' + today.getDate()).slice(-2);
    var nowHM = ('0' + today.getHours()).slice(-2) + ':' + ('0' + today.getMinutes()).slice(-2);
    return { iso: iso, list: (o.calendar || []).filter(function (e) { return e.date > iso || (e.date === iso && (e.all_day || (e.time || '') >= nowHM)); })
      .sort(function (a, b) { return (a.date + a.time) < (b.date + b.time) ? -1 : 1; }) };
  }
  function upNext(d, pos) {
    var u = upcoming(d), ev = u.list[0];
    if (ev) return accTile(pos, 'cal', ev.title.length > 18 ? ev.title.slice(0, 17) + '…' : ev.title, (ev.date === u.iso ? 'Today' : ev.day.split(',')[0]) + ' · ' + (ev.all_day ? 'All Day' : hm(ev.time)), true);
    return accTile(pos, 'cal', 'No Events', 'Calendar', true);
  }
  // The events after the next one, as a wide list widget.
  function comingUp(d, pos) {
    var u = upcoming(d), rows = u.list.slice(1, 4);
    var sub = (d.info || {}).calendar_live === false && !d.demo ? 'Calendar not connected' : rows.length ? u.list.length + ' coming up' : 'Nothing else coming up';
    return el('tile glass glass-text mt-tile ' + pos,
      el('mt-head', '<div class="mt-orb"></div><b>Coming Up</b><span>' + sub + '</span>') +
      rows.map(function (e) {
        var when = (e.date === u.iso ? '' : e.day.split(',')[0] + ' ') + (e.all_day ? 'All Day' : hm(e.time));
        return el('mt-row ' + (e.date === u.iso ? 'run' : 'idle'), '<i></i><span>' + esc(e.title) + '</span><em>' + when + '</em>');
      }).join('') +
      (rows.length ? '' : el('mt-none', 'Say “' + esc(d.wake || 'Hey Apple') + ', what’s on my calendar?”')));
  }
  // One Home Assistant device (the first in config.json): tap to toggle. Without one, it opens the Lights screen.
  function homeTile(d, pos) {
    var g = (d.grid || [])[0];
    if (!g) return accTile(pos, 'house', 'Home', 'Not set up', false);
    var icon = { light: 'bulb', fan: 'fan', scene: 'sun', shade: 'blinds', media: 'intercom' }[g.kind] || 'house';
    var st = !g.available ? 'No Response' : g.kind === 'scene' ? 'Scene' : g.kind === 'shade' ? (g.state || '') : g.kind === 'media' ? (g.state || '') : g.on ? (g.brightness ? g.brightness + '%' : 'On') : 'Off';
    return accTile(pos, icon, g.name, (g.room ? g.room + ' · ' : '') + st, g.kind === 'scene' || !!g.on || g.state === 'playing' || g.state === 'open', g.id, !g.available);
  }
  function countdownTile(d, now, pos) {
    var c = (d.info || {}).countdown;
    if (c && c.days != null) return accTile(pos, 'heart', c.days + (c.days === 1 ? ' Day' : ' Days'), 'Until ' + c.label, true);
    var start = new Date(now.getFullYear(), 0, 1), wk = Math.ceil(((now - start) / 86400000 + start.getDay() + 1) / 7);
    return accTile(pos, 'cal', 'Week ' + wk, now.toLocaleDateString('en-US', { year: 'numeric' }), true);
  }
  function infoTile(d, now, pos) {
    var md = now.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    var pl = d.playing;
    if (pl && pl.state === 'playing' && pl.title) {   // Apple Music small widget: cover, badge, title, artist on the cover's colors
      var artSt = pl.art_url ? 'background-image:url(' + pl.art_url + ')' : '';
      return '<div class="tile np-tile ' + pos + '" style="' + artMesh(pl, 0.12) + '"><div class="np-tart" style="' + artSt + '"></div>' +
        '<div class="np-badge">' + NP.note + '</div><div class="np-tt">' + esc(pl.title) + '</div><div class="np-ta">' + esc(pl.artist || pl.name || '') + '</div></div>';
    }
    return accTile(pos, 'sun', 'Today', md, true);
  }
  function modular(d) {
    var now = new Date(d.now), wx = d.weather || {};
    var photo = d.photo ? 'background-image:url(/photo/' + encodeURIComponent(d.photo) + ')' : '';
    var hh = now.getHours() % 12 || 12, mm = ('0' + now.getMinutes()).slice(-2);
    var wp = d.wallpaper || 'auto';
    var wcls = wp === 'auto' || wp === 'green' ? '' : wp === 'red' ? ' wp-red' : ' wp-' + wp;
    return el('wallpaper' + wcls, '', wp === 'photo' && d.photo ? 'background-image:url(/photo/' + encodeURIComponent(d.photo) + ')' : '') +
      el('tile glass bigclock glass-text c0 r0 w2 h2',
        el('bc-time' + (hh >= 10 ? ' wide' : ''), hh + ':' + mm) +
        el('bc-date', now.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' }))) +
      el('tile glass wxtile glass-text c2 r0 w1 h1',
        el('wt-temp', (wx.temp != null ? wx.temp : '--') + '°') + el('wt-icon', wx.code != null ? wxIcon(wx.code, wx.day, 80) : '') +
        el('wt-cond', wx.code != null ? wxName(wx.code) : '—') +
        el('wt-hl', 'H:' + (wx.high != null ? wx.high : '--') + '°  L:' + (wx.low != null ? wx.low : '--') + '°')) +
      upNext(d, 'c3 r0 w1 h1') +
      el('tile photo c2 r1 w1 h1', '', photo) +
      infoTile(d, now, 'c3 r1 w1 h1') +
      comingUp(d, 'c0 r2 w2 h1') +
      homeTile(d, 'c2 r2 w1 h1') +
      countdownTile(d, now, 'c3 r2 w1 h1');
  }

  function weather(d) {
    var wx = d.weather || {}, now = new Date(d.now);
    var kind = !wx.day ? (wx.code >= 3 ? 'night overcast' : 'night') : (wx.code >= 51 ? 'rain' : 'day');
    var clouds = '';
    var cl = [[-120, 10, 520, 320], [220, -30, 600, 330], [600, 0, 600, 320], [-100, 210, 560, 300], [330, 170, 520, 300], [640, 200, 560, 290], [-60, 320, 440, 220], [720, 320, 420, 200], [980, -20, 600, 330], [1000, 200, 520, 300], [1060, 330, 420, 210]];
    var drift = ((now.getTime() / 1000) % 600) / 600;   // clouds move slowly over ten minutes, so successive renders cross-fade into motion
    cl.forEach(function (c, i) { c = [c[0] + Math.round((i % 2 ? -1 : 1) * drift * 180) , c[1] + Math.round(Math.sin(drift * 6.28 + i) * 10), c[2], c[3]];
      clouds += '<div class="cloud" style="left:' + c[0] + 'px;top:' + c[1] + 'px;width:' + c[2] + 'px;height:' + c[3] + 'px;opacity:' + (kind === 'day' ? 0.7 : kind === 'night' ? 0.35 : 0.7) + '"></div>'; });
    var hrs = (wx.hours || []).slice(0, 9).map(function (h, i) {
      var dt = new Date(h.time), hh = dt.getHours(), lab = i === 0 ? 'Now' : ((hh % 12) || 12) + '<small>' + (hh < 12 ? 'AM' : 'PM') + '</small>';
      return '<div class="wx-hour"><div class="t">' + lab + '</div>' + wxIcon(h.code, h.day, 84) + '<div class="d">' + (h.temp != null ? h.temp + '°' : '') + '</div></div>';
    }).join('');
    var days = (wx.days || []).slice(0, 6).map(function (dy, i) {
      var dt = new Date(dy.date + 'T12:00:00'), name = i === 0 ? 'Today' : dt.toLocaleDateString('en-US', { weekday: 'short' });
      var rain = dy.rain != null && dy.rain >= 30 ? '<span class="rain">' + dy.rain + '%</span>' : '';
      return '<div class="wx-day"><div class="n">' + name + '</div><div class="ic">' + wxIcon(dy.code, 1, 64) + rain + '</div>' +
        '<div class="range"><span class="lo">' + dy.low + '°</span><span class="bar"><i style="left:' + Math.round((dy.low - wx.span[0]) / (wx.span[1] - wx.span[0]) * 100) + '%;right:' + Math.round((wx.span[1] - dy.high) / (wx.span[1] - wx.span[0]) * 100) + '%"></i></span><span class="hi">' + dy.high + '°</span></div></div>';
    }).join('');
    var time = now.getHours() % 12 || 12; time += ':' + ('0' + now.getMinutes()).slice(-2);
    return '<div class="sky ' + kind + '">' + clouds + '</div>' +
      el('wx-time', time) + el('wx-city', wx.location || '') + el('wx-temp', (wx.temp != null ? wx.temp : '--') + '°') +
      el('wx-cond', wx.code != null ? wxName(wx.code) : '') + el('wx-hl', 'H:' + (wx.high != null ? wx.high : '--') + '° L:' + (wx.low != null ? wx.low : '--') + '°') +
      '<div class="wx-card"><div class="wx-hours">' + hrs + '</div><div class="wx-rule"></div><div class="wx-days">' + days + '</div></div>' +
      (wx.source ? el('wx-src', 'Weather data by ' + esc(wx.source)) : '');
  }

  // Tall stadium-stroke digits like Apple's Photos face. Each glyph box 177x970, stroke 63.
  var DIG = (function () {
    var L = 31.5, R = 145.5, T = 31.5, B = 938.5, r = 57, c = 88.5;
    function A(x, y, sw) { return ' A' + r + ' ' + r + ' 0 0 ' + sw + ' ' + x + ' ' + y; }
    return {
      '0': 'M' + L + ' ' + (T + r) + A(R, T + r, 1) + ' V' + (B - r) + A(L, B - r, 1) + 'Z',
      '1': 'M144 4 V967',
      '2': 'M31.5 210 V88.5 A57 57 0 0 1 145.5 88.5 V330 L36 938.5 H177',
      '3': 'M31.5 210 V88.5 A57 57 0 0 1 145.5 88.5 V400 Q145.5 470 70 470 Q145.5 470 145.5 560 V881.5 A57 57 0 0 1 31.5 881.5 V760',
      '4': 'M128 0 V970 M128 4 L28 690 H177',
      '5': 'M177 31.5 H31.5 V520 M31.5 520 Q31.5 430 100 430 Q145.5 430 145.5 520 V881.5 A57 57 0 0 1 31.5 881.5 V760',
      '6': 'M145.5 271.5 V88.5 A57 57 0 0 0 31.5 88.5 V881.5 A57 57 0 0 0 145.5 881.5 V427 A57 57 0 0 0 31.5 427',
      '7': 'M0 31.5 H145.5 L64 970',
      '8': 'M' + L + ' ' + (T + r) + A(R, T + r, 1) + ' V' + (470 - r) + A(L, 470 - r, 1) + 'Z M' + L + ' ' + (470 + r) + A(R, 470 + r, 1) + ' V' + (B - r) + A(L, B - r, 1) + 'Z',
      '9': 'M31.5 698.5 V881.5 A57 57 0 0 0 145.5 881.5 V88.5 A57 57 0 0 0 31.5 88.5 V543 A57 57 0 0 0 145.5 543'
    };
  })();
  function photo(d) {
    var now = new Date(d.now), h = String(now.getHours() % 12 || 12), m = ('0' + now.getMinutes()).slice(-2);
    var tq = location.search.match(/time=(\d{1,2})(\d\d)/); if (tq) { h = String(+tq[1]); m = tq[2]; }
    var bg = d.photo ? 'background-image:url(/photo/' + encodeURIComponent(d.photo) + ')' : 'background:#c96a5c';
    // Hours end at x 400, minutes start at x 630 (Apple leaves the middle open for the subject). Pitch 213.
    var paths = '';
    var FLAG1 = 'M120 4 L52 62 V128 L120 79Z';
    function put(ch, x) { var t = 'translate(' + x + ' 58)';
      paths += '<path transform="' + t + '" d="' + DIG[ch] + '"/>';
      if (ch === '1') paths += '<path transform="' + t + '" fill="#fff" stroke="none" d="' + FLAG1 + '"/>'; }
    for (var i = 0; i < h.length; i++) put(h.charAt(i), 581.5 - 177 - (h.length - 1 - i) * 213);
    put(m.charAt(0), 811.5); put(m.charAt(1), 1024.5);
    var strokes = '<g filter="url(#rnd)"><g fill="none" stroke="#fff" stroke-width="63" stroke-linecap="butt" stroke-linejoin="miter">' + paths + '</g></g>';
    var href = d.photo ? '/photo/' + encodeURIComponent(d.photo) : '';
    var svg = '<svg class="bt-rim" viewBox="0 0 1451 1088"><defs><filter id="rnd"><feGaussianBlur stdDeviation="5"/><feComponentTransfer><feFuncA type="linear" slope="10" intercept="-4.5"/></feComponentTransfer></filter><mask id="btMask" maskUnits="userSpaceOnUse" x="0" y="0" width="1451" height="1088">' + strokes + '</mask>' +
      '<filter id="frost" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="10"/><feColorMatrix type="saturate" values="1.3"/><feComponentTransfer><feFuncR type="linear" slope="1.18" intercept="0.10"/><feFuncG type="linear" slope="1.18" intercept="0.10"/><feFuncB type="linear" slope="1.16" intercept="0.09"/></feComponentTransfer></filter>' +
      '<filter id="ig" x="-5%" y="-5%" width="110%" height="110%"><feGaussianBlur in="SourceAlpha" stdDeviation="2.5" result="b"/><feOffset in="b" dy="3" result="bo"/><feComposite in="SourceAlpha" in2="bo" operator="arithmetic" k2="1" k3="-1" result="rim"/><feFlood flood-color="#fff" flood-opacity=".75"/><feComposite in2="rim" operator="in" result="glow"/><feMorphology in="SourceAlpha" operator="dilate" radius="2" result="d"/><feComposite in="d" in2="SourceAlpha" operator="out" result="e"/><feFlood flood-color="#000" flood-opacity=".28"/><feComposite in2="e" operator="in" result="dark"/><feMerge><feMergeNode in="dark"/><feMergeNode in="glow"/></feMerge></filter></defs>' +
      (href ? '<g mask="url(#btMask)"><image href="' + href + '" x="0" y="0" width="1451" height="1088" preserveAspectRatio="xMidYMid slice" filter="url(#frost)"/></g>' : '') +
      '<g mask="url(#btMask)"><rect width="1451" height="1088" fill="rgba(255,248,240,0.06)"/></g>' +
      '<g filter="url(#ig)">' + strokes + '</g></svg>';
    var person = '';
    if (href && d.mask) {
      person = '<svg class="bt-rim" viewBox="0 0 1451 1088"><defs><mask id="pm" maskUnits="userSpaceOnUse" x="0" y="0" width="1451" height="1088">' +
        '<image href="/mask/' + encodeURIComponent(d.photo) + '" x="0" y="0" width="1451" height="1088" preserveAspectRatio="xMidYMid slice"/></mask></defs>' +
        '<image href="' + href + '" x="0" y="0" width="1451" height="1088" preserveAspectRatio="xMidYMid slice" mask="url(#pm)"/></svg>';
    }
    return el('full-photo', '', bg) + svg + person + el('photo-tint');
  }

  // Night: HomeView turns the Modular face's widgets monochrome red in the dark (StandBy-style), on black.
  function night(d) {
    return '<svg width="0" height="0" style="position:absolute"><filter id="redf" color-interpolation-filters="sRGB">' +
      '<feColorMatrix type="matrix" values="0.21 0.42 0.08 0 0  0.03 0.06 0.01 0 0  0.02 0.04 0.01 0 0  0 0 0 1 0"/></filter></svg>' +
      el('night-bg') + el('redmode', modular(d));
  }

  var NP = {};
  ['prev', 'next', 'play', 'pause', 'volLo', 'volHi', 'lyrics', 'airplay', 'queue', 'note'].forEach(function (n) { NP[n] = sf(n); });
  function mmss(t) { t = Math.max(0, Math.round(t || 0)); return Math.floor(t / 60) + ':' + ('0' + t % 60).slice(-2); }
  // Apple Music builds its Now Playing background from the cover's own colors; the server sends them as m.colors.
  function artMesh(m, dim) {
    var c = (m.colors && m.colors.length) ? m.colors : ['#2c2c3a', '#5b4b6e', '#2f4256', '#6b5452'];
    var c0 = c[0], c1 = c[1] || c0, c2 = c[2] || c1, c3 = c[3] || c2;
    return 'background:' + (dim ? 'linear-gradient(rgba(0,0,0,' + dim + '),rgba(0,0,0,' + dim + ')),' : '') +
      'radial-gradient(62% 72% at 16% 20%,' + c1 + ' 0%,transparent 72%),radial-gradient(58% 70% at 88% 84%,' + c2 + ' 0%,transparent 72%),' +
      'radial-gradient(48% 58% at 82% 12%,' + c3 + ' 0%,transparent 70%),radial-gradient(50% 60% at 30% 92%,' + c0 + ' 0%,transparent 70%),' + c0;
  }
  function nowplaying(d) {
    var m = d.playing || d.paused;
    if (/demo=1/.test(location.search)) m = { id: 'sonos', name: 'Living Room Sonos', state: 'playing', title: 'Preview Track', artist: 'Sample Artist', volume: 0.35, art: false, duration: 214, position: 62 };
    if (!m) return el('np-bg', '', 'background:#1c1c1e') + el('np-empty', NP.note + '<b>Not Playing</b>');
    var art = m.art_url ? m.art_url : (d.photo ? '/photo/' + encodeURIComponent(d.photo) : '');
    var artStyle = art ? 'background-image:url(' + art + ')' : 'background:#444';
    var dur = m.duration || 0, pos = Math.min(dur, m.position_now != null ? m.position_now : (m.position || 0));
    var prog = dur ? el('np-prog', el('np-bar', '<i style="width:' + (pos / dur * 100).toFixed(2) + '%"></i>') +
      el('np-times', '<span>' + mmss(pos) + '</span><span>-' + mmss(dur - pos) + '</span>')) : '';
    var vol = m.volume != null ? el('np-volrow', NP.volLo + el('np-vol', '<i style="width:' + Math.round(m.volume * 100) + '%"></i>') + NP.volHi) : '';
    return el('np-bg', '', artMesh(m, 0.42)) + el('np-blur', '', artStyle) +
      el('np-tl', NP.note) + el('np-tr', NP.airplay + NP.volHi) +
      el('np-art', el('np-frost', '', artStyle), artStyle) +
      el('np-meta' + ((m.title || '').length > 22 ? ' long' : ''), el('np-title', esc(m.title || 'Unknown')) + el('np-artist', esc(m.artist || ''))) +
      el('np-more', '<i></i><i></i><i></i>') + prog +
      el('np-side l', NP.lyrics) + el('np-side r', NP.queue) +
      el('np-btn prev', NP.prev) + el('np-btn play', m.state === 'playing' ? NP.pause : NP.play) + el('np-btn next', NP.next);
  }

  // Synced lyrics (Apple Music style): current line big and bold, the rest dimmed, on the cover's colours.
  function lyricsFace(d) {
    var m = d.playing || d.paused || {}, lines = d.lyrics || [];
    var art = m.art_url ? 'background-image:url(' + m.art_url + ')' : 'background:#444';
    var pos = m.position_now != null ? m.position_now : (m.position || 0), cur = -1;
    for (var i = 0; i < lines.length; i++) if (lines[i][0] <= pos + 0.3) cur = i;
    var head = el('ly-head', el('ly-art', '', art) + '<div><b>' + esc(m.title || '') + '</b><span>' + esc(m.artist || '') + '</span></div>');
    var body;
    if (!lines.length) body = el('ly-none', d.lyrics ? "Lyrics aren\u2019t available for this song" : 'Loading lyrics…');
    else {
      var from = Math.max(0, cur - 1), out = [];
      for (var k = from; k < Math.min(lines.length, from + 6); k++) {
        var t = lines[k][1] || '♪';
        out.push('<div class="ly-l' + (k === cur ? ' cur' : k < cur ? ' past' : '') + '">' + esc(t) + '</div>');
      }
      if (cur < 0) out.unshift('<div class="ly-l cur">♪</div>');
      body = el('ly-lines', out.join(''));
    }
    return el('np-bg', '', artMesh(m, 0.30)) + el('np-blur', '', art) + head + body;
  }
  // Calendar face (StandBy style): time + today's events on the left, the month on the right, today circled in red.
  function calendarFace(d) {
    var now = new Date(d.now), seenEv = {}, cal = ((d.info || {}).calendar || []).filter(function (e) { var k = e.title + e.date + e.time; if (seenEv[k]) return false; seenEv[k] = 1; return true; });
    var iso = function (dt) { return dt.getFullYear() + '-' + ('0' + (dt.getMonth() + 1)).slice(-2) + '-' + ('0' + dt.getDate()).slice(-2); };
    var has = {}; cal.forEach(function (e) { has[e.date] = true; });
    var first = new Date(now.getFullYear(), now.getMonth(), 1), days = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
    var cells = ['S', 'M', 'T', 'W', 'T', 'F', 'S'].map(function (x) { return '<i class="wd">' + x + '</i>'; });
    for (var k = 0; k < first.getDay(); k++) cells.push('<i></i>');
    for (var n = 1; n <= days; n++) {
      var dt = new Date(now.getFullYear(), now.getMonth(), n), key = iso(dt);
      cells.push('<i class="' + (n === now.getDate() ? 'today' : dt < now ? 'past' : '') + (has[key] ? ' ev' : '') + '"><b>' + n + '</b></i>');
    }
    var up = cal.filter(function (e) { return e.date >= iso(now) && (e.date > iso(now) || e.all_day || !e.time || e.time >= ('0' + now.getHours()).slice(-2) + ':' + ('0' + now.getMinutes()).slice(-2)); })
      .slice(0, 3).map(function (e) {
        var when = e.date === iso(now) ? (e.all_day ? 'All Day' : hm12(e.time)) : e.day.replace(/^\w+, /, '') + (e.all_day ? '' : ' · ' + hm12(e.time));
        return '<div class="cf-ev"><i></i><div><b>' + esc(e.title) + '</b><span>' + when + '</span></div></div>';
      }).join('') || '<div class="cf-none">No upcoming events</div>';
    var hh = now.getHours() % 12 || 12, mm = ('0' + now.getMinutes()).slice(-2);
    return el('cf-bg') +
      el('cf-left', el('cf-day', now.toLocaleDateString('en-US', { weekday: 'long' }).toUpperCase()) + el('cf-time', hh + ':' + mm) + up) +
      el('cf-right', el('cf-month', now.toLocaleDateString('en-US', { month: 'long' }).toUpperCase()) + el('cf-grid', cells.join('')));
  }
  // Flow face: huge time filled with slowly shifting colour blobs (hue moves through the day).
  function flowFace(d) {
    var now = new Date(d.now), hh = now.getHours() % 12 || 12, mm = ('0' + now.getMinutes()).slice(-2);
    var dayf = (now.getHours() * 60 + now.getMinutes()) / 1440, hue = 205 + 25 * Math.sin(dayf * Math.PI * 2), m = now.getMinutes();
    function c(h, l) { return 'hsl(' + ((hue + h) % 360).toFixed(0) + ',92%,' + l + '%)'; }
    var x1 = 20 + (m * 7) % 60, x2 = 80 - (m * 5) % 60;
    var fill = 'radial-gradient(40% 60% at ' + x1 + '% 30%,' + c(115, 70) + ',transparent 70%),radial-gradient(45% 60% at ' + x2 + '% 75%,' + c(0, 64) + ',transparent 70%),' +
      'radial-gradient(35% 50% at 55% 50%,' + c(80, 78) + ',transparent 70%),' + c(40, 60);
    return el('fl-bg', '', 'background:radial-gradient(70% 70% at 50% 60%,' + c(60, 13) + ',#050508)') +
      el('fl-time' + (hh >= 10 ? ' wide' : ''), hh + ':' + mm, 'background:' + fill + ';-webkit-background-clip:text;background-clip:text') +
      el('fl-date', now.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' }));
  }
  // Home Camera face: up to 9 live pictures in a grid.
  function camerasFace(d) {
    var c = d.cams || {}, list = c.list || [];
    if (!list.length) {
      var msg = c.error === 'no_token' ? 'Connect Home Assistant to see your cameras' : c.error === 'no_cameras' ? 'No cameras in Home Assistant yet' : 'Loading cameras…';
      return el('cm-bg') + el('cm-empty', sf('camera') + '<b>' + msg + '</b>');
    }
    var cols = list.length <= 1 ? 1 : list.length <= 4 ? 2 : 3, rows = Math.ceil(list.length / cols);
    var g = 18, W0 = 1451 - 2 * 40, H0 = 1088 - 2 * 40, w = (W0 - g * (cols - 1)) / cols, h = (H0 - g * (rows - 1)) / rows;
    return el('cm-bg') + list.map(function (x, i) {
      var l = 40 + (i % cols) * (w + g), t = 40 + Math.floor(i / cols) * (h + g);
      return el('cm-cell', el('cm-name', '<i></i>' + esc(x.name)), 'left:' + l + 'px;top:' + t + 'px;width:' + w + 'px;height:' + h + 'px;background-image:url(' + x.url + ')');
    }).join('');
  }
  // Home Screen: greeting, avatar, big Photos widget, app icons (each opens its screen).
  var APPS = [['Home', 'home', 'house', '#ffcc33', '#ff9500'], ['Music', 'music', 'note', '#ff5f7e', '#fa233b'], ['Weather', 'weather', 'wx_sun', '#4fb5ff', '#1a6dff'],
              ['Calendar', 'calendar', null, '#ffffff', '#f2f2f7'], ['Photos', 'photos', 'photo', '#ffffff', '#f2f2f7'], ['Lights', 'lights', 'bulb', '#ffd84d', '#ffb000'],
              ['Cameras', 'cameras', 'camera', '#5ac8fa', '#007aff'], ['Lyrics', 'lyrics', 'lyrics', '#ff6b8b', '#d42a5b'], ['Flow', 'flow', 'clock', '#7a5cff', '#ff5cb0']];
  function appsFace(d) {
    var now = new Date(d.now), h = now.getHours();
    var greet = (h < 12 ? 'GOOD MORNING' : h < 17 ? 'GOOD AFTERNOON' : 'GOOD EVENING') + (d.owner && !d.demo ? ', ' + esc(d.owner).toUpperCase() : '');
    var photo = d.photo ? 'background-image:url(/photo/' + encodeURIComponent(d.photo) + ')' : '';
    var icons = APPS.map(function (a, i) {
      var x = 772 + (i % 3) * 216, y = 176 + Math.floor(i / 3) * 284, inner;
      if (a[1] === 'calendar') inner = '<div class="ap-cal"><span>' + now.toLocaleDateString('en-US', { weekday: 'short' }).toUpperCase() + '</span><b>' + now.getDate() + '</b></div>';
      else if (a[1] === 'photos') inner = '<div class="ap-flower">' + [0, 45, 90, 135, 180, 225, 270, 315].map(function (r, k) {
          return '<i style="transform:rotate(' + r + 'deg);background:' + ['#ff9500', '#ffcc00', '#a6e22e', '#34c759', '#32ade6', '#5856d6', '#af52de', '#ff2d55'][k] + '"></i>'; }).join('') + '</div>';
      else inner = sf(a[2]);
      return '<div class="ap-app" style="left:' + x + 'px;top:' + y + 'px"><div class="ap-ic" style="background:linear-gradient(180deg,' + a[3] + ',' + a[4] + ')">' + inner + '</div><span>' + a[0] + '</span></div>';
    }).join('');
    return el('ap-bg', '', photo) + el('ap-shade') +
      el('ap-greet', greet) + el('ap-avatar', d.owner && !d.demo ? esc(d.owner.charAt(0)).toUpperCase() : sf('person')) +
      el('ap-photo', el('ap-photo-label', '<b>Photos</b><span>' + now.toLocaleDateString('en-US', { month: 'long', day: 'numeric' }) + '</span>'), photo) + icons;
  }
  // Cooking (HomeView recipe card): full-bleed photo, title + meta, Ingredients / Start Cooking; then big steps.
  function cookFace(d) {
    var c = d.cook, now = new Date(d.now);
    if (!c) return el('ck-bg', '', 'background:#1c1c1e') + el('ck-title', 'No recipe open');
    var bg = c.image ? 'background-image:url(' + c.image + ')' : 'background:linear-gradient(160deg,#ff9f6b,#c2412d)';
    var clock = el('ck-clock', (now.getHours() % 12 || 12) + ':' + ('0' + now.getMinutes()).slice(-2));
    var x = el('ck-x', '<i></i><i></i>');
    if (c.view === 'overview')
      return el('ck-photo', '', bg) + el('ck-fade') + x + clock + el('ck-title', esc(c.title)) + el('ck-meta', esc(c.meta || (c.steps.length + ' steps'))) +
        el('ck-btn l', 'Ingredients') + el('ck-btn r', 'Start Cooking');
    if (c.view === 'ingredients')
      return el('ck-photo blur', '', bg) + el('ck-dim') + x + clock + el('ck-panel', '<div class="ck-k">Ingredients</div>' +
        c.ingredients.map(function (i) { return '<div class="ck-ing"><i></i>' + esc(i) + '</div>'; }).join('') + '<div class="ck-hint">Say “start cooking”</div>');
    var st = c.steps[c.step] || { text: '', mins: 0 };
    return el('ck-photo blur', '', bg) + el('ck-dim') + x + clock +
      el('ck-step', '<div class="ck-k">Step ' + (c.step + 1) + ' of ' + c.steps.length + ' · ' + esc(c.title) + '</div><div class="ck-st">' + esc(st.text) + '</div>' +
        (st.mins ? '<div class="ck-timer">' + sf('timer') + '<b>Start ' + st.mins + ' min timer</b></div>' : '')) +
      el('ck-progress', c.steps.map(function (_, i) { return '<i class="' + (i <= c.step ? 'on' : '') + '"></i>'; }).join('')) +
      el('ck-nav', '<span>' + (c.step ? 'Back' : 'Overview') + '</span><span>' + (c.step < c.steps.length - 1 ? 'Next' : 'Done') + '</span>');
  }
  // ---------------- the Muse screen: a full-page answer ----------------
  function esc(t) { return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function inline(t) { return esc(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`(.+?)`/g, '$1'); }
  // Apple-style emphasis when Muse sent plain text: years, numbers with units and multi-word names in bold.
  function autoBold(h) {
    if (/<b>/.test(h)) return h;
    return h.replace(/\b(1[0-9]{3}|20[0-9]{2})\b/g, '<b>$1</b>')
      .replace(/(\$\d[\d,.]*\s?(?:[KMB]|million|billion)?|\b\d[\d,.]*\s?(?:%|percent|miles|mi|feet|ft|meters|km|degrees|°|days|hours|minutes|years|people|pounds|lbs)\b)/g, '<b>$1</b>')
      .replace(/(^|[^.!?]\s)((?:[A-Z][a-z'’]+|[A-Z]\.)(?:\s(?:of|de|the|van|von)?\s?[A-Z][a-z'’]+)+)/g, function (m, pre, name) { return pre + '<b>' + name + '</b>'; });
  }
  // Muse's markdown -> Siri-style answer: big sentence, date / section heads, and Calendar-style pills.
  function mdBlocks(md) {
    var lines = String(md || '').replace(/\r/g, '').split('\n'), title = '', out = [], sec = '';
    lines.forEach(function (raw) {
      var l = raw.trim(); if (!l) return;
      var m;
      if (!title && !/^([-*•]|\d+[.)])\s/.test(l) && !/^#/.test(l)) { title = l.replace(/^#+\s*/, ''); return; }
      if ((m = l.match(/^#{1,3}\s+(.*)$/))) { sec = m[1].replace(/:$/, ''); out.push('<div class="sr-h">' + inline(sec) + '</div>'); return; }
      if ((m = l.match(/^(?:[-*•]|\d+[.)])\s+(.*)$/))) {
        var t = m[1], cls = 'gray', tm = '', right = '', c, ic = '';
        if (/^!/.test(t)) { cls = 'orange'; t = t.slice(1); right = 'Needs you'; ic = 'bell'; }
        else if (/^~/.test(t)) { cls = 'green'; t = t.slice(1); right = 'Running'; ic = 'sparkles'; }
        else if ((c = t.match(/^\[( |x|X)\]\s*(.*)$/))) { cls = c[1] === ' ' ? 'gray' : 'done'; t = c[2]; ic = c[1] === ' ' ? '' : 'check'; }
        if ((c = t.match(/^(?:\*\*)?(\d{1,2}(?::\d\d)?\s?(?:[AaPp]\.?[Mm]\.?)(?:\s?[–-]\s?\d{1,2}(?::\d\d)?\s?(?:[AaPp]\.?[Mm]\.?)?)?)(?:\*\*)?\s*[-–·:,]?\s*(.+)$/))) { cls = 'blue'; tm = c[1]; t = c[2]; }
        else if ((c = t.match(/^(.+?)\s*[-–·,(]\s*(\d{1,2}(?::\d\d)?\s?(?:[AaPp]\.?[Mm]\.?))\)?$/))) { cls = 'blue'; tm = c[2]; t = c[1]; }
        else if (/\ball[- ]day\b/i.test(t) || /birthday|anniversary|holiday|halloween/i.test(t)) { cls = 'peach'; t = t.replace(/\s*[-–·(]*\s*all[- ]day\)?/i, ''); right = 'all-day'; ic = 'cal'; }
        else if (/^(due|today|tomorrow|deadline)\b/i.test(sec) || /needs you/i.test(sec)) { if (cls === 'gray') { cls = 'orange'; ic = 'bell'; } }
        if (cls === 'blue') out.push('<div class="sr-pill blue"><i class="bar"></i><div><b>' + inline(t) + '</b><span>' + sf('clock') + tm + '</span></div></div>');
        else out.push('<div class="sr-pill ' + cls + '">' + (ic ? '<i class="ic">' + sf(ic) + '</i>' : '<i class="dot"></i>') + '<b>' + inline(t) + '</b>' + (right ? '<em>' + right + '</em>' : '') + '</div>');
        return;
      }
      out.push('<div class="sr-p">' + autoBold(inline(l)) + '</div>');
    });
    return { title: title, html: out.join('') };
  }
  function muse(d) {
    var pg = d.muse_page || {};
    var b = mdBlocks(pg.md);
    var list = /sr-pill/.test(b.html);
    var img = pg.image ? el('sr-img', '', 'background-image:url(' + pg.image + ')' + (pg.image_pos ? ';background-position:' + pg.image_pos : '')) : '';
    return el('sr-bg') + el('sr-orb', '<i></i>') +
      el('sr-body' + (list ? ' list' : ' prose') + (img ? ' withimg' : ''), (b.title ? '<div class="sr-title">' + autoBold(inline(b.title)) + '</div>' : '') + b.html +
        (pg.source ? '<div class="sr-chips"><span>' + esc(pg.source) + '</span></div>' : '')) + img;
  }
  function fitMuse() {      // largest text that fits, like Siri's answer cards
    var body = document.querySelector('.sr-body');
    if (!body) return;
    var px = body.classList.contains('list') ? 62 : 76;
    body.style.fontSize = px + 'px';
    while (body.scrollHeight > body.clientHeight + 2 && px > 26) { px -= 2; body.style.fontSize = px + 'px'; }
  }

  function ltile(pos, icon, name, room, on, extra) {
    return el('tile ltile ' + pos + (on ? ' on' : '') + (extra ? ' ' + extra : ''), el('icon', ICON[icon]) + (name ? el('name', esc(name)) : '') + (room ? el('room', esc(room)) : ''));
  }
  // Lights: a light-mode grid of the Home Assistant devices from config.json (the analog clock takes the first cell).
  function grid(d) {
    var now = new Date(d.now), items = d.grid || [];
    var ICONS = { light: 'bulb', fan: 'fan', scene: 'sun', shade: 'blinds', media: 'intercom' };
    var out = el('light-bg') + el('tile ltile clockw c0 r0 w1 h1', el('clock', clockSVG(now, true)));
    items.slice(0, 11).forEach(function (g, i) {
      var pos = 'c' + ((i + 1) % 4) + ' r' + Math.floor((i + 1) / 4) + ' w1 h1';
      var st = !g.available ? 'No Response' : g.kind === 'scene' ? 'Scene' : g.room || '';
      out += ltile(pos + (CHANGED[g.id] ? ' changed' : ''), ICONS[g.kind] || 'house', g.name, st, g.kind !== 'scene' && (!!g.on || g.state === 'playing' || g.state === 'open'));
    });
    if (!items.length) out += ltile('c1 r0 w3 h1', 'house', 'No devices yet', 'Add Home Assistant devices to config.json', false);
    return out;
  }

  var face = (location.search.match(/face=(\w+)/) || [])[1];
  var xhr = new XMLHttpRequest();
  xhr.open('GET', '/api/data', true);
  xhr.onload = function () {
    var d = JSON.parse(xhr.responseText); face = face || d.face;
    if (d.weather && d.weather.days && d.weather.days.length) { var lo = 999, hi = -999; d.weather.days.forEach(function (x) { lo = Math.min(lo, x.low); hi = Math.max(hi, x.high); }); d.weather.span = [lo, Math.max(hi, lo + 1)]; }
    var pq = location.search.match(/photo=([^&]+)/); if (pq) { d.photo = decodeURIComponent(pq[1]); d.mask = true; }  // preview a given photo
    var fn = { modular: modular, weather: weather, photo: photo, grid: grid, night: night, nowplaying: nowplaying, muse: muse, lyrics: lyricsFace, calendar: calendarFace, flow: flowFace, cameras: camerasFace, apps: appsFace, cook: cookFace }[face] || modular;
    CHANGED = d.changed || {};
    var html = fn(d);
    if (d.dim != null && d.dim < 1 && face !== 'night') html += el('dim', '', 'opacity:' + (1 - d.dim).toFixed(2));
    if (face !== 'muse') html += el('vignette');      // the white answer page stays pure white like Apple's

    document.getElementById('screen').innerHTML = html;
    if (face === 'muse') fitMuse();
  };
  xhr.send();
})();
