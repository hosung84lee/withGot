import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
const proxy = { '/api': 'http://127.0.0.1:8000' }
const policy = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
  + "img-src 'self' blob: data:; font-src 'self' blob: data:; worker-src 'self' blob:; "
  + "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
const headers = {
  'Cache-Control': 'no-store',
  'Referrer-Policy': 'no-referrer',
  'X-Content-Type-Options': 'nosniff',
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1', port: 5173, strictPort: true, proxy,
    headers: { ...headers, 'Content-Security-Policy': policy
      .replace("script-src 'self'", "script-src 'self' 'unsafe-inline'")
      .replace("connect-src 'self'", "connect-src 'self' ws://127.0.0.1:5173") },
  },
  preview: {
    host: '127.0.0.1', port: 5173, strictPort: true, proxy,
    headers: { ...headers, 'Content-Security-Policy': policy },
  },
})
