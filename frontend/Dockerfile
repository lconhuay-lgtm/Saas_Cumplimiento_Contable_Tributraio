# Modo desarrollo (next dev) a proposito, no build de produccion: este
# proyecto todavia esta en fase de pruebas activas contra el backend real,
# y next dev arranca en segundos con hot-reload en vez de requerir un
# "docker-compose build" completo cada vez que cambia una pagina.
# Pasar a produccion (next build + next start) queda para Fase 5
# (endurecimiento para produccion real, ver el plan de fases).
FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
