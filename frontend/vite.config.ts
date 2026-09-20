import { defineConfig } from 'vite'
import type { Plugin } from 'vite'
import react from '@vitejs/plugin-react'

const sitesWorker: Plugin = {
  name: 'sites-static-worker',
  generateBundle() {
    this.emitFile({
      type: 'asset',
      fileName: 'server/index.js',
      source: `const worker = {
  async fetch(request, env) {
    const incoming = new URL(request.url);
    if (incoming.pathname.startsWith("/api/")) {
      if (!env.API_BASE_URL) {
        return Response.json(
          { detail: "Sentinel production API is not configured." },
          { status: 503, headers: { "Cache-Control": "no-store" } },
        );
      }
      const upstream = new URL(env.API_BASE_URL);
      upstream.pathname = incoming.pathname.replace(/^\\/api/, "");
      upstream.search = incoming.search;
      return fetch(new Request(upstream, request));
    }
    let response = await env.ASSETS.fetch(request);
    if (response.status === 404 && request.method === "GET") {
      const url = incoming;
      url.pathname = "/";
      response = await env.ASSETS.fetch(new Request(url, request));
    }
    if (response.headers.get("content-type")?.includes("text/html")) {
      const html = (await response.text()).replaceAll(
        "__SENTINEL_OG_URL__",
        new URL("/og.png", request.url).toString(),
      );
      return new Response(html, { status: response.status, headers: response.headers });
    }
    return response;
  },
};
export default worker;
`,
    })
  },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), sitesWorker],
  build: {
    // Reviewer charts use a bounded Cartesian-only Plotly bundle. Keep the
    // warning budget aligned with that deliberate, lazy-loaded payload.
    chunkSizeWarningLimit: 1500,
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
