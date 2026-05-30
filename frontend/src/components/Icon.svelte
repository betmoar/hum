<script lang="ts">
  export type IconName =
    | 'play' | 'pause' | 'skip-forward' | 'skip-back'
    | 'shuffle' | 'repeat' | 'repeat-1'
    | 'volume-2' | 'volume-x'
    | 'plus' | 'list-plus' | 'list-music'
    | 'search' | 'settings'
    | 'radio'
    | 'x'
    | 'grip-vertical'
    | 'chevron-up' | 'chevron-down'
    | 'chevron-right'
    | 'maximize-2' | 'minimize-2';

  type Props = {
    name: IconName;
    size?: number;
    'aria-label'?: string;
  };
  let { name, size = 20, ...rest }: Props = $props();
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill={name === 'play' ? 'currentColor' : 'none'}
  stroke="currentColor"
  stroke-width="1.75"
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden={rest['aria-label'] ? undefined : true}
  role={rest['aria-label'] ? 'img' : undefined}
  {...rest}
>
  {#if name === 'play'}<polygon points="6 3 20 12 6 21 6 3" stroke="none" fill="currentColor"/>
  {:else if name === 'pause'}<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>
  {:else if name === 'skip-forward'}<polygon points="5 4 15 12 5 20 5 4" fill="currentColor" stroke="none"/><line x1="19" y1="5" x2="19" y2="19"/>
  {:else if name === 'skip-back'}<polygon points="19 20 9 12 19 4 19 20" fill="currentColor" stroke="none"/><line x1="5" y1="5" x2="5" y2="19"/>
  {:else if name === 'shuffle'}<path d="M2 18h1.4c1.3 0 2.5-.6 3.3-1.7L13.3 8.4c.8-1.1 2-1.7 3.3-1.7H22"/><path d="M22 6.7l-3-3"/><path d="M22 6.7l-3 3"/><path d="M22 17.3l-3-3"/><path d="M22 17.3l-3 3"/><path d="M2 6.7h1.4c1.3 0 2.5.6 3.3 1.7l3.5 4.8"/><path d="M13 13.4l.5-.7c.8-1.1 2-1.7 3.3-1.7H22"/>
  {:else if name === 'repeat'}<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>
  {:else if name === 'repeat-1'}<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/><path d="M11 10h1v4"/>
  {:else if name === 'volume-2'}<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" fill="currentColor" stroke-linejoin="round"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>
  {:else if name === 'volume-x'}<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" fill="currentColor" stroke-linejoin="round"/><line x1="22" x2="16" y1="9" y2="15"/><line x1="16" x2="22" y1="9" y2="15"/>
  {:else if name === 'plus'}<path d="M5 12h14"/><path d="M12 5v14"/>
  {:else if name === 'list-plus'}<path d="M11 12H3"/><path d="M16 6H3"/><path d="M16 18H3"/><path d="M18 9v6"/><path d="M21 12h-6"/>
  {:else if name === 'list-music'}<path d="M21 15V6"/><path d="M18.5 18a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z"/><path d="M12 12H3"/><path d="M16 6H3"/><path d="M12 18H3"/>
  {:else if name === 'search'}<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
  {:else if name === 'settings'}<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>
  {:else if name === 'radio'}<path d="M4.9 19.1C1 15.2 1 8.8 4.9 4.9"/><path d="M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.5"/><circle cx="12" cy="12" r="2"/><path d="M16.2 7.8c2.3 2.3 2.3 6.1 0 8.5"/><path d="M19.1 4.9C23 8.8 23 15.2 19.1 19.1"/>
  {:else if name === 'x'}<path d="M18 6 6 18"/><path d="m6 6 12 12"/>
  {:else if name === 'grip-vertical'}<circle cx="9" cy="12" r="1" fill="currentColor"/><circle cx="9" cy="5" r="1" fill="currentColor"/><circle cx="9" cy="19" r="1" fill="currentColor"/><circle cx="15" cy="12" r="1" fill="currentColor"/><circle cx="15" cy="5" r="1" fill="currentColor"/><circle cx="15" cy="19" r="1" fill="currentColor"/>
  {:else if name === 'chevron-up'}<path d="m18 15-6-6-6 6"/>
  {:else if name === 'chevron-down'}<path d="m6 9 6 6 6-6"/>
  {:else if name === 'chevron-right'}<path d="m9 18 6-6-6-6"/>
  {:else if name === 'maximize-2'}<polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" x2="14" y1="3" y2="10"/><line x1="3" x2="10" y1="21" y2="14"/>
  {:else if name === 'minimize-2'}<polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/><line x1="14" x2="21" y1="10" y2="3"/><line x1="3" x2="10" y1="21" y2="14"/>
  {/if}
</svg>
