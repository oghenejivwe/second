# Second's design: Letters, light

Second is dressed in the Letters style. It is a light, paper-and-ink look: a
white page, near-black type set in a soft rounded face, generous space, cards
that sit on shadows so faint you notice the lift before the edge, and a single
clear blue kept for instruments. It suits Second because Second listens,
remembers and reports back. A calm white page with honest black text puts the
user's day in front, keeps controls quiet, and leaves the product's two
signals, something slipped and something held, as the only colour that means
anything.

Source: https://styles.refero.design/style/04109c48-f591-4110-9739-622243d4ecc2

## Tokens

All tokens live in `web/src/styles/tokens.css`. Letters tokens are new; the
older names (`--bg`, `--text-dim` and so on) still work and now point at light
values, so a module written for the dark theme still renders sensibly.

### Colour

| Token | Value | Use |
| --- | --- | --- |
| `--color-obsidian` | `#070709` | Primary text, filled pills, the focus ring |
| `--color-paper` | `#ffffff` | Page, cards, the rail |
| `--color-cloud` | `#f5f5f5` | Secondary and inset surfaces, hover behind a pill |
| `--color-sky-tint` | `#d7e6f5` | Selected highlight, text selection, canvas selection |
| `--color-charcoal` | `#60606c` | Secondary text, nav labels, muted borders |
| `--color-slate` | `#8b8b8b` | Placeholders, disabled controls, text 18px and up only (3.41:1) |
| `--color-ink` | `#151515` | Headings, the wordmark, strong dividers |
| `--color-hairline` | `#bebecc` | Card and control borders, ghost pill border, drop zone |
| `--accent` | `#2597d0` | Instruments only: mic glyph, waveform, small icons, canvas selection edge |
| `--gradient-sky` | `linear-gradient(180deg, #779bc1 0%, #9abfda 58%, #cbdcec 100%)` | The login hero, once |
| `--bg` | `#ffffff` | Page and main area |
| `--bg-raised` | `#ffffff` | Cards and panels (lifted by border and shadow, not by tone) |
| `--bg-inset` | `#f5f5f5` | Quoted and inset blocks |
| `--bg-hover` | `#efeff3` | Hover on a row or control |
| `--rule` | `#e7e7ee` | Quiet dividers |
| `--rule-strong` | `#bebecc` | Stronger dividers and borders |
| `--text` | `#070709` | Primary text (20.13:1 on white) |
| `--text-dim` | `#60606c` | Secondary text (6.20:1) |
| `--text-faint` | `#6a6a76` | Tertiary text (5.34:1) |
| `--text-ghost` | `#6f6f7b` | The quietest readable text (4.96:1 on white, 4.55:1 on Cloud) |
| `--slip` | `#a8493f` | Something slipped, as text or a mark (5.69:1) |
| `--slip-dim` | `#d49c94` | Border beside a slip |
| `--slip-wash` | `rgba(168, 73, 63, 0.07)` | Faint background behind a slip |
| `--held` | `#4e7048` | Something held (5.62:1) |
| `--held-dim` | `#9fb899` | Border beside a held item |
| `--held-wash` | `rgba(78, 112, 72, 0.08)` | Faint background behind a held item |
| `--focus` | `#070709` | Focus ring |
| `--ink-000` to `--ink-900` | `#ffffff` to `#070709` | Legacy grey scale, inverted; prefer the named tokens in new work |

### Type

| Token | Value | Use |
| --- | --- | --- |
| `--font-display` | Open Runde, then system sans | Headings, nav, body copy |
| `--font` | `var(--font-display)` | Legacy name for the body face |
| `--font-ui` | Inter, then system sans | Small UI labels, tags, captions |
| `--font-mono` | System monospace | Evidence from the calendar, inbox or audit |
| `--tracking-tight` | `-0.04em` | 28px and larger |
| `--tracking-body` | `-0.01em` | 14 to 18px |
| `--size-11` … `--size-44` | 11, 12, 13, 14, 16, 18, 19, 20, 24, 28, 32, 44px (in rem) | Type sizes |

The scale Second works to: caption 12/1.2, body-sm 14/1.4, body 16/1.49,
body-lg 18/1.4, subheading 20/1.4, heading-sm 28/1.2, heading 44/1.1, and
display 80/0.9 for the rare very large number. Headings are weight 600.
Text at 10 to 12px keeps normal tracking.

### Space, shape and depth

| Token | Value | Use |
| --- | --- | --- |
| `--space-1` … `--space-8` | 4, 8, 12, 16, 24, 32, 48, 64px | Spacing on a 4px base |
| `--radius-pill` | `100px` | Buttons, tags, nav pills |
| `--radius-card` | `18px` | Cards |
| `--radius-card-lg` | `32px` | Large cards, the login panel |
| `--radius-input` | `12px` | Inputs, text areas, selects, drop zones |
| `--radius-icon` | `8px` | Icon tiles, canvas controls |
| `--shadow-card` | three blue-tinted layers, 0.02 to 0.03 | Cards |
| `--shadow-button` | four short neutral layers, up to 0.1 | Filled pills |
| `--shadow-accent` | two blue layers, 0.07 to 0.08 | A blue instrument that needs to sit up |
| `--shadow-subtle` | `rgba(228, 229, 231, 0.24) 0 1px 2px` | Small controls |
| `--rail-width` | `192px` | The navigation rail |
| `--measure` | `62ch` | Longest comfortable line |
| `--beat` / `--ease` | `240ms` / `cubic-bezier(0.2, 0, 0.2, 1)` | The one transition (1ms under reduced motion) |

## Fonts

| Face | npm package | Weights loaded | Where |
| --- | --- | --- | --- |
| Open Runde | `@fontsource/open-runde` 5.3.0 | 400, 500, 600, 700 | Headings, nav, body, with `font-feature-settings: 'ss01'` |
| Inter | `@fontsource/inter` 5.3.0 | 400, 500 | Small UI labels |

Both are imported at the top of `web/src/main.tsx`, before the stylesheets.

## Recipes

**Pill button (primary).** Obsidian background, white text at 14 to 16px
weight 500, `12px 24px` padding, `--radius-pill`, `--shadow-button`. The
current nav item in the rail uses the same fill as a place marker.

**Ghost pill (secondary).** Transparent, `1px solid var(--color-hairline)`,
Obsidian text, `--radius-pill`. Hover on Cloud Gray.

**Tag.** `--radius-pill`, 1px hairline border, `4px 12px` padding, Inter at 12
to 14px weight 500, Charcoal text. A blue icon is allowed inside when the tag
names an instrument. The fixtures tag in the rail is one.

**Card.** `--bg-raised`, `--radius-card`, a `--rule` border and
`--shadow-card`. App screens pad at the low end, 24px.

**Drop zone.** `1px dashed var(--color-hairline)`, `--radius-input`; the border
darkens to `--color-slate` on hover or while a file is over it.

**Waveform.** Drawn in `--accent`. It is the clearest case of blue as an
instrument, as is the mic glyph beside it.

**Login hero.** The only place `--gradient-sky` appears: a full band behind a
white `--radius-card-lg` panel with `--shadow-card`. No other screen gets a
gradient.

## Rules that survive from Second's first look

- Two semantic hues only, `--slip` and `--held`. They carry information and
  never decorate. No celebratory success green.
- Both hues, and every text token, meet WCAG AA 4.5:1 on white. Text 18px and
  larger may drop to 3:1, which is the only place `--color-slate` is text.
- Evidence quoted from the calendar, inbox or audit is set in `--font-mono`.
- Action is monochrome: no chromatic button fill, anywhere.
- The old token names keep working, remapped to light values.
- One transition duration, `--beat`, cut to 1ms under reduced motion.

## Changing the look

Start in `web/src/styles/tokens.css`. Change a value there and every module
that names the token follows. Global element defaults (body, headings, focus,
form controls, `.evidence`, `.label`) are in `base.css`, React Flow's canvas in
`flow.css`, and everything else is a CSS Module next to its component. If a
new colour seems necessary, check the rules above first; the answer is usually
a grey, a weight or more space.
