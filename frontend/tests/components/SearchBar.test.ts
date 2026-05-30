import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import SearchBar from '../../src/components/SearchBar.svelte';

describe('SearchBar', () => {
  it('renders an input', () => {
    const { getByPlaceholderText } = render(SearchBar, { props: { onsubmit: () => {} } });
    expect(getByPlaceholderText(/search/i)).toBeInTheDocument();
  });

  it('emits submit on Enter', async () => {
    const onsubmit = vi.fn();
    const { getByPlaceholderText } = render(SearchBar, { props: { onsubmit } });
    const input = getByPlaceholderText(/search/i) as HTMLInputElement;
    await fireEvent.input(input, { target: { value: 'hello' } });
    await fireEvent.keyDown(input, { key: 'Enter' });
    expect(onsubmit).toHaveBeenCalledWith('hello');
  });

  it('does not emit on empty Enter', async () => {
    const onsubmit = vi.fn();
    const { getByPlaceholderText } = render(SearchBar, { props: { onsubmit } });
    const input = getByPlaceholderText(/search/i) as HTMLInputElement;
    await fireEvent.keyDown(input, { key: 'Enter' });
    expect(onsubmit).not.toHaveBeenCalled();
  });
});
