# Hum — design system conventions

Compact reference for tokens, container rhythm, and layout patterns.
Pair this with the screenshots in `docs/screenshots/` and the rationale
in `docs/design-system-plan.md` for the longer-form decisions.

## Container rhythm

Every route-level page renders one `<section>` at its root that reads
its padding, max-width, and block-gap from CSS custom properties. Don't
redeclare these literals — drift is the failure mode this convention
exists to prevent.

### Tokens (defined in `frontend/src/app.css`, on `:root`)

| Token | Value | What it controls |
|---|---|---|
| `--container-pad-block-start` | `var(--s-7)` (48px) | Top padding of a page section |
| `--container-pad-block-end` | `var(--s-6)` (32px) | Bottom padding (lighter — the player capsule lives below) |
| `--container-pad-inline` | `var(--s-6)` (32px) | Horizontal padding |
| `--container-gap` | `var(--s-5)` (24px) | Vertical rhythm between major blocks inside the section |
| `--container-max` | `var(--content-max)` (1080px) | Default max-width (lists, hero pages) |
| `--container-max-narrow` | `760px` | Narrow variant (Settings, forms) |

### Usage

```css
/* Inside any pages/*.svelte <style> block */
section {
  padding:
    var(--container-pad-block-start)
    var(--container-pad-inline)
    var(--container-pad-block-end);
  max-width: var(--container-max);  /* or --container-max-narrow */
  margin: 0 auto;
}
```

Reference implementations:
- [Queue.svelte](../frontend/src/pages/Queue.svelte) — default width
- [Settings.svelte](../frontend/src/pages/Settings.svelte) — narrow width

### Mobile

A single global `:root` clamp at `(max-width: 640px)` in `app.css`
overrides the container tokens to mobile values. Every page
consuming the tokens picks this up without its own override.

```css
@media (max-width: 640px) {
  :root {
    --container-pad-block-start: var(--s-5);   /* 24 */
    --container-pad-block-end:   var(--s-5);
    --container-pad-inline:      var(--s-4);   /* 16 */
    --container-gap:             var(--s-4);
  }
}
```

Page-local `@media` blocks remain free to override for
**layout-specific** adjustments at their own breakpoints:

| Page | Local @media | Concern |
|---|---|---|
| Video | 720px | Hero column collapses (artwork no longer beside content) |
| Settings | 560px | Panels tighten, rows stack |
| Queue | 640px | Artwork shrinks, queue padding tightens |

The convention: **token-driven concerns** (page padding, gap,
max-width) follow the unified 640 breakpoint. **Layout-specific
concerns** (column collapse, internal spacing) get their own
breakpoint at the value that matches the layout, not the global
rhythm.

## Eyebrow

Small label that sits above route titles and section heroes. Hum brand:
coral is precious (icon/CTA/focus/active only), one typeface, no all-caps
body, never 600+. So this uses sentence-case, soft ink, Medium 500. One
global rule lives in `app.css`:

```css
.eyebrow {
  color: var(--ink-soft);
  font-size: var(--t-xs);
  letter-spacing: 0.01em;
  font-weight: 500;
  margin: 0 0 var(--s-2);
}
```

Don't redeclare. Position-specific tweaks (margin overrides for nested
contexts) are fine but never re-define colour, weight, or letter-
spacing — that breaks the visual cohesion.

## Buttons

Three intent classes layer on the default glass button:

| Class | Use | Treatment |
|---|---|---|
| (default) | Neutral, secondary | `--glass-2`, hairline border |
| `.primary` | Primary CTA | Filled `--accent`, white text |
| `.destructive` | Triggers irreversible flow | Neutral at rest, red on hover/focus; pairs with the confirm dialog's `.primary.danger` (filled red commit button) |

The destructive treatment exists for *triggers* like "Clear all" — the
filled-red commit button is reserved for the actual irreversible action
inside the dialog.

## Chromatic identity

The `--art-hue` custom property is sampled from the currently-playing
artwork (`lib/artHue.svelte.ts`) and propagates through the glass token
system. Surfaces opt into intensity via classes on `.art-stage`:

| Class | When | Layer opacity |
|---|---|---|
| (none) | Player-active, expanded view | 1.0 (full bloom) |
| `.preview` | Queue page with no current track | 0.5 |
| `.dampened` | Routes where cards lead, not artwork (`/queue`) | 0.55 |
| `.dampened.preview` | Queue route + queue preview | 0.3 |

Add a new dampener class to `App.svelte` and CSS only when introducing
a route where the wash visibly competes with content.

## Motion

All motion (drift, breathe, shimmer, view-transitions) lives behind
`@media (prefers-reduced-motion: no-preference)` for the additive
animations, or has a `(prefers-reduced-motion: reduce)` override that
flattens duration to `0.01ms`. The contract is tested by:
- [tests/unit/livingGlass.test.ts](../frontend/tests/unit/livingGlass.test.ts) — the three living-glass keyframes
- [tests/unit/viewTransitions.test.ts](../frontend/tests/unit/viewTransitions.test.ts) — the view-transition durations and reduced-motion override

If you add a new animation, add a guard and add a test.

## Typography

- **Content** (track titles, brand wordmark, italic hints) uses
  `var(--font-display)` (Instrument Serif).
- **Chrome** (route headers, button labels, eyebrows, metadata) uses
  `var(--font-sans)` (SF Pro Display fallback chain).
- The split is enforced by per-element font-family declarations, not by
  cascade — there's no global "h1 uses serif" rule.

When in doubt: is this text the *content* (what the user is here to
see) or the *frame around the content* (navigation, labels, helpers)?
Content gets serif; frame gets sans.

## Overlay layout — three zones

Full-bleed modal overlays (today: NowPlaying expanded view) use a
three-zone grid that mirrors the main app shell (nav / main / player
capsule):

```
┌────────────────────────────────────┐
│ chrome (close, queue)               │  ← position:absolute, top corners
├────────────────────────────────────┤
│ content (artwork, title, meta)      │  ← scrolls when overflowing
├────────────────────────────────────┤
│ controls (scrubber, transport)      │  ← sticky bottom, always visible
└────────────────────────────────────┘
```

CSS shape:

```css
.overlay {
  position: fixed; inset: 0; z-index: 200;
  display: grid;
  grid-template-rows: 1fr auto;
}
.overlay-content {
  min-height: 0;            /* lets flex children shrink within grid 1fr */
  overflow-y: auto;
  display: flex; flex-direction: column;
  align-items: center;
  justify-content: safe center;  /* falls back to flex-start on overflow */
  gap: var(--container-gap);
  padding:
    var(--container-pad-block-start)
    var(--container-pad-inline)
    var(--s-4);
}
.overlay-controls {
  display: flex; flex-direction: column;
  align-items: center;
  gap: var(--s-4);
  padding:
    var(--s-4)
    var(--container-pad-inline)
    var(--container-pad-block-end);
}
```

Reference: [NowPlaying.svelte](../frontend/src/components/NowPlaying.svelte).

The artwork in a hero overlay uses `min(45vh, 480px)` (not `60vh`) to
leave room for a 3-line title and metadata strip alongside the sticky
controls at typical 900px-tall viewports.

If a second overlay materialises (settings sheet, queue drawer), lift
this pattern to a shared `<Overlay>` component.

## Out-of-scope right now

These are deliberate punts — flagging so future contributors don't
assume they're missing accidentally:

- No `<Section>` / `<Overlay>` Svelte components. Tokens + per-page
  styling are sufficient at the current surface count. The overlay
  shape exists once (NowPlaying); a second instance justifies a
  component lift.
- Page-local layout @media blocks at varying breakpoints
  (Video 720, Settings 560) remain by design — they handle
  layout-specific transitions, not the global container rhythm
  which is now unified at 640px.
- The "Queue" affordance is at three different positions across
  surfaces — top-right link in the desktop nav, bottom-middle tab on
  mobile, top-left button in the expanded NowPlaying overlay. This
  is intentional: each surface follows its own convention (route nav
  vs platform-native tab bar vs modal chrome). Unifying would force
  one of the three to violate its surface's convention.
- The `.art-stage` modifier matrix (`preview`, `dampened`, and
  their intersection) is written as three explicit rules rather
  than a single CSS custom property fed by each modifier. At three
  rules the explicit form is more readable; if a fourth modifier
  lands, switch to the variable approach.
- The scrubber `height: 44px` hit zone in the expanded overlay
  relies on the default range-track + thumb rendering centring
  inside the taller input element. This works consistently across
  WebKit/Blink; Firefox is presumed-correct but unverified. If
  cross-browser parity issues surface, add explicit
  `::-moz-range-track` / `::-moz-range-thumb` styling.
