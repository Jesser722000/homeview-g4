// Full-screen HomeView viewer for the iMac G4 (Java 1.4, Mac OS X 10.4).
//
// The Mac renders each screen (a "face") and every pop-up (with real SF fonts and frosted glass). This viewer:
//  * shows the face edge to edge; a new face slides in like a card, same-face changes cross-fade only what changed;
//  * places the pop-ups exactly over the frame they were cut from, switching face and pop-ups together (no blinking);
//  * draws analog clock hands and the Siri-style edge glow itself, so they move smoothly;
//  * streams the internal microphone to the Mac and plays spoken replies one at a time;
//  * keeps the display awake except 1-6 AM, and wakes it for the wake word, timers and alarms.
// Quit with Esc or Command-Q.
//
// The Mac's address comes from the first argument, or else from ~/HVViewer/server.txt (one line, e.g.
// http://my-macbook.local:8090). Use the Mac's Bonjour name: the link-local address can change.
import java.awt.*;
import java.awt.event.*;
import java.awt.geom.*;
import java.awt.image.BufferedImage;
import java.io.*;
import java.net.*;
import java.util.Calendar;
import java.util.Hashtable;
import java.util.Vector;
import java.util.regex.*;
import javax.sound.sampled.*;

public class HVViewer extends Frame {
    static String BASE = "http://your-mac.local:8090";      // replaced by the argument or ~/HVViewer/server.txt
    static final int W = 1024, H = 768;

    // ---- what is on screen ----
    BufferedImage base;                       // current face (no clock hands, no pop-ups)
    String face = "", lastAt = "";
    double[][] clocks = new double[0][];      // cx, cy, r, style(0 dark, 1 light)
    static class Sprite { String id, v; Rectangle r; BufferedImage img; }
    Sprite[] sprites = new Sprite[0];         // pop-ups belonging to the current face frame
    BufferedImage buf, buf2;                  // the composed screen, and a scratch frame for transitions
    BufferedImage edgeShadow, edgeShadowR;
    final Object drawLock = new Object();
    volatile boolean transitioning = false;
    final Hashtable spriteCache = new Hashtable();
    PrintStream perf;

    // ---- cursor, display sleep ----
    volatile long lastMove = 0, ignoreMoveUntil = 0, lastNudge = 0;
    boolean cursorShown = true;
    Cursor blank;
    Robot robot;
    int mouseX = 512, mouseY = 384;
    static final int SLEEP_FROM = 1, SLEEP_TO = 6;

    // ---- voice ----
    volatile String vPhase = "idle";
    volatile String ringing = "";
    volatile int timerCount = 0;
    volatile boolean speaking = false;
    int lastReply = -1;
    byte[] chimeWav;
    final Object audioLock = new Object();
    byte[] pendingWav = null;
    boolean pendingIsReply = false;
    volatile SourceDataLine curLine = null;

    // ---- camera touch cursor (position comes from the Mac's /touch.txt; drawn here so it keeps up with your finger) ----
    volatile int tX = -1, tY = -1;
    volatile float tP = 0f;
    volatile boolean tR = false;

    // ---- Siri-style edge glow ----
    static final int GT = 46;
    static final Color[] GC = { new Color(188, 130, 243), new Color(245, 185, 234), new Color(141, 159, 255),
                                new Color(255, 103, 120), new Color(255, 186, 113), new Color(198, 134, 255) };
    BufferedImage gTop, gBottom, gLeft, gRight;   // twice as long as the edge; the visible window scrolls along them
    float glowLevel = 0f;                         // 0..1, fades in and out
    int glowOffH = 0, glowOffV = 0;

    public HVViewer() {
        super("HomeView");
        setUndecorated(true);
        setBackground(Color.black);
        blank = Toolkit.getDefaultToolkit().createCustomCursor(new BufferedImage(16, 16, BufferedImage.TYPE_INT_ARGB), new Point(0, 0), "blank");
        hideCursor();
        addMouseListener(new MouseAdapter() { public void mousePressed(MouseEvent e) { tap(e.getX(), e.getY()); } });
        addMouseMotionListener(new MouseMotionAdapter() {
            public void mouseMoved(MouseEvent e) { mouseX = e.getX(); mouseY = e.getY(); if (System.currentTimeMillis() > ignoreMoveUntil) showCursor(); }
            public void mouseDragged(MouseEvent e) { mouseX = e.getX(); mouseY = e.getY(); showCursor(); }
        });
        addKeyListener(new KeyAdapter() {
            public void keyPressed(KeyEvent e) {
                if (e.getKeyCode() == KeyEvent.VK_ESCAPE || (e.getKeyCode() == KeyEvent.VK_Q && e.isMetaDown())) System.exit(0);
            }
        });
        try { robot = new Robot(); } catch (Exception e) { robot = null; }
        edgeShadow = shadowStrip(false); edgeShadowR = shadowStrip(true);
        chimeWav = wavOf(makeChime());
        buildGlow();
        try { perf = new PrintStream(new FileOutputStream(System.getProperty("user.home") + "/HVViewer/perf.log", true), true); } catch (IOException e) { perf = null; }
    }

    void log(String s) { if (perf != null) perf.println(System.currentTimeMillis() / 1000 + " " + s); }
    void showCursor() { lastMove = System.currentTimeMillis(); if (!cursorShown) { setCursor(Cursor.getDefaultCursor()); cursorShown = true; } }
    void hideCursor() { if (cursorShown) { setCursor(blank); cursorShown = false; } }

    void tap(int sx, int sy) {
        final int x = sx * W / Math.max(1, getWidth()), y = sy * H / Math.max(1, getHeight());
        new Thread() { public void run() { try { read(BASE + "/hvtap?" + x + "," + y); } catch (Exception ex) { } } }.start();
    }

    static byte[] read(String url) throws IOException {
        InputStream in = new URL(url).openStream();
        ByteArrayOutputStream out = new ByteArrayOutputStream(200000);
        byte[] b = new byte[16384]; int n;
        while ((n = in.read(b)) > 0) out.write(b, 0, n);
        in.close();
        return out.toByteArray();
    }

    static String field(String json, String key) {
        Matcher m = Pattern.compile("\"" + key + "\"\\s*:\\s*\"?([^\",}\\]]*)").matcher(json);
        return m.find() ? m.group(1).trim() : "";
    }

    // Native (Apple) decoder via Toolkit (ImageIO on PPC Java 1.4 swaps red and blue), copied once into a
    // screen-compatible image so every later draw takes the fast path.
    BufferedImage decode(byte[] data, int w, int h) {
        Image i = Toolkit.getDefaultToolkit().createImage(data);
        MediaTracker mt = new MediaTracker(this);
        mt.addImage(i, 0);
        try { mt.waitForID(0, 15000); } catch (InterruptedException ie) { }
        if (mt.isErrorID(0) || i.getWidth(null) <= 0) return null;
        BufferedImage b = newFrame(w, h);
        Graphics g = b.getGraphics(); g.drawImage(i, 0, 0, null); g.dispose();
        i.flush();
        return b;
    }

    BufferedImage newFrame(int w, int h) {
        GraphicsConfiguration gc = getGraphicsConfiguration();
        return gc != null ? gc.createCompatibleImage(w, h) : new BufferedImage(w, h, BufferedImage.TYPE_INT_RGB);
    }

    static double[][] parseClocks(String json) {
        Matcher m = Pattern.compile("\\{\"cx\":\\s*([0-9.]+),\\s*\"cy\":\\s*([0-9.]+),\\s*\"r\":\\s*([0-9.]+),\\s*\"style\":\\s*\"(\\w+)\"\\}").matcher(json);
        Vector v = new Vector();
        while (m.find()) v.addElement(new double[] { Double.parseDouble(m.group(1)), Double.parseDouble(m.group(2)), Double.parseDouble(m.group(3)), m.group(4).equals("light") ? 1 : 0 });
        double[][] out = new double[v.size()][];
        for (int i = 0; i < out.length; i++) out[i] = (double[]) v.elementAt(i);
        return out;
    }

    static Rectangle[] parseDirty(String json) {
        int i = json.indexOf("\"dirty\"");
        if (i < 0) return null;
        int j = json.indexOf(':', i) + 1;
        while (j < json.length() && json.charAt(j) == ' ') j++;
        if (json.startsWith("null", j)) return null;
        int end = json.indexOf("]]", j);
        String part = end > 0 ? json.substring(j, end + 2) : json.substring(j);
        Matcher m = Pattern.compile("\\[(\\d+),\\s*(\\d+),\\s*(\\d+),\\s*(\\d+)\\]").matcher(part);
        Vector v = new Vector();
        while (m.find()) v.addElement(new Rectangle(Integer.parseInt(m.group(1)), Integer.parseInt(m.group(2)), Integer.parseInt(m.group(3)), Integer.parseInt(m.group(4))));
        Rectangle[] out = new Rectangle[v.size()];
        v.copyInto(out);
        return out;
    }

    static final Pattern SPRITE = Pattern.compile("\\{\"id\": \"(\\w+)\", \"x\": (\\d+), \"y\": (\\d+), \"w\": (\\d+), \"h\": (\\d+), \"v\": \"(\\w+)\"\\}");

    // Keep only the newest version of each pop-up, and at most ~6 screens' worth of pixels (the JVM heap is only 64 MB).
    void cachePut(String id, String v, Sprite sp) {
        java.util.Enumeration ks = spriteCache.keys();
        Vector drop = new Vector(); long px = 0;
        while (ks.hasMoreElements()) {
            String k = (String) ks.nextElement();
            if (k.startsWith(id + "/")) drop.addElement(k);
            else { Sprite o = (Sprite) spriteCache.get(k); px += (long) o.r.width * o.r.height; }
        }
        for (int i = 0; i < drop.size(); i++) spriteCache.remove(drop.elementAt(i));
        if (px + (long) sp.r.width * sp.r.height > 6L * W * H) spriteCache.clear();
        spriteCache.put(id + "/" + v, sp);
    }

    // The pop-ups listed in an /ov.json, loading any new versions. null if one could not be fetched.
    Sprite[] loadSprites(String js) {
        Matcher m = SPRITE.matcher(js);
        Vector list = new Vector();
        while (m.find()) {
            String id = m.group(1), v = m.group(6);
            Sprite sp = (Sprite) spriteCache.get(id + "/" + v);
            if (sp == null) {
                int x = Integer.parseInt(m.group(2)), y = Integer.parseInt(m.group(3)), w = Integer.parseInt(m.group(4)), h = Integer.parseInt(m.group(5));
                try {
                    BufferedImage img = decode(read(BASE + "/ov/" + id + ".png?v=" + v), w, h);
                    if (img == null) return null;
                    sp = new Sprite(); sp.id = id; sp.v = v; sp.r = new Rectangle(x, y, w, h); sp.img = img;
                    cachePut(id, v, sp);
                } catch (IOException e) { return null; }
            }
            list.addElement(sp);
        }
        Sprite[] out = new Sprite[list.size()];
        list.copyInto(out);
        return out;
    }

    // ---- clock hands ----
    static void hand(Graphics2D g, double cx, double cy, double k, double ang, double from, double to, float w, Color c) {
        double a = Math.toRadians(ang), sx = Math.sin(a), cy2 = -Math.cos(a);
        g.setColor(c);
        g.setStroke(new BasicStroke(w, BasicStroke.CAP_ROUND, BasicStroke.JOIN_ROUND));
        g.draw(new Line2D.Double(cx + sx * from * k, cy + cy2 * from * k, cx + sx * to * k, cy + cy2 * to * k));
    }

    void drawHands(Graphics2D g, double[] c) {
        Calendar now = Calendar.getInstance();
        double s = now.get(Calendar.SECOND) + now.get(Calendar.MILLISECOND) / 1000.0;
        double m = now.get(Calendar.MINUTE) + s / 60.0, h = (now.get(Calendar.HOUR) % 12) + m / 60.0;
        double cx = c[0], cy = c[1], k = c[2] / 150.0;
        boolean light = c[3] == 1;
        Color main = light ? new Color(0x1c, 0x1c, 0x1e) : Color.white;
        Color sec = light ? new Color(0x6c, 0x64, 0xb0) : new Color(255, 255, 255, 230);
        g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
        if (!light) {
            Color sh = new Color(0, 0, 0, 55);
            hand(g, cx, cy + 1.5, k, h * 30, 18, 76, (float) (11 * k), sh);
            hand(g, cx, cy + 1.5, k, m * 6, 18, 137, (float) (9 * k), sh);
        }
        hand(g, cx, cy, k, h * 30, 0, 18, (float) (3 * k), main);
        hand(g, cx, cy, k, h * 30, 18, 76, (float) ((light ? 10 : 11) * k), main);
        hand(g, cx, cy, k, m * 6, 0, 18, (float) (3 * k), main);
        hand(g, cx, cy, k, m * 6, 18, 137, (float) ((light ? 8 : 9) * k), main);
        hand(g, cx, cy, k, s * 6, -24, 141, (float) (3 * k), sec);
        double r = (light ? 3.5 : 6) * k;
        g.setColor(Color.white); g.fill(new Ellipse2D.Double(cx - r, cy - r, 2 * r, 2 * r));
        if (light) { g.setColor(sec); g.setStroke(new BasicStroke((float) (2 * k))); g.draw(new Ellipse2D.Double(cx - r, cy - r, 2 * r, 2 * r)); }
    }

    // ---- Siri-style glow: built once; each frame only scrolls a window along four long strips ----
    void buildGlow() {
        int n = GC.length;
        int[] lut = new int[1024];
        for (int i = 0; i < 1024; i++) {
            double t = i / 1024.0 * n; int a = ((int) Math.floor(t)) % n, b = (a + 1) % n; double f = t - Math.floor(t);
            f = f * f * (3 - 2 * f);
            lut[i] = ((int) (GC[a].getRed() + (GC[b].getRed() - GC[a].getRed()) * f) << 16)
                   | ((int) (GC[a].getGreen() + (GC[b].getGreen() - GC[a].getGreen()) * f) << 8)
                   | (int) (GC[a].getBlue() + (GC[b].getBlue() - GC[a].getBlue()) * f);
        }
        int[] fall = new int[GT];
        for (int d = 0; d < GT; d++) {
            double x = d / (double) GT;
            fall[d] = (int) Math.max(0, Math.min(255, (0.80 * Math.pow(1 - x, 2.4) + (d < 2 ? 0.2 : 0)) * 255));
        }
        gTop = strip(true, false, 2 * W, lut, fall, 0.0); gBottom = strip(true, true, 2 * W, lut, fall, 0.5);
        gLeft = strip(false, false, 2 * H, lut, fall, 0.75); gRight = strip(false, true, 2 * H, lut, fall, 0.25);
    }

    static BufferedImage strip(boolean horizontal, boolean flip, int len, int[] lut, int[] fall, double shift) {
        BufferedImage b = horizontal ? new BufferedImage(len, GT, BufferedImage.TYPE_INT_ARGB) : new BufferedImage(GT, len, BufferedImage.TYPE_INT_ARGB);
        int half = len / 2;
        int[] px = new int[len * GT];
        for (int i = 0; i < len; i++) {
            int c = lut[(int) (((i % half) / (double) half + shift) * 1024) & 1023];      // period = one edge, so it loops seamlessly
            for (int d = 0; d < GT; d++) {
                int dd = flip ? GT - 1 - d : d;
                if (horizontal) px[dd * len + i] = (fall[d] << 24) | c; else px[i * GT + dd] = (fall[d] << 24) | c;
            }
        }
        if (horizontal) b.setRGB(0, 0, len, GT, px, 0, len); else b.setRGB(0, 0, GT, len, px, 0, GT);
        return b;
    }

    void drawGlow(Graphics2D g) {
        if (glowLevel <= 0.01f) return;
        Shape clip = g.getClip();
        g.setComposite(AlphaComposite.getInstance(AlphaComposite.SRC_OVER, Math.min(1f, glowLevel)));
        clipTo(g, clip, new Rectangle(0, 0, W, GT)); g.drawImage(gTop, -glowOffH, 0, null);
        clipTo(g, clip, new Rectangle(0, H - GT, W, GT)); g.drawImage(gBottom, -(W - glowOffH), H - GT, null);
        clipTo(g, clip, new Rectangle(0, 0, GT, H)); g.drawImage(gLeft, 0, -(H - glowOffV), null);
        clipTo(g, clip, new Rectangle(W - GT, 0, GT, H)); g.drawImage(gRight, W - GT, -glowOffV, null);
        g.setClip(clip);
        g.setComposite(AlphaComposite.SrcOver);
    }

    static void clipTo(Graphics2D g, Shape outer, Rectangle r) {
        g.setClip(outer);
        g.clipRect(r.x, r.y, r.width, r.height);
    }

    static final Rectangle[] BANDS = { new Rectangle(0, 0, W, GT), new Rectangle(0, H - GT, W, GT), new Rectangle(0, GT, GT, H - 2 * GT), new Rectangle(W - GT, GT, GT, H - 2 * GT) };

    // ---- composition ----
    void composeInto(BufferedImage target, Rectangle clip, BufferedImage b, Sprite[] sp, double[][] clk) {
        Graphics2D g = target.createGraphics();
        if (clip != null) g.setClip(clip);
        if (b != null) g.drawImage(b, 0, 0, null); else { g.setColor(Color.black); g.fillRect(0, 0, W, H); }
        for (int i = 0; i < clk.length; i++) drawHands(g, clk[i]);
        for (int i = 0; i < sp.length; i++) {
            if (clip == null || sp[i].r.intersects(clip)) g.drawImage(sp[i].img, sp[i].r.x, sp[i].r.y, null);
        }
        drawCursor(g);
        drawGlow(g);
        g.dispose();
    }

    Rectangle cursorRect(int x, int y) { return x < 0 ? null : new Rectangle(x - 40, y - 40, 80, 80); }

    void drawCursor(Graphics2D g) {
        int x = tX, y = tY;
        if (x < 0) return;
        boolean rip = tR; float p = tP;
        g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
        int r = rip ? 34 : 27;
        g.setColor(new Color(255, 255, 255, rip ? 120 : 46));
        g.fillOval(x - r, y - r, 2 * r, 2 * r);
        g.setColor(new Color(0, 0, 0, 60));
        g.setStroke(new BasicStroke(5f));
        g.drawOval(x - r, y - r, 2 * r, 2 * r);
        g.setColor(new Color(255, 255, 255, 240));
        g.setStroke(new BasicStroke(3f));
        g.drawOval(x - r, y - r, 2 * r, 2 * r);
        if (p > 0f && !rip) {
            g.setStroke(new BasicStroke(6f, BasicStroke.CAP_ROUND, BasicStroke.JOIN_ROUND));
            g.drawArc(x - r + 7, y - r + 7, 2 * r - 14, 2 * r - 14, 90, -Math.round(360 * p));
        }
        g.fillOval(x - 5, y - 5, 10, 10);
    }

    void touchLoop() {
        String last = "";
        while (true) {
            String s = "0";
            try {
                s = new String(read(BASE + "/touch.txt?t=" + System.currentTimeMillis()), "UTF-8").trim();
                if (!s.equals(last)) {
                    last = s;
                    String[] a = s.split(" ");
                    int nx = -1, ny = -1; float np = 0f; boolean nr = false;
                    if (a.length >= 4 && a[0].equals("1")) {
                        nx = Integer.parseInt(a[1]); ny = Integer.parseInt(a[2]); np = Float.parseFloat(a[3]); nr = a.length > 4 && a[4].equals("1");
                    }
                    Rectangle old = cursorRect(tX, tY);
                    tX = nx; tY = ny; tP = np; tR = nr;
                    Rectangle nw = cursorRect(tX, tY);
                    Rectangle u = old == null ? nw : (nw == null ? old : old.union(nw));
                    if (u != null && !transitioning) { compose(u); blit(u); }
                }
            } catch (Throwable ex) { s = "0"; }
            try { Thread.sleep(s.startsWith("1") ? 25 : 200); } catch (InterruptedException ie) { }
        }
    }

    void compose(Rectangle clip) {
        synchronized (drawLock) { composeInto(buf, clip, base, sprites, clocks); }
    }

    void blit(Rectangle r) {
        Graphics g = getGraphics();
        if (g == null) return;
        synchronized (drawLock) {
            if (r == null || getWidth() != W || getHeight() != H) g.drawImage(buf, 0, 0, getWidth(), getHeight(), null);
            else { g.setClip(r); g.drawImage(buf, 0, 0, null); }
        }
        g.dispose();
        Toolkit.getDefaultToolkit().sync();
    }

    // New face: it slides in over the old one like a card (from the left when going back Home), with a soft shadow.
    void slide(BufferedImage from, BufferedImage to, boolean fromLeft) {
        Graphics g = getGraphics();
        if (g == null || getWidth() != W || getHeight() != H) return;
        long t0 = System.currentTimeMillis(), dur = 400;
        int frames = 0, prevShadow = -1;
        while (true) {
            double t = Math.min(1.0, (System.currentTimeMillis() - t0) / (double) dur);
            double e = 1 - Math.pow(1 - t, 3);
            int off = (int) Math.round(e * W);
            int edge = fromLeft ? off : W - off, sx = fromLeft ? edge : edge - 28;
            if (prevShadow >= 0) { g.setClip(prevShadow, 0, 28, H); g.drawImage(from, 0, 0, null); }
            if (off > 0 && off < W) { g.setClip(sx, 0, 28, H); g.drawImage(fromLeft ? edgeShadowR : edgeShadow, sx, 0, null); prevShadow = sx; }
            if (off > 0) {
                if (fromLeft) { g.setClip(0, 0, off, H); g.drawImage(to, off - W, 0, null); }
                else { g.setClip(edge, 0, off, H); g.drawImage(to, edge, 0, null); }
            }
            Toolkit.getDefaultToolkit().sync();
            frames++;
            if (t >= 1.0) break;
        }
        g.dispose();
        log("slide " + (fromLeft ? "back " : "") + frames + " frames in " + (System.currentTimeMillis() - t0) + " ms");
    }

    // Cross-fade between two whole frames, but only inside the given rectangles.
    void fadeRects(BufferedImage from, BufferedImage to, Rectangle[] rs, long dur) {
        Graphics2D g = (Graphics2D) getGraphics();
        if (g == null || getWidth() != W || getHeight() != H) return;
        long t0 = System.currentTimeMillis();
        while (true) {
            float t = Math.min(1f, (System.currentTimeMillis() - t0) / (float) dur);
            float e = t * t * (3 - 2 * t);
            for (int i = 0; i < rs.length; i++) {
                g.setClip(rs[i]);
                g.setComposite(AlphaComposite.SrcOver); g.drawImage(from, 0, 0, null);
                g.setComposite(AlphaComposite.getInstance(AlphaComposite.SRC_OVER, e)); g.drawImage(to, 0, 0, null);
            }
            Toolkit.getDefaultToolkit().sync();
            if (t >= 1f) break;
        }
        g.dispose();
    }

    static Rectangle[] addRects(Rectangle[] a, Sprite[] x, Sprite[] y) {
        Vector v = new Vector();
        if (a != null) for (int i = 0; i < a.length; i++) v.addElement(a[i]);
        for (int i = 0; i < x.length; i++) { boolean same = false; for (int j = 0; j < y.length; j++) if (x[i] == y[j]) same = true; if (!same) v.addElement(x[i].r); }
        for (int j = 0; j < y.length; j++) { boolean same = false; for (int i = 0; i < x.length; i++) if (x[i] == y[j]) same = true; if (!same) v.addElement(y[j].r); }
        Rectangle[] out = new Rectangle[v.size()];
        v.copyInto(out);
        return out;
    }

    // Swap in a new face and/or new pop-ups with the right transition, then make it the current frame.
    void present(BufferedImage nb, String nf, String nat, double[][] nclk, Sprite[] nsp, Rectangle[] dirty, long fade) {
        transitioning = true;
        try {
            composeInto(buf2, null, nb, nsp, nclk);
            boolean faceChange = base != null && !nf.equals(face);
            if (faceChange) slide(buf, buf2, nf.equals("modular"));
            else if (base != null) {
                Rectangle[] rs = addRects(nb == base ? new Rectangle[0] : dirty, sprites, nsp);
                if (dirty == null && nb != base) { blitFrame(buf2); }
                else if (rs.length > 0) fadeRects(buf, buf2, rs, fade);
            } else blitFrame(buf2);
            synchronized (drawLock) {
                BufferedImage t = buf; buf = buf2; buf2 = t;
                base = nb; face = nf; lastAt = nat; clocks = nclk; sprites = nsp;
            }
            blit(null);
        } finally { transitioning = false; }
    }

    void blitFrame(BufferedImage f) {
        Graphics g = getGraphics();
        if (g == null) return;
        g.drawImage(f, 0, 0, getWidth(), getHeight(), null);
        g.dispose();
        Toolkit.getDefaultToolkit().sync();
    }

    // ---- one loop for the face and its pop-ups, so they always change together ----
    void displayLoop() {
        String lastOv = "";
        while (true) {
            try {
                String js = new String(read(BASE + "/hv.json?t=" + System.currentTimeMillis()), "UTF-8");
                String at = field(js, "at");
                if (at.length() > 0 && !at.equals(lastAt)) {
                    long t0 = System.currentTimeMillis();
                    BufferedImage n = decode(read(BASE + "/hv.jpg?t=" + t0), W, H);
                    if (n != null) {
                        // wait (briefly) for the pop-ups cut from this exact frame
                        Sprite[] nsp = null; String ov = "";
                        for (int k = 0; k < 15 && nsp == null; k++) {
                            ov = new String(read(BASE + "/ov.json?t=" + System.currentTimeMillis()), "UTF-8");
                            if (field(ov, "at").equals(at)) nsp = loadSprites(ov);
                            if (nsp == null) Thread.sleep(100);
                        }
                        if (nsp == null) nsp = new Sprite[0];
                        lastOv = ov;
                        present(n, field(js, "face"), at, parseClocks(js), nsp, parseDirty(js), 200);
                        log("update " + face + " in " + (System.currentTimeMillis() - t0) + " ms, " + nsp.length + " pop-ups");
                    }
                } else {
                    String ov = new String(read(BASE + "/ov.json?t=" + System.currentTimeMillis()), "UTF-8");
                    if (!ov.equals(lastOv) && field(ov, "at").equals(lastAt)) {
                        Sprite[] nsp = loadSprites(ov);
                        if (nsp != null) { lastOv = ov; present(base, face, lastAt, clocks, nsp, new Rectangle[0], 150); }
                    }
                }
            } catch (OutOfMemoryError oom) {
                spriteCache.clear(); System.gc(); log("out of memory: cleared the pop-up cache");     // never let the display loop die
            } catch (Throwable ex) { }
            try { Thread.sleep(150); } catch (InterruptedException ie) { }
        }
    }

    // ---- audio: one player, newest reply wins, mic muted while speaking ----
    static byte[] wavOf(byte[] pcm) {
        ByteArrayOutputStream o = new ByteArrayOutputStream(pcm.length + 44);
        try {
            AudioInputStream a = new AudioInputStream(new ByteArrayInputStream(pcm), new AudioFormat(44100f, 16, 1, true, false), pcm.length / 2);
            AudioSystem.write(a, AudioFileFormat.Type.WAVE, o);
        } catch (IOException e) { }
        return o.toByteArray();
    }

    void enqueue(byte[] wav, boolean reply) {
        synchronized (audioLock) {
            pendingWav = wav; pendingIsReply = reply;
            SourceDataLine l = curLine;
            if (l != null) { try { l.stop(); l.flush(); l.close(); } catch (Exception e) { } }
            audioLock.notifyAll();
        }
    }

    void audioLoop() {
        while (true) {
            byte[] wav; boolean reply;
            synchronized (audioLock) {
                while (pendingWav == null) { try { audioLock.wait(); } catch (InterruptedException e) { } }
                wav = pendingWav; reply = pendingIsReply; pendingWav = null;
            }
            speaking = true;
            boolean finished = play(wav);
            boolean more;
            synchronized (audioLock) { more = pendingWav != null; }
            if (finished && reply && !more) { try { post(BASE + "/voice-done", new byte[0], "text/plain"); } catch (IOException e) { } }
            try { Thread.sleep(450); } catch (InterruptedException e) { }      // let the room go quiet before listening again
            synchronized (audioLock) { if (pendingWav == null) speaking = false; }
        }
    }

    boolean play(byte[] wav) {
        SourceDataLine out = null;
        try {
            AudioInputStream in = AudioSystem.getAudioInputStream(new ByteArrayInputStream(wav));
            AudioFormat f = in.getFormat();
            out = (SourceDataLine) AudioSystem.getLine(new DataLine.Info(SourceDataLine.class, f));
            out.open(f); out.start();
            curLine = out;
            byte[] b = new byte[4096]; int n;
            while ((n = in.read(b, 0, b.length)) > 0) {
                if (curLine != out || !out.isOpen()) return false;
                out.write(b, 0, n);
            }
            out.drain();
            return curLine == out;
        } catch (Exception ex) {
            return false;
        } finally {
            if (curLine == out) curLine = null;
            if (out != null) { try { out.close(); } catch (Exception ex) { } }
        }
    }

    static void post(String url, byte[] body, String ctype) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setDoOutput(true); c.setRequestMethod("POST"); c.setRequestProperty("Content-Type", ctype);
        c.setRequestProperty("Content-Length", String.valueOf(body.length));
        OutputStream o = c.getOutputStream(); o.write(body); o.close();
        c.getResponseCode(); c.disconnect();
    }

    void micLoop() {
        AudioFormat f = new AudioFormat(44100f, 16, 1, true, false);
        while (true) {
            TargetDataLine line = null;
            try {
                line = (TargetDataLine) AudioSystem.getLine(new DataLine.Info(TargetDataLine.class, f));
                line.open(f, 44100 * 2); line.start();
                byte[] chunk = new byte[44100 * 2 / 4];   // 0.25 s
                while (true) {
                    int got = 0;
                    while (got < chunk.length) { int n = line.read(chunk, got, chunk.length - got); if (n <= 0) break; got += n; }
                    if (speaking) continue;               // never listen to ourselves
                    try { post(BASE + "/audio", chunk, "application/octet-stream"); } catch (IOException ex) { Thread.sleep(2000); }
                }
            } catch (Exception ex) {
                try { Thread.sleep(5000); } catch (InterruptedException ie) { }
            } finally {
                if (line != null) { try { line.close(); } catch (Exception ex) { } }
            }
        }
    }

    static byte[] makeChime() {
        int rate = 44100, n1 = rate * 9 / 100, n2 = rate * 14 / 100, gap = rate / 100;
        byte[] out = new byte[(n1 + gap + n2) * 2];
        int p = 0;
        double[][] notes = { { 1046.5, n1 }, { 0, gap }, { 1568.0, n2 } };
        for (int k = 0; k < notes.length; k++) {
            int len = (int) notes[k][1];
            for (int i = 0; i < len; i++) {
                double env = Math.min(1.0, i / 220.0) * Math.min(1.0, (len - i) / 900.0);
                double v = notes[k][0] == 0 ? 0 : (Math.sin(2 * Math.PI * notes[k][0] * i / rate) + 0.25 * Math.sin(4 * Math.PI * notes[k][0] * i / rate)) * env;
                short s = (short) (v * 11000);
                out[p++] = (byte) s; out[p++] = (byte) (s >> 8);
            }
        }
        return out;
    }

    void voiceLoop() {
        while (true) {
            try {
                String js = new String(read(BASE + "/voice-state?t=" + System.currentTimeMillis()), "UTF-8");
                String p = field(js, "phase");
                if (p.length() > 0 && !p.equals(vPhase)) {
                    String was = vPhase;
                    vPhase = p;
                    if (was.equals("idle") && p.equals("listening") && !speaking) enqueue(chimeWav, false);
                }
                ringing = field(js, "ringing");
                int tc = 0, i = -1;
                while ((i = js.indexOf("\"remaining\"", i + 1)) >= 0) tc++;
                timerCount = tc;
                String rs = field(js, "reply");
                int rid = rs.length() == 0 ? 0 : Integer.parseInt(rs);
                if (lastReply < 0) lastReply = rid;                 // don't replay an old answer at startup
                else if (rid > lastReply) { lastReply = rid; enqueue(read(BASE + "/reply.wav?id=" + rid), true); }
            } catch (Exception ex) { }
            try { Thread.sleep(150); } catch (InterruptedException ie) { }
        }
    }

    // ---- display sleep ----
    boolean sleepHours() { int h = Calendar.getInstance().get(Calendar.HOUR_OF_DAY); return h >= SLEEP_FROM && h < SLEEP_TO; }

    void nudge() {
        if (robot == null) return;
        ignoreMoveUntil = System.currentTimeMillis() + 500;
        try { robot.mouseMove(mouseX + 1, mouseY); robot.mouseMove(mouseX, mouseY); } catch (Exception e) { }
        lastNudge = System.currentTimeMillis();
    }

    BufferedImage shadowStrip(boolean right) {
        BufferedImage s = new BufferedImage(28, H, BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = s.createGraphics();
        g.setPaint(right ? new GradientPaint(0, 0, new Color(0, 0, 0, 110), 28, 0, new Color(0, 0, 0, 0)) : new GradientPaint(0, 0, new Color(0, 0, 0, 0), 28, 0, new Color(0, 0, 0, 110)));
        g.fillRect(0, 0, 28, H); g.dispose();
        return s;
    }

    public void update(Graphics g) { paint(g); }
    public void paint(Graphics g) { synchronized (drawLock) { if (buf != null) g.drawImage(buf, 0, 0, getWidth(), getHeight(), null); } }

    // UI loop: clock sweep and the edge glow, redrawing only their small regions.
    void run() {
        compose(null); blit(null);
        long lastTick = 0, lastGlow = 0;
        String wasPhase = "idle";
        nudge();
        while (true) {
            long now = System.currentTimeMillis();
            boolean voiceOn = !vPhase.equals("idle");
            if (!vPhase.equals(wasPhase) && voiceOn) nudge();          // the wake word wakes a sleeping screen at once
            wasPhase = vPhase;
            if (ringing.length() > 0 && now - lastNudge > 5000) nudge();
            if (now - lastNudge > 60000 && (!sleepHours() || voiceOn || timerCount > 0 || ringing.length() > 0)) nudge();
            if (!transitioning) {
                float target = voiceOn ? (vPhase.equals("speaking") ? 0.7f : 1f) : 0f;
                if ((glowLevel > 0.01f || target > 0) && now - lastGlow > 70) {
                    lastGlow = now;
                    glowLevel += Math.max(-0.12f, Math.min(0.2f, target - glowLevel));
                    if (glowLevel < 0.01f) glowLevel = 0f;
                    if (vPhase.equals("thinking")) glowLevel = Math.min(glowLevel, (float) (0.75 + 0.25 * Math.abs(Math.sin(now / 220.0))));
                    glowOffH = (int) ((now / 9) % W); glowOffV = (int) ((now / 9) % H);
                    for (int i = 0; i < BANDS.length; i++) { compose(BANDS[i]); blit(BANDS[i]); }
                }
                if (clocks.length > 0 && now - lastTick > 120) {
                    lastTick = now;
                    for (int i = 0; i < clocks.length; i++) {
                        double[] c = clocks[i];
                        Rectangle r = new Rectangle((int) (c[0] - c[2] - 2), (int) (c[1] - c[2] - 2), (int) (2 * c[2] + 4), (int) (2 * c[2] + 4));
                        compose(r); blit(r);
                    }
                }
            }
            if (cursorShown && now - lastMove > 2500) hideCursor();
            try { Thread.sleep(25); } catch (InterruptedException ie) { }
        }
    }

    public static void main(String[] args) {
        System.setProperty("sun.net.client.defaultConnectTimeout", "5000");
        System.setProperty("sun.net.client.defaultReadTimeout", "8000");
        java.security.Security.setProperty("networkaddress.cache.ttl", "20");
        if (args.length > 0) BASE = args[0];
        else {
            try {
                BufferedReader r = new BufferedReader(new FileReader(System.getProperty("user.home") + "/HVViewer/server.txt"));
                String line = r.readLine();
                r.close();
                if (line != null && line.trim().length() > 0) BASE = line.trim();
            } catch (IOException e) { }
        }
        while (BASE.endsWith("/")) BASE = BASE.substring(0, BASE.length() - 1);
        final HVViewer f = new HVViewer();
        GraphicsDevice gd = GraphicsEnvironment.getLocalGraphicsEnvironment().getDefaultScreenDevice();
        if (gd.isFullScreenSupported()) gd.setFullScreenWindow(f);
        else { Dimension d = Toolkit.getDefaultToolkit().getScreenSize(); f.setBounds(0, 0, d.width, d.height); f.setVisible(true); }
        f.requestFocus();
        f.buf = f.newFrame(W, H); f.buf2 = f.newFrame(W, H);
        new Thread() { public void run() { f.audioLoop(); } }.start();
        new Thread() { public void run() { f.micLoop(); } }.start();
        new Thread() { public void run() { f.voiceLoop(); } }.start();
        new Thread() { public void run() { f.displayLoop(); } }.start();
        new Thread() { public void run() { f.touchLoop(); } }.start();
        f.run();
    }
}
