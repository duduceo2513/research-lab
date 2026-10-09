import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Backend origin for the dev proxy.
const backend = process.env.BACKEND_URL ?? 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    // Same-origin API/WebSocket during development: no CORS, and the browser talks only to :5173.
    proxy: {
      '/api': backend,
      '/admin': backend,
      '/static': backend,
      '/media': backend,
      '/ws': { target: backend, ws: true },
    },
  },
})
