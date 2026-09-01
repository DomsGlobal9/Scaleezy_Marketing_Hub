// @lovable.dev/vite-tanstack-config already includes the following — do NOT add them manually
// or the app will break with duplicate plugins:
//   - TanStack devtools (dev-only, first), tanstackStart, viteReact, tailwindcss, tsConfigPaths,
//     nitro (build-only using cloudflare as a default target), VITE_* env injection, @ path alias,
//     React/TanStack dedupe, error logger plugins, and sandbox detection (port/host/strictPort).
// You can pass additional config via defineConfig({ vite: { ... }, etc... }) if needed.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";

// Nitro defaults temporary build output to node_modules/.nitro. Keep generated
// files in the project build directory so installs may remain read-only.
const nitroBuild = { buildDir: ".nitro" } as unknown as { preset?: string };
const apiProxyTarget = process.env["SCALEEZY_API_PROXY_TARGET"]?.trim();
const localApiProxy = apiProxyTarget
  ? {
      server: {
        proxy: {
          "/api": { target: apiProxyTarget, changeOrigin: true, secure: true },
        },
      },
      preview: {
        proxy: {
          "/api": { target: apiProxyTarget, changeOrigin: true, secure: true },
        },
      },
    }
  : {};

export default defineConfig({
  nitro: nitroBuild,
  // Keep both local workflows functional: `vite dev` reads `server`, while
  // `vite preview` reads `preview`. Production remains unchanged unless the
  // explicit local proxy variable is present.
  vite: localApiProxy,
  tanstackStart: {
    // Redirect TanStack Start's bundled server entry to src/server.ts (our SSR error wrapper).
    // nitro/vite builds from this
    server: { entry: "server" },
  },
});
