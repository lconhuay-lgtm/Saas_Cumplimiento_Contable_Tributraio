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
# NEXT_PUBLIC_* se "hornea" en el bundle JS durante "next build" -- no
# alcanza con environment: en docker-compose.yml (eso solo afecta el
# contenedor ya corriendo, el build ya termino para entonces). Por eso
# viaja como build ARG, no solo como variable de entorno del servicio (ver
# docker-compose.yml, seccion frontend.build.args).
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
