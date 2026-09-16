import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { defineConfig } from 'vite';

const rootDir = dirname(fileURLToPath(import.meta.url));
const frontendDir = resolve(rootDir, 'frontend');

function backendTarget() {
    const fromEnv = process.env.CAD_API_TARGET;
    if (fromEnv) {
        return fromEnv.replace(/\/$/, '');
    }
    const portFile = resolve(rootDir, '.runtime-macos', 'server.port');
    if (existsSync(portFile)) {
        const port = readFileSync(portFile, 'utf8').trim();
        if (/^\d+$/.test(port)) {
            return `http://127.0.0.1:${port}`;
        }
    }
    // 受管启动器 backend/server.py 写的是 .cad-runtime/server.json；
    // Windows 脚本族还会写 .cad-server.json（--legacy-state）。两个都读，顺序在后。
    const stateFiles = [
        resolve(rootDir, '.cad-runtime', 'server.json'),
        resolve(rootDir, '.cad-server.json'),
    ];
    for (const stateFile of stateFiles) {
        if (!existsSync(stateFile)) continue;
        try {
            const state = JSON.parse(readFileSync(stateFile, 'utf8'));
            if (state && typeof state.url === 'string' && state.url.startsWith('http')) {
                return String(state.url).replace(/\/$/, '');
            }
            if (state && Number.isInteger(state.port)) {
                return `http://127.0.0.1:${state.port}`;
            }
        } catch {
            // fall through to next candidate
        }
    }
    return 'http://127.0.0.1:8000';
}

export default defineConfig(() => {
    const target = backendTarget();
    return {
        root: frontendDir,
        publicDir: false,
        appType: 'spa',
        resolve: {
            alias: [
                {
                    find: /^three\/addons\/(.*)$/,
                    replacement: `${resolve(frontendDir, 'vendor/three/examples/jsm')}/$1`,
                },
                {
                    find: 'three',
                    replacement: resolve(frontendDir, 'vendor/three/three.module.js'),
                },
            ],
        },
        server: {
            host: '127.0.0.1',
            port: Number(process.env.VITE_PORT || 5173),
            strictPort: false,
            proxy: {
                '/api': { target, changeOrigin: true },
                '/exports': { target, changeOrigin: true },
                '/ws/logs': { target, ws: true, changeOrigin: true },
            },
        },
        build: {
            outDir: resolve(rootDir, 'dist'),
            emptyOutDir: true,
        },
    };
});
