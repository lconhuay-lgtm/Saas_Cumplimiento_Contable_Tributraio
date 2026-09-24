# Build de produccion real (fix Fase R4) -- antes este Dockerfile corria
# "next dev" tambien en produccion (mas lento, sin optimizar, trazas de
# error detalladas). La variante de desarrollo con hot-reload ahora vive en
# Dockerfile.dev (ver docker-compose.override.yml).
#
# Dos etapas: la primera instala TODO (incluidas devDependencies) y corre
# "next build"; gracias a output: "standalone" en next.config.js, ese build
# genera .next/standalone/server.js autocontenido con solo el subconjunto
# de node_modules que de verdad se usa en runtime -- la segunda etapa copia
# unicamente eso, sin arrastrar devDependencies ni el resto de node_modules
# a la imagen final.

FROM node:20-alpine AS builder
WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
