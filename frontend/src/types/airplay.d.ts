// WebKit AirPlay playback-target APIs on HTMLMediaElement. Non-standard,
// absent from lib.dom.d.ts. Declared here so svelte-check passes; the
// runtime feature-detects each one before use.
export {};

declare global {
  interface HTMLMediaElement {
    webkitShowPlaybackTargetPicker?: () => void;
    webkitCurrentPlaybackTargetIsWireless?: boolean;
    addEventListener(
      type: 'webkitplaybacktargetavailabilitychanged',
      listener: (this: HTMLMediaElement, ev: AirplayAvailabilityEvent) => void,
    ): void;
    addEventListener(
      type: 'webkitcurrentplaybacktargetiswirelesschanged',
      listener: (this: HTMLMediaElement, ev: Event) => void,
    ): void;
    removeEventListener(
      type: 'webkitplaybacktargetavailabilitychanged',
      listener: (this: HTMLMediaElement, ev: AirplayAvailabilityEvent) => void,
    ): void;
    removeEventListener(
      type: 'webkitcurrentplaybacktargetiswirelesschanged',
      listener: (this: HTMLMediaElement, ev: Event) => void,
    ): void;
  }

  interface AirplayAvailabilityEvent extends Event {
    availability: 'available' | 'not-available';
  }
}
