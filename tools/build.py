"""Builds every SVG in assets/ in a dark and a light version, and the projects block in README.md.

    python tools/build.py

Add a project: append it to tools/projects.json and run the script again. Nothing else to touch.
Needs fontTools and brotli (pip install fonttools brotli). The fonts in tools/fonts are subset into
each SVG, because an SVG shown as an image loads no external fonts.

The palette below is this profile's own. It borrows the portfolio's hues but nothing reads from the
site, so a change there never forces a change here.
"""
import base64
import io
import json
import re
from pathlib import Path
from xml.sax.saxutils import escape

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / 'tools' / 'fonts'
ASSETS = ROOT / 'assets'
README = ROOT / 'README.md'
USER = 'Idan-Babayan'

# key: (file, @font-face family, weight, fallback stack)
FONT = {
    'syne800': ('syne-800.woff2', 'IB-S8', 800, "'Arial Black', Impact, sans-serif"),
    'syne700': ('syne-700.woff2', 'IB-S7', 700, "'Arial Black', Impact, sans-serif"),
    'mono': ('jetbrains-mono-400.woff2', 'IB-M4', 400, "ui-monospace, Menlo, Consolas, monospace"),
    'mono700': ('jetbrains-mono-700.woff2', 'IB-M7', 700, "ui-monospace, Menlo, Consolas, monospace"),
}

# Fills that carry text are solved for 4.5:1 against their `on` colour in each theme. The `deco`
# fills are shapes only and never sit under text.
THEMES = {
    'dark': dict(
        ground='#07090a', raised='#0d1113', text='#e9f1ee', muted='#79857f', dot='#3c4642',
        line='#ffffff', line_op=0.10, lime_ink='#b6ff3c',
        fill={'lime': '#b6ff3c', 'cyan': '#41efff', 'magenta': '#ff4d9d', 'gold': '#ffc23d'},
        on={'lime': '#06251a', 'cyan': '#07090a', 'magenta': '#07090a', 'gold': '#07090a'},
        deco={'lime': '#b6ff3c', 'cyan': '#41efff', 'magenta': '#ff4d9d', 'gold': '#ffc23d', 'low': '#20330a'},
    ),
    'light': dict(
        ground='#ece9e0', raised='#f7f5ee', text='#12181a', muted='#515c59', dot='#b3b0a6',
        line='#000000', line_op=0.13, lime_ink='#3e6700',
        fill={'lime': '#4d7c0f', 'cyan': '#08697a', 'magenta': '#c41d6f', 'gold': '#c6a243'},
        on={'lime': '#f6f4ec', 'cyan': '#f6f4ec', 'magenta': '#f6f4ec', 'gold': '#12181a'},
        deco={'lime': '#6fae00', 'cyan': '#0a9ec2', 'magenta': '#c41d6f', 'gold': '#c6a243', 'low': '#d6e7b4'},
    ),
}

EASE = 'cubic-bezier(.2,.7,.2,1)'
BASE_CSS = (
    '@keyframes rise{from{opacity:0;transform:translateY(28px)}to{opacity:1;transform:none}}'
    '@keyframes fade{from{opacity:0}to{opacity:1}}'
    '@keyframes pop{from{opacity:0;transform:scale(.92)}to{opacity:1;transform:none}}'
    '@keyframes grow-y{from{transform:scaleY(0)}to{transform:none}}'
    '@keyframes grow-x{from{transform:scaleX(0)}to{transform:none}}'
    '@keyframes grow{from{transform:scale(0)}to{transform:none}}'
    '@keyframes blink{0%,49.9%{opacity:1}50%,100%{opacity:0}}'
    '.fb{transform-box:fill-box}'
    '@media (prefers-reduced-motion:reduce){*{animation:none!important}}'
)

_tt = {}


def tt(key):
    if key not in _tt:
        _tt[key] = TTFont(FONTS / FONT[key][0])
    return _tt[key]


def adv(key, txt, size, track=0.0):
    f = tt(key)
    cmap, hm, upm = f.getBestCmap(), f['hmtx'], f['head'].unitsPerEm
    units = sum(hm[cmap.get(ord(c), '.notdef')][0] for c in txt)
    return units / upm * size + track * size * len(txt)


def font_css(uses):
    out = []
    for key, chars in uses.items():
        if not chars:
            continue
        file, fam, weight, fallback = FONT[key]
        f = TTFont(FONTS / file)
        opts = subset.Options()
        opts.flavor = 'woff2'
        opts.hinting = False
        opts.layout_features = ['kern']
        sub = subset.Subsetter(opts)
        sub.populate(text=''.join(sorted(chars | {' '})))
        sub.subset(f)
        buf = io.BytesIO()
        f.flavor = 'woff2'
        f.save(buf)
        data = base64.b64encode(buf.getvalue()).decode()
        out.append(f"@font-face{{font-family:{fam};font-weight:{weight};"
                   f"src:url(data:font/woff2;base64,{data}) format('woff2')}}")
        out.append(f'.{key}{{font-family:{fam},{fallback};font-weight:{weight}}}')
    return ''.join(out)


def wrap_px(font, txt, size, width):
    lines, cur = [], ''
    for word in txt.split():
        trial = f'{cur} {word}'.strip()
        if cur and adv(font, trial, size) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return lines + ([cur] if cur else [])


class Ctx:
    def __init__(self, theme, w, h):
        self.theme = theme
        self.t = THEMES[theme]
        self.w, self.h = w, h
        self.uses = {k: set() for k in FONT}
        self.css = []
        self.n = 0

    def uid(self, prefix='k'):
        self.n += 1
        return f'{prefix}{self.n}'

    def text(self, x, y, txt, font, size, fill, anchor='start', track=0.0, style='', attrs=''):
        self.uses[font].update(txt)
        if track:
            total = adv(font, txt, size, track) - track * size
            cx = x - {'middle': total / 2, 'end': total}.get(anchor, 0)
            xs = []
            for c in txt:
                xs.append(f'{cx:.1f}')
                cx += adv(font, c, size, track)
            xa, anchor = ' '.join(xs), 'start'
        else:
            xa = f'{x:.1f}'
        st = f' style="{style}"' if style else ''
        return (f'<text x="{xa}" y="{y:.1f}" class="{font}" font-size="{size}" fill="{fill}" '
                f'text-anchor="{anchor}"{st}{attrs}>{escape(txt)}</text>')

    def spans(self, x, y, segs, size, style=''):
        out = []
        for txt, font, fill in segs:
            self.uses[font].update(txt)
            out.append(f'<tspan class="{font}" fill="{fill}">{escape(txt)}</tspan>')
        st = f' style="{style}"' if style else ''
        return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}"{st}>{"".join(out)}</text>'

    def label(self, x, y, txt, fill, size=13):
        """Small uppercase mono label, the system's eyebrow."""
        return self.text(x, y, txt, 'mono700', size, fill, track=0.28)

    def doc(self, body, title, desc):
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
                f'viewBox="0 0 {self.w} {self.h}" role="img" aria-labelledby="t d" xml:space="preserve">'
                f'<title id="t">{escape(title)}</title><desc id="d">{escape(desc)}</desc>'
                f'<style>{font_css(self.uses)}text{{white-space:pre}}{BASE_CSS}{"".join(self.css)}</style>'
                f'{body}</svg>\n')


# Shared pieces -----------------------------------------------------------------------------------

def panel(s, x, y, w, h, rx=16, fill=None, style=''):
    t = s.t
    st = f' style="{style}"' if style else ''
    return (f'<rect class="fb" x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill or t["raised"]}" '
            f'stroke="{t["line"]}" stroke-opacity="{t["line_op"]}"{st}/>')


def dots(s, x0, y0, cols, rows, pitch=24, r=1.6, delay=0.0, step=0.05):
    out = []
    for j in range(rows):
        row = ''.join(f'<circle cx="{x0 + i * pitch:.1f}" cy="{y0 + j * pitch:.1f}" r="{r}"/>' for i in range(cols))
        out.append(f'<g style="animation:fade .6s ease {delay + j * step:.2f}s both">{row}</g>')
    return f'<g fill="{s.t["dot"]}">{"".join(out)}</g>'


def block(x, y, w, h, rx, fill, grow, origin, delay, dur=0.9):
    return (f'<rect class="fb" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" fill="{fill}" '
            f'style="transform-origin:{origin};animation:{grow} {dur}s {EASE} {delay:.2f}s both"/>')


def frame(s, rx=18):
    t = s.t
    return (f'<defs><clipPath id="cp"><rect width="{s.w}" height="{s.h}" rx="{rx}"/></clipPath></defs>'
            f'<g clip-path="url(#cp)"><rect width="{s.w}" height="{s.h}" fill="{t["ground"]}"/>')


def border(s, rx=18):
    t = s.t
    return (f'<rect x=".5" y=".5" width="{s.w - 1}" height="{s.h - 1}" rx="{rx}" fill="none" '
            f'stroke="{t["line"]}" stroke-opacity="{t["line_op"]}"/>')


# Hero --------------------------------------------------------------------------------------------

def hero(theme):
    W, H = 1200, 380
    s = Ctx(theme, W, H)
    t, d = s.t, s.t['deco']
    out = [frame(s)]

    # The cover's composition: one tall lime slab with satellites, bleeding off the edges, and a
    # dot grid. Laid out on a 480 x 288 field and scaled to the banner's height.
    k = H / 288
    ox = W - 480 * k

    def at(x, y, w, h):
        return ox + x * k, y * k, w * k, h * k

    out.append(dots(s, ox + 12 * k, 36 * k, 8, 5, pitch=24 * k, r=2, delay=0.15))
    out.append(block(*at(200, -16, 168, 232), 21, d['lime'], 'grow-y', 'top', 0.25))
    out.append(block(*at(384, -16, 112, 120), 21, d['cyan'], 'grow-y', 'top', 0.4))
    out.append(block(*at(384, 120, 112, 72), 13, d['magenta'], 'grow-x', 'left', 0.55))
    out.append(block(*at(200, 232, 296, 72), 21, d['low'], 'grow-x', 'left', 0.7))
    out.append(block(*at(96, 152, 88, 88), 13, d['gold'], 'grow', 'center', 0.85, dur=0.7))

    # Name, stacked, sized so it stays clear of the gold block.
    gold_left = ox + 96 * k
    size = round(min(118, (gold_left - 48 - 24) / adv('syne800', 'Babayan', 1)))
    lead = round(size * 0.92)
    y2 = 300
    y1 = y2 - lead
    out.append(f'<g style="animation:rise .8s {EASE} .1s both">'
               + s.label(50, y1 - size + 6, 'CYBERSECURITY STUDENT · CTF PLAYER', t['lime_ink'])
               + '</g>')
    out.append(f'<g style="animation:rise .8s {EASE} .2s both">'
               + s.text(44, y1, 'Idan', 'syne800', size, t['text'])
               + s.text(44, y2, 'Babayan', 'syne800', size, t['text']) + '</g>')
    out.append(f'<g style="animation:rise .8s {EASE} .35s both">'
               + s.text(48, y2 + 44, 'Curiosity is my exploit.', 'mono', 17, t['muted']) + '</g>')

    out.append('</g>' + border(s))
    return s.doc(''.join(out), 'Idan Babayan',
                 'Cybersecurity student and CTF player. Curiosity is my exploit.')


# whoami bento ------------------------------------------------------------------------------------

def bento(theme):
    W, H, g = 1200, 490, 16
    s = Ctx(theme, W, H)
    t = s.t
    out = []

    # A: the statement.
    aw = 584
    a = [panel(s, 0, 0, aw, H), s.label(36, 52, 'ABOUT', t['lime_ink'])]
    y = 118
    for line in wrap_px('syne700', 'Cybersecurity student, CTF player, offensive security enthusiast.', 38, aw - 72):
        a.append(s.text(36, y, line, 'syne700', 38, t['text']))
        y += 46
    for line in wrap_px('mono', 'Learning offensive security in public, one box at a time.', 17, aw - 72):
        y += 4
        a.append(s.text(36, y + 10, line, 'mono', 17, t['muted']))
        y += 22
    a.append(dots(s, aw - 36 - 7 * 24, H - 36 - 3 * 24, 8, 4, delay=0.5))
    out.append(f'<g class="fb" style="transform-origin:center;animation:pop .8s {EASE} .05s both">{"".join(a)}</g>')

    def tile(x, y, w, h, key, title, body, delay):
        fill, on = t['fill'][key], t['on'][key]
        parts = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{fill}"/>',
                 s.label(x + 32, y + 46, title, on)]
        parts += body(x, y, on)
        return f'<g class="fb" style="transform-origin:center;animation:pop .8s {EASE} {delay}s both">{"".join(parts)}</g>'

    bx = aw + g
    bw = W - bx
    focus = [['Web security', 'Reverse engineering', 'Privilege escalation'], ['OSINT and recon', 'Cryptography']]

    def focus_body(x, y, on):
        parts = []
        for c, col in enumerate(focus):
            for r, item in enumerate(col):
                ix, iy = x + 32 + c * 290, y + 98 + r * 38
                parts.append(f'<rect x="{ix}" y="{iy - 11}" width="9" height="9" rx="2" fill="{on}"/>')
                parts.append(s.text(ix + 22, iy, item, 'mono700', 18, on))
        return parts

    out.append(tile(bx, 0, bw, 212, 'lime', 'FOCUS', focus_body, 0.2))

    cw = (bw - g) // 2
    ch = H - 212 - g

    def lines_body(txt, size, font, top, width):
        def body(x, y, on):
            return [s.text(x + 32, y + top + i * (size + 8), ln, font, size, on)
                    for i, ln in enumerate(wrap_px(font, txt, size, width))]
        return body

    out.append(tile(bx, 212 + g, cw, ch, 'cyan', 'PRACTICE',
                    lines_body('CTFs, intentionally vulnerable labs and my own VMs. Legal and controlled, always.',
                               17, 'mono', 92, cw - 60), 0.35))
    sh = (ch - g) / 2
    out.append(tile(bx + cw + g, 212 + g, W - bx - cw - g, sh, 'magenta', 'TOOLBOX',
                    lines_body('Kali, Python, Bash', 18, 'mono700', 82, cw - 50), 0.5))
    out.append(tile(bx + cw + g, 212 + g + sh + g, W - bx - cw - g, sh, 'gold', 'NEXT',
                    lines_body('First role in security: pentest or red team.', 16, 'mono700', 74, cw - 50), 0.65))

    return s.doc(''.join(out), 'whoami',
                 'Idan Babayan: cybersecurity student, CTF player, offensive security enthusiast, learning '
                 'offensive security in public, one box at a time. Focus: web security, reverse engineering, '
                 'privilege escalation, OSINT and recon, cryptography. Practice: CTFs, intentionally vulnerable '
                 'labs and my own VMs, legal and controlled, always. Toolbox: Kali, Python, Bash. Next: a first '
                 'role in security, pentest or red team.')


# The loop ----------------------------------------------------------------------------------------

PHASES = [
    ('01', 'Recon', 'Map the surface before touching it.', 'cyan'),
    ('02', 'Foothold', 'Find the crack and slip through.', 'magenta'),
    ('03', 'Escalation', 'Climb from user to root.', 'lime'),
    ('04', 'Reflection', 'Document what the defender missed.', 'gold'),
]


def loop(theme):
    W, H, g = 1200, 236, 16
    s = Ctx(theme, W, H)
    t = s.t
    tw = (W - 3 * g) / 4
    cycle, step, lead = 9.0, 1.5, 0.4
    out = []

    def face(x, num, name, desc, key, ink, sub, square):
        parts = [s.label(x + 28, 50, num, sub),
                 f'<rect x="{x + tw - 28 - 16:.1f}" y="34" width="16" height="16" rx="3" fill="{square}"/>',
                 s.text(x + 28, 140, name, 'syne700', 32, ink)]
        for i, ln in enumerate(wrap_px('mono', desc, 15, tw - 56)):
            parts.append(s.text(x + 28, 176 + i * 22, ln, 'mono', 15, sub))
        return ''.join(parts)

    for i, (num, name, desc, key) in enumerate(PHASES):
        x = i * (tw + g)
        fill, on = t['fill'][key], t['on'][key]
        out.append(panel(s, round(x, 1), 0, round(tw, 1), H) + face(x, num, name, desc, key, t['text'], t['muted'], fill))
        # Lit face: the tile fills in its colour while the loop passes through it.
        a = (lead + i * step) / cycle * 100
        b = (lead + (i + 1) * step) / cycle * 100
        k = s.uid('lit')
        s.css.append(f'@keyframes {k}{{0%,{a:.2f}%{{opacity:0}}{a + 3:.2f}%,{b:.2f}%{{opacity:1}}{b + 3:.2f}%,100%{{opacity:0}}}}')
        out.append(f'<g style="opacity:0;animation:{k} {cycle}s ease-in-out infinite">'
                   f'<rect x="{x:.1f}" y="0" width="{tw:.1f}" height="{H}" rx="16" fill="{fill}"/>'
                   + face(x, num, name, desc, key, on, on, on) + '</g>')

    return s.doc(''.join(out), 'Recon, foothold, escalation, reflection.',
                 'The loop every box gets: recon, map the surface before touching it. Foothold, find the crack and '
                 'slip through. Escalation, climb from user to root. Reflection, document what the defender missed.')


# Project cards -----------------------------------------------------------------------------------

PAIRS = [('lime', 'cyan'), ('cyan', 'magenta'), ('magenta', 'gold'), ('gold', 'lime')]


def card(theme, idx, p):
    W, H = 600, 250
    s = Ctx(theme, W, H)
    t, d = s.t, s.t['deco']
    big, small = PAIRS[idx % len(PAIRS)]
    out = [frame(s, rx=16).replace(f'fill="{t["ground"]}"', f'fill="{t["raised"]}"', 1)]
    out.append(dots(s, W - 300, 34, 5, 3, delay=0.2))
    out.append(block(W - 128, -24, 112, 116, 16, d[big], 'grow-y', 'top', 0.3))
    out.append(block(W - 128 - 16 - 52, 40, 52, 52, 10, d[small], 'grow', 'center', 0.45, dur=0.7))
    out.append(s.label(32, 52, f'{idx + 1:02d}', t['muted']))
    name_size = round(min(44, 330 / adv('syne800', p['name'], 1)))
    out.append(s.text(30, 134, p['name'], 'syne800', name_size, t['text']))
    lines = wrap_px('mono', p['desc'], 17, W - 64)
    if len(lines) > 2:
        raise SystemExit(f'{p["name"]}: description wraps to {len(lines)} lines, keep it to two')
    for j, line in enumerate(lines):
        out.append(s.text(32, 168 + 24 * j, line, 'mono', 17, t['muted']))
    x = 32
    for tag in p.get('tags', []):
        w = adv('mono', tag, 14) + 24
        out.append(f'<rect x="{x}" y="{H - 50}" width="{w:.1f}" height="28" rx="14" fill="none" '
                   f'stroke="{t["muted"]}" stroke-opacity=".6"/>'
                   + s.text(x + w / 2, H - 31, tag, 'mono', 14, t['muted'], anchor='middle'))
        x += w + 8
    out.append('</g>' + border(s, rx=16))
    return s.doc(''.join(out), p['name'], p['desc'])


# Footer ------------------------------------------------------------------------------------------

def footer(theme):
    W, H = 1200, 120
    s = Ctx(theme, W, H)
    t, d = s.t, s.t['deco']
    out = [frame(s)]
    out.append(dots(s, 820, 36, 6, 3, delay=0.1))
    out.append(block(1000, 56, 132, 90, 16, d['lime'], 'grow-y', 'bottom', 0.2))
    out.append(block(1148, -20, 80, 76, 16, d['cyan'], 'grow-y', 'top', 0.35))
    out.append(block(948, 76, 36, 36, 8, d['magenta'], 'grow', 'center', 0.5, dur=0.6))
    segs = [('logout. ', 'mono', t['muted']), ('Curiosity keeps running in the background.', 'mono', t['text'])]
    out.append(f'<g style="animation:rise .8s {EASE} .1s both">{s.spans(40, 68, segs, 18)}</g>')
    cx = 40 + adv('mono', segs[0][0] + segs[1][0], 18) + 6
    out.append(f'<rect x="{cx:.1f}" y="53" width="11" height="20" fill="{d["lime"]}" '
               f'style="animation:fade .3s ease .6s both,blink 1.1s step-end .9s 6"/>')
    out.append('</g>' + border(s))
    return s.doc(''.join(out), 'logout', 'logout. Curiosity keeps running in the background.')


# Buttons -----------------------------------------------------------------------------------------

ICONS = {
    'globe': '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.5 2.5 15 0 18M12 3c-2.5 2.5-2.5 15 0 18"/>',
    'linkedin': '<rect x="3" y="3" width="18" height="18" rx="3.5"/><path d="M8 11v6M12 17v-6M12 13.6c0-1.7 1-2.7 2.5-2.7S17 11.9 17 13.6V17"/>'
                '<circle cx="8" cy="7.9" r=".6" fill="currentColor"/>',
    'mail': '<rect x="2.5" y="4.5" width="19" height="15" rx="2"/><path d="m3 6 9 6.5L21 6"/>',
}


def button(theme, label, icon, primary):
    t = THEMES[theme]
    fs, h, pad = 15, 48, 22
    arrow = '  ↗' if primary else ''
    W = round(pad + 20 + 12 + adv('mono700', label + arrow, fs) + pad)
    s = Ctx(theme, W, h)
    fg = t['on']['lime'] if primary else t['text']
    if primary:
        out = [f'<rect width="{W}" height="{h}" rx="10" fill="{t["fill"]["lime"]}"/>']
    else:
        out = [f'<rect x=".75" y=".75" width="{W - 1.5}" height="{h - 1.5}" rx="9.5" fill="{t["raised"]}" '
               f'stroke="{t["line"]}" stroke-opacity="{t["line_op"] * 2:.2f}" stroke-width="1.5"/>']
    out.append(f'<g transform="translate({pad},{(h - 20) / 2}) scale({20 / 24})" fill="none" stroke="{fg}" color="{fg}" '
               f'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">{ICONS[icon]}</g>')
    out.append(s.text(pad + 32, h / 2 + 5.2, label + arrow, 'mono700', fs, fg))
    return s.doc(''.join(out), label, label)


# README block ------------------------------------------------------------------------------------

def picture(name, alt, width=None):
    size = f' width="{width}"' if width else ''
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="assets/{name}-dark.svg">'
            f'<source media="(prefers-color-scheme: light)" srcset="assets/{name}-light.svg">'
            f'<img src="assets/{name}-dark.svg"{size} alt="{escape(alt, {chr(34): "&quot;"})}"></picture>')


def projects_block(projects):
    cells = []
    for p in projects:
        url = p.get('url') or f'https://github.com/{USER}/{p["repo"]}'
        cells.append(f'<a href="{url}">{picture("project-" + p["repo"].lower(), p["name"] + ": " + p["desc"], width="49%")}</a>')
    return '<p align="center">\n' + '\n'.join(cells) + '\n</p>'


def write(name, svg):
    for bad in ('—', '–'):
        assert bad not in svg, f'{name}: banned dash'
    (ASSETS / name).write_text(svg, encoding='utf-8', newline='\n')
    return len(svg.encode())


def main():
    ASSETS.mkdir(exist_ok=True)
    projects = json.loads((ROOT / 'tools' / 'projects.json').read_text(encoding='utf-8'))
    sizes = {}
    for theme in THEMES:
        for name, fn in (('hero', hero), ('whoami', bento), ('loop', loop), ('footer', footer)):
            sizes[f'{name}-{theme}.svg'] = write(f'{name}-{theme}.svg', fn(theme))
        for i, p in enumerate(projects):
            nm = f'project-{p["repo"].lower()}-{theme}.svg'
            sizes[nm] = write(nm, card(theme, i, p))
        for label, icon, primary, key in (('idanlab.dev', 'globe', True, 'site'),
                                          ('LinkedIn', 'linkedin', False, 'linkedin'),
                                          ('contact@idanlab.dev', 'mail', False, 'email')):
            sizes[f'btn-{key}-{theme}.svg'] = write(f'btn-{key}-{theme}.svg', button(theme, label, icon, primary))

    if README.exists():
        md = README.read_text(encoding='utf-8')
        md2 = re.sub(r'(<!-- projects:start -->).*?(<!-- projects:end -->)',
                     lambda m: f'{m.group(1)}\n{projects_block(projects)}\n{m.group(2)}', md, flags=re.S)
        if md2 != md:
            README.write_text(md2, encoding='utf-8', newline='\n')
    for k, v in sorted(sizes.items()):
        print(f'{v / 1024:7.1f} KB  {k}')


if __name__ == '__main__':
    main()
