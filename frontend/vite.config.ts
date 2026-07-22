import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = fileURLToPath(new URL('.', import.meta.url))

// https://vite.dev/config/
// Ops admin pages are static: public/ops-*/index.html → dist/ops-*/
// Architecture explainer is a React MPA entry: architecture/index.html → dist/architecture/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/ops': 'http://127.0.0.1:8000',
    },
  },
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        architecture: resolve(__dirname, 'architecture/index.html'),
      },
    },
  },
})
