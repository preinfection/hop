"""The look of clipper's notifications: drawn with Pillow into a per-pixel-alpha
image (soft shadow, anti-aliased rounded corners, Windows 11 fonts) that
clipper.py shows in a layered window (UpdateLayeredWindow). Tk's canvas
could do none of that: its shapes are aliased and a colour-key window
can't have a shadow or fade.

    render(state, s) -> (PIL.Image RGBA, hit boxes)

state:
    title, sub       text (sub may be "")
    status           "saving" | "done" | "failed" | "rec" | ""
    spin             0..1, the spinner's turn while saving
    picker           None, or {"options": [(15, "15s"), ...], "selected": 30, "hover": 15 or None}
    buttons          None, or {"items": [("go", "Update now"), ("later", "Later")], "hover": "go" or None}
    hover            the pointer is on the card
s is the display scale (1.25 on this laptop)."""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
FONTS = r"C:\Windows\Fonts"
MARGIN = 24                       # room for the shadow around the card (logical px)
W, H, PICK_H = 300, 64, 46        # card, and how much the length picker adds
BTN_H = 42                        # the buttons row (update notice)
BLUE = (10, 132, 255, 255)
RADIUS = 16
SS = 3                            # supersampling for smooth shapes

BG = (26, 26, 30, 246)
BG_HOVER = (32, 32, 37, 248)
BORDER = (255, 255, 255, 20)
TEXT = (245, 245, 247, 255)
DIM = (161, 161, 170, 255)
GREEN = (48, 209, 88, 255)
RED = (255, 69, 58, 255)
PINK = (255, 159, 207, 255)

_font_cache = {}
_bunny = {}


def font(size, weight="regular"):
    key = (size, weight)
    if key not in _font_cache:
        try:
            f = ImageFont.truetype(os.path.join(FONTS, "SegUIVar.ttf"), size)
            f.set_variation_by_axes([600 if weight == "semibold" else 400, 12 if size <= 13 else 36][: len(f.get_variation_axes())])
        except Exception:
            f = ImageFont.truetype(os.path.join(FONTS, "seguisb.ttf" if weight == "semibold" else "segoeui.ttf"), size)
        _font_cache[key] = f
    return _font_cache[key]


def bunny(px):
    if px not in _bunny:
        _bunny[px] = Image.open(os.path.join(HERE, "bunny.png")).convert("RGBA").resize((px, px), Image.LANCZOS)
    return _bunny[px]


def _shape(w, h, r, fill, border):
    """An anti-aliased rounded rectangle (drawn big, scaled down)."""
    big = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), r * SS, fill=fill, outline=border, width=max(1, SS))
    return big.resize((w, h), Image.LANCZOS)


def _pill(w, h, fill):
    big = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), h * SS // 2 if h < 40 else 10 * SS, fill=fill)
    return big.resize((w, h), Image.LANCZOS)


def _clamp(v):
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def _ease_in_out(v):                      # cubic-bezier(.65,0,.35,1)-ish
    v = _clamp(v)
    return 4 * v ** 3 if v < 0.5 else 1 - (-2 * v + 2) ** 3 / 2


def _ease_out(v):
    return 1 - (1 - _clamp(v)) ** 3


def _partial_path(d, pts, frac, fill, width):
    """Draw the first `frac` of a polyline (a stroke being drawn in)."""
    segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    lens = [math.dist(p, q) for p, q in segs]
    left = frac * sum(lens)
    out = [pts[0]]
    for (p, q), ln in zip(segs, lens):
        if left <= 0:
            break
        f = min(1.0, left / ln) if ln else 1.0
        out.append((p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f))
        left -= ln
    if len(out) > 1:
        d.line(out, fill=fill, width=width, joint="curve")
        r = width / 2                     # round caps
        for x, y in (out[0], out[-1]):
            d.ellipse((x - r, y - r, x + r, y + r), fill=fill)


# The timeline, in seconds after the mark appears (same as the demo page)
DONE_LEN = 1.3


def _status(kind, size, spin, t=None):
    """The status mark on the right, as an image `size` px square (drawn on a
    bigger canvas so the pop and glow can spill over; see PAD).
    saving: a pink arc turning       done: the ring closes, the tick draws, pop + glow
    failed: red ring + cross drawn   rec: a red dot breathing   update: an arrow dropping in
    t = seconds since the mark appeared (None: the finished picture)."""
    t = 99.0 if t is None else t
    big = Image.new("RGBA", (size * SS * 2, size * SS * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    S = size * SS
    o = S / 2                                            # the mark's box inside the 2x canvas
    u = S / 22                                           # one unit of the 22-unit design
    lw = max(2, round(2.1 * u))
    if kind == "saving":
        w = max(2, int(S * 0.11))
        d.ellipse((o + w, o + w, o + S - w, o + S - w), outline=(255, 255, 255, 34), width=w)
        start = spin * 360
        d.arc((o + w, o + w, o + S - w, o + S - w), start, start + 95, fill=PINK, width=w)
    elif kind in ("done", "failed"):
        color = GREEN if kind == "done" else RED
        if kind == "done":                               # the glow: a soft green ring of light
            g = _clamp((t - 0.38) / 0.9)
            if 0 < g < 1:
                a = int(90 * (1 - g) * min(1, g * 3))
                rr = S * (0.3 + 0.45 * g)
                d.ellipse((S - rr, S - rr, S + rr, S + rr), fill=(48, 209, 88, a))
        ring = _ease_in_out(t / (0.42 if kind == "done" else 0.38))
        if ring > 0:
            pad = lw / 2 + u
            d.arc((o + pad, o + pad, o + S - pad, o + S - pad), -90, -90 + 360 * ring, fill=color, width=lw)
        P = lambda x, y: (o + x * u, o + y * u)
        if kind == "done":
            _partial_path(d, [P(6.6, 11.4), P(9.6, 14.4), P(15.4, 8.1)], _ease_out((t - 0.33) / 0.30), color, lw + 1)
        else:
            _partial_path(d, [P(7.8, 7.8), P(14.2, 14.2)], _ease_out((t - 0.30) / 0.20), color, lw + 1)
            _partial_path(d, [P(14.2, 7.8), P(7.8, 14.2)], _ease_out((t - 0.42) / 0.20), color, lw + 1)
    elif kind == "rec":
        glow = 0.5 + 0.5 * math.sin(spin * 2 * math.pi)
        r = S * (0.30 + 0.12 * glow)
        d.ellipse((S - r, S - r, S + r, S + r), fill=(255, 69, 58, int(70 * (1 - glow) + 30)))
        r = S * 0.25
        d.ellipse((S - r, S - r, S + r, S + r), fill=RED)
    elif kind == "update":
        pad = lw / 2 + u
        d.ellipse((o + pad, o + pad, o + S - pad, o + S - pad), outline=(10, 132, 255, 95), width=lw)
        ph = spin % 1.0                                   # the arrow drops in, again and again
        dy = (-5 + 9 * _ease_in_out(ph)) * u
        a = int(255 * min(1, ph / 0.3, (1 - ph) / 0.3))
        col = (10, 132, 255, max(0, a))
        d.line([(S, o + 6.5 * u + dy), (S, o + 14.7 * u + dy)], fill=col, width=lw + 1)
        d.line([(o + 7.6 * u, o + 11.4 * u + dy), (S, o + 14.8 * u + dy), (o + 14.4 * u, o + 11.4 * u + dy)],
               fill=col, width=lw + 1, joint="curve")
    img = big.resize((size * 2, size * 2), Image.LANCZOS)
    if kind == "done":                                    # the pop: 1 -> 1.18 -> 1 (a spring)
        k = _clamp((t - 0.33) / 0.52)
        scale = 1 + 0.18 * math.sin(math.pi * min(1, k * 1.25)) * (1 - k * 0.6) if 0 < k < 1 else 1
        if scale != 1:
            n = round(size * 2 * scale)
            img2 = img.resize((n, n), Image.LANCZOS)
            img = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
            img.alpha_composite(img2.crop(((n - size * 2) // 2, (n - size * 2) // 2,
                                           (n - size * 2) // 2 + size * 2, (n - size * 2) // 2 + size * 2)))
    return img


_bases = {}


def _base(cw, ch, m, r, drop, blur, hover):
    """Card + soft shadow (the blur is the costly part, so it is cached: the
    spinner redraws the card 30 times a second)."""
    key = (cw, ch, m, r, drop, blur, hover)
    if key not in _bases:
        img = Image.new("RGBA", (cw + 2 * m, ch + 2 * m), (0, 0, 0, 0))
        card = _shape(cw, ch, r, BG_HOVER if hover else BG, BORDER)
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sh.paste((0, 0, 0, 120), (m, m + drop, m + cw, m + ch + drop), card.split()[3])
        img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(blur)))
        img.alpha_composite(card, (m, m))
        if len(_bases) > 8:
            _bases.clear()
        _bases[key] = img
    return _bases[key]


def card_size(state, s):
    h = H + (PICK_H if state.get("picker") else 0) + (BTN_H if state.get("buttons") else 0)
    return round((W + 2 * MARGIN) * s), round((h + 2 * MARGIN) * s)


def render(state, s=1.0):
    P = lambda v: round(v * s)                                   # logical -> physical px
    picker = state.get("picker")
    buttons = state.get("buttons")
    cw, ch = P(W), P(H + (PICK_H if picker else 0) + (BTN_H if buttons else 0))
    m = P(MARGIN)
    img = _base(cw, ch, m, P(RADIUS), P(6), P(12), bool(state.get("hover"))).copy()
    d = ImageDraw.Draw(img)
    hits = {"card": (m, m, m + cw, m + ch)}

    # bunny, title, subtitle
    bp = P(34)
    img.alpha_composite(bunny(bp), (m + P(15), m + (P(H) - bp) // 2))
    tx = m + P(62)
    title, sub = state.get("title", ""), state.get("sub", "")
    ft, fs = font(P(14), "semibold"), font(P(12))
    kind = state.get("status", "")
    tcol = GREEN if kind == "done" else (255, 105, 97, 255) if kind == "failed" else TEXT   # saved: green, failed: red
    if sub:
        d.text((tx, m + P(H / 2 - 2)), title, font=ft, fill=tcol, anchor="ls")
        d.text((tx, m + P(H / 2 + 15)), sub, font=fs, fill=DIM, anchor="ls")
    else:
        d.text((tx, m + P(H / 2)), title, font=ft, fill=tcol, anchor="lm")

    if kind:
        sz = P(22)
        mark = _status(kind, sz, state.get("spin", 0.0), state.get("t"))
        img.alpha_composite(mark, (m + cw - P(18) - sz - sz // 2, m + (P(H) - sz) // 2 - sz // 2))

    # the length picker: a segmented control inside the same card
    if picker:
        d.line([(m + P(14), m + P(H)), (m + cw - P(14), m + P(H))], fill=(255, 255, 255, 16), width=max(1, P(1)))
        x0, y0 = m + P(14), m + P(H + 6)
        tw, th = cw - P(28), P(30)
        img.alpha_composite(_pill(tw, th, (255, 255, 255, 18)), (x0, y0))
        opts = picker["options"]
        segw = tw // len(opts)
        fo = font(P(13), "semibold")
        for i, (secs, label) in enumerate(opts):
            sx = x0 + i * segw
            sel, hov = secs == picker.get("selected"), secs == picker.get("hover")
            if sel or hov:
                img.alpha_composite(_pill(segw - P(4), th - P(4), (255, 255, 255, 235) if sel else (255, 255, 255, 26)),
                                    (sx + P(2), y0 + P(2)))
            d.text((sx + segw // 2, y0 + th // 2), label, font=fo, anchor="mm",
                   fill=(20, 20, 24, 255) if sel else (230, 230, 235, 255))
            hits[f"len{secs}"] = (sx, y0, sx + segw, y0 + th)
    # buttons under the text (the update notice): white "go", quiet "later"
    if buttons:
        x = m + P(62)
        y = m + P(H - 6)
        fb = font(P(12.5), "semibold")
        for key, label in buttons["items"]:
            tw_ = round(d.textlength(label, font=fb)) + P(24)
            primary = key == "go"
            hov = buttons.get("hover") == key
            fill = ((255, 255, 255, 255) if not hov else (230, 230, 235, 255)) if primary else \
                   ((255, 255, 255, 26) if not hov else (255, 255, 255, 40))
            img.alpha_composite(_pill(tw_, P(28), fill), (x, y))
            d.text((x + tw_ // 2, y + P(14)), label, font=fb, anchor="mm",
                   fill=(17, 17, 17, 255) if primary else (245, 245, 247, 255))
            hits[f"btn_{key}"] = (x, y, x + tw_, y + P(28))
            x += tw_ + P(8)
    return img, hits


if __name__ == "__main__":
    # A preview sheet of every state over a dark desktop-ish background.
    import sys
    s = float(sys.argv[1]) if len(sys.argv) > 1 else 1.25
    states = [
        ("F8 pressed", {"title": "Saving 30s", "sub": "Click to change the length", "status": "saving", "spin": 0.15}),
        ("saved", {"title": "30s saved", "sub": "Click to change the length", "status": "done"}),
        ("clicked: pick a length", {"title": "30s saved", "sub": "Pick a length", "status": "done",
                                    "picker": {"options": [(15, "15s"), (30, "30s"), (60, "1 min")], "selected": 30, "hover": 15}, "hover": True}),
        ("recording started", {"title": "Recording", "sub": "", "status": "rec", "spin": 0.3}),
        ("recording saved", {"title": "2:14 recording saved", "sub": "Click to show it", "status": "done"}),
        ("save failed", {"title": "Couldn't save 30s", "sub": "E: drive missing?", "status": "failed"}),
    ]
    tiles = [render(st, s)[0] for _, st in states]
    cols = 2
    tw = max(t.width for t in tiles)
    th = max(t.height for t in tiles) + round(22 * s)
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * tw + round(40 * s), rows * th + round(40 * s)))
    grad = Image.linear_gradient("L").resize(sheet.size)
    sheet = Image.merge("RGBA", [grad.point(lambda v: 20 + v // 10), grad.point(lambda v: 26 + v // 14),
                                 grad.point(lambda v: 38 + v // 9), Image.new("L", sheet.size, 255)])
    d = ImageDraw.Draw(sheet)
    for i, ((label, _), t) in enumerate(zip(states, tiles)):
        x, y = round(20 * s) + (i % cols) * tw, round(20 * s) + (i // cols) * th
        d.text((x + round(MARGIN * s), y), label, font=font(round(12 * s)), fill=(180, 184, 200, 255))
        sheet.alpha_composite(t, (x, y + round(10 * s)))
    out = os.path.join(os.environ["TEMP"], "clipper-toast-preview.png")
    sheet.convert("RGB").save(out)
    print(out)
