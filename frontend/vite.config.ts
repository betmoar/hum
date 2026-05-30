/// <reference types="vitest" />
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
  resolve: {
    // Force Svelte 5 to use the client-side build under Vitest+jsdom; without
    // this it picks the server build and `mount(...)` fails.
    conditions: process.env.VITEST ? ['browser'] : undefined,
  },
  server: {
    port: 5173,
    proxy: {
      '/api':    { target: 'http://127.0.0.1:8000', changeOrigin: false },
      '/proxy':  { target: 'http://127.0.0.1:8000', changeOrigin: false },
      '/health': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.test.ts'],
  },
});
