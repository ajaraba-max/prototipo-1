#!/usr/bin/env python3
"""Consulta el precio del café C (Bolsa de Nueva York, ICE Futures U.S.) y lo
guarda en bolsa.json para que el prototipo lo lea.

El navegador no puede pedirle el dato a Yahoo Finance directamente, porque
Yahoo no permite consultas desde otras páginas web. Por eso este script corre
en GitHub Actions (cada 15 minutos en horario de bolsa) y deja el resultado en
el repositorio.

El contrato continuo KC=F mezcla meses cuando el contrato del frente está por
vencer, así que el script revisa los próximos tres contratos y usa el que más
se negoció en los últimos cinco días.

Solo usa la biblioteca estándar de Python, para no tener que instalar nada.
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ARCHIVO = Path(__file__).resolve().parent.parent / "bolsa.json"
HOSTS = ("query2.finance.yahoo.com", "query1.finance.yahoo.com")
# Yahoo responde 429 a algunos identificadores de navegador (por ejemplo, el
# de Python o uno completo de Chrome sin cookies). Estos dos sí funcionan.
AGENTES = ("Mozilla/5.0", "prototipo-mi-origen/1.0")
# Meses en que vence el café C: marzo, mayo, julio, septiembre y diciembre.
MESES = (
    (3, "H", "marzo"),
    (5, "K", "mayo"),
    (7, "N", "julio"),
    (9, "U", "septiembre"),
    (12, "Z", "diciembre"),
)
# Campos que, si no cambian, no vale la pena volver a guardar el archivo.
CAMPOS_COMPARADOS = ("simbolo", "precio", "cierreAnterior", "horaDelDato")


def pedir(simbolo, parametros):
    """Pide un gráfico a Yahoo Finance, con reintentos y dos servidores."""
    ultimo_error = None
    for intento in range(3):
        for agente in AGENTES:
            for host in HOSTS:
                url = (
                    f"https://{host}/v8/finance/chart/"
                    f"{urllib.parse.quote(simbolo, safe='')}?{parametros}"
                )
                pedido = urllib.request.Request(
                    url, headers={"User-Agent": agente, "Accept": "application/json"}
                )
                try:
                    with urllib.request.urlopen(pedido, timeout=20) as respuesta:
                        datos = json.load(respuesta)
                    resultado = datos["chart"]["result"]
                    if resultado:
                        return resultado[0]
                    ultimo_error = datos["chart"].get("error")
                except urllib.error.HTTPError as error:
                    if error.code == 404:
                        # El contrato no existe o ya venció: no tiene caso reintentar.
                        raise RuntimeError(f"{simbolo} no existe en Yahoo Finance") from error
                    ultimo_error = error
                except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as error:
                    ultimo_error = error
        time.sleep(2 * (intento + 1))
    raise RuntimeError(f"no se pudo consultar {simbolo}: {ultimo_error}")


def contratos_candidatos(hoy, cantidad=3):
    """Devuelve los próximos contratos del café C, desde el mes actual."""
    candidatos = []
    anio = hoy.year
    while len(candidatos) < cantidad:
        for mes, codigo, nombre in MESES:
            if (anio, mes) >= (hoy.year, hoy.month) and len(candidatos) < cantidad:
                simbolo = f"KC{codigo}{anio % 100:02d}.NYB"
                candidatos.append((simbolo, f"{nombre} {anio}"))
        anio += 1
    return candidatos


def volumen_reciente(simbolo):
    """Suma los contratos negociados en los últimos cinco días."""
    resultado = pedir(simbolo, "range=5d&interval=1d")
    volumenes = resultado["indicators"]["quote"][0].get("volume") or []
    return sum(v for v in volumenes if v)


def a_iso(segundos):
    return datetime.fromtimestamp(segundos, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def consultar():
    ahora = datetime.now(timezone.utc)

    activos = []
    for simbolo, nombre in contratos_candidatos(ahora):
        try:
            activos.append((volumen_reciente(simbolo), simbolo, nombre))
        except RuntimeError as error:
            print(f"Aviso: {error}", file=sys.stderr)

    if activos and max(activos)[0] > 0:
        _, simbolo, contrato = max(activos)
    else:
        simbolo, contrato = "KC=F", "continuo"

    meta = pedir(simbolo, "range=1d&interval=1h")["meta"]
    precio = meta.get("regularMarketPrice")
    anterior = meta.get("previousClose") or meta.get("chartPreviousClose")
    hora = meta.get("regularMarketTime")
    if not precio or not anterior or not hora:
        raise RuntimeError(f"respuesta incompleta para {simbolo}: {meta}")

    return {
        "fuente": "Yahoo Finance (ICE Futures U.S.)",
        "mercado": "Café C, Bolsa de Nueva York",
        "contrato": contrato,
        "simbolo": simbolo,
        "unidad": "centavos de dólar por libra",
        "precio": round(precio, 2),
        "cierreAnterior": round(anterior, 2),
        "variacion": round(precio - anterior, 2),
        "horaDelDato": a_iso(hora),
        "actualizadoEn": a_iso(ahora.timestamp()),
    }


def main():
    try:
        nuevo = consultar()
    except RuntimeError as error:
        # No se marca el proceso como fallido para no llenar de correos al
        # dueño del repositorio. La página muestra la hora del dato, así que
        # se nota si quedó viejo.
        print(f"::warning::No se actualizó la bolsa: {error}")
        return

    if ARCHIVO.exists():
        try:
            actual = json.loads(ARCHIVO.read_text(encoding="utf-8"))
        except ValueError:
            actual = {}
        if all(actual.get(campo) == nuevo[campo] for campo in CAMPOS_COMPARADOS):
            print("La bolsa no cambió; bolsa.json queda igual.")
            return

    ARCHIVO.write_text(json.dumps(nuevo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Bolsa actualizada: {nuevo['precio']} ({nuevo['variacion']:+}) "
        f"contrato {nuevo['contrato']}, dato de {nuevo['horaDelDato']}"
    )


if __name__ == "__main__":
    main()
