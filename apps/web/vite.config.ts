import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const backendPort = process.env.VINCUL_PORT || '8192';
const backendUrl = `http://localhost:${backendPort}`;

export default defineConfig({
  plugins: [react()],
  server: {
    port: 8199,
    host: '0.0.0.0',
    proxy: {
      '/contract': backendUrl,
      '/action': backendUrl,
      '/vote': backendUrl,
      '/demo': backendUrl,
      '/marketplace': backendUrl,
      '/ws': {
        target: `ws://localhost:${backendPort}`,
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
});
