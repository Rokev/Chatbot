"""Pruebas automáticas del canal de Telegram (clase 13). No necesita Telegram, Groq ni tocar reservas.db.

Qué hace:
  1. Copia la API (Demos/Demostraciones_02_03) a una carpeta temporal con una base NUEVA y salidas de viaje
     generadas a partir de la fecha de hoy (así las pruebas no caducan).
  2. Arranca esa API de verdad (uvicorn, puerto libre) con CHATBOT_API_KEY de prueba.
  3. Prueba las rutas /telegram con peticiones HTTP reales (incluida una carrera de dos escrituras simultáneas
     por el último cupo) y contrasta cada escritura con SQLite.
  4. Prueba bot_telegram.py con un Telegram simulado (sin red): botones, resúmenes, reinicio, resultado incierto...
     El "modelo" es una función que devuelve el plan JSON que Groq habría devuelto.

Uso:   python probar_telegram.py          (con python-telegram-bot, fastapi y uvicorn instalados)
Esto NO reemplaza la prueba manual con dos cuentas reales de Telegram: demuestra la lógica y deja evidencia.
"""

import asyncio
import json
import os
import shutil
import socket
import sqlite3
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from threading import Barrier, Thread

AQUI = Path(__file__).resolve().parent
ORIGEN_API = AQUI / "Demos" / "Demostraciones_02_03"
CLAVE = "clave-de-prueba-0123456789"
TMP = Path(tempfile.mkdtemp(prefix="viajesya_telegram_"))
for archivo in list(ORIGEN_API.glob("*.py")) + [ORIGEN_API / "negocio.json"]:
    if archivo.name not in {"probar_cruces.py", "probar_demo.py", "probar_sqlite.py", "probar_viajes.py", "ver_reservas.py"}:
        shutil.copy(archivo, TMP / archivo.name)
HOY = date.today()
(TMP / "viajes.py").write_text(f'''from dataclasses import dataclass
from datetime import date, timedelta

@dataclass(frozen=True)
class Viaje:
    servicio: str
    fecha: date
    cupos: int

    @property
    def id(self):
        return f"{{self.servicio}}|{{self.fecha.isoformat()}}"

    def ocupados(self, registros):
        return sum(1 for r in registros if r["estado"] == "activa" and r["servicio"] == self.servicio
                   and r["fecha"] == self.fecha.isoformat())

    def cupos_libres(self, registros):
        return max(self.cupos - self.ocupados(registros), 0)

    def resumen(self, registros):
        return {{"servicio": self.servicio, "fecha": self.fecha.isoformat(),
                "cupos_totales": self.cupos, "cupos_disponibles": self.cupos_libres(registros)}}

H = date.today()
VIAJES = [
    Viaje("Santa Marta", H + timedelta(days=30), 10),
    Viaje("Santa Marta", H + timedelta(days=60), 10),
    Viaje("Caño Cristales", H + timedelta(days=40), 8),
    Viaje("Manizales", H + timedelta(days=41), 12),
    Viaje("Manizales", H + timedelta(days=50), 12),
    Viaje("Nuquí", H + timedelta(days=80), 6),
    Viaje("Capurganá", H + timedelta(days=90), 1),
    Viaje("Amazonas", H + timedelta(days=2), 8),
]

def viajes_de(servicio):
    return sorted((v for v in VIAJES if v.servicio == servicio), key=lambda v: v.fecha)

def buscar_viaje(servicio, fecha):
    return next((v for v in VIAJES if v.servicio == servicio and v.fecha == fecha), None)
''', encoding="utf-8")
os.environ["CHATBOT_API_KEY"] = CLAVE
sys.path[:0] = [str(TMP), str(AQUI)]

import uvicorn  # noqa: E402
from telegram import Update  # noqa: E402
from telegram.request import BaseRequest  # noqa: E402

import bot_telegram as bot  # noqa: E402
import main as api_main  # noqa: E402

F = lambda dias: (HOY + timedelta(days=dias)).isoformat()  # noqa: E731
SM1, SM2, CC, MZ1, MZ2, NU, CAP, AMZ = F(30), F(60), F(40), F(41), F(50), F(80), F(90), F(2)
DB = TMP / "reservas.db"
RESULTADOS = []


def puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PUERTO = puerto_libre()
BASE = f"http://127.0.0.1:{PUERTO}"
servidor = uvicorn.Server(uvicorn.Config(api_main.app, host="127.0.0.1", port=PUERTO, log_level="error"))
Thread(target=servidor.run, daemon=True).start()
for _ in range(100):
    if servidor.started:
        break
    time.sleep(0.1)


def http(metodo, ruta, usuario=None, datos=None, clave=CLAVE):
    headers = {"Content-Type": "application/json"}
    if clave is not None:
        headers["X-API-Key"] = clave
    if usuario is not None:
        headers["X-Telegram-User"] = str(usuario)
    cuerpo = json.dumps(datos).encode() if datos is not None else None
    solicitud = urllib.request.Request(BASE + ruta, data=cuerpo, headers=headers, method=metodo)
    try:
        with urllib.request.urlopen(solicitud, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def operar(usuario, accion, datos, referencia="", sid=None):
    sid = sid or uuid.uuid4().hex
    completos = {"cliente": "", "servicio": "", "fecha": "", "codigo": "", **datos}
    estado, cuerpo = http("POST", "/telegram/operaciones", usuario,
                          {"solicitud_id": sid, "accion": accion, "datos": completos,
                           "referencia": referencia, "confirmada": True})
    return sid, estado, cuerpo


def fila(codigo):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        r = con.execute("SELECT * FROM reservas WHERE codigo=?", (codigo,)).fetchone()
        return dict(r) if r else None
    finally:
        con.close()


def contar(sql="SELECT COUNT(*) FROM reservas", *args):
    con = sqlite3.connect(DB)
    try:
        return con.execute(sql, args).fetchone()[0]
    finally:
        con.close()


def prueba(nombre):
    def decorador(funcion):
        def envoltura():
            try:
                resultado = funcion()
                if asyncio.iscoroutine(resultado):
                    resultado = asyncio.run(resultado)
                RESULTADOS.append((nombre, True, ""))
                print(f"  OK   {nombre}")
            except Exception as error:  # noqa: BLE001
                RESULTADOS.append((nombre, False, f"{type(error).__name__}: {error}"))
                print(f"  FALLA {nombre}: {type(error).__name__}: {error}")
                traceback.print_exc()
        envoltura.__name__ = funcion.__name__
        envoltura.nombre = nombre
        PRUEBAS.append(envoltura)
        return envoltura
    return decorador


PRUEBAS = []
LAURA, ANDRES = 1001, 1002

# ======================================================================== API


@prueba("API: sin clave o con clave incorrecta -> 401; sin X-Telegram-User -> 422")
def _():
    assert http("GET", "/telegram/servicios", clave=None)[0] == 401
    assert http("GET", "/telegram/viajes", 1, clave="otra-clave-incorrecta")[0] == 401
    assert http("GET", f"/telegram/reservas/PN-X", None)[0] == 422
    assert http("GET", "/telegram/reservas/PN-X", 0)[0] == 422


@prueba("API: servicios, viajes y disponibilidad coinciden con el catálogo (T01-T03)")
def _():
    estado, negocio = http("GET", "/telegram/servicios", LAURA)
    assert estado == 200 and negocio["servicios"] == api_main.NEGOCIO["servicios"]
    estado, datos = http("GET", "/telegram/viajes?servicio=macarena", LAURA)
    assert estado == 200 and [v["servicio"] for v in datos["viajes"]] == ["Caño Cristales"]
    estado, d = http("GET", f"/telegram/disponibilidad?fecha={CC}&servicio=macarena", LAURA)
    assert estado == 200 and d["cupos_totales"] == 8 and d["cupos_disponibles"] == 8 and d["servicio"] == "Caño Cristales"
    assert http("GET", f"/telegram/disponibilidad?fecha={F(41)}&servicio=macarena", LAURA)[0] == 422  # sin salida ese día
    assert http("GET", f"/telegram/disponibilidad?fecha={AMZ}&servicio=amazonas", LAURA)[0] == 422  # reservas cerradas
    assert http("GET", f"/telegram/disponibilidad?fecha={CC}&servicio=paris", LAURA)[0] == 422


@prueba("API: crear -> 201, fila real en SQLite, propietario registrado y recibo guardado (T18)")
def _():
    antes = contar()
    sid, estado, r = operar(LAURA, "crear", {"cliente": "Laura", "servicio": "macarena", "fecha": CC})
    assert estado == 201 and r["ok"] and r["accion"] == "crear"
    codigo = r["reserva"]["codigo"]
    assert codigo.startswith("PN-") and r["reserva"]["servicio"] == "Caño Cristales"
    assert contar() == antes + 1 and fila(codigo)["estado"] == "activa"
    assert contar("SELECT usuario_id FROM propietarios_telegram WHERE codigo=?", codigo) == LAURA
    # Repetir la misma solicitud (doble pulsación o reenvío): mismo recibo, una sola fila.
    _, estado2, r2 = operar(LAURA, "crear", {"cliente": "Laura", "servicio": "macarena", "fecha": CC}, sid=sid)
    assert estado2 == 201 and r2["reserva"]["codigo"] == codigo and contar() == antes + 1
    # Mismo identificador con otros datos -> 409; otro usuario con ese identificador -> 404.
    assert operar(LAURA, "crear", {"cliente": "Laura", "servicio": "Manizales", "fecha": MZ2}, sid=sid)[1] == 409
    assert operar(ANDRES, "crear", {"cliente": "Laura", "servicio": "macarena", "fecha": CC}, sid=sid)[1] == 404
    assert contar() == antes + 1
    # Recibo recuperable solo por quien lo creó.
    estado, rec = http("GET", f"/telegram/operaciones/{sid}", LAURA)
    assert estado == 200 and rec["estado_http"] == 201 and rec["resultado"]["reserva"]["codigo"] == codigo
    assert http("GET", f"/telegram/operaciones/{sid}", ANDRES)[0] == 404
    assert http("GET", f"/telegram/operaciones/{uuid.uuid4().hex}", LAURA)[0] == 404
    ESTADO["codigo_laura"] = codigo


ESTADO = {}


@prueba("API: otra cuenta no consulta, modifica ni cancela la reserva ajena (T13)")
def _():
    codigo = ESTADO["codigo_laura"]
    antes = fila(codigo)
    assert http("GET", f"/telegram/reservas/{codigo}", ANDRES)[0] == 404
    ref = http("GET", f"/telegram/reservas/{codigo}", LAURA)[1]["referencia"]
    assert operar(ANDRES, "modificar", {"codigo": codigo, "fecha": MZ2}, ref)[1] == 404
    assert operar(ANDRES, "cancelar", {"codigo": codigo}, ref)[1] == 404
    assert fila(codigo) == antes
    # Una reserva antigua (sin propietario de Telegram) tampoco se asigna a quien conozca el código.
    con = sqlite3.connect(DB)
    con.execute("INSERT INTO reservas VALUES ('PN-ANTIGUA0001','Kevin','kevin','Nuquí',?, 'activa',975000,4,'2026-01-01T00:00:00',NULL,NULL)", (NU,))
    con.commit()
    con.close()
    assert http("GET", "/telegram/reservas/PN-ANTIGUA0001", LAURA)[0] == 404
    assert http("GET", "/telegram/reservas/pn-noexiste", LAURA)[1]["detail"] == http("GET", "/telegram/reservas/PN-ANTIGUA0001", LAURA)[1]["detail"]


@prueba("API: modificar conserva el código y actualiza; un rechazo deja la reserva intacta (T19, T25)")
def _():
    codigo = ESTADO["codigo_laura"]
    actual = http("GET", f"/telegram/reservas/{codigo}", LAURA)[1]
    _, estado, r = operar(LAURA, "modificar", {"codigo": codigo, "servicio": "Manizales", "fecha": MZ2}, actual["referencia"])
    assert estado == 200 and r["reserva"]["codigo"] == codigo
    f = fila(codigo)
    assert (f["servicio"], f["fecha"], f["precio_cop"], f["duracion_viaje_dias"]) == ("Manizales", MZ2, 830000, 3) and f["modificada_en"]
    nueva_ref = r["referencia"]
    # Rechazo: fecha sin salida -> 422 y la fila queda igual.
    _, estado, r = operar(LAURA, "modificar", {"codigo": codigo, "fecha": F(51)}, nueva_ref)
    assert estado == 422 and not r["ok"] and fila(codigo)["fecha"] == MZ2
    # Resumen antiguo: la referencia ya no coincide -> 409.
    _, estado, r = operar(LAURA, "modificar", {"codigo": codigo, "fecha": MZ1}, actual["referencia"])
    assert estado == 409 and "cambió" in r["detalle"] and fila(codigo)["fecha"] == MZ2
    ESTADO["ref_laura"] = nueva_ref


@prueba("API: cruce del mismo cliente se rechaza y no revela reservas ajenas (T22)")
def _():
    codigo = ESTADO["codigo_laura"]  # Laura: Manizales MZ2 (3 días)
    # Otra cuenta usando el nombre «laura»: se rechaza, sin código ni fechas de la reserva de Laura.
    _, estado, r = operar(ANDRES, "crear", {"cliente": "laura", "servicio": "Manizales", "fecha": MZ2})
    assert estado in (409,) and codigo not in json.dumps(r) and MZ2 not in json.dumps(r)
    # La propia dueña sí recibe el detalle.
    _, estado, r = operar(LAURA, "crear", {"cliente": "Laura", "servicio": "Manizales", "fecha": MZ2})
    assert estado == 409 and codigo in r["detalle"]
    assert contar("SELECT COUNT(*) FROM reservas WHERE cliente_clave='laura' AND estado='activa'") == 1
    # Salir justo después del regreso sí se permite: Laura vuelve MZ2+2; no hay salida compatible, así que se comprueba con disponibilidad.
    estado, d = http("GET", f"/telegram/disponibilidad?fecha={MZ2}&servicio=Manizales&cliente=Laura", LAURA)
    assert estado == 200 and d["disponible"] is False and codigo in d["motivo"]
    estado, d = http("GET", f"/telegram/disponibilidad?fecha={MZ2}&servicio=Manizales&cliente=Laura", ANDRES)
    assert d["disponible"] is False and codigo not in d["motivo"]


@prueba("API: cancelar cambia el estado y libera el cupo (T20)")
def _():
    codigo = ESTADO["codigo_laura"]
    libres = lambda: next(v for v in http("GET", "/telegram/viajes?servicio=Manizales", LAURA)[1]["viajes"] if v["fecha"] == MZ2)["cupos_disponibles"]  # noqa: E731
    antes = libres()
    _, estado, r = operar(LAURA, "cancelar", {"codigo": codigo}, ESTADO["ref_laura"])
    assert estado == 200 and r["reserva"]["estado"] == "cancelada" and fila(codigo)["estado"] == "cancelada"
    assert libres() == antes + 1
    # Una reserva cancelada ya no se modifica.
    ref = http("GET", f"/telegram/reservas/{codigo}", LAURA)[1]["referencia"]
    assert operar(LAURA, "modificar", {"codigo": codigo, "fecha": MZ1}, ref)[1] == 409


@prueba("API: dos escrituras HTTP simultáneas por el último cupo -> una se acepta y una se rechaza (T22, concurrencia)")
def _():
    antes = contar("SELECT COUNT(*) FROM reservas WHERE servicio='Capurganá' AND estado='activa'")
    barrera = Barrera = Barrier(2)

    def intentar(usuario, nombre):
        barrera.wait()
        return operar(usuario, "crear", {"cliente": nombre, "servicio": "Capurganá", "fecha": CAP})[1]

    with ThreadPoolExecutor(2) as pool:
        estados = sorted(f.result() for f in [pool.submit(intentar, LAURA, "Ana"), pool.submit(intentar, ANDRES, "Beto")])
    assert estados == [201, 409], estados
    assert contar("SELECT COUNT(*) FROM reservas WHERE servicio='Capurganá' AND estado='activa'") == antes + 1


@prueba("API: validaciones de entrada (cliente corto, servicio inexistente, confirmada=false)")
def _():
    antes = contar()
    assert operar(LAURA, "crear", {"cliente": "A", "servicio": "Nuquí", "fecha": NU})[1] == 422
    assert operar(LAURA, "crear", {"cliente": "Ana", "servicio": "Marte", "fecha": NU})[1] == 422
    assert operar(LAURA, "crear", {"cliente": "Ana", "servicio": "Nuquí", "fecha": "2026-13-45"})[1] == 422
    assert operar(LAURA, "crear", {"cliente": "Ana", "servicio": "Amazonas", "fecha": AMZ})[1] == 422  # cerrada
    estado, _ = http("POST", "/telegram/operaciones", LAURA, {"solicitud_id": uuid.uuid4().hex, "accion": "crear",
                     "datos": {}, "referencia": "", "confirmada": False})
    assert estado == 422 and contar() == antes


# ======================================================================== BOT con Telegram simulado


class TelegramFalso(BaseRequest):
    """Sustituye la red de Telegram: guarda lo que el bot envía y contesta como la API de Bot."""

    def __init__(self):
        self.enviados = []  # (chat_id, texto, tiene_teclado)
        self.editados = []
        self.siguiente = 500

    @property
    def read_timeout(self):
        return 5

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, read_timeout=None, write_timeout=None,
                         connect_timeout=None, pool_timeout=None):
        nombre = url.rsplit("/", 1)[-1]
        p = request_data.parameters if request_data else {}
        if nombre == "getMe":
            resultado = {"id": 1, "is_bot": True, "first_name": "ViajesYa", "username": "viajesya_bot"}
        elif nombre == "sendMessage":
            self.siguiente += 1
            self.enviados.append((int(p["chat_id"]), p["text"], "reply_markup" in p))
            resultado = {"message_id": self.siguiente, "date": int(time.time()),
                         "chat": {"id": int(p["chat_id"]), "type": "private"}, "text": p["text"]}
        elif nombre == "editMessageReplyMarkup":
            self.editados.append((int(p["chat_id"]), int(p["message_id"])))
            resultado = True
        else:
            resultado = True
        return 200, json.dumps({"ok": True, "result": resultado}).encode()


class Mundo:
    """Un bot completo (Application) con su Telegram falso, su API real y un modelo simulado."""

    def __init__(self, base=BASE, clave=CLAVE, interprete=None):
        self.red = TelegramFalso()
        self.plan = {}
        self.api = bot.ClienteAPI(base, clave)
        self.app = bot.crear_aplicacion("123456:TOKEN-DE-PRUEBA", self.api, "clave", "modelo",
                                        interprete or self.modelo, request=self.red)
        self.n = 0
        self.mensajes_por_chat = {}

    def modelo(self, pregunta, historial, clave, modelo):
        if pregunta not in self.plan:
            raise AssertionError(f"El modelo simulado no conoce el mensaje: {pregunta!r}")
        return dict(self.plan[pregunta])

    async def iniciar(self):
        await self.app.initialize()

    async def cerrar(self):
        await self.app.shutdown()

    async def escribir(self, usuario, texto, plan=None):
        if plan is not None:
            self.plan[texto] = {"accion": "", "cliente": "", "servicio": "", "fecha": "", "codigo": "", **plan}
        self.n += 1
        mensaje = {"message_id": 9000 + self.n, "date": int(time.time()), "chat": {"id": usuario, "type": "private"},
                   "from": {"id": usuario, "is_bot": False, "first_name": f"U{usuario}"}, "text": texto}
        if texto.startswith("/"):
            mensaje["entities"] = [{"type": "bot_command", "offset": 0, "length": len(texto.split()[0])}]
        corte = len(self.red.enviados)
        await self.app.process_update(Update.de_json({"update_id": self.n, "message": mensaje}, self.app.bot))
        return [t for (c, t, _) in self.red.enviados[corte:] if c == usuario]

    async def pulsar(self, usuario, dato):
        self.n += 1
        consulta = {"id": str(self.n), "chat_instance": "x", "data": dato,
                    "from": {"id": usuario, "is_bot": False, "first_name": f"U{usuario}"},
                    "message": {"message_id": 1, "date": int(time.time()), "chat": {"id": usuario, "type": "private"},
                                "from": {"id": 1, "is_bot": True, "first_name": "ViajesYa"}, "text": "resumen"}}
        corte = len(self.red.enviados)
        await self.app.process_update(Update.de_json({"update_id": self.n, "callback_query": consulta}, self.app.bot))
        return [t for (c, t, _) in self.red.enviados[corte:] if c == usuario]

    def propuesta(self, usuario):
        pendiente = self.app.chat_data[usuario].get("pendiente")
        return pendiente


def referencia_en(textos):
    for t in textos:
        for linea in t.splitlines():
            if linea.startswith("Referencia de solicitud: "):
                return linea.split(": ", 1)[1]
    raise AssertionError("No apareció una referencia de solicitud: " + repr(textos))


def codigo_en(textos):
    for t in textos:
        for linea in t.splitlines():
            if linea.startswith("Código: "):
                return linea.split(": ", 1)[1]
    raise AssertionError("No apareció un código de reserva: " + repr(textos))


@prueba("Bot: consultas de lectura (servicios, precio, viajes, disponibilidad) usan la API (T01-T03)")
async def _():
    m = Mundo()
    await m.iniciar()
    r = await m.escribir(LAURA, "catalogo", {"accion": "servicios"})
    assert "Caño Cristales" in r[0] and "$3.587.000 COP" in r[0]
    r = await m.escribir(LAURA, "salidas manizales", {"accion": "viajes", "servicio": "manizales"})
    assert MZ1 in r[0] and MZ2 in r[0]
    r = await m.escribir(LAURA, "cupo", {"accion": "disponibilidad", "servicio": "macarena", "fecha": CC})
    assert "cupos libres" in r[0]
    assert not m.propuesta(LAURA) if LAURA in m.app.chat_data else True
    await m.cerrar()


@prueba("Bot: crear -> resumen con referencia y botones; confirmar escribe una vez; repetir la pulsación no repite (T18)")
async def _():
    m = Mundo()
    await m.iniciar()
    antes = contar()
    r = await m.escribir(ANDRES, "soy Andres macarena", {"accion": "crear", "cliente": "Andrés", "servicio": "macarena", "fecha": CC})
    assert len(r) == 1 and "Acción: crear" in r[0] and "Caño Cristales" in r[0]  # servicio con id oficial
    assert contar() == antes  # nada se escribe antes de confirmar
    sid = referencia_en(r)
    assert m.red.enviados[-1][2] is True  # lleva botones
    r1 = await m.pulsar(ANDRES, f"confirmar:{sid}")
    codigo = codigo_en(r1)
    assert contar() == antes + 1 and fila(codigo)["cliente"] == "Andrés"
    r2 = await m.pulsar(ANDRES, f"confirmar:{sid}")
    assert "No hay una solicitud pendiente" in r2[0] and contar() == antes + 1
    r3 = await m.escribir(ANDRES, f"/reserva {codigo.lower()}")
    assert codigo in r3[0] and "activa" in r3[0]
    # T05: el contexto de la conversación conserva el código y el resultado real devuelto por la API.
    ultimo = m.app.chat_data[ANDRES]["historial"]
    assert any(codigo in x["content"] and '"ok": true' in x["content"] for x in ultimo if x["role"] == "assistant")
    ESTADO["codigo_andres"] = codigo
    await m.cerrar()


@prueba("Bot: un resumen reemplazado deja inválido el botón antiguo (T14)")
async def _():
    m = Mundo()
    await m.iniciar()
    antes = contar()
    r = await m.escribir(LAURA, "reserva A", {"accion": "crear", "cliente": "Lucía", "servicio": "Santa Marta", "fecha": SM1})
    viejo = referencia_en(r)
    r = await m.escribir(LAURA, "mejor la otra fecha", {"accion": "crear", "cliente": "Lucía", "servicio": "Santa Marta", "fecha": SM2})
    nuevo = referencia_en(r)
    assert viejo != nuevo and SM2 in r[0]
    r = await m.pulsar(LAURA, f"confirmar:{viejo}")
    assert "ya no es el vigente" in r[0] and contar() == antes
    r = await m.pulsar(LAURA, f"confirmar:{nuevo}")
    cod = codigo_en(r)
    assert fila(cod)["fecha"] == SM2 and contar() == antes + 1
    await m.cerrar()


@prueba("Bot: descartar (botón y comando) no ejecuta y deja de ser confirmable (T21)")
async def _():
    m = Mundo()
    await m.iniciar()
    antes = contar()
    r = await m.escribir(LAURA, "reserva B", {"accion": "crear", "cliente": "Marta", "servicio": "Nuquí", "fecha": NU})
    sid = referencia_en(r)
    r = await m.pulsar(LAURA, f"descartar:{sid}")
    assert "Descarté" in r[0]
    r = await m.pulsar(LAURA, f"confirmar:{sid}")
    assert "No hay una solicitud pendiente" in r[0] and contar() == antes
    r = await m.escribir(LAURA, "reserva C", {"accion": "crear", "cliente": "Marta", "servicio": "Nuquí", "fecha": NU})
    sid = referencia_en(r)
    r = await m.escribir(LAURA, "/descartar")
    assert "Retiré" in r[0]
    assert "No hay una solicitud pendiente" in (await m.pulsar(LAURA, f"confirmar:{sid}"))[0] and contar() == antes
    await m.cerrar()


@prueba("Bot: datos incompletos piden el dato y no preparan escritura (T07, T09, T10)")
async def _():
    m = Mundo()
    await m.iniciar()
    antes = contar()
    r = await m.escribir(LAURA, "reserva sin fecha", {"accion": "crear", "cliente": "Laura", "servicio": "Manizales"})
    assert "Necesito: fecha" in r[0] and MZ1 in r[0]  # ayuda con las salidas
    assert "pendiente" not in m.app.chat_data[LAURA]
    r = await m.escribir(LAURA, "reserva sin nada util", {"accion": "crear"})
    assert "Necesito: cliente, servicio, fecha" in r[0]
    r = await m.escribir(LAURA, "cambia mi reserva", {"accion": "modificar", "fecha": MZ2})
    assert "Necesito: codigo" in r[0]
    r = await m.escribir(LAURA, "cambia esa", {"accion": "modificar", "codigo": "PN-INVENTADO123", "fecha": MZ2})
    assert "Necesito: codigo" in r[0]  # un código que no escribió ni conoce se descarta
    assert contar() == antes
    await m.cerrar()


@prueba("Bot: dos cuentas intercaladas, aislamiento, /reset y propiedad (T11, T12, T13)")
async def _():
    m = Mundo()
    await m.iniciar()
    # Laura ya tiene una reserva confirmada.
    r = await m.escribir(LAURA, "laura crea", {"accion": "crear", "cliente": "Laura Díaz", "servicio": "Nuquí", "fecha": NU})
    cod_laura = codigo_en(await m.pulsar(LAURA, f"confirmar:{referencia_en(r)}"))
    # Intercalado: Laura prepara Santa Marta, Andrés prepara Manizales.
    rl = await m.escribir(LAURA, "otra de laura", {"accion": "crear", "cliente": "Laura Díaz", "servicio": "Santa Marta", "fecha": SM1})
    ra = await m.escribir(ANDRES, "otra de andres", {"accion": "crear", "cliente": "Andrés Gil", "servicio": "Manizales", "fecha": MZ1})
    assert "Santa Marta" in rl[0] and "Manizales" in ra[0] and "Manizales" not in rl[0] and "Santa Marta" not in ra[0]
    sid_l, sid_a = referencia_en(rl), referencia_en(ra)
    assert sid_l != sid_a
    # Andrés intenta usar el botón de Laura y el código de Laura.
    assert "ya no es el vigente" in (await m.pulsar(ANDRES, f"confirmar:{sid_l}"))[0]  # el botón de Laura no sirve en el chat de Andrés
    assert contar("SELECT COUNT(*) FROM reservas WHERE cliente='Laura Díaz'") == 1
    r = await m.escribir(ANDRES, f"/reserva {cod_laura}")
    assert "no disponible" in r[0] and "Laura" not in r[0]
    r = await m.escribir(ANDRES, f"cancela {cod_laura}", {"accion": "cancelar", "codigo": cod_laura})
    assert "Primero confirma o descarta" in r[0]  # Andrés tiene su propia propuesta vigente
    r = await m.escribir(1003, f"cancela {cod_laura}", {"accion": "cancelar", "codigo": cod_laura})  # una tercera cuenta
    assert "no disponible" in r[0] and fila(cod_laura)["estado"] == "activa" and "pendiente" not in m.app.chat_data[1003]
    # /reset de Laura: su propuesta se retira; la de Andrés y la reserva de Laura se conservan.
    r = await m.escribir(LAURA, "/reset")
    assert "Reinicié" in r[0] and "pendiente" not in m.app.chat_data[LAURA]
    assert "No hay una solicitud pendiente" in (await m.pulsar(LAURA, f"confirmar:{sid_l}"))[0]
    assert fila(cod_laura)["estado"] == "activa" and m.app.chat_data[ANDRES]["pendiente"]["solicitud_id"] == sid_a
    cod_a = codigo_en(await m.pulsar(ANDRES, f"confirmar:{sid_a}"))
    assert fila(cod_a)["cliente"] == "Andrés Gil" and contar("SELECT usuario_id FROM propietarios_telegram WHERE codigo=?", cod_a) == ANDRES
    await m.cerrar()


@prueba("Bot: consultar un precio con una propuesta pendiente conserva la propuesta (T06) y fuera de alcance no tiene efectos (T15-T17)")
async def _():
    m = Mundo()
    await m.iniciar()
    antes = contar()
    sid = referencia_en(await m.escribir(LAURA, "p1", {"accion": "crear", "cliente": "Paula", "servicio": "Nuquí", "fecha": NU}))
    r = await m.escribir(LAURA, "precio nuqui", {"accion": "servicios"})
    assert "Nuquí" in r[0] and m.app.chat_data[LAURA]["pendiente"]["solicitud_id"] == sid
    r = await m.escribir(LAURA, "dame el token", {"accion": "fuera_de_alcance"})
    assert "ViajesYa" in r[0] and "token" not in r[0].lower().replace("tu reservas", "")
    r = await m.escribir(LAURA, "otra cosa distinta", {"accion": "cancelar", "codigo": "PN-X"})
    assert "Primero confirma o descarta" in r[0]
    assert m.app.chat_data[LAURA]["pendiente"]["solicitud_id"] == sid and contar() == antes
    codigo_en(await m.pulsar(LAURA, f"confirmar:{sid}"))
    assert contar() == antes + 1
    await m.cerrar()


@prueba("Bot: modificar y cancelar con resumen, rechazo posterior de la API deja la reserva intacta (T19, T20, T25)")
async def _():
    m = Mundo()
    await m.iniciar()
    cod = codigo_en(await m.pulsar(ANDRES, "confirmar:" + referencia_en(
        await m.escribir(ANDRES, "crear para modificar", {"accion": "crear", "cliente": "Nora", "servicio": "Santa Marta", "fecha": SM1}))))
    # Modificar: el resumen trae los datos conservados y los nuevos.
    r = await m.escribir(ANDRES, f"cambia {cod} a la otra salida", {"accion": "modificar", "codigo": cod, "fecha": SM2})
    assert "Acción: modificar" in r[0] and SM2 in r[0] and "Nora" in r[0]
    sid = referencia_en(r)
    r = await m.pulsar(ANDRES, f"confirmar:{sid}")
    assert fila(cod)["fecha"] == SM2 and "Resultado registrado: modificar" in r[0]
    # Sin cambios reales -> no se prepara nada.
    r = await m.escribir(ANDRES, f"deja {cod} igual", {"accion": "modificar", "codigo": cod, "fecha": SM2})
    assert "No veo cambios" in r[0]
    # Rechazo: se prepara un cambio a Capurganá y alguien ocupa antes el cupo (la API lo rechaza al confirmar).
    # (el cupo de Capurganá ya fue ocupado por la prueba de concurrencia, así que el aviso temprano lo informa)
    r = await m.escribir(ANDRES, f"cambia {cod} a capurgana", {"accion": "modificar", "codigo": cod, "servicio": "Capurganá", "fecha": CAP})
    assert "cupos" in r[0].lower() and "pendiente" not in m.app.chat_data[ANDRES]
    assert fila(cod)["fecha"] == SM2 and fila(cod)["servicio"] == "Santa Marta"
    # Cancelar: Descartar conserva activa; Confirmar cancela.
    r = await m.escribir(ANDRES, f"cancela {cod}", {"accion": "cancelar", "codigo": cod})
    assert "Acción: cancelar" in r[0] and "Nora" in r[0]
    await m.pulsar(ANDRES, f"descartar:{referencia_en(r)}")
    assert fila(cod)["estado"] == "activa"
    r = await m.escribir(ANDRES, f"cancela {cod} ya", {"accion": "cancelar", "codigo": cod})
    r = await m.pulsar(ANDRES, f"confirmar:{referencia_en(r)}")
    assert fila(cod)["estado"] == "cancelada" and "cancelada" in r[0]
    r = await m.escribir(ANDRES, f"cancela {cod} otra vez", {"accion": "cancelar", "codigo": cod})
    assert "ya está cancelada" in r[0] or "está cancelada" in r[0]
    await m.cerrar()


@prueba("Bot: la API rechaza al confirmar (cupo ocupado entre el resumen y la pulsación) y no queda registro (T22)")
async def _():
    m = Mundo()
    await m.iniciar()
    # Dos propuestas para una salida de 8 cupos no sirven; se usa Nuquí (6 cupos) llenándola por la API.
    antes = contar()
    # Cupo de Capurganá: ya está ocupado. Se prepara un resumen sobre otra salida y luego se llena.
    sid = referencia_en(await m.escribir(LAURA, "q1", {"accion": "crear", "cliente": "Quique", "servicio": "Nuquí", "fecha": NU}))
    for i in range(contar("SELECT COUNT(*) FROM reservas WHERE servicio='Nuquí' AND fecha=? AND estado='activa'", NU), 6):
        assert operar(ANDRES, "crear", {"cliente": f"Relleno {i}", "servicio": "Nuquí", "fecha": NU})[1] == 201
    r = await m.pulsar(LAURA, f"confirmar:{sid}")
    assert "La API rechazó la operación" in r[0] and "cupos" in r[0]
    assert contar("SELECT COUNT(*) FROM reservas WHERE cliente='Quique'") == 0
    assert "pendiente" not in m.app.chat_data[LAURA]
    await m.cerrar()


@prueba("Bot: resumen vencido y reserva cambiada mientras se revisaba el resumen")
async def _():
    m = Mundo()
    await m.iniciar()
    sid = referencia_en(await m.escribir(LAURA, "v1", {"accion": "crear", "cliente": "Vera", "servicio": "Manizales", "fecha": MZ1}))
    m.app.chat_data[LAURA]["pendiente"]["vence_en"] = 0
    r = await m.pulsar(LAURA, f"confirmar:{sid}")
    assert "venció" in r[0] and "pendiente" not in m.app.chat_data[LAURA] and contar("SELECT COUNT(*) FROM reservas WHERE cliente='Vera'") == 0
    cod = codigo_en(await m.pulsar(LAURA, "confirmar:" + referencia_en(
        await m.escribir(LAURA, "v2", {"accion": "crear", "cliente": "Vera", "servicio": "Manizales", "fecha": MZ1}))))
    r = await m.escribir(LAURA, f"cancela {cod}", {"accion": "cancelar", "codigo": cod})
    sid = referencia_en(r)
    ref = http("GET", f"/telegram/reservas/{cod}", LAURA)[1]["referencia"]
    assert operar(LAURA, "modificar", {"codigo": cod, "servicio": "Manizales", "fecha": MZ2}, ref)[1] == 200  # cambia mientras se revisa
    r = await m.pulsar(LAURA, f"confirmar:{sid}")
    assert "cambió" in r[0] and fila(cod)["estado"] == "activa"
    await m.cerrar()


@prueba("Bot: respuesta perdida después de escribir -> incierto, /estado recupera el recibo sin duplicar (T24)")
async def _():
    m = Mundo()
    await m.iniciar()
    original = bot.ClienteAPI.ejecutar

    def perdida(self, pendiente):
        original(self, pendiente)  # la API escribió...
        raise TimeoutError("respuesta perdida")  # ...pero el bot no se entera

    antes = contar()
    sid = referencia_en(await m.escribir(LAURA, "t24", {"accion": "crear", "cliente": "Tomás", "servicio": "Santa Marta", "fecha": SM1}))
    bot.ClienteAPI.ejecutar = perdida
    try:
        r = await m.pulsar(LAURA, f"confirmar:{sid}")
    finally:
        bot.ClienteAPI.ejecutar = original
    assert "No pude verificar" in r[0] and sid in r[0] and m.app.chat_data[LAURA]["pendiente"]["estado"] == "incierta"
    assert contar() == antes + 1  # la escritura sí ocurrió
    assert "operación por verificar" in (await m.escribir(LAURA, "otra", {"accion": "servicios"}))[0]
    assert "Primero verifica" in (await m.escribir(LAURA, "/reset"))[0]
    r = await m.escribir(LAURA, "/estado")
    cod = codigo_en(r)
    assert contar() == antes + 1 and fila(cod)["cliente"] == "Tomás" and "pendiente" not in m.app.chat_data[LAURA]
    # Tras reiniciar el proceso (otro Mundo), la referencia sigue sirviendo.
    m2 = Mundo()
    await m2.iniciar()
    assert cod in (await m2.escribir(LAURA, f"/estado {sid}"))[0]
    assert contar() == antes + 1
    await m.cerrar()
    await m2.cerrar()


@prueba("Bot: respuesta perdida ANTES de escribir -> /estado no asume fallo; /reintentar usa el mismo identificador (T24)")
async def _():
    m = Mundo()
    await m.iniciar()
    original = bot.ClienteAPI.ejecutar

    def no_llega(self, pendiente):
        raise urllib.error.URLError("sin conexión")

    antes = contar()
    sid = referencia_en(await m.escribir(LAURA, "t24b", {"accion": "crear", "cliente": "Ursula", "servicio": "Santa Marta", "fecha": SM2}))
    bot.ClienteAPI.ejecutar = no_llega
    try:
        r = await m.pulsar(LAURA, f"confirmar:{sid}")
    finally:
        bot.ClienteAPI.ejecutar = original
    assert "No pude verificar" in r[0] and contar() == antes
    assert "no asumo que la escritura falló" in (await m.escribir(LAURA, "/estado"))[0]
    r = await m.escribir(LAURA, "/reintentar")
    cod = codigo_en(r)
    assert contar() == antes + 1 and fila(cod)["cliente"] == "Ursula"
    assert "No hay una operación incierta" in (await m.escribir(LAURA, "/reintentar"))[0]
    assert contar() == antes + 1
    await m.cerrar()


@prueba("Bot: API apagada o clave incorrecta -> aviso sin inventar resultados (T23)")
async def _():
    m = Mundo(base=f"http://127.0.0.1:{puerto_libre()}")
    await m.iniciar()
    r = await m.escribir(LAURA, "catalogo caido", {"accion": "servicios"})
    assert "No pude completar la conexión" in r[0] and "Caño" not in r[0]
    await m.cerrar()
    m = Mundo(clave="otra-clave-distinta-123")
    await m.iniciar()
    r = await m.escribir(LAURA, "catalogo 401", {"accion": "servicios"})
    assert "no autorizado" in r[0].lower()
    await m.cerrar()


@prueba("Bot: error del modelo no escribe nada y /help /start responden")
async def _():
    def roto(pregunta, historial, clave, modelo):
        raise ValueError("JSON inválido")

    m = Mundo(interprete=roto)
    await m.iniciar()
    antes = contar()
    assert "formato esperado" in (await m.escribir(LAURA, "hola"))[0] and contar() == antes
    assert "/reserva" in (await m.escribir(LAURA, "/help"))[0]
    assert "ViajesYa" in (await m.escribir(LAURA, "/start"))[0]
    assert "no disponible" in (await m.escribir(LAURA, "/otro"))[0].lower()
    await m.cerrar()


def main():
    print(f"Datos de práctica en {TMP}\nAPI de prueba en {BASE}\n")
    for prueba_ in PRUEBAS:
        prueba_()
    malas = [r for r in RESULTADOS if not r[1]]
    print(f"\n{len(RESULTADOS) - len(malas)} de {len(RESULTADOS)} grupos de pruebas correctos.")
    servidor.should_exit = True
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if malas else 0)


if __name__ == "__main__":
    main()
