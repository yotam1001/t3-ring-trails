"""Build an animated ASCII T3 Code theme from a star-trail image.

    python engine/build_theme.py source/ring-trails.jpg themes/ring-trails-ascii.json

Layers (all pure CSS, no scripts):
  html::before  the image as a grid of monospace glyphs, coloured with a per-glyph colour map
  html::after   an animated SVG: comets that travel along streaks traced from the image,
                plus a dotted outline around the black hole
  body::after   scanlines and vignette
"""
import argparse, base64, io, json, re
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from flow import Flow, W, H

HERE = Path(__file__).resolve().parent
MONO = '"Cascadia Mono",Consolas,ui-monospace,"Courier New",monospace'
RAMP = " .:;+*o#%@"   # brightness ramp
FLAT = " .--==*#%@"   # same density, streak-shaped glyphs where trails run flat
LIMIT = 50_000        # T3 Code rejects theme CSS longer than this


def b64(d):
    return base64.b64encode(d).decode()


class Builder:
    def __init__(self, image_path, cols=240):
        self.src = Image.open(image_path).convert("RGB")
        self.cols, self.rows = cols, round(cols / 2 / 1.51)
        self.flow = Flow(self.src)
        self.rgb = np.asarray(self.src.resize((W, H), Image.LANCZOS)).astype(float)

    def cellmean(self, a):
        R, C = self.rows, self.cols
        h, w = a.shape[:2]
        ys = (np.arange(R + 1) * h / R).astype(int)
        xs = (np.arange(C + 1) * w / C).astype(int)
        out = np.zeros((R, C) + a.shape[2:], float)
        for i in range(R):
            band = a[ys[i]:ys[i + 1]].mean(0)
            for j in range(C):
                out[i, j] = band[xs[j]:xs[j + 1]].mean(0)
        return out

    # -- black hole outline: funnel silhouette + the lip where the bright rings begin
    def hole(self):
        R, C = self.rows, self.cols
        blur = np.asarray(self.src.convert("L").resize((C * 4, R * 6), Image.LANCZOS)
                          .filter(ImageFilter.GaussianBlur(10)).resize((C, R), Image.BOX)).astype(float)
        pts = []
        for y in range(R // 2):
            br = np.nonzero(blur[y] > 16)[0]
            if len(br) and y > 2:
                pts.append((y, int(br.min()), 1))
                if br.min() == 0:
                    break
            else:
                f = np.nonzero(blur[y, :C // 2] > 3.6)[0]
                pts.append((y, int(f.max()) if len(f) else 0, 0))
        rim = [p for p in pts if p[2] == 0]
        rim = [p for p in rim if p[1] <= rim[0][1] + 3]
        path = rim + [p for p in pts if p[2] == 1]

        mask = np.zeros((R, C), bool)
        for y, x, _ in path:
            mask[y, :x] = True
        mask[:path[0][0], :path[0][1]] = True

        P = np.array([(x + .5, (y + .5) * (C / 2) / R) for y, x, _ in path], float)
        for _ in range(3):
            P[:, 0] = np.convolve(np.pad(P[:, 0], 3, mode="edge"), np.ones(7) / 7, mode="valid")
        P = np.vstack([[P[0][0], 0], P[:-1:2], P[-1:]])
        d = "M%.1f %.1f" % tuple(P[0])
        for i in range(len(P) - 1):  # Catmull-Rom -> cubic Bezier
            p0, p1, p2, p3 = P[max(i - 1, 0)], P[i], P[i + 1], P[min(i + 2, len(P) - 1)]
            c1, c2 = p1 + (p2 - p0) / 6, p2 - (p3 - p1) / 6
            d += "C%.1f %.1f %.1f %.1f %.1f %.1f" % (*c1, *c2, *p2)
        return d, mask

    def glyphs(self, hole_mask):
        f = self.flow
        I = self.rgb / 255
        lum = self.cellmean(I[..., 0] * .22 + I[..., 1] * .4 + I[..., 2] * .13 + I.max(-1) * .25)
        lum = np.clip((lum - .06) / .7, 0, 1) ** 1.1
        inner = np.clip((self.cellmean(I[..., 0] * .3 + I[..., 1] * .5 + I[..., 2] * .2) - .012) / .11, 0, 1) ** .8 * .3
        c2 = self.cellmean(np.stack([np.cos(2 * f.theta) * f.coh, np.sin(2 * f.theta) * f.coh], -1))
        t = .5 * np.arctan2(c2[..., 1], c2[..., 0])
        k = np.hypot(c2[..., 0], c2[..., 1])
        out = []
        for i in range(self.rows):
            for j in range(self.cols):
                L = max(lum[i, j], inner[i, j]) if hole_mask[i, j] else lum[i, j]
                n = min(int(L * len(RAMP) + .35), len(RAMP) - 1)
                a = abs(np.degrees(t[i, j])) % 180
                a = min(a, 180 - a)
                out.append((FLAT if k[i, j] > .3 and a < 33 else RAMP)[n])
        return "".join(out)

    def colour_map(self):
        c = self.cellmean(self.rgb)
        c = c / np.maximum(c.max(-1, keepdims=True), 1) * 255
        c = np.clip(c.mean(-1, keepdims=True) + (c - c.mean(-1, keepdims=True)) * 1.5, 110, 255)
        buf = io.BytesIO()
        Image.fromarray(c.astype(np.uint8)).save(buf, "WEBP", quality=80, method=6)
        return "url(data:image/webp;base64," + b64(buf.getvalue()) + ")"

    def comets(self):
        f = self.flow
        paths = f.trace(n=16, minlen=200, seed=2, seed_lum=.15, stop_lum=.06) + \
            f.trace(n=10, minlen=120, seed=3, seed_lum=.035, stop_lum=.02)
        cx, cy = W * .6, H * .62
        rng = np.random.default_rng(11)
        U = self.cols / W
        out = []
        for p in paths:
            v, r = p[1:] - p[:-1], p[:-1] - [cx, cy]
            if np.sum(r[:, 0] * v[:, 1] - r[:, 1] * v[:, 0]) < 0:
                p = p[::-1]  # everything orbits the same way
            d = "M" + " ".join("%.1f %.1f" % tuple(z) for z in p[::4] * U)
            mid = p[len(p) // 2].astype(int)
            col = self.rgb[np.clip(mid[1], 0, H - 1), np.clip(mid[0], 0, W - 1)]
            hexc = "ff8f78" if col[0] > col[2] * 1.25 and col[0] > col[1] * 1.3 else "cfe0ff"
            dur = 6 + 22 * np.hypot(*(p.mean(0) - [cx, cy])) / W + rng.uniform(-1.5, 1.5)  # inner = faster
            out.append((d, hexc, dur, rng.uniform(0, dur)))
        return out

    def svg(self, hole_d):
        s = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 %d %d' preserveAspectRatio='none'>"
             "<style>path{fill:none;stroke-linecap:round}"
             "use{animation:linear infinite;animation-duration:var(--d);animation-delay:var(--l)}"
             ".a{stroke-width:.3;stroke-opacity:.16;stroke-dasharray:16 84;animation-name:a}"
             ".b{stroke-width:.36;stroke-opacity:.45;stroke-dasharray:5 95;animation-name:b}"
             ".h{stroke:%%23fff;stroke-width:.55;stroke-dasharray:1.2 98.8;animation-name:h}"
             "@keyframes a{from{stroke-dashoffset:16}to{stroke-dashoffset:-84}}"
             "@keyframes b{from{stroke-dashoffset:5}to{stroke-dashoffset:-95}}"
             "@keyframes h{from{stroke-dashoffset:1.2}to{stroke-dashoffset:-98.8}}"
             ".o{stroke:%%23e6f0ff;stroke-width:.28;stroke-dasharray:.5 .4}"
             ".g{stroke:%%23a9c8ff;stroke-opacity:.25;stroke-width:1}"
             "</style>") % (self.cols, self.cols // 2)
        s += "<path class='g' d='%s'/><path class='o' d='%s'/>" % (hole_d, hole_d)
        for i, (d, col, dur, dl) in enumerate(self.comets()):
            s += ("<g stroke='%%23%s' style='--d:%.1fs;--l:-%.1fs'><defs><path id='c%d' pathLength='100' d='%s'/></defs>"
                  "<use href='%%23c%d' class='a'/><use href='%%23c%d' class='b'/><use href='%%23c%d' class='h'/></g>"
                  ) % (col, dur, dl, i, d, i, i, i)
        s += "</svg>"
        # encode tags so the CSS never contains a literal </style>
        return 'url("data:image/svg+xml;utf8,' + s.replace("<", "%3C").replace(">", "%3E") + '")'

    def css(self):
        C, R = self.cols, self.rows
        hole_d, hole_mask = self.hole()
        text = self.glyphs(hole_mask)
        box = (f"position:fixed;pointer-events:none;left:50%;top:50%;transform:translate(-50%,-50%);"
               f"font:700 calc(max(100vw,200vh) / {C} / .55) / 1 {MONO};width:calc({C}ch + .5ch);height:calc({C}ch / 2);"
               f"line-height:calc({C}ch / 2 / {R});white-space:break-spaces;word-break:break-all;line-break:anywhere;"
               f"overflow:hidden;letter-spacing:0;font-variant-ligatures:none;")
        return f"""
html{{background:#000 !important}}
body{{background:transparent !important}}
html::before{{content:"{text}";{box}z-index:-4;color:transparent;background:{self.colour_map()} 0 0/calc(100% - .5ch) 100% no-repeat;-webkit-background-clip:text;background-clip:text;image-rendering:pixelated;opacity:.9}}
html::after{{content:"";{box}width:{C}ch;z-index:-3;background:{self.svg(hole_d)} 0 0/100% 100% no-repeat}}
body::after{{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;
background:repeating-linear-gradient(0deg,rgba(0,0,0,.14) 0 1px,transparent 1px 3px),radial-gradient(ellipse at 50% 55%,transparent 60%,rgba(0,0,0,.6))}}
*{{border-radius:0 !important}}
[data-message-role="assistant"] .chat-markdown{{background:rgba(2,4,10,.84);border:1px solid #a9c8ff33;padding:12px 16px;box-shadow:4px 4px 0 0 #a9c8ff1c;backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px)}}
[data-user-message-bubble]{{background:rgba(10,16,32,.9) !important;box-shadow:inset 0 0 0 1px #a9c8ff40,4px 4px 0 0 #ff5a3c33}}
[data-timeline-row-kind="work"]{{background:rgba(2,4,10,.72);box-shadow:0 0 0 1px #a9c8ff1a}}
.chat-markdown-codeblock{{background:rgba(0,0,0,.6) !important}}
[data-slot="sidebar"],[data-chat-header],.composer-tiptap,[data-slot="button"],[data-slot="input"],[data-slot="select-trigger"],[data-slot="menu-popup"],[data-slot="tooltip-popup"],[data-thread-item]{{font-family:{MONO} !important}}
[data-slot="sidebar-inner"]{{backdrop-filter:blur(6px) brightness(.55);-webkit-backdrop-filter:blur(6px) brightness(.55)}}
[data-chat-header]{{backdrop-filter:blur(6px) brightness(.5);-webkit-backdrop-filter:blur(6px) brightness(.5)}}
[data-slot="composer-host"]{{box-shadow:0 0 0 1px #a9c8ff66,4px 4px 0 0 #ff5a3c66 !important;backdrop-filter:blur(8px) brightness(.4);-webkit-backdrop-filter:blur(8px) brightness(.4)}}
[data-slot="composer-host"]:focus-within{{box-shadow:0 0 0 1px #cfe0ff,4px 4px 0 0 #ff5a3c !important}}
[data-thread-item]{{position:relative}}
[data-thread-item]:hover::before{{content:">";position:absolute;left:2px;color:#ff5a3c}}
::-webkit-scrollbar-thumb{{background:repeating-linear-gradient(0deg,#a9c8ff66 0 2px,transparent 2px 4px)}}
@media (prefers-reduced-motion:reduce){{html::after{{display:none}}}}
""".strip()


def validate(css):
    """Mirror T3 Code's theme CSS checks; returns a list of problems."""
    problems = []
    if len(css) > LIMIT:
        problems.append(f"css is {len(css)} chars (limit {LIMIT})")
    if "\\" in css:
        problems.append("css contains a backslash (T3 drops the whole stylesheet)")
    strip = re.compile(r"""url\((?![ \t\n\f\r]*["'])[^)]*|url\([ \t\n\f\r]*("[^"\n\r\f]*"|'[^'\n\r\f]*')|"[^"\n\r\f]*"|'[^'\n\r\f]*'""", re.I)
    def repl(m):
        g = m.group(1)
        if g is None:
            return "" if m.group(0)[:1] in "\"'" else m.group(0)
        return "" if re.match(r"""^["'](?:data:|#)""", g, re.I) else "url("
    t = strip.sub(repl, css)
    if re.search(r"image-set\(|\bsrc\(", t, re.I) or re.search(r"""url\((?![ \t\n\f\r]*["']?(?:data:|#))""", t, re.I):
        problems.append("css loads a non-data: url(), image-set() or src()")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("out", help="theme .json to write")
    ap.add_argument("--cols", type=int, default=240, help="glyph columns (bigger = sharper, but bigger CSS)")
    ap.add_argument("--name", default="Ring Trails ASCII")
    a = ap.parse_args()

    css = Builder(a.image, a.cols).css()
    problems = validate(css)
    theme = json.loads((HERE / "palette.json").read_text(encoding="utf-8"))
    theme["name"] = a.name
    theme["css"] = css
    Path(a.out).write_text(json.dumps(theme, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {a.out}: {len(css)} chars of CSS")
    for p in problems:
        print("  PROBLEM:", p)
    raise SystemExit(1 if problems else 0)


if __name__ == "__main__":
    main()
