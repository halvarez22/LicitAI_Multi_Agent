import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

/** Lee LICITAI_APP_VERSION de src/appVersion.js para bust de caché del entry en modo dev. */
function readAppVersion() {
    try {
        const p = path.join(__dirname, 'src', 'appVersion.js')
        const txt = fs.readFileSync(p, 'utf8')
        const m = txt.match(/LICITAI_APP_VERSION\s*=\s*['"]([^'"]+)['"]/)
        return m?.[1] || 'dev'
    } catch {
        return 'dev'
    }
}

const APP_VERSION = readAppVersion()

const proxyTarget =
    process.env.LICITAI_PROXY_API_TARGET || 'http://127.0.0.1:8001'

// https://vitejs.dev/config/
export default defineConfig({
    plugins: [
        react(),
        {
            name: 'licitai-dev-cache-bust',
            transformIndexHtml(html) {
                // Fuerza al navegador a no reusar un main.jsx viejo (muy habitual con localhost + Docker).
                // No usar versión con puntos en el query (ej. 5.21): esbuild/Vite puede interpretar ".21"
                // como sufijo y lanzar "Invalid loader value: 21".
                const v = String(APP_VERSION).replace(/\./g, '_')
                return html.replace(
                    'src="/src/main.jsx"',
                    `src="/src/main.jsx?v=${v}"`
                )
            },
        },
    ],
    server: {
        port: 8504,
        host: '0.0.0.0',
        headers: {
            'Cache-Control': 'no-store',
        },
        // El navegador llama al mismo origen (:8504); Vite reenvía al backend (evita localhost:8001 roto en Docker/IPv6).
        proxy: {
            '/api': {
                target: proxyTarget,
                changeOrigin: true,
            },
        },
    },
})
