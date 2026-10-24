"""Prueba del almacenamiento SQLite: transacción única, concurrencia, persistencia y migración.

Ejecutar dentro del entorno de la API:   python probar_sqlite.py
Usa bases temporales: no toca reservas.db ni reservas.json.
"""
import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

import main
import viajes
from almacen_sqlite import AgendaSQLite, ConflictoReserva, CruceReserva, ReservaNoEncontrada, SinCupos
from viajes import Viaje


def registro(codigo, cliente, servicio, fecha, dias, estado="activa"):
    return {"codigo": codigo, "cliente": cliente, "servicio": servicio, "fecha": fecha.isoformat(), "estado": estado,
            "precio_cop": 1000, "duracion_viaje_dias": dias, "creada_en": "2026-01-01T00:00:00-05:00",
            "cancelada_en": None, "modificada_en": None}


def probar():
    hoy = datetime.now(main.ZONA).date()
    a = hoy + timedelta(days=30)
    original = list(viajes.VIAJES)
    viajes.VIAJES[:] = [Viaje("Santa Marta", a, 1), Viaje("Manizales", a + timedelta(days=1), 5),
                        Viaje("Nuquí", a + timedelta(days=2), 5)]
    with TemporaryDirectory() as carpeta:
        ruta = Path(carpeta) / "reservas.db"
        agenda = AgendaSQLite(ruta)

        # --- la tabla y los índices existen; la base queda en el archivo
        with sqlite3.connect(ruta) as con:
            assert {f[0] for f in con.execute("SELECT name FROM sqlite_master WHERE type='index'")} >= {"idx_salida", "idx_cliente"}
            assert con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='reservas'").fetchone()[0] == 1

        # --- sin cupos / cruce, directamente en el almacén
        agenda.crear(registro("A1", "Laura", "Santa Marta", a, 2), cupos=1)
        try:
            agenda.crear(registro("A2", "Pedro", "Santa Marta", a, 2), cupos=1); raise SystemExit("debía fallar")
        except SinCupos:
            pass
        try:
            agenda.crear(registro("A3", "  LAURA ", "Manizales", a + timedelta(days=1), 3), cupos=5); raise SystemExit("debía fallar")
        except CruceReserva as e:
            assert e.reserva["codigo"] == "A1"
        assert [r["codigo"] for r in agenda.listar()] == ["A1"]  # los rechazos no dejaron filas
        agenda.crear(registro("A4", "Laura", "Nuquí", a + timedelta(days=2), 4), cupos=5)  # justo al terminar: ok

        # --- modificar: falla -> revierte y conserva datos; cancelar libera cupo e intervalo
        malo = registro("A4", "Laura", "Manizales", a + timedelta(days=1), 3) | {"modificada_en": "x"}
        try:
            agenda.modificar("A4", malo, cupos=5); raise SystemExit("debía fallar")
        except CruceReserva:
            pass
        assert agenda.consultar("A4")["servicio"] == "Nuquí" and agenda.consultar("A4")["modificada_en"] is None
        assert agenda.cancelar("A1", "2026-01-02")["estado"] == "cancelada"
        assert agenda.cancelar("A1", "2026-01-03")["cancelada_en"] == "2026-01-02"  # idempotente
        agenda.crear(registro("A5", "Pedro", "Santa Marta", a, 2), cupos=1)  # el cupo volvió a quedar libre
        try:
            agenda.consultar("NOEXISTE"); raise SystemExit("debía fallar")
        except ReservaNoEncontrada:
            pass
        try:
            agenda.modificar("A1", registro("A1", "Laura", "Santa Marta", a, 2), cupos=1); raise SystemExit("debía fallar")
        except ConflictoReserva:
            pass  # una reserva cancelada no se modifica

        # --- concurrencia: dos "procesos" (dos objetos, dos conexiones) compiten por el último cupo
        agenda2 = AgendaSQLite(Path(carpeta) / "carrera.db")
        otro = AgendaSQLite(Path(carpeta) / "carrera.db")
        resultados = []

        def intentar(ag, codigo, cliente):
            try:
                ag.crear(registro(codigo, cliente, "Santa Marta", a, 2), cupos=1); resultados.append("ok")
            except ConflictoReserva:
                resultados.append("rechazada")
        hilos = [threading.Thread(target=intentar, args=(ag, c, n))
                 for ag, c, n in ((agenda2, "C1", "Ana"), (otro, "C2", "Beto"), (agenda2, "C3", "Cami"), (otro, "C4", "Dani"))]
        [h.start() for h in hilos]; [h.join() for h in hilos]
        assert sorted(resultados) == ["ok", "rechazada", "rechazada", "rechazada"], resultados

        # --- persistencia: una instancia nueva (como reiniciar la API) ve lo mismo
        assert [r["codigo"] for r in AgendaSQLite(ruta).listar()] == ["A1", "A4", "A5"]

        # --- migración desde JSON
        datos = [registro("M1", "Kevin", "Manizales", a, 3, "cancelada"), registro("M2", "Andrea", "Santa Marta", a, 2),
                 registro("M3", "Andrea", "Nuquí", a + timedelta(days=2), 4)]
        origen = Path(carpeta) / "reservas.json"
        origen.write_text(json.dumps(datos), encoding="utf-8")
        destino = AgendaSQLite(Path(carpeta) / "migrada.db")
        assert destino.importar_json(origen) == {"importadas": 3, "ya_existentes": 0}
        assert destino.importar_json(origen) == {"importadas": 0, "ya_existentes": 3}  # repetir no duplica
        assert len(destino.listar()) == 3 and destino.consultar("M1")["estado"] == "cancelada"
        cruzado = datos + [registro("M4", "andrea", "Manizales", a + timedelta(days=1), 3)]
        origen.write_text(json.dumps(cruzado), encoding="utf-8")
        vacia = AgendaSQLite(Path(carpeta) / "revertida.db")
        try:
            vacia.importar_json(origen); raise SystemExit("debía fallar")
        except ConflictoReserva:
            assert vacia.vacia()  # se revirtieron todas las inserciones de ese intento
        origen.write_text(json.dumps([datos[1] | {"estado": "pendiente"}]), encoding="utf-8")
        try:
            vacia.importar_json(origen); raise SystemExit("debía fallar")
        except ValueError:
            assert vacia.vacia()

        # --- la API usa SQLite de punta a punta (las filas están en la base, no en un JSON)
        anterior = main.agenda
        main.agenda = AgendaSQLite(Path(carpeta) / "api.db", clave_cliente=main._normalizar)
        try:
            with TestClient(main.app) as api:
                r = api.post("/reservas", json={"cliente": "Laura", "servicio": "Santa Marta",
                                                "fecha": a.isoformat(), "confirmado": True})
                assert r.status_code == 201, r.text
                cod = r.json()["codigo"]
                with sqlite3.connect(Path(carpeta) / "api.db") as con:
                    assert con.execute("SELECT cliente, fecha, estado FROM reservas WHERE codigo=?", (cod,)).fetchone() \
                           == ("Laura", a.isoformat(), "activa")
                assert api.post("/reservas", json={"cliente": "Otra", "servicio": "Santa Marta", "fecha": a.isoformat(),
                                                   "confirmado": True}).status_code == 409  # 1 solo cupo
                assert api.get("/reservas/" + cod.lower()).json()["codigo"] == cod
                assert api.get("/reservas/PN-NOEXISTE").status_code == 404
                assert api.delete("/reservas/" + cod, params={"confirmado": True}).json()["estado"] == "cancelada"
                with sqlite3.connect(Path(carpeta) / "api.db") as con:
                    assert con.execute("SELECT estado FROM reservas WHERE codigo=?", (cod,)).fetchone()[0] == "cancelada"
                assert api.post("/reservas", json={"cliente": "Otra", "servicio": "Santa Marta", "fecha": a.isoformat(),
                                                   "confirmado": True}).status_code == 201  # cupo liberado
                # base inaccesible -> 503 y no se confirma nada
                main.agenda = AgendaSQLite(Path(carpeta) / "x.db", clave_cliente=main._normalizar)
                main.agenda.ruta = Path(carpeta) / "no_existe" / "x.db"
                assert api.get("/viajes").status_code == 503
        finally:
            main.agenda = anterior
            viajes.VIAJES[:] = original
    print("OK: SQLite (transacción única, concurrencia, persistencia, migración, API)")


if __name__ == "__main__":
    probar()
