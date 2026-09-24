/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Fix Fase R4: genera .next/standalone -- un server.js autocontenido con
  // solo el subconjunto de node_modules que de verdad se usa, para que el
  // Dockerfile de produccion no tenga que copiar node_modules completo.
  output: "standalone",
};

module.exports = nextConfig;
