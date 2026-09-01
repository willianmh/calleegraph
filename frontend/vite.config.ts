import { fileURLToPath, URL } from 'node:url';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

/**
 * Dev server proxies `/api` (REST + the SSE stream) to the backend so the
 * browser only ever talks to one origin — the same shape nginx serves in
 * production (see `nginx.conf`). Override the target with `BACKEND_ORIGIN`
 * when the backend runs somewhere other than localhost:8000; point it at the
 * local mock (`npm run dev:mock`) on :8001 to develop without a backend.
 */
const backendOrigin = process.env.BACKEND_ORIGIN ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: backendOrigin,
        changeOrigin: true,
        // SSE must not be buffered or the connection dot never goes live.
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              proxyRes.headers['cache-control'] = 'no-cache, no-transform';
            }
          });
        },
      },
    },
  },
  build: { outDir: 'dist', sourcemap: false },
});
