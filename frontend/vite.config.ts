import { defineConfig } from "vite";
import reactProd from "@vitejs/plugin-react";
import reactDev from "@vitejs/plugin-react-swc";
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import tsconfigPaths from "vite-tsconfig-paths";
import svgr from "vite-plugin-svgr";
import { VitePWA } from "vite-plugin-pwa";

const ReactCompilerConfig = {
    target: "19", // '17' | '18' | '19'
};

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
    const isProd = mode === "production";

    return {
        plugins: [
            tsconfigPaths(),
            tanstackRouter({ autoCodeSplitting: true }),
            // React compiler plugin for production builds
            isProd
                ? reactProd({
                      babel: {
                          plugins: [
                              ["babel-plugin-react-compiler", ReactCompilerConfig],
                          ],
                      },
                  })
                : reactDev(),
            svgr(),
            VitePWA({
                registerType: 'autoUpdate',
                manifest: {
                    name: 'Beets Flask',
                    short_name: 'Beets',
                    theme_color: '#121212',
                    background_color: '#121212',
                    display: 'standalone',
                    start_url: '/',
                    icons: [
                        { src: '/logo_beets.png', sizes: '192x192', type: 'image/png' },
                        { src: '/logo_beets.png', sizes: '512x512', type: 'image/png' },
                    ],
                },
            }),
        ],
        // not minifying helped when debugging in production mode
        // we can enable this again when the code base is a bit more mature.
        build: {
            minify: isProd,
        },
        server: {
            /** Allow the api calls to be
             * made to the another port during
             * development as the frontend and
             * backend are running independently
             * in dev.
             *
             * For production, the frontend and
             * backend are served from the quart
             * app, so the api calls are made
             * to and from the same port.
             */
            proxy: {
                "^/api_v1/.*": {
                    target: "http://127.0.0.1:5002",
                    changeOrigin: true,
                },
                "/socket.io": {
                    target: "http://127.0.0.1:5002",
                    changeOrigin: true,
                    ws: true,
                },
            },
            allowedHosts: ["belar"],
        },
        define: {
            // Load from package.json
            __FRONTEND_VERSION__: JSON.stringify(
                process.env.npm_package_version || "unk"
            ),
            __MODE__: JSON.stringify(mode),
        },
    };
});
