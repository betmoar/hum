<script lang="ts">
  type Props = { size?: 'sm' | 'md' };
  let { size = 'md' }: Props = $props();
</script>

<span class="live-pill" class:sm={size === 'sm'} aria-label="Live">
  <span class="dot" aria-hidden="true"></span>
  LIVE
</span>

<style>
  .live-pill {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 8px;
    border-radius: var(--r-pill);
    background: var(--danger, #ff3b30);
    color: white;
    font-size: var(--t-xs);
    font-weight: 600;
    letter-spacing: 0.04em;
    vertical-align: baseline;
  }
  .live-pill.sm {
    padding: 1px 6px;
    font-size: 10px;
  }
  .dot {
    width: 6px;
    height: 6px;
    background: white;
    border-radius: 50%;
  }
</style>
