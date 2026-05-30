<script lang="ts">
  type Props = { text: string };
  let { text }: Props = $props();

  const GAP_PX = 64;
  // Target reading speed. 30 px/s is a comfortable scrolling-text rate.
  // Driven by a rAF loop (not CSS animation) so the speed is frame-accurate
  // and constant regardless of title length — and immune to mid-scroll
  // re-measurement, which made the previous custom-property-driven CSS
  // animation snap and run far too fast.
  const SPEED_PX_PER_SEC = 30;

  let wrap = $state<HTMLElement | null>(null);
  let inner = $state<HTMLElement | null>(null);
  let isOverflowing = $state(false);

  // Plain (non-reactive) loop state — read/written only inside the rAF tick.
  let travelPx = 0; // distance the strip moves per loop iteration (span + gap)

  function measure() {
    if (!wrap || !inner) return;
    const firstSpan = inner.querySelector('span');
    if (!firstSpan) return;
    const textWidth = firstSpan.getBoundingClientRect().width;
    isOverflowing = textWidth > wrap.clientWidth + 1;
    // Travel exactly one (span + gap) per loop so the duplicate copy lands
    // precisely where the original was — seamless, pixel-precise wrap.
    travelPx = textWidth + GAP_PX;
  }

  $effect(() => {
    // Re-run whenever `text` changes (new track) so a long-title track
    // doesn't inherit a previous short-title's state.
    void text;
    if (!wrap || !inner) return;
    const strip = inner;

    // Reduced motion: keep a slow crawl rather than freezing (a truncated
    // title is its own UX failure), at a third of the normal rate.
    const reduceMotion =
      typeof matchMedia !== 'undefined' &&
      matchMedia('(prefers-reduced-motion: reduce)').matches;
    const speed = reduceMotion ? SPEED_PX_PER_SEC / 3 : SPEED_PX_PER_SEC;

    // Custom Google Fonts swap in 50-500ms after first paint, changing the
    // measured text width. Re-measure across phases — the rAF loop below
    // picks up the new travelPx without restarting, so there is no glitch.
    measure();
    const t1 = setTimeout(measure, 300);
    const t2 = setTimeout(measure, 1000);
    if (typeof document !== 'undefined' && 'fonts' in document) {
      document.fonts.ready.then(measure).catch(() => { /* ignore */ });
    }
    const ro = new ResizeObserver(measure);
    ro.observe(wrap);
    ro.observe(inner);

    let pos = 0; // current leftward offset in px
    let last = 0; // timestamp of previous frame
    let frame = 0;
    const tick = (ts: number) => {
      frame = requestAnimationFrame(tick);
      if (!last) { last = ts; return; }
      const dt = (ts - last) / 1000;
      last = ts;
      if (!isOverflowing || travelPx <= 0) {
        if (pos !== 0) { pos = 0; strip.style.transform = ''; }
        return;
      }
      pos += speed * dt;
      if (pos >= travelPx) pos -= travelPx; // seamless wrap to the duplicate
      strip.style.transform = `translateX(${-pos}px)`;
    };
    frame = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(t1);
      clearTimeout(t2);
      ro.disconnect();
      strip.style.transform = '';
    };
  });
</script>

<div class="wrap" bind:this={wrap}>
  <div class="inner" class:scroll={isOverflowing} bind:this={inner}>
    <span>{text}</span>
    {#if isOverflowing}<span aria-hidden="true">{text}</span>{/if}
  </div>
</div>

<style>
  .wrap {
    overflow: hidden;
    mask-image: linear-gradient(to right, transparent 0, black 8px, black calc(100% - 16px), transparent 100%);
    -webkit-mask-image: linear-gradient(to right, transparent 0, black 8px, black calc(100% - 16px), transparent 100%);
  }
  .inner {
    display: inline-flex;
    gap: 64px;
    white-space: nowrap;
    width: max-content;
  }
  /* Position is driven per-frame from JS (see the rAF loop). Promote to its
     own layer so the per-frame transform stays on the compositor. */
  .inner.scroll {
    will-change: transform;
  }
</style>
