import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig} from 'vite';

export default defineConfig(({mode}) => {
  const backendTarget = process.env.VITE_BACKEND_TARGET ?? 'http://127.0.0.1:8003';

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      proxy: {
        '/api': {
          target: backendTarget,
          changeOrigin: true,
        },
        '/v1': {
          target: backendTarget,
          changeOrigin: true,
        },
      },
    },
  };
});
