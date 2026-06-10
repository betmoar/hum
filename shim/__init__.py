"""hum-subsonic-shim — a Subsonic-compatible adapter in front of Hum.

Sibling service to the Hum backend (spec: docs/SONOS_SPEC.md). bonob points
at this shim via BNB_SUBSONIC_URL; the shim translates the Subsonic subset
bonob calls into Hum API calls and remuxes/transcodes audio for Sonos.
"""
