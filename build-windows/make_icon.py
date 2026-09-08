"""Generate the SCRATCH Frame Grabber app icon: the Assimilate ring mark
with a flat 6-blade camera shutter at its centre."""
import math, os
from PIL import Image, ImageDraw

S = 1024
SS = 4                      # supersample factor for clean edges
N = S * SS

ORANGE      = (255, 80, 1)
ORANGE_DIM  = (196, 58, 0)
GREY        = (134, 139, 150)
BG_TOP      = (38, 41, 47)
BG_BOTTOM   = (17, 19, 22)

def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m

def vertical_gradient(size, top, bottom):
    g = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        g.putpixel((0, y), tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return g.resize((size, size), Image.NEAREST)

# ---- background: macOS-style rounded square with a subtle vertical gradient
base = vertical_gradient(N, BG_TOP, BG_BOTTOM).convert("RGBA")
base.putalpha(rounded_mask(N, int(N * 0.2237)))

layer = Image.new("RGBA", (N, N), (0, 0, 0, 0))
d = ImageDraw.Draw(layer)
c = N / 2

# ---- the Assimilate ring
RING_R = N * 0.385
RING_W = N * 0.026
d.ellipse([c - RING_R, c - RING_R, c + RING_R, c + RING_R],
          outline=GREY + (255,), width=round(RING_W))

# ---- flat 6-blade shutter
R = N * 0.300                 # blade disc radius
OPEN = R * 0.46               # hexagonal opening (circumradius)
SEP = N * 0.020               # blade separation thickness
SWEEP = -26                   # degrees of blade sweep

d.ellipse([c - R, c - R, c + R, c + R], fill=ORANGE + (255,))

# opening
hexpts = [(c + OPEN * math.cos(math.radians(-90 + k * 60)),
           c + OPEN * math.sin(math.radians(-90 + k * 60))) for k in range(6)]

# blade separation lines: from each opening vertex, swept out past the disc edge
cut = Image.new("RGBA", (N, N), (0, 0, 0, 0))
dc = ImageDraw.Draw(cut)
for k in range(6):
    a = -90 + k * 60
    v = hexpts[k]
    out_a = math.radians(a + SWEEP)
    outer = (c + R * 1.25 * math.cos(out_a), c + R * 1.25 * math.sin(out_a))
    dc.line([v, outer], fill=(0, 0, 0, 255), width=round(SEP), joint="curve")
for k in range(6):
    a = -90 + k * 60
    v = hexpts[k]
    out_a = math.radians(a + SWEEP)
    outer = (c + R * 1.25 * math.cos(out_a), c + R * 1.25 * math.sin(out_a))
    dc.ellipse([v[0] - SEP/2, v[1] - SEP/2, v[0] + SEP/2, v[1] + SEP/2], fill=(0,0,0,255))
    dc.ellipse([outer[0]-SEP/2, outer[1]-SEP/2, outer[0]+SEP/2, outer[1]+SEP/2], fill=(0,0,0,255))

# keep cuts inside the disc only
disc = Image.new("L", (N, N), 0)
ImageDraw.Draw(disc).ellipse([c - R, c - R, c + R, c + R], fill=255)
cut.putalpha(Image.composite(cut.split()[3], Image.new("L", (N, N), 0), disc))

# punch separations out of the blade disc
la = layer.split()[3]
la = Image.composite(Image.new("L", (N, N), 0), la, cut.split()[3])
layer.putalpha(la)

# punch the hexagonal opening out
hexmask = Image.new("L", (N, N), 0)
ImageDraw.Draw(hexmask).polygon(hexpts, fill=255)
la = layer.split()[3]
la = Image.composite(Image.new("L", (N, N), 0), la, hexmask)
layer.putalpha(la)

out = Image.alpha_composite(base, layer).resize((S, S), Image.LANCZOS)
out.save("icon_1024.png")
out.resize((512, 512), Image.LANCZOS).save("icon_512.png")
print("icon written", out.size)
