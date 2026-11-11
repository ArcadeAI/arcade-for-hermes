"""Edit take 7 like a person would: chapter cards, a camera that eases between regions of the screen,
real speed for the moments that matter, fast-forward through thinking, a highlight on the verdict.

Frames are decoded once per shot from the source, cropped/scaled with PIL, captioned, and piped to one
encoder. Source is 3420x2214 (retina capture of the studio)."""
import json, subprocess, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

WORK = Path(__file__).parent
SRC = Path.home() / "Movies/arcade-for-hermes-demo-take8.mp4"
OUT = Path.home() / "Movies/arcade-for-hermes-demo-v3.mp4"
SW, SH_ = 3420, 2214
W, H, FPS = 1920, 1080, 30
CAP = 120
AREA = (W, H - CAP)
BG, INK, DIM, ACC = (11, 13, 18), (240, 236, 226), (150, 146, 170), (255, 159, 28)
SANS = "/System/Library/Fonts/HelveticaNeue.ttc"
MONO = "/System/Library/Fonts/SFNSMono.ttf"


def font(size, bold=True, mono=False):
    return ImageFont.truetype(MONO if mono else SANS, size, index=0 if mono else (1 if bold else 0))


F_CAP = font(46)
F_TAG = font(30, bold=False)


def ease(u):
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def fit_rect(cx, cy, w):
    """A rect of the output aspect centred on (cx, cy), w wide, kept inside the source."""
    h = w * AREA[1] / AREA[0]
    if h > SH_:
        h = SH_; w = h * AREA[0] / AREA[1]
    x = min(max(cx - w / 2, 0), SW - w)
    y = min(max(cy - h / 2, 0), SH_ - h)
    return (x, y, w, h)


def region(x0, y0, x1, y1, pad=40):
    """Smallest output-aspect rect that holds the box (source px)."""
    w = max(x1 - x0 + 2 * pad, (y1 - y0 + 2 * pad) * AREA[0] / AREA[1])
    return fit_rect((x0 + x1) / 2, (y0 + y1) / 2, w)


FULL = (0, 0, SW, SW * AREA[1] / AREA[0]) if SW * AREA[1] / AREA[0] <= SH_ else fit_rect(SW / 2, SH_ / 2, SW)


def caption_bar(text, tag=""):
    im = Image.new("RGB", (W, CAP), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 12, CAP], fill=ACC)
    d.text((56, CAP // 2), text, font=F_CAP, fill=INK, anchor="lm")
    if tag:
        d.text((W - 48, CAP // 2), tag, font=F_TAG, fill=DIM, anchor="rm")
    return im


def card(lines, sub=None):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    fonts = [font(s, b, m) for _, s, _, b, m in lines]
    hs = [f.getbbox("Ag")[3] + g for f, (_, _, _, _, _), g in zip(fonts, lines, [30] * len(lines))]
    y = (H - sum(hs)) // 2
    for (t, s, c, b, m), f, h in zip(lines, fonts, hs):
        d.text((W // 2, y), t, font=f, fill=c, anchor="mt")
        y += h
    return im


class Encoder:
    def __init__(self, out):
        self.p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                   "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium",
                                   "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
                                  stdin=subprocess.PIPE)
        self.n = 0

    last = None
    fade = 0          # frames left to dissolve from `fade_from`
    fade_from = None
    FADE_N = 12

    def put(self, im):
        if self.fade and self.fade_from is not None:
            u = 1 - self.fade / (self.FADE_N + 1)
            im = Image.blend(self.fade_from, im, ease(u))
            self.fade -= 1
        self.last = im
        self.p.stdin.write(im.tobytes()); self.n += 1

    def dissolve(self):
        self.fade_from, self.fade = self.last, self.FADE_N

    def hold(self, im, seconds):
        for _ in range(int(seconds * FPS)):
            self.put(im)

    def close(self):
        self.p.stdin.close(); self.p.wait()


def frames(t0, t1):
    """Source frames from t0 to t1 at the source rate, as PIL images."""
    p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}", "-i", str(SRC),
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    size = SW * SH_ * 3
    while True:
        buf = p.stdout.read(size)
        if len(buf) < size:
            break
        yield Image.frombuffer("RGB", (SW, SH_), buf, "raw", "RGB", 0, 1)
    p.wait()


def lerp_rect(a, b, u):
    return tuple(a[i] + (b[i] - a[i]) * u for i in range(4))


PREV = [None]


def shot(enc, t0, t1, cam, text, speed=1.0, move=2.0, hl=None, hl_at=0.0, tag="", tail=2.5, focus=False, mask=None):
    """Play source t0..t1 at `speed`. cam: [rect] or [rect_from, rect_to] (eased over `move` s of output).
    hl: a source box drawn in the accent colour from output time hl_at. Holds the last frame `tail` s."""
    bar = caption_bar(text, tag or (f"{speed:g}x" if speed > 1 else ""))
    a, b = (cam[0], cam[-1])
    if len(cam) == 1 and PREV[0] is not None:
        a = PREV[0]           # pan from where the last shot ended instead of cutting
    PREV[0] = b
    enc.dissolve()
    lead = 0.4                # hold the start framing a beat before the camera moves
    out_t, src_i, last = 0.0, 0, None
    step = speed  # source frames per output frame at a 30 fps source
    acc = 0.0
    for im in frames(t0, t1):
        acc += 1
        if acc < step:
            continue
        acc -= step
        last = im
        compose(enc, im, lerp_rect(a, b, ease((out_t - lead) / move) if move else 1), bar, hl if out_t >= hl_at else None, focus, mask)
        out_t += 1 / FPS
    if last is not None:
        for _ in range(int(tail * FPS)):   # keep easing if the pan has not finished, never snap
            compose(enc, last, lerp_rect(a, b, ease((out_t - lead) / move) if move else 1), bar,
                    hl if out_t >= hl_at else None, focus, mask)
            out_t += 1 / FPS


def compose(enc, im, rect, bar, hl, focus=False, mask=None):
    x, y, w, h = rect
    from PIL import ImageFilter
    for m in mask or []:   # private details (a real inbox search) get blurred out of the source
        im = im.copy() if im.readonly else im
        region_ = im.crop(tuple(m)).filter(ImageFilter.GaussianBlur(14))
        im.paste(region_, tuple(m[:2]))
    view = im.crop((int(x), int(y), int(x + w), int(y + h))).resize(AREA, Image.BILINEAR)
    if hl:
        sx, sy = AREA[0] / w, AREA[1] / h
        bx0, by0, bx1, by1 = hl
        box = [int((bx0 - x) * sx), int((by0 - y) * sy), int((bx1 - x) * sx), int((by1 - y) * sy)]
        if focus:   # spotlight: everything outside the box goes near-black
            keep = view.crop(box)
            view = Image.blend(view.filter(__import__("PIL.ImageFilter", fromlist=["x"]).GaussianBlur(12)), Image.new("RGB", AREA, BG), 0.8)
            view.paste(keep, box[:2])
        d = ImageDraw.Draw(view)
        d.rounded_rectangle(box, radius=10, outline=ACC, width=5)
    frame = Image.new("RGB", (W, H), BG)
    frame.paste(view, (0, 0))
    frame.paste(bar, (0, H - CAP))
    enc.put(frame)


if __name__ == "__main__":
    plan = json.loads((WORK / "plan.json").read_text())
    enc = Encoder(OUT)
    for s in plan:
        kind = s.pop("kind")
        if kind == "card":
            enc.dissolve()
            enc.hold(card([(l[0], l[1], tuple(l[2]), l[3], l[4]) for l in s["lines"]]), s["seconds"])
        else:
            s["cam"] = [tuple(r) if len(r) == 4 and not isinstance(r[0], list) else r for r in s["cam"]]
            s["cam"] = [region(*r[1:]) if r[0] == "box" else (FULL if r[0] == "full" else tuple(r)) for r in s["cam"]]
            shot(enc, **s)
        print(kind, s.get("text", ""), f"{enc.n / FPS:.1f}s", flush=True)
    enc.close()
    print(OUT, f"{enc.n / FPS:.1f}s")
