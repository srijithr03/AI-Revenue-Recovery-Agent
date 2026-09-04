import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The API serves the heavy per-case artifacts. audits.json is 4.4MB and
    // there is no reason to ship it to the browser so a judge can open one case.
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
  },
});
