import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  const DEV_API_TARGET = env.VITE_DEV_API_TARGET || 'http://localhost:8080'

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target: DEV_API_TARGET,
          changeOrigin: true,
          rewrite: (path: string) => path.replace(/^\/api/, ''),
          // Indexing a large PDF can take minutes.
          timeout: 600_000,
        },
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: './src/tests/setupTests.ts',
      include: ['src/**/*.{test,spec}.{ts,tsx}'],
      exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
      coverage: {
        reporter: ['text', 'json-summary', ['lcov', { projectRoot: '../..' }], 'html'],
        reportsDirectory: './coverage',
      },
    },
  }
})
