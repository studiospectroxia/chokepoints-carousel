"""
Chokepoints Carousel Generator v2
----------------------------------
Self-contained — downloads fonts on first run, works on any machine.

Usage:
    python3 generate_carousel_v2.py --name "Suez"
    python3 generate_carousel_v2.py --id 1
    python3 generate_carousel_v2.py --all

Requirements:
    pip install pillow requests
"""

import os, math, io, json, argparse, urllib.request
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ── CONFIG ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH    = os.path.join(SCRIPT_DIR, "chokepoints.json")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output_v2")
TILE_CACHE = os.path.join(SCRIPT_DIR, ".tile_cache")
FONTS_DIR  = os.path.join(SCRIPT_DIR, "fonts")
W          = 1080
ACCOUNT    = "@straitsandcanals"
ESRI_URL   = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"

# Fonts — Google Fonts CSS API approach: fetch the CSS, extract the TTF URL, download it
# This is the most reliable method — Google Fonts always serves valid TTF
FONT_URLS = {
    "bold":      "https://fonts.googleapis.com/css2?family=Roboto:wght@700",
    "regular":   "https://fonts.googleapis.com/css2?family=Roboto:wght@400",
    "mono":      "https://fonts.googleapis.com/css2?family=Roboto+Mono:wght@400",
    "mono_bold": "https://fonts.googleapis.com/css2?family=Roboto+Mono:wght@700",
}

# ── PALETTE ────────────────────────────────────────────────────────────────────
DARK       = (6,   13,  26)
DITHER_LIT = (44,  62,  88)
RED        = (255, 60,  40)
AMBER      = (245, 195, 50)
WHITE      = (255, 255, 255)
OFF_WHITE  = (220, 220, 210)

# ── FONT SETUP ─────────────────────────────────────────────────────────────────
def is_valid_ttf(path):
    """Check file starts with TTF/OTF magic bytes."""
    try:
        with open(path, "rb") as f:
            h = f.read(4)
        return h in (b'\x00\x01\x00\x00', b'true', b'OTTO', b'ttcf')
    except:
        return False

def ensure_fonts():
    """
    Downloads fonts via Google Fonts CSS API.
    Fetches the CSS with a desktop User-Agent to get TTF URLs,
    extracts the URL with regex, downloads the actual TTF file.
    """
    import re
    os.makedirs(FONTS_DIR, exist_ok=True)
    
    headers = {
        # Desktop UA gets TTF format (mobile gets woff2 which Pillow can't read)
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    for name, css_url in FONT_URLS.items():
        dest = os.path.join(FONTS_DIR, f"{name}.ttf")
        if os.path.exists(dest) and is_valid_ttf(dest):
            continue
        
        print(f"  Downloading font: {name}...", end=" ", flush=True)
        try:
            # Step 1: Fetch the CSS
            css_r = requests.get(css_url, headers=headers, timeout=10)
            if css_r.status_code != 200:
                print(f"CSS fetch failed ({css_r.status_code})")
                continue
            
            # Step 2: Extract TTF/font URL from CSS
            # CSS contains: src: url(https://fonts.gstatic.com/...) format('truetype')
            urls = re.findall(r'url\((https://fonts\.gstatic\.com/[^)]+)\)', css_r.text)
            if not urls:
                print("no font URL found in CSS")
                continue
            
            # Step 3: Download the actual font file
            font_r = requests.get(urls[0], headers=headers, timeout=15)
            if font_r.status_code == 200 and len(font_r.content) > 5000:
                with open(dest, "wb") as f:
                    f.write(font_r.content)
                if is_valid_ttf(dest):
                    print("done.")
                else:
                    os.remove(dest)
                    print(f"invalid file format ({font_r.content[:4]})")
            else:
                print(f"font download failed ({font_r.status_code})")
        except Exception as e:
            print(f"error: {e}")

def font_path(name):
    p = os.path.join(FONTS_DIR, f"{name}.ttf")
    return p if os.path.exists(p) else None

def load_font(name, pt):
    """Load font at exact point size. pt is relative to 1080px canvas."""
    p = font_path(name)
    if p:
        return ImageFont.truetype(p, pt)
    # Fallback: system fonts
    sys_fallbacks = {
        "bold":    ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"],
        "regular": ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"],
        "mono":    ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"],
        "mono_bold": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"],
    }
    for fp in sys_fallbacks.get(name, []):
        if os.path.exists(fp):
            return ImageFont.truetype(fp, pt)
    print(f"  [warn] no font found for '{name}' at {pt}pt — text will be tiny")
    return ImageFont.load_default()

def calibrated_size(target_fraction):
    """
    Returns a font point size such that a typical headline
    renders at target_fraction of the canvas width (1080px).
    Calibrated against Roboto Bold: ~0.82px per point for avg char.
    """
    # target_fraction = desired rendered width / W for a ~15 char string
    # Roboto Bold: 1pt ≈ 0.75px per character at 96dpi
    # For a 15-char string at fraction 0.75: pt = (0.75 * 1080) / (15 * 0.75) = 72
    return int((target_fraction * W) / 0.75)

def load_fonts():
    """Returns font dict with sizes calibrated to 1080px canvas."""
    ensure_fonts()
    return {
        # Headlines — sized as fraction of canvas width
        "h_hero":   load_font("bold",      int(W * 0.085)),   # ~92px — for short punchy titles
        "h_xl":     load_font("bold",      int(W * 0.072)),   # ~78px
        "h_lg":     load_font("bold",      int(W * 0.060)),   # ~65px
        "h_md":     load_font("bold",      int(W * 0.050)),   # ~54px
        "h_sm":     load_font("bold",      int(W * 0.042)),   # ~45px
        # Body — large and readable
        "body_lg":  load_font("regular",   int(W * 0.034)),   # ~37px
        "body_md":  load_font("regular",   int(W * 0.028)),   # ~30px
        # Labels + UI
        "label":    load_font("mono_bold", int(W * 0.022)),   # ~24px
        "counter":  load_font("mono",      int(W * 0.018)),   # ~19px
    }

def pick_headline_font(text, fonts):
    n = len(text)
    if n <= 25: return fonts["h_hero"]
    if n <= 40: return fonts["h_xl"]
    if n <= 58: return fonts["h_lg"]
    if n <= 75: return fonts["h_md"]
    return fonts["h_sm"]


# ── SLIDE LAYOUT DEFINITIONS ───────────────────────────────────────────────────
# filter: "dither" or "ascii"
# tint_dark / tint_lit = the two colours for dither slides
SLIDE_DEFS = [
    # Slide 1 — dither, cold blue, map visible top half
    {"layout": "HERO",         "zoom_offset": -1, "accent": RED,
     "filter": "dither",       "overlay": "top_clear",
     "tint_dark": (4,  10, 22),  "tint_lit": (52, 78, 110),  "threshold": 0.38},

    # Slide 2 — dither, warmer teal, location dot, map readable
    {"layout": "TOP_HEAVY",    "zoom_offset":  0, "accent": AMBER,
     "filter": "dither",       "overlay": "split_mid",    "show_dot": True,
     "tint_dark": (5,  18, 28),  "tint_lit": (48, 88, 100),  "threshold": 0.42},

    # Slide 3 — ASCII, stat card, zoomed out
    {"layout": "STAT_CARD",    "zoom_offset": -2, "accent": AMBER,
     "filter": "ascii",        "overlay": "center_clear",
     "tint_dark": (3,   8, 18),  "tint_lit": (60, 85, 105),  "threshold": 0.45},

    # Slide 4 — dither, red threat tint, danger energy
    {"layout": "SPLIT_BOTTOM", "zoom_offset":  0, "accent": RED,
     "filter": "dither",       "overlay": "top_clear",
     "tint_dark": (18,  5,  8),  "tint_lit": (88, 42, 38),   "threshold": 0.40},

    # Slide 5 — dither, neutral blue-grey, zoomed out world view
    {"layout": "BOTTOM_BLOCK", "zoom_offset": -3, "accent": AMBER,
     "filter": "dither",       "overlay": "split_mid",
     "tint_dark": (6,  12, 24),  "tint_lit": (55, 72, 90),   "threshold": 0.43},

    # Slide 6 — ASCII, CTA, darkest
    {"layout": "CTA",          "zoom_offset": -2, "accent": RED,
     "filter": "ascii",        "overlay": "full_soft",
     "tint_dark": (4,   8, 18),  "tint_lit": (40, 58, 80),   "threshold": 0.35},
]


# ── MAP TILES ──────────────────────────────────────────────────────────────────
def deg2tile(lat, lon, z):
    lr = math.radians(lat)
    n  = 2 ** z
    return (int((lon+180)/360*n),
            int((1 - math.log(math.tan(lr)+1/math.cos(lr))/math.pi)/2*n))

def lat_lon_to_pixel(lat, lon, zoom):
    """
    Returns the exact (x, y) pixel position of lat/lon on the rendered 1080x1080 slide.

    How it works:
      - We fetch a 3x3 grid of 256px tiles centred on tile (cx, cy)
      - The mosaic is 768x768, then resized to 1080x1080
      - The mosaic's top-left is tile (cx-1, cy-1)
      - So the target's pixel in the mosaic = (fx - (cx-1)) * 256
      - Then scale by 1080/768

    Uses pure float math throughout — no int truncation until the very end.
    """
    lat_r = math.radians(lat)
    n     = 2 ** zoom

    # Exact fractional tile coordinates
    fx = (lon + 180) / 360 * n
    fy = (1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n

    # Integer centre tile (floor, same as deg2tile)
    cx = int(fx)
    cy = int(fy)

    # Position within the 768px mosaic
    mosaic_x = (fx - (cx - 1)) * 256
    mosaic_y = (fy - (cy - 1)) * 256

    # Scale to 1080px canvas
    scale = W / 768.0
    return (mosaic_x * scale, mosaic_y * scale)

def fetch_map(lat, lon, zoom):
    os.makedirs(TILE_CACHE, exist_ok=True)
    px = 256
    cx, cy = deg2tile(lat, lon, zoom)
    mosaic = Image.new("RGB", (px*3, px*3), DARK)
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            tx, ty = cx+dx, cy+dy
            cp = os.path.join(TILE_CACHE, f"esri_{zoom}_{tx}_{ty}.png")
            if os.path.exists(cp):
                tile = Image.open(cp).convert("RGB")
            else:
                try:
                    r = requests.get(ESRI_URL.format(z=zoom, x=tx, y=ty),
                                     timeout=12, headers={"User-Agent": "chokepoints/1.0"})
                    if r.status_code == 200:
                        tile = Image.open(io.BytesIO(r.content)).convert("RGB")
                        tile.save(cp)
                    else:
                        tile = _placeholder(px)
                except:
                    tile = _placeholder(px)
            mosaic.paste(tile, ((dx+1)*px, (dy+1)*px))
    return mosaic.resize((W, W), Image.LANCZOS)

def _placeholder(size):
    import random; rng = random.Random(7)
    img = Image.new("RGB", (size, size), DARK)
    d   = ImageDraw.Draw(img)
    for _ in range(8):
        pts = [(rng.randint(0,size), rng.randint(0,size)) for _ in range(5)]
        s   = rng.randint(16, 46)
        d.polygon(pts, fill=(s, s+4, s+9))
    return img.filter(ImageFilter.GaussianBlur(1.5))


# ── DITHER ─────────────────────────────────────────────────────────────────────
def dither(img, threshold=0.38, dark=DARK, lit=DITHER_LIT):
    """
    Floyd-Steinberg dither.
    - threshold: higher = more lit pixels = map reads brighter and clearer
    - dark/lit: the two output colours — vary per slide for tint variation
    Uses 4x4 contrast boost before dithering so land/sea separation is clear.
    """
    # Boost contrast so satellite land/sea difference is amplified before dither
    gray = img.convert("L")
    # Stretch histogram: find 10th and 90th percentile and stretch to 0-255
    pixels = sorted(gray.getdata())
    n = len(pixels)
    p10 = pixels[int(n * 0.08)]
    p90 = pixels[int(n * 0.72)]
    span = max(1, p90 - p10)

    w, h = gray.size
    buf  = []
    for p in gray.getdata():
        stretched = (p - p10) / span
        buf.append(max(0.0, min(1.0, stretched)))

    # Floyd-Steinberg
    for y in range(h):
        for x in range(w):
            idx = y*w+x; old = buf[idx]
            nv = 1.0 if old > threshold else 0.0
            buf[idx] = nv; e = old - nv
            if x+1<w:           buf[idx+1]   += e*7/16
            if x>0 and y+1<h:   buf[idx+w-1] += e*3/16
            if y+1<h:           buf[idx+w]   += e*5/16
            if x+1<w and y+1<h: buf[idx+w+1] += e/16

    out = Image.new("RGB", (w, h)); px = out.load()
    for y in range(h):
        for x in range(w):
            px[x,y] = lit if buf[y*w+x] > 0.5 else dark
    return out


# ── ASCII FILTER ───────────────────────────────────────────────────────────────
def ascii_filter(img, char_size=14, dark=DARK, lit=None):
    """
    Renders the image as an ASCII art grid.
    Each cell picks a character based on brightness:
    dense chars = bright (land), sparse = dark (ocean).
    Returns an RGB image the same size as input.
    """
    # Characters ordered dark → light (sparse → dense)
    CHARS = " .'`^,:;Il!i><~+_-?][}{1)(|/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$"
    n_chars = len(CHARS)

    gray  = img.convert("L")
    w, h  = gray.size

    # Output canvas
    out = Image.new("RGB", (w, h), dark)
    draw = ImageDraw.Draw(out)

    # Load a small mono font for the characters
    char_font = None
    mono_paths = [
        os.path.join(FONTS_DIR, "mono.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ]
    for p in mono_paths:
        if os.path.exists(p):
            char_font = ImageFont.truetype(p, char_size)
            break
    if char_font is None:
        char_font = ImageFont.load_default()

    # Character cell size
    bbox     = char_font.getbbox("M")
    cell_w   = bbox[2] - bbox[0]
    cell_h   = bbox[3] - bbox[1] + 2

    cols = w // cell_w
    rows = h // cell_h

    # Histogram stretch for contrast
    pixels = sorted(gray.getdata())
    n      = len(pixels)
    p_lo   = pixels[int(n * 0.05)]
    p_hi   = pixels[int(n * 0.80)]
    span   = max(1, p_hi - p_lo)

    for row in range(rows):
        for col in range(cols):
            # Sample brightness from center of cell
            sx = min(w-1, col * cell_w + cell_w // 2)
            sy = min(h-1, row * cell_h + cell_h // 2)
            brightness = gray.getpixel((sx, sy))
            # Stretch and clamp
            b_norm = max(0.0, min(1.0, (brightness - p_lo) / span))
            char   = CHARS[int(b_norm * (n_chars - 1))]
            if char == " ":
                continue  # skip blanks — background shows through
            # Color: interpolate between dark and a lighter tint
            intensity = int(b_norm * 180)
            r = dark[0] + intensity // 3
            g = dark[1] + intensity // 2
            b = dark[2] + intensity
            color = (min(255, r), min(255, g), min(255, b))
            draw.text((col * cell_w, row * cell_h), char,
                      font=char_font, fill=color)

    return out


# ── OVERLAYS ───────────────────────────────────────────────────────────────────
def apply_overlay(img, style, dark=DARK):
    """
    Varied overlay styles so slides feel different:
    - top_clear:    map fully visible top 50%, fades to dark at bottom
    - split_mid:    light vignette top, strong dark bottom third
    - center_clear: map visible in center band, dark top and bottom
    - full_soft:    uniform dark-ish overlay, map shows as texture
    """
    size = img.size[0]
    ov   = Image.new("RGBA", (size, size), (0,0,0,0))
    d    = ImageDraw.Draw(ov)

    for y in range(size):
        t = y / size

        if style == "top_clear":
            # Map crystal clear in top half, fades to near-black at bottom 35%
            if t < 0.45:
                a = int(t * 40)                          # barely visible vignette top
            else:
                a = int(40 + ((t-0.45)/0.55)**2.2 * 215)

        elif style == "split_mid":
            # Top 30% visible, middle transition, bottom 40% dark for text
            if t < 0.28:
                a = int(t * 60)
            elif t < 0.55:
                a = int(60 + ((t-0.28)/0.27) * 80)
            else:
                a = int(140 + ((t-0.55)/0.45)**1.6 * 105)

        elif style == "center_clear":
            # Darkest at very top and very bottom, clearest in center band
            dist_from_center = abs(t - 0.42)
            a = int(30 + dist_from_center * 2.2 * 200)

        elif style == "full_soft":
            # Uniform but not completely opaque — map shows as texture
            a = 165

        else:  # fallback
            a = int(min(238, t**1.6 * 245))

        d.line([(0,y),(size,y)], fill=(*dark, min(248, max(0, a))))

    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


# ── TEXT DRAWING ───────────────────────────────────────────────────────────────
PAD = 64  # side padding in pixels

def wrap_draw(draw, text, font, x, y, max_w, color, lh=1.25, align="left"):
    words = text.split(); lines, cur = [], []
    for w in words:
        t = " ".join(cur + [w])
        if font.getbbox(t)[2] > max_w and cur:
            lines.append(" ".join(cur)); cur = [w]
        else:
            cur.append(w)
    if cur: lines.append(" ".join(cur))
    line_h = int(font.getbbox("Ag")[3] * lh)
    for line in lines:
        lx = x - font.getbbox(line)[2]//2 if align == "center" else x
        draw.text((lx, y), line, font=font, fill=color)
        y += line_h
    return y

def block_h(text, font, max_w, lh=1.25):
    words = text.split(); lines, cur = [], []
    for w in words:
        t = " ".join(cur + [w])
        if font.getbbox(t)[2] > max_w and cur:
            lines.append(" ".join(cur)); cur = [w]
        else:
            cur.append(w)
    if cur: lines.append(" ".join(cur))
    return int(font.getbbox("Ag")[3] * lh) * len(lines)

def bar(draw, x, y, w, color, h=5):
    draw.rectangle([(x, y), (x+w, y+h)], fill=color)

def dot(draw, cx, cy, accent):
    for r, a in [(34, 40), (20, 0), (11, 255)]:
        if a == 0:
            draw.ellipse([(cx-r, cy-r),(cx+r, cy+r)], outline=(*accent, 190), width=3)
        else:
            draw.ellipse([(cx-r, cy-r),(cx+r, cy+r)], fill=(*accent, a))

def topbar(draw, fonts, num):
    draw.text((PAD, 44), f"{num:02d} / 06", font=fonts["counter"], fill=(*WHITE, 65))
    aw = fonts["counter"].getbbox(ACCOUNT)[2]
    draw.text((W-PAD-aw, 44), ACCOUNT, font=fonts["counter"], fill=(*WHITE, 65))


# ── LAYOUTS ────────────────────────────────────────────────────────────────────
def layout_hero(d, f, data, accent):
    """Big headline anchored to bottom-left. Accent bar above it."""
    max_w    = W - PAD*2
    headline = data["headline"]
    body     = data["body"]
    label    = data["label"]
    hf       = pick_headline_font(headline, f)
    hh       = block_h(headline, hf, max_w, 1.18)
    bh       = block_h(body, f["body_lg"], max_w, 1.45)
    total    = 28 + 10 + 24 + hh + 30 + bh
    y        = W - 80 - total

    d.text((PAD, y), label, font=f["label"], fill=(*accent, 255))
    y += 32; bar(d, PAD, y, 90, accent, 6); y += 24
    y  = wrap_draw(d, headline, hf, PAD, y, max_w, (*WHITE, 255), 1.18)
    y += 30
    wrap_draw(d, body, f["body_lg"], PAD, y, max_w, (*OFF_WHITE, 195), 1.45)


def draw_map_labels(draw, labels, lat, lon, zoom, fonts, text_zone_bottom):
    """
    Renders nearby place labels at their exact geographic positions.
    Loads fonts directly from disk so it works even if main font download failed.
    """
    def _font(size):
        for p in [
            os.path.join(FONTS_DIR, "regular.ttf"),
            os.path.join(FONTS_DIR, "bold.ttf"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]:
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
        return ImageFont.load_default()

    def _mono(size):
        for p in [
            os.path.join(FONTS_DIR, "mono.ttf"),
            os.path.join(FONTS_DIR, "mono_bold.ttf"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        ]:
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
        return _font(size)

    type_fonts = {
        "country": _mono(int(W * 0.016)),     # smaller — like a real atlas
        "water":   _font(int(W * 0.020)),     # italic-feel regular, medium
        "city":    _mono(int(W * 0.013)),     # tiny
        "region":  _mono(int(W * 0.013)),     # tiny muted
    }
    type_colors = {
        "country": (210, 210, 200),           # off-white, not full white — more map-like
        "water":   (100, 165, 210),           # clear blue tint
        "city":    (175, 172, 162),           # warm grey
        "region":  (130, 128, 120),           # most muted
    }
    # Letter spacing simulation: insert thin spaces between chars for country/region
    def spaced(text, t):
        if t in ("country", "region"):
            return " ".join(list(text))       # single space — tighter, cleaner
        return text

    placed = []  # track bounding boxes to avoid overlap

    def overlaps(x, y, w, h):
        pad = 18
        for (ox, oy, ow, oh) in placed:
            if (x - pad < ox + ow and x + w + pad > ox and
                y - pad < oy + oh and y + h + pad > oy):
                return True
        return False

    # Sort: water first (biggest, most background), then country, region, city
    order = {"water": 0, "country": 1, "region": 2, "city": 3}
    sorted_labels = sorted(labels, key=lambda l: order.get(l["type"], 9))

    print(f"    [map labels] {len(sorted_labels)} labels, zoom={zoom}, text_zone_bottom={text_zone_bottom}")
    for lbl in sorted_labels:
        ltype = lbl["type"]
        font  = type_fonts.get(ltype, type_fonts.get("city"))
        color = type_colors.get(ltype, (180, 180, 170))
        text  = spaced(lbl["name"], ltype)

        # Pixel position
        px, py = lat_lon_to_pixel(lbl["lat"], lbl["lon"], zoom)
        px, py = int(px), int(py)

        # Skip if off canvas with margin
        if not (20 < px < W - 20 and 20 < py < W - 20):
            print(f"      SKIP canvas:   {lbl['name']} px={px} py={py}")
            continue

        # Measure text
        bb = font.getbbox(text)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]

        # Centre the label on its coordinate
        lx = px - tw // 2
        ly = py - th // 2

        # Skip if it overlaps the text content zone at the bottom
        if ly + th > text_zone_bottom - 20:
            print(f"      SKIP zone:     {lbl['name']} py={py} ly={ly} th={th} bottom={ly+th} zone={text_zone_bottom}")
            continue

        # Skip if it overlaps an already-placed label
        if overlaps(lx, ly, tw, th):
            print(f"      SKIP overlap:  {lbl['name']} ({lx},{ly},{tw},{th})")
            continue

        # Draw city dot marker
        if ltype == "city":
            r = 3
            draw.ellipse([(px-r, py-r), (px+r, py+r)], fill=(*color[:3], 200))
            ly = py - th // 2 + 10  # nudge text below dot

        # Shadow for readability
        draw.text((lx+1, ly+1), text, font=font, fill=(0, 0, 0))
        draw.text((lx, ly), text, font=font, fill=color)
        placed.append((lx, ly, tw, th))
        print(f"      DREW:          {lbl['name']} at ({lx},{ly}) size={tw}x{th} color={color}")

def layout_top_heavy(d, f, data, accent, show_dot=False, dot_xy=None,
                     nearby_labels=None, lat=None, lon=None, zoom=None):
    """Headline at top, map in middle, body at bottom. Map labels in middle zone."""
    max_w = W - PAD*2

    # Measure body block height so we know where text starts
    bh = block_h(data["body"], f["body_md"], max_w, 1.45)
    text_zone_top = W - 72 - bh - 20  # top of body text block

    # Top: label + bar + headline
    d.text((PAD, 130), data["label"], font=f["label"], fill=(*accent, 230))
    bar(d, PAD, 164, 60, accent, 5)
    hf = pick_headline_font(data["headline"], f)
    y  = wrap_draw(d, data["headline"], hf, PAD, 180, max_w, (*WHITE, 255), 1.18)

    # Location dot — placed after headline, clamped above text zone
    if show_dot and dot_xy:
        dx, dy = int(dot_xy[0]), int(dot_xy[1])
        dy = max(y + 50, min(text_zone_top - 60, dy))
        dot(d, dx, dy, accent)

    # Body at bottom
    wrap_draw(d, data["body"], f["body_md"], PAD, W - 72 - bh, max_w, (*OFF_WHITE, 195), 1.45)

def layout_stat_card(d, f, data, accent):
    """Big stat centered vertically."""
    max_w = W - PAD*2
    hf    = pick_headline_font(data["headline"], f)
    lh    = int(f["label"].getbbox("Ag")[3])
    hh    = block_h(data["headline"], hf, max_w, 1.18)
    bh    = block_h(data["body"], f["body_lg"], max_w, 1.45)
    total = lh + 14 + 8 + hh + 32 + bh
    y     = (W - total) // 2

    d.text((PAD, y), data["label"], font=f["label"], fill=(*accent, 230))
    y += lh + 14; bar(d, PAD, y, 100, accent, 7); y += 18
    y  = wrap_draw(d, data["headline"], hf, PAD, y, max_w, (*WHITE, 255), 1.18)
    y += 32
    wrap_draw(d, data["body"], f["body_lg"], PAD, y, max_w, (*OFF_WHITE, 190), 1.45)

def layout_split_bottom(d, f, data, accent):
    """Full-width red bar, threat energy, big headline."""
    max_w = W - PAD*2
    hf    = pick_headline_font(data["headline"], f)
    lh    = int(f["label"].getbbox("Ag")[3])
    hh    = block_h(data["headline"], hf, max_w, 1.18)
    bh    = block_h(data["body"], f["body_lg"], max_w, 1.45)
    total = 8 + 24 + lh + 28 + hh + 28 + bh
    y     = W - 80 - total

    bar(d, PAD, y, W - PAD*2, accent, 5); y += 20
    d.text((PAD, y), data["label"], font=f["label"], fill=(*accent, 255))
    y += lh + 28
    y  = wrap_draw(d, data["headline"], hf, PAD, y, max_w, (*WHITE, 255), 1.18)
    y += 28
    wrap_draw(d, data["body"], f["body_lg"], PAD, y, max_w, (*OFF_WHITE, 185), 1.45)

def layout_bottom_block(d, f, data, accent):
    """Clean bottom. Label, bar, headline, body."""
    max_w = W - PAD*2
    hf    = pick_headline_font(data["headline"], f)
    lh    = int(f["label"].getbbox("Ag")[3])
    hh    = block_h(data["headline"], hf, max_w, 1.18)
    bh    = block_h(data["body"], f["body_md"], max_w, 1.45)
    total = lh + 14 + 8 + hh + 28 + bh
    y     = W - 80 - total

    d.text((PAD, y), data["label"], font=f["label"], fill=(*accent, 230))
    y += lh + 14; bar(d, PAD, y, 70, accent, 5); y += 20
    y  = wrap_draw(d, data["headline"], hf, PAD, y, max_w, (*WHITE, 255), 1.18)
    y += 28
    wrap_draw(d, data["body"], f["body_md"], PAD, y, max_w, (*OFF_WHITE, 185), 1.45)

def layout_cta(d, f, data, accent):
    """Centered CTA — everything on axis."""
    max_w = W - PAD*2
    hf    = pick_headline_font(data["headline"], f)
    lh    = int(f["label"].getbbox("Ag")[3])
    hh    = block_h(data["headline"], hf, max_w, 1.18)
    bh    = block_h(data["body"], f["body_lg"], max_w, 1.45)
    total = lh + 20 + hh + 32 + bh
    y     = (W - total) // 2

    lw = f["label"].getbbox(data["label"])[2]
    d.text((W//2 - lw//2, y), data["label"], font=f["label"], fill=(*accent, 230))
    y += lh + 20
    y  = wrap_draw(d, data["headline"], hf, W//2, y, max_w, (*WHITE, 255), 1.18, align="center")
    y += 32
    wrap_draw(d, data["body"], f["body_lg"], W//2, y, max_w, (*OFF_WHITE, 185), 1.45, align="center")
    hw = f["label"].getbbox(ACCOUNT)[2]
    d.text((W//2 - hw//2, W-72), ACCOUNT, font=f["label"], fill=(*accent, 185))


# ── RENDER ─────────────────────────────────────────────────────────────────────
def render_slide(map_img, slide_def, slide_data, slide_num, fonts, dot_xy=None, nearby_labels=None, entry_lat=None, entry_lon=None, slide_zoom=None):
    if slide_num == 2:
        print(f"    [debug slide 2] nearby_labels={'YES '+str(len(nearby_labels))+' items' if nearby_labels else 'NONE — check chokepoints.json has nearby_labels field'}")
    tint_dark = slide_def.get("tint_dark", DARK)
    tint_lit  = slide_def.get("tint_lit",  DITHER_LIT)
    threshold = slide_def.get("threshold", 0.38)
    filt      = slide_def.get("filter", "dither")

    if filt == "ascii":
        filtered = ascii_filter(map_img, char_size=13, dark=tint_dark)
    else:
        filtered = dither(map_img, threshold=threshold, dark=tint_dark, lit=tint_lit)

    base   = apply_overlay(filtered, slide_def["overlay"], dark=tint_dark)
    canvas = base.convert("RGBA")
    ov     = Image.new("RGBA", (W, W), (0,0,0,0))
    d      = ImageDraw.Draw(ov)
    accent = slide_def["accent"]

    topbar(d, fonts, slide_num)

    layout = slide_def["layout"]
    if   layout == "HERO":         layout_hero(d, fonts, slide_data, accent)
    elif layout == "TOP_HEAVY":    layout_top_heavy(d, fonts, slide_data, accent, slide_def.get("show_dot"), dot_xy=dot_xy, nearby_labels=nearby_labels, lat=entry_lat, lon=entry_lon, zoom=slide_zoom)
    elif layout == "STAT_CARD":    layout_stat_card(d, fonts, slide_data, accent)
    elif layout == "SPLIT_BOTTOM": layout_split_bottom(d, fonts, slide_data, accent)
    elif layout == "BOTTOM_BLOCK": layout_bottom_block(d, fonts, slide_data, accent)
    elif layout == "CTA":          layout_cta(d, fonts, slide_data, accent)

    final = Image.alpha_composite(canvas, ov).convert("RGB")

    # Draw map labels on the final RGB image — must be last so they're always visible
    if nearby_labels and slide_def.get("layout") == "TOP_HEAVY" and entry_lat is not None:
        from PIL import ImageDraw as _ID
        label_draw = _ID.Draw(final)
        bh = block_h(slide_data.get("body",""), fonts.get("body_md", fonts.get("body_lg")), W - PAD*2, 1.45)
        text_zone_top = W - 72 - bh - 20
        draw_map_labels(label_draw, nearby_labels, entry_lat, entry_lon, slide_zoom, fonts, text_zone_top)

    return final


# ── GENERATE ───────────────────────────────────────────────────────────────────
def generate(entry):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    slug  = entry["name"].lower().replace(" ", "_")
    lat   = entry["coordinates"]["lat"]
    lon   = entry["coordinates"]["lon"]
    zoom  = entry.get("map_zoom", 7)
    fonts = load_fonts()

    print(f"\n  {entry['name']}")
    paths = []
    for i, sdef in enumerate(SLIDE_DEFS, 1):
        z    = max(2, zoom + sdef.get("zoom_offset", 0))
        data = entry["carousel"][f"slide{i}"]
        # Merge dot coords from DB into slide_def for top_heavy
        if sdef.get("show_dot") and "dot_x" in data:
            sdef = dict(sdef, show_dot=True)

        print(f"    [{i}/6] map z{z}...", end=" ", flush=True)
        map_img = fetch_map(lat, lon, z)
        # Compute exact pixel position of the chokepoint on this slide's map
        dot_xy  = lat_lon_to_pixel(lat, lon, z) if sdef.get("show_dot") else None
        print("render...", end=" ", flush=True)
        slide = render_slide(map_img, sdef, data, i, fonts, dot_xy=dot_xy,
                          nearby_labels=entry.get('nearby_labels'), entry_lat=lat, entry_lon=lon, slide_zoom=z)
        path  = os.path.join(OUTPUT_DIR, f"{slug}_slide_{i:02d}.png")
        slide.save(path, "PNG")
        paths.append(path)
        print("saved.")
    return paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", type=str)
    ap.add_argument("--id",   type=int)
    ap.add_argument("--all",  action="store_true")
    args = ap.parse_args()

    with open(DB_PATH) as f:
        db = json.load(f)

    if args.id:       entries = [e for e in db if e["id"] == args.id]
    elif args.name:   entries = [e for e in db if args.name.lower() in e["name"].lower()]
    elif args.all:    entries = [e for e in db if e.get("post_status") == "pending"]
    else:             entries = [e for e in db if e.get("post_status") == "pending"][:1]

    if not entries: print("No entries found."); return
    for entry in entries:
        generate(entry)
    print(f"\n  Done. Slides in: {OUTPUT_DIR}/")

if __name__ == "__main__":
    main()