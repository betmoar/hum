<script lang="ts"></script>

<!-- Apple-style 12-spoke radial spinner. CSS conic mask gives the
     classic fading-tail look without any JS or extra DOM. -->
<div class="spinner" role="status" aria-label="Loading">
  <div class="ring"></div>
</div>

<style>
  .spinner {
    width: 28px;
    height: 28px;
    display: inline-grid;
    place-items: center;
    margin: var(--s-5) auto;
  }
  .ring {
    width: 100%;
    height: 100%;
    border-radius: 50%;
    background: conic-gradient(
      from 0deg,
      rgba(255, 255, 255, 0) 0deg,
      var(--ink) 360deg
    );
    /* Donut mask so the centre is hollow. */
    -webkit-mask: radial-gradient(circle, transparent 38%, black 40%);
            mask: radial-gradient(circle, transparent 38%, black 40%);
    animation: spin 0.9s linear infinite;
  }
</style>
