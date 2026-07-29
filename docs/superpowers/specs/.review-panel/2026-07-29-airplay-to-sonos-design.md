# Panel run — 2026-07-29-airplay-to-sonos-design.md  (2026-07-29 15:51)

- **artifact:** docs/superpowers/specs/2026-07-29-airplay-to-sonos-design.md
- **reviewer:** glm-review-design     **N:** 3
- **lenses:** A ambiguity · B contradictions/feasibility · C testability
- **per-lens:** A → 13 findings · B → 2 · C → 13  (tokens: none reported by agents; omitting per-skill "never fabricate")
- **buckets:** must-resolve 4 · should-clarify 7 · consider ~8 · dropped <50: 0 (all reports were already scoped)
- **asked:** 4 should-clarify → answers in the artifact's Clarifications section
- **verdict:** GLM first pass. No code-vs-claim contradictions (lens B clean). Findings cluster on two missing artifacts: a falsifier for Task 0, and explicit acceptance/per-option pass-fail. One live-strategy answer (lens C Q3) reframed the build sequencing — see Clarifications.

## Findings

### must-resolve
- [85] Task 0 "verify empirically" has no falsifier (lens A:38-41, lens C:37-41). Verdict confirmed by two lenses. → RESOLVE in spec: pass = audio plays from Sonos with HOST=127.0.0.1 unchanged; fail = Safari/Sonos attempts a fetch to a 127.0.0.1 URL it would have to resolve.
- [80] Option A→B→C sequencing has no per-option pass/fail signal (lens A:121-123, lens C:121-123). → RESOLVE in spec: define the observable that triggers fallback (target connected + no audio within Ns, or fatal Hls.Error).
- [78] AirPlay disconnect mid-playback undefined (lens A:96-123). → RESOLVE in spec: button reverts to inactive via the changed event; local playback continues at current position; no stall.
- [75] Manual gate has no acceptance language (lens C:131-135). → RESOLVE in spec: binary-outcome checklist with a named Sonos model recorded alongside results.

### should-clarify  (→ asked)
- [72] Track-skip while routed — undefined (lens A:96-104). → **A:** Keep routing (route persists across track changes).
- [70] Expiry-induced src swap drops the route (lens A/C:90-94, 127-130). → **A:** Auto re-assert after the recovery swap.
- [68] Live A→B→C sequencing / hardware availability (lens C gaps, lens B consider). → **A:** dev machine is a Mac (Safari local) — build full A→B→C chain, validate locally; C-first MVP rationale withdrawn.
- [65] AirPlay picker entry point across both surfaces (lens B:78-80). → **A:** new playerControls method (showPlaybackTargetPicker).
- [60] Feature-detect contract for partial WebKit support (lens A:144, C:144). [hold for spec edit]
- [60] Vitest scope — what "our logic" observably proves (lens C:127-130). [hold for spec edit]
- [60] Manual gate acceptance wording (lens C:131-135). [overlaps must-resolve]

### consider
- [58] ALAC 16/44.1 vs lossy ≤48kHz source — one-line note (lens A:27-35).
- [55] Battery-listener lifecycle tied to element mount vs playback (lens A:66-70).
- [55] "survives past expiry" wording — expiry is on signed URL not route (lens A:90-94).
- [52] Sonos model/firmware baseline recorded with results (lens C gap).
- [50] iOS "no in-page picker" assertion uncited (lens A:43-51).
- [50] NowPlaying querySelector('audio') path sufficient for the action or needs the new method (lens B:78-80) — resolved by the picker-method answer.

### dropped <50
- (none — all three reports were already scoped; dedup removed rest)
