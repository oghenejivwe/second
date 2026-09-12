import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

/**
 * The dev server proxies `/api` to uvicorn so the browser makes same-origin
 * requests. Two reasons that beats CORS headers in development: the fetch code
 * is then identical in dev and in production (where FastAPI serves the built
 * bundle from the same origin), and a misconfigured CORS header fails as an
 * opaque network error with nothing useful in it.
 *
 * `127.0.0.1` rather than `localhost`: on Windows, `localhost` can resolve to
 * `::1` first while uvicorn is listening only on IPv4, which shows up as an
 * intermittent ECONNREFUSED that looks like the backend crashed.
 *
 * ## Where the data comes from
 *
 * `VITE_SOURCE` is set here rather than in a `.env` file, because the
 * repository ignores `.env.*` as a credentials rule -- correctly -- and a mode
 * switch that cannot be committed is a mode switch that works on one machine.
 *
 *   npm run dev        fixtures   the checked-in payloads, generated from the
 *                                 real code paths by scripts/make_fixtures.py
 *   npm run dev:live   live       uvicorn on :8000, through the proxy below
 *   npm run build      live       the bundle FastAPI serves; never ships fixtures
 *   npm run build:demo fixtures   a static bundle for a host with no backend
 *
 * `build:demo` is the one exception to "a built bundle never ships fixtures",
 * and it is an exception by name rather than by accident. It exists because the
 * demo has to be shown before real Google and AWS access exist, on a static host
 * with no API behind it. The ordinary build would call an `/api` that is not
 * there and render nothing but errors. It keeps the rail's `fixtures` marker,
 * because that marker is what stops example data passing for a live account.
 *
 * Development defaults to fixtures, and not for convenience: `second.agents`
 * does not exist yet and there is no ANTHROPIC_API_KEY, so every route that
 * runs a graph answers 503 today. The rail shows a `fixtures` marker whenever
 * this is on, because fixture data that looks live is the one dishonesty this
 * app must not commit.
 */
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  define: {
    'import.meta.env.VITE_SOURCE': JSON.stringify(
      mode === 'development' || mode === 'demo' ? 'fixtures' : 'live',
    ),
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
}))
