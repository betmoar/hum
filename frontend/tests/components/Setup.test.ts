import { describe, it, expect, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import Setup from '../../src/components/Setup.svelte';
import { store } from '../../src/lib/store.svelte';

beforeEach(() => {
  localStorage.clear();
  store.invalidateToken();
});

describe('Setup', () => {
  it('renders an input and a save button', () => {
    const { getByPlaceholderText, getByRole } = render(Setup);
    expect(getByPlaceholderText(/bearer token/i)).toBeInTheDocument();
    expect(getByRole('button', { name: /save/i })).toBeInTheDocument();
  });

  it('saves the token to the store on submit', async () => {
    const { getByPlaceholderText, getByRole } = render(Setup);
    const input = getByPlaceholderText(/bearer token/i) as HTMLInputElement;
    await fireEvent.input(input, { target: { value: 'my-token-1234567890' } });
    await fireEvent.click(getByRole('button', { name: /save/i }));
    expect(store.settings.bearerToken).toBe('my-token-1234567890');
  });

  it('rejects tokens shorter than 16 characters', async () => {
    const { getByPlaceholderText, getByRole, queryByText } = render(Setup);
    const input = getByPlaceholderText(/bearer token/i) as HTMLInputElement;
    await fireEvent.input(input, { target: { value: 'short' } });
    await fireEvent.click(getByRole('button', { name: /save/i }));
    expect(store.settings.bearerToken).toBeNull();
    expect(queryByText(/at least 16 characters/i)).toBeInTheDocument();
  });
});
