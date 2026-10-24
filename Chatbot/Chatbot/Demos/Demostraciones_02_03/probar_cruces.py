"""Prueba de la regla de cruces: un mismo cliente no puede tener dos viajes activos que se solapen.

Cada viaje ocupa [salida, salida + duracion_viaje_dias). Usa una base SQLite temporal: no toca reservas.db.
Ejecutar dentro del entorno de la API:   python probar_cruces.py
(Las fechas salen de hoy, así que la prueba no caduca cuando pasen las fechas de viajes.py.)
"""
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
    a = hoy + timedelta(days=30)  # Santa Marta dura 2 días: ocupa a y a+1
    original = list(viajes.VIAJES)
    viajes.VIAJES[:] = [
        Viaje("Santa Marta", a, 5),                         # a .. a+1
        Viaje("Manizales", a + timedelta(days=1), 5),       # empieza el último día de Santa Marta -> cruce
        Viaje("Nuquí", a + timedelta(days=2), 5),           # empieza justo al terminar Santa Marta -> permitido
        Viaje("Santa Marta", a + timedelta(days=40), 5),    # lejos de todo
    ]
    with TemporaryDirectory() as carpeta:
        anterior = main.agenda
        main.agenda = AgendaSQLite(Path(carpeta) / "reservas.db", clave_cliente=main._normalizar)
        try:
            with TestClient(main.app) as api:
                def reservar(cliente, servicio, fecha):
                    return api.post("/reservas", json={"cliente": cliente, "servicio": servicio,
                                                       "fecha": fecha.isoformat(), "confirmado": True})

                def disp(servicio, fecha, cliente=None):
                    params = {"fecha": fecha.isoformat(), "servicio": servicio}
                    if cliente:
                        params["cliente"] = cliente
                    return api.get("/disponibilidad", params=params).json()

                # --- /viajes informa el regreso
                v = api.get("/viajes", params={"servicio": "Santa Marta"}).json()["viajes"][0]
                assert v["fecha_regreso"] == (a + timedelta(days=1)).isoformat(), v

                # --- crear: el cruce se rechaza aunque la hora/fecha de salida sea distinta
                base = reservar("Laura", "Santa Marta", a)
                assert base.status_code == 201, base.text
                codigo = base.json()["codigo"]
                cruce = reservar("Laura", "Manizales", a + timedelta(days=1))
                assert cruce.status_code == 409 and codigo in cruce.json()["detail"], cruce.text
                assert reservar(" laura ", "Manizales", a + timedelta(days=1)).status_code == 409  # mismo nombre, otra forma
                assert reservar("Laura", "Santa Marta", a).status_code == 409                       # el mismo viaje dos veces
                assert reservar("Pedro", "Manizales", a + timedelta(days=1)).status_code == 201     # otro cliente: sin problema

                # --- salir justo al terminar el viaje anterior sí se acepta
                ok = reservar("Laura", "Nuquí", a + timedelta(days=2))
                assert ok.status_code == 201, ok.text

                # --- disponibilidad avisa antes de reservar
                d = disp("Manizales", a + timedelta(days=1), "Laura")
                assert d["disponible"] is False and d["cruce_con"]["codigo"] == codigo and "motivo" in d, d
                d = disp("Manizales", a + timedelta(days=1), "Ana")
                assert d["disponible"] is True and d["cruce_con"] is None, d
                assert "cruce_con" not in disp("Manizales", a + timedelta(days=1))  # sin cliente: respuesta de siempre

                # --- cancelar libera el intervalo
                assert api.delete(f"/reservas/{codigo}", params={"confirmado": True}).status_code == 200
                assert disp("Santa Marta", a, "Laura")["disponible"] is True  # el intervalo a..a+1 volvió a quedar libre
                # Laura solo conserva Nuquí (a+2 .. a+5): Manizales en a+1 dura 3 días (a+1..a+3) y SÍ se cruza con Nuquí
                assert reservar("Laura", "Manizales", a + timedelta(days=1)).status_code == 409
                assert api.delete(f"/reservas/{ok.json()['codigo']}", params={"confirmado": True}).status_code == 200
                assert reservar("Laura", "Manizales", a + timedelta(days=1)).status_code == 201

                # --- modificar: mover hacia un intervalo ocupado se rechaza y conserva los datos anteriores
                lista = main.leer()
                laura_mani = next(r for r in lista if r["cliente"] == "Laura" and r["estado"] == "activa")
                lejana = a + timedelta(days=40)
                otra = reservar("Laura", "Santa Marta", lejana)
                assert otra.status_code == 201
                mover = api.put(f"/reservas/{otra.json()['codigo']}",
                                json={"servicio": "Santa Marta", "fecha": a.isoformat(), "confirmado": True})
                assert mover.status_code == 409, mover.text  # a..a+1 se cruza con Manizales a+1..a+3
                assert api.get(f"/reservas/{otra.json()['codigo']}").json()["fecha"] == lejana.isoformat()
                # cambiar de destino recalcula la duración y vuelve a comprobar: Santa Marta (2 días) -> Nuquí (4 días)
                cambio = api.put(f"/reservas/{otra.json()['codigo']}",
                                 json={"servicio": "Nuquí", "fecha": (a + timedelta(days=2)).isoformat(), "confirmado": True})
                assert cambio.status_code == 409, cambio.text  # Nuquí a+2..a+5 se cruza con Manizales a+1..a+3
                # modificar sin moverse de intervalo (solo el nombre de otra persona) no se cruza consigo misma
                assert api.put(f"/reservas/{laura_mani['codigo']}",
                               json={"cliente": "Laura Gómez", "confirmado": True}).status_code == 200

                # --- el chat de Flowise también avisa ANTES de pedir confirmación
                sid = "prueba-cruces"
                for texto, datos in [("hola", {"intencion": "reservar", "cliente": "Pedro", "servicio": "Santa Marta",
                                               "fecha": a.isoformat()})]:
                    r = api.post("/chat", json={"session_id": sid, "mensaje": texto, "datos": datos}).json()
                assert "no pueden cruzarse" in r["respuesta"] and "pendiente" not in r["estado_sesion"], r
                print("OK: cruces de viaje por cliente (crear, modificar, disponibilidad, chat)")
        finally:
            main.agenda = anterior
            viajes.VIAJES[:] = original


if __name__ == "__main__":
    probar()
