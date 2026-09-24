FROM python:3.12-slim

WORKDIR /app

# Chromium + su chromedriver (para el motor de scraping). Se instalan en la
# misma imagen que usan tanto el backend (API) como el worker (consume la
# cola), para no mantener dos Dockerfiles -- el backend simplemente no los
# usa. fonts-liberation evita paginas rotas por falta de fuentes.
#
# xvfb: pantalla virtual para correr Chrome en modo NO headless dentro del
# contenedor. e-menu.sunat.gob.pe (el login real) corta la conexion cuando
# detecta Chrome headless (ERR_EMPTY_RESPONSE, confirmado por diagnostico de
# red) -- probablemente proteccion anti-bot especifica del portal
# transaccional, que la pagina publica www.sunat.gob.pe no tiene. Con Xvfb,
# Chrome corre "visible" (sin ninguna senal de headless) dentro de una
# pantalla que nunca se muestra a nadie.
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    fonts-liberation \
    xvfb \
    xauth \
    && rm -rf /var/lib/apt/lists/*

ENV CHROME_BINARY_LOCATION=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Dependencias del backend
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Dependencias del motor de scraping
COPY core_scraper/requirements.txt /app/core_scraper/requirements.txt
RUN pip install --no-cache-dir -r /app/core_scraper/requirements.txt

COPY backend /app/backend
COPY core_scraper /app/core_scraper

ENV PYTHONPATH=/app/backend:/app/core_scraper
WORKDIR /app/backend

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
