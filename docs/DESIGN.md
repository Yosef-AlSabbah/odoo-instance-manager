# Design

**Audience:** developers changing or restyling the web app.
**Covers:** the direction, the design tokens, type, materials, motion, charts, and how to make Sudoo.sh look like
your own product.

---

## Contents

1. [Direction](#1-direction)
2. [Where things are](#2-where-things-are)
3. [Tokens](#3-tokens)
4. [Type](#4-type)
5. [Materials and depth](#5-materials-and-depth)
6. [Motion](#6-motion)
7. [Charts](#7-charts)
8. [Copy](#8-copy)
9. [Restyling Sudoo.sh](#9-restyling-sudoosh)
10. [Checklist for a change](#10-checklist-for-a-change)
11. [Sources](#11-sources)

---

## 1. Direction

| | |
| :--- | :--- |
| **Product** | A panel that runs a live Odoo for every Git branch on your own server. |
| **Character** | Exact, calm, a little warm. |
| **World** | A server room on a night shift: terminals, status lights. Odoo's plum is the brand. |
| **Moments** | The live charts and the terminal log: the only places with rich colour. |
| **Signature** | The mark: a plum ring with a dot and a blinking text cursor on a white tile (light plum on graphite in dark mode), and a status dot that moves only while something is really running. |

The chrome (sidebar, buttons, borders, labels) stays quiet and graphite, so the content reads first. The accent
marks the primary action, the selection and the one figure that matters. Nothing glows, nothing is decorated for
its own sake, and the screen works without any animation.

---

## 2. Where things are

```
web/src/styles/
├── _tokens.scss       every colour, size, radius, shadow, material and motion value, light and dark
├── _mixins.scss       hover (only for real pointers) and press feedback
├── _base.scss         page, type, helpers
├── _motion.scss       page transitions, keyframes, reduced motion
├── _components.scss   buttons, cards, tags, status, forms, segmented control, tabs, tables, sheets, menus, toasts
├── _layout.scss       sidebar, top bar, page header
└── _pages.scss        sign-in, figures, charts, instance cards, settings rows, help pages
web/src/components/ui/  the React side of the same pieces (basics.tsx, overlay.tsx, OtpInput.tsx, Brand.tsx)
web/src/components/charts/LiveChart.tsx   the charts
```

Components take their look only from tokens. A component never names a raw colour, so a theme is one file.

---

## 3. Tokens

| Group | Tokens | Notes |
| :--- | :--- | :--- |
| Accent | `--accent`, `--accent-ink`, `--on-accent`, `--accent-soft`, `--accent-ring` | `--accent` follows `BRAND_COLOR` (Settings, Appearance) |
| Neutrals | `--bg`, `--surface`, `--raised`, `--hairline`, `--hairline-strong`, `--text`, `--text-2`, `--text-3` | Graphite in both themes; three text roles only |
| Meaning | `--positive`, `--negative`, `--caution`, `--working`, `--idle` | Used for status only, never for decoration |
| Charts | `--series-1` (the accent), `--series-2`, `--series-grid` | The first series leads, others stay quiet |
| Type | `--font`, `--mono`, `--text-12` to `--text-32` | See [Type](#4-type) |
| Shape | `--radius-tag` 6, `--radius-control` 8, `--radius-card` 14, `--radius-panel` 16 | Inner radius = outer radius minus the padding |
| Space | `--s1` to `--s12` | A 4 px grid; equal things get equal sizes |
| Materials | `--material`, `--material-blur` | Translucent chrome, see [Materials](#5-materials-and-depth) |
| Motion | `--ease`, `--ease-move`, `--ease-drawer`, `--press`, `--quick`, `--menu`, `--enter`, `--sheet` | See [Motion](#6-motion) |

Dark mode redefines the same tokens (the `dark` mixin in `_tokens.scss`): it follows the system, or the choice made
with the theme button at the bottom of the sidebar. A theme change fades over 300 ms instead of flashing.

`prefers-reduced-transparency` makes the materials solid, and `prefers-contrast: more` makes hairlines and muted
text stronger.

---

## 4. Type

- **The platform's own face first:** San Francisco on Apple devices (with its optical sizes), Inter elsewhere,
  shipped with the app. Figures, versions, commit hashes and logs use the monospace face.
- **Tracking follows size:** headings are tightened (`-0.022em` on page titles, `-0.025em` on large figures), body
  text stays near zero, the smallest text is opened slightly (`0.01em`).
- **Weights:** 400 for text, 500 for labels and emphasis, 600 for headings. Hierarchy comes from size and colour
  more than weight.
- **Numbers** always use tabular figures, so changing values do not jitter.
- **Sentence case** everywhere; no uppercase labels with wide tracking.

---

## 5. Materials and depth

Following Apple's use of translucent materials:

- The **sidebar** and the **top bar** are translucent (`--material`, a blur of 20 px with raised saturation); content
  scrolls under the top bar, and a soft fade marks where they meet instead of a hard line.
- **Sheets** (dialogs) sit on a dimming scrim, because they are a task that needs attention. The **drawer** (a job's
  details) slides in from the right edge over a dimmed page.
- **Depth on light** comes from small neutral shadows; **on dark** from surface steps and hairlines, without shadows.
- No coloured shadows, glows or gradients on surfaces.

---

## 6. Motion

The rules come from Emil Kowalski's animation standards and Apple's *Designing Fluid Interfaces*.

**Only as much motion as the action is rare.** Moving between pages happens all day, so it is a quick cross-fade
(120 ms out, 180 ms in), with no slide. Menus, sheets and toasts appear occasionally and get a short, purposeful
animation. The first-run and sign-in screens, seen rarely, bring their blocks in one after the other.

| Thing | Motion | Curve and duration |
| :--- | :--- | :--- |
| Any press (buttons, cards, rows, choices, segments) | Scales to 0.97 (0.985 for large surfaces) on press, before the click | `--ease`, 160 ms |
| Menus | Grow from the button that opened them (`transform-origin` at the trigger), shrink back into it; drawn above the page (a portal), below the button or above it when there is no room | `--ease`, 180 ms in, 120 ms out |
| Dialogs | Not anchored to a trigger: materialize in the centre (scale 0.96, opacity, 4 px blur) | `--ease`, 240 ms |
| Drawer | In from the right edge and out the same way (spatial consistency) | `--ease-drawer` (the iOS sheet curve), 400 ms in, 280 ms out |
| Toasts | Rise from the bottom edge, sink back when they go | `--ease`, 320 ms |
| Segmented control | The thumb slides to the chosen option | `--ease-move`, 280 ms |
| Switch | The thumb stretches while pressed, as on iOS | `--ease`, 160 ms |
| Numbers | Tween to the new value | ease-out, 600 ms |
| Progress | Constant motion | linear |
| A running job's status dot | The only looping motion: it says something is happening right now | 1.4 s |

Implementation rules:

- **Ease-out** for things entering and leaving, **ease-in-out** for things moving on screen, never ease-in.
- **Transitions, not keyframes,** for anything that can be interrupted: entry uses `@starting-style`, exit sets
  `data-closing` and removes the element after the transition (`components/ui/overlay.tsx`), so a menu closed while
  opening reverses smoothly from where it is.
- **Only `transform` and `opacity`** (and a small `filter: blur`) are animated; never width, height or position,
  except the segmented thumb's width.
- **Nothing appears from `scale(0)`:** entries start at 0.96 to 0.97.
- **Hover styles only for real pointers** (`@media (hover: hover) and (pointer: fine)`), so taps on a phone do not
  leave things highlighted.
- **Reduced motion** keeps changes understandable: movement is removed and replaced by short cross-fades.
- **Status chrome only when it matters:** no "live" or "synced" badge; a small "Reconnecting" notice appears only
  when the connection to the server has been lost for more than three seconds.

---

## 7. Charts

[Chart.js](https://www.chartjs.org/) draws every chart (`components/charts/`): `LiveChart` (lines over time),
`Sparkline` (the line inside a figure card), `Bars` (one bar per instance) and `Ring` (parts of a whole).

- **Each chart answers its own question;** no figure is drawn twice on a page. On the Instances page: the figure
  cards (processor, memory, disk, instances running), then requests and errors of all instances, instances by state,
  response time, and which instances use the most (processor, memory or disk, with a switch).
- **Figure cards carry a line** of the last hour under the figure: no axes, no labels, no tooltip. The figure says
  the value; the line says the direction.
- **One accent per chart:** the first series is the accent with a soft gradient under it; a second series is quiet
  (`--series-2`, or `--negative` for errors). In bars only the largest is the accent. Rings use the status colours.
- **Muted grid and monospace labels;** the time axis shows seconds while the chart covers only a few minutes.
- **Live without redrawing:** each sample from the event stream is written into the chart, and the points glide to
  their new places (300 ms). Colours are read from the tokens (`charts/theme.ts`) and follow the theme.

---

## 8. Copy

- Titles name the place: "Instances", "Settings". No greetings, no exclamation marks.
- Short labels without a full stop: "Search", "Save", "Use .env". Sentences in descriptions keep their full stops.
- A figure says what it compares to: "6% average, last hour", "of 3".
- Errors say what is wrong and what to do, in the user's words.

---

## 9. Restyling Sudoo.sh

| To change | Do this |
| :--- | :--- |
| The accent colour | Settings, Contact and appearance, **Accent colour** (or `BRAND_COLOR` in `.env`); it also colours the e-mails |
| Neutrals, radii, spacing, motion | Edit `web/src/styles/_tokens.scss` (both the light block and the `dark` mixin), then rebuild: `docker compose build web` on the server, or `npm run build` |
| Fonts | `--font` and `--mono` in `_tokens.scss`; add the font files with `npm install @fontsource/<name>` and import them in `web/src/main.tsx` |
| One component | Its block in `_components.scss` or `_pages.scss`, named after the component |
| The e-mails | Templates in `src/sudoo/mail/templates/`, or your own folder with `MAIL_TEMPLATES_DIR` ([Configuration](CONFIGURATION.md)) |
| The logo mark | `web/public/favicon.svg` is the drawing; `web/src/components/ui/Brand.tsx`, `src/sudoo/instances/mark.svg` (status pages), `docs/images/brand/` and the e-mail header (`src/sudoo/mail/templates/layout.html`, drawn in HTML because Gmail removes SVG) repeat it. A test checks the copies match |

Working on the web app: `cd web && npm install && npm run dev` serves it with live reload on port 5173, using a
backend on `127.0.0.1:9002` (see `web/vite.config.ts`; set `SUDOO_API` to use another one, for example through an
SSH tunnel to a server).

---

## 10. Checklist for a change

- [ ] Every value comes from a token, on the 4 px grid; equal things have equal sizes.
- [ ] Icons from lucide at 16 px with a 1.5 stroke, coloured like their text.
- [ ] No gradients on surfaces, glows, coloured shadows or emoji.
- [ ] Sentence case, short labels without full stops, no exclamation marks.
- [ ] Pressable things scale on press; hover styles are behind the hover mixin.
- [ ] Motion follows the table in [Motion](#6-motion); it works with reduced motion.
- [ ] Light and dark both checked; numbers tabular.
- [ ] The page makes sense at phone width.

---

## 11. Sources

- [Apple, *Designing Fluid Interfaces* (WWDC 2018) and *The Details of UI Typography* (WWDC 2020)](https://developer.apple.com/videos/),
  through the `apple-design` notes in [emilkowalski/skills](https://github.com/emilkowalski/skills) (MIT licence).
- Emil Kowalski's animation standards and design-engineering notes, in the same repository.
- [unslop](https://github.com/heydamir/unslop) by Damir Sokolovsky ([@heydamir](https://x.com/heydamir)), CC BY 4.0:
  the direction, the redline passes and the checklist behind the quiet chrome.
