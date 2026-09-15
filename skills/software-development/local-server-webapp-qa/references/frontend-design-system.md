# Frontend design system for a plain local web app

Use when a bare/templated local app is asked to "look designed". Keep the stack; add a token-driven
stylesheet, an icon sprite, and a browser-verified check. Works with vanilla CSS or any existing
framework.

## Audit first (what makes a UI read as generic AI output)
- Browser-default font everywhere; only 400/700 weights; headline lacks weight/tight tracking.
- Pure `#000`/`#fff`, oversaturated accent, more than one accent, mixed warm/cool greys.
- Uniform border-radius on everything; generic black `box-shadow`; flat surfaces with no texture.
- Emoji used as section icons; identical card look (border + shadow + white) repeated.
- No hover/active/focus states, no empty/loading/error states, no active-nav indication.
- Inline styles mixed with classes; non-semantic `div` soup; hardcoded px widths.

## Token starter (adapt, don't copy blindly)
```css
:root{
  --bg:#f3f1ec; --surface:#fffefb; --surface-2:#faf8f3;
  --ink:#1b1a17; --ink-2:#55514a; --ink-3:#8c867b;
  --line:#e7e1d7; --line-2:#d9d2c4;
  --accent:#0f6d6a; --accent-2:#0b5653; --accent-soft:#e3f1ef;
  --ok:#2f7d4f; --fail:#b4453a; --warn:#a9761a;
  --r-xl:20px; --r-lg:14px; --r-md:10px; --r-sm:7px;
  --shadow-2:0 1px 2px rgba(27,26,23,.05), 0 10px 28px -16px rgba(27,26,23,.28);
  --sans:"Outfit",ui-sans-serif,system-ui,sans-serif;
  --mono:"JetBrains Mono",ui-monospace,Menlo,monospace;
  --ease:cubic-bezier(.2,.7,.25,1);
}
body{
  background:radial-gradient(1100px 520px at 82% -12%, rgba(15,109,106,.07), transparent 62%), var(--bg);
  min-height:100dvh;
}
:focus-visible{ outline:2px solid var(--accent); outline-offset:2px; }
```
Add a fixed, `pointer-events:none`, low-opacity SVG-turbulence overlay for grain. Give numbers
`font-variant-numeric: tabular-nums`.

## Icon sprite
One `templates/_icons.html` with `<symbol id="i-..." viewBox="0 0 24 24">` paths, `{% include %}`d at
the top of each page, used as `<svg class="ic"><use href="#i-send"/></svg>`. Keep one stroke width
(`stroke-width:1.6`, `fill:none`, round caps/joins). Replaces emoji headings.

## Verification probe (browser_exec, text-first)
```python
new_tab("http://127.0.0.1:PORT/"); wait_for_load()
js("""(() => {
  const g=(s,p)=>{const e=document.querySelector(s);return e?getComputedStyle(e)[p]:null;};
  return { font:g('h1','fontFamily'), accent:g('.btn--accent','backgroundImage'),
           radius:g('.section','borderRadius'), nums:g('.stat__value','fontVariantNumeric'),
           css:[...document.styleSheets].some(s=>(s.href||'').includes('style.css')) };
})()""")
# then phone width — must not overflow
cdp('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=2, mobile=True)
js("document.documentElement.scrollWidth > window.innerWidth + 1")  # -> False
cdp('Emulation.clearDeviceMetricsOverride')
```

## Do not break functionality
After restyling, grep the rendered HTML for `action="..."` and `name="..."` and confirm the set is
unchanged — every form still posts to its route with its fields. Re-test empty and error states
(empty data file, unparseable file) still render (HTTP 200, not 500).
