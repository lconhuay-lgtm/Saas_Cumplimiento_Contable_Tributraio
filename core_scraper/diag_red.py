#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Diagnostico de red puro (sin Selenium/Chrome) para comparar si el contenedor
puede llegar a e-menu.sunat.gob.pe igual que a www.sunat.gob.pe. Se ejecuta
con: docker-compose exec worker python -c "import diag_red"
"""
import socket
import ssl
import time
import urllib.request
import urllib.error


def resolver_dns(host):
    print(f"  DNS de {host}:")
    try:
        t0 = time.time()
        info = socket.getaddrinfo(host, 443)
        ips = sorted(set(i[4][0] for i in info))
        print(f"    OK ({round(time.time()-t0, 2)}s) -> {ips}")
        return ips
    except Exception as e:
        print(f"    FALLO: {type(e).__name__}: {e}")
        return []


def probar_https(url):
    print(f"  GET {url}:")
    try:
        t0 = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        resp = urllib.request.urlopen(req, timeout=15)
        cuerpo = resp.read(200)
        print(f"    OK, status={resp.status}, en {round(time.time()-t0, 2)}s, primeros bytes: {cuerpo[:80]!r}")
    except urllib.error.HTTPError as e:
        print(f"    HTTPError: status={e.code} en {round(time.time()-t0, 2)}s -- el servidor SI respondio, solo con un error HTTP")
    except urllib.error.URLError as e:
        print(f"    URLError (no llego respuesta): {e.reason} en {round(time.time()-t0, 2)}s")
    except (ssl.SSLError, socket.timeout, ConnectionResetError, ConnectionAbortedError) as e:
        print(f"    {type(e).__name__}: {e} en {round(time.time()-t0, 2)}s")
    except Exception as e:
        print(f"    Error inesperado: {type(e).__name__}: {e} en {round(time.time()-t0, 2)}s")


print("=" * 70)
print("1) www.sunat.gob.pe (sabemos que esta SI funciona con Selenium)")
print("=" * 70)
resolver_dns("www.sunat.gob.pe")
probar_https("https://www.sunat.gob.pe/")

print()
print("=" * 70)
print("2) e-menu.sunat.gob.pe (la que falla con ERR_EMPTY_RESPONSE)")
print("=" * 70)
resolver_dns("e-menu.sunat.gob.pe")
probar_https("https://e-menu.sunat.gob.pe/cl-ti-itmenucabina/MenuInternet.htm")

print()
print("=" * 70)
print("Fin del diagnostico")
print("=" * 70)
