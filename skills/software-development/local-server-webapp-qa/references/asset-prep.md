# Preparing an image asset the user hands you

Use when the user supplies an image (a logo, a mark, a screenshot crop) and wants it in the UI:
background removed, recoloured to the palette, correct in both themes. Do it numerically with
Pillow, then verify with the numbers. Doing it by eye fails.

## The preview lies about transparency

An image viewer renders transparent pixels as black or as the page colour, so a clean cut-out looks
like "a black background" and a vision pass reports it as opaque. Never judge this from a screenshot;
read the alpha channel:

```python
from PIL import Image
im = Image.open('web/logo.png')
a = im.getchannel('A').histogram()
print('fully transparent:', a[0], 'soft edge:', sum(a[1:255]), 'opaque:', a[255])
w, h = im.size
px = a.load()
print('corners:', px[0, 0], px[w-1, 0], px[0, h-1], px[w-1, h-1])  # all 0 = background gone
```

A near-opaque source is common: check `a[0]` FIRST, because if the supplied file has no transparency
the background must be separated before anything else can be done.

## A light mark on a dark background is a luminance cut

Print the luminance histogram and read where the background mass ends. A threshold chosen by taste
either eats thin strokes or leaves a halo:

```python
lo, hi = 120, 205                      # read off the histogram, not chosen by taste
l = (r*299 + g*587 + b*114) // 1000
alpha = 0 if l <= lo else (255 if l >= hi else round((l - lo) * 255 / (hi - lo)))
```

- The ramp between `lo` and `hi` is what keeps edges smooth; a hard cut reads as scissors work at 2x.
- Crop to the bounding box of `alpha > 0` afterwards, or the asset carries a big transparent margin
  and cannot be sized predictably in CSS.
- Report the alpha histogram as the proof: fully transparent count, soft-edge count, opaque count.

## Recolour to the palette

Replace the source colour with the accent while keeping a trace of the original shading so thin
strokes do not go flat:

```python
f = 0.82 + 0.18 * (l / 255)
pixel = (accent_r * f, accent_g * f, accent_b * f, alpha)
```

Read the accent from the design tokens and emit ONE FILE PER THEME: a single value cannot clear
contrast on both a light paper background and a dark charcoal one. Then check each against the 3:1
non-text floor and record both ratios.

## Wire it in

Two files swapped by CSS, so the theme change costs no JavaScript:

```css
.lambang { background: url("/logo.png") center / contain no-repeat; }
[data-tema="gelap"] .lambang { background-image: url("/logo-gelap.png"); }
```

Set `<link rel="icon">` and an `apple-touch-icon` from the same files, and keep a copy under
`assets/` when the README shows it (`<picture>` with a `prefers-color-scheme: dark` source).

## Do not redraw a mark the user already has

When the user supplies their brand mark, use it. A hand-drawn stand-in is a placeholder they will ask
you to replace. If the source is low resolution or has a baked-in background, say what that costs
(soft edges from an upscaled raster) and ask for a vector or a transparent original rather than
silently redrawing it.
