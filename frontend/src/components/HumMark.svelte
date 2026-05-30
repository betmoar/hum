<script lang="ts">
  /**
   * Hum mark — three concentric rings + center dot.
   *
   * Geometry is fixed per the brand guide (radii 22/44/66, strokes 5/4.5/4,
   * opacities 1.0/0.55/0.25, center dot diameter 6). At 32px or below the
   * outermost ring is dropped — it vanishes optically anyway. Stroke color
   * inherits from CSS `color` so the same mark works coral, charcoal, or
   * warm-white depending on context.
   *
   * Hard constraints from the brand guide — do not add:
   *   - filter / box-shadow / drop-shadow
   *   - linear-gradient / radial-gradient
   *   - rotate / skew / stretch transforms
   *   - segmented arcs (rings stay whole)
   */
  let {
    size = 32,
    title = 'Hum',
    class: className = '',
  }: { size?: number; title?: string; class?: string } = $props();

  // Drop the outermost ring at favicon-ish sizes per the brand rule.
  let dropOuter = $derived(size <= 32);
</script>

<svg
  xmlns="http://www.w3.org/2000/svg"
  width={size}
  height={size}
  viewBox="-72 -72 144 144"
  role="img"
  aria-label={title}
  class={className}
  fill="none"
  stroke="currentColor"
>
  {#if !dropOuter}
    <circle cx="0" cy="0" r="66" stroke-width="4"   opacity="0.25" />
  {/if}
  <circle   cx="0" cy="0" r="44" stroke-width="4.5" opacity="0.55" />
  <circle   cx="0" cy="0" r="22" stroke-width="5"   opacity="1" />
  <circle   cx="0" cy="0" r="3"  fill="currentColor" stroke="none" />
</svg>
