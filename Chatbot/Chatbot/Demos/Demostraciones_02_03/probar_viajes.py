"""Prueba de la lógica de Viaje (fecha fija + cupos) y del resolvedor de nombres. Usa una base SQLite temporal: no toca reservas.db.

Ejecutar dentro del entorno de la API:   python probar_viajes.py
(Las fechas se generan a partir de hoy, así que la prueba no caduca cuando pasen las fechas de viajes.py.)
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

import main
import viajes
from almacen_sqlite import AgendaSQLite
from viajes import Viaje


def probar():
    hoy = datetime.now(main.ZONA).date()
    f1, f2, f3 = hoy + timedelta(days=20), hoy + timedelta(days=30), hoy + timedelta(days=1)
    original = list(viajes.VIAJES)
    viajes.VIAJES[:] = [  # misma lista que usa main.py
        Viaje("Viaje a Caño Cristales", f1, 2),
        Viaje("Viaje a Caño Cristales", f2, 1),
        Viaje("Manizales", f3, 5),  # sale mañana: ya cerró (Manizales exige 2 días de anticipación)
    ]
    with TemporaryDirectory() as carpeta:
        anterior = main.agenda
        main.agenda = AgendaSQLite(Path(carpeta) / "reservas.db", clave_cliente=main._normalizar)
        try:
            with TestClient(main.app) as api:
                # --- nombres flexibles
                for texto, esperado in [("Viaje a Caño Cristales", "Viaje a Caño Cristales"), ("cano cristales", "Viaje a Caño Cristales"),
                                        ("la macarena", "Viaje a Caño Cristales"), ("SANTA MARTA", "Santa Marta"),
                                        ("el nevado", "Manizales"), ("nuqui", "Nuquí")]:
                    assert main.resolver_servicio(texto) == esperado, texto
                assert main.resolver_servicio("París") is None
                assert api.get("/viajes", params={"servicio": "macarena"}).json()["viajes"][0]["servicio"] == "Viaje a Caño Cristales"
                assert api.get("/viajes", params={"servicio": "paris"}).status_code == 422

                # --- cupos
                lista = api.get("/viajes", params={"servicio": "macarena"}).json()["viajes"]
                assert [(v["fecha"], v["cupos_disponibles"]) for v in lista] == [(f1.isoformat(), 2), (f2.isoformat(), 1)]
                d = api.get("/disponibilidad", params={"fecha": f1.isoformat(), "servicio": "caño cristales"}).json()
                assert d["disponible"] and d["cupos_disponibles"] == 2

                def reservar(cliente, servicio, fecha):
                    return api.post("/reservas", json={"cliente": cliente, "servicio": servicio, "fecha": fecha.isoformat(), "confirmado": True})

                r1 = reservar("Ana", "la macarena", f1)
                assert r1.status_code == 201 and r1.json()["servicio"] == "Viaje a Caño Cristales"  # se guarda el id oficial
                r2 = reservar("Beto", "Viaje a Caño Cristales", f1)
                assert r2.status_code == 201  # mismo viaje, otro cliente: antes se rechazaba
                assert reservar("Carla", "Viaje a Caño Cristales", f1).status_code == 409  # sin cupos
                assert api.get("/disponibilidad", params={"fecha": f1.isoformat(), "servicio": "macarena"}).json()["disponible"] is False
                assert reservar("Carla", "Viaje a Caño Cristales", hoy + timedelta(days=21)).status_code == 422  # no hay viaje ese día
                assert reservar("Dani", "Manizales", f3).status_code == 422  # reservas cerradas

                # --- cancelar libera un cupo
                assert api.delete("/reservas/" + r1.json()["codigo"], params={"confirmado": True}).json()["estado"] == "cancelada"
                assert reservar("Carla", "Viaje a Caño Cristales", f1).status_code == 201

                # --- modificar
                assert reservar("Eva", "Viaje a Caño Cristales", f2).status_code == 201  # llena f2 (1 cupo)
                cod = r2.json()["codigo"]
                assert api.put("/reservas/" + cod, json={"fecha": f2.isoformat(), "confirmado": True}).status_code == 409
                assert api.put("/reservas/" + cod, json={"cliente": "Beto R.", "confirmado": True}).json()["cliente"] == "Beto R."
                assert len(main.agenda.listar()) == 4
        finally:
            main.agenda = anterior
            viajes.VIAJES[:] = original
    print("OK: viajes con fecha fija y cupos funcionan.")


if __name__ == "__main__":
    probar()
