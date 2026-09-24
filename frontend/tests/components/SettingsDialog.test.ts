import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import { flushSync } from 'svelte';
import SettingsDialog from '../../src/components/SettingsDialog.svelte';
import Search from '../../src/pages/Search.svelte';
import { api } from '../../src/lib/api';
import { router } from '../../src/routes.svelte';
import type { SearchResponse } from '../../src/lib/types';

const emptyResults: SearchResponse = { query: '', items: [] };

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
  router.closeSettings();
});

describe('SettingsDialog', () => {
  it('is closed (no open attribute) when open=false', () => {
    const { container } = render(SettingsDialog, { open: false, onclose: () => {} });
    const dialog = container.querySelector('dialog');
    expect(dialog?.open).toBeFalsy();
  });

  it('opens (native showModal) when open=true and renders Settings content', async () => {
    const { container } = render(SettingsDialog, { open: true, onclose: () => {} });
    await flushSync();
    const dialog = container.querySelector('dialog');
    expect(dialog?.open).toBeTruthy();
    expect(container.querySelector('#settings-dialog-title')?.textContent).toBe('Settings');
  });

  it('Esc (native cancel event) calls onclose', async () => {
    const onclose = vi.fn();
    const { container } = render(SettingsDialog, { open: true, onclose });
    await flushSync();
    const dialog = container.querySelector('dialog')!;
    const cancelEvent = new Event('cancel', { cancelable: true });
    dialog.dispatchEvent(cancelEvent);
    expect(onclose).toHaveBeenCalledOnce();
    expect(cancelEvent.defaultPrevented).toBe(true);
  });

  it('clicking the backdrop (a click landing on the dialog element itself) calls onclose', async () => {
    const onclose = vi.fn();
    const { container } = render(SettingsDialog, { open: true, onclose });
    await flushSync();
    const dialog = container.querySelector('dialog')!;
    await fireEvent.click(dialog);
    expect(onclose).toHaveBeenCalledOnce();
  });

  it('the close button calls onclose', async () => {
    const onclose = vi.fn();
    const { getByLabelText } = render(SettingsDialog, { open: true, onclose });
    await flushSync();
    await fireEvent.click(getByLabelText('Close settings'));
    expect(onclose).toHaveBeenCalledOnce();
  });

  it('mounting/opening the dialog does not unmount or reset a page rendered alongside it', async () => {
    vi.spyOn(api, 'search').mockResolvedValue(emptyResults);
    const { getByPlaceholderText, container } = render(Search);
    const input = getByPlaceholderText(/search/i) as HTMLInputElement;

    await fireEvent.input(input, { target: { value: 'brian eno' } });
    await fireEvent.keyDown(input, { key: 'Enter' });
    await new Promise((r) => setTimeout(r, 0));

    expect(container.querySelector('.meta')?.textContent).toContain('brian eno');

    // Simulate SettingsDialog mounting/opening alongside the already-rendered
    // page (the whole point of #17: it's a dialog, not a route swap).
    const dialog = render(SettingsDialog, { open: true, onclose: () => {} });
    await flushSync();
    expect(dialog.container.querySelector('dialog')?.open).toBeTruthy();

    // Search's state must be untouched — nothing about opening the dialog
    // should have caused a remount or reset of the page underneath it.
    expect(input.value).toBe('brian eno');
    expect(container.querySelector('.meta')?.textContent).toContain('brian eno');

    dialog.unmount();
  });
});
