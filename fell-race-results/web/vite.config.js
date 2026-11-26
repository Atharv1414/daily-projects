import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  // In development the FastAPI app runs on :8000 (see the README); the browser only ever
  // talks to this origin.
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  test: { environment: 'jsdom', setupFiles: './tests/setup.js', include: ['tests/**/*.test.{js,jsx}'] },
})
