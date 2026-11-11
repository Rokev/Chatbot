"""Rutas protegidas de Telegram sobre la AgendaSQLite de ViajesYa (clase 13).

Qué añade al almacenamiento existente (almacen_sqlite.py):
  - propietarios_telegram: código de reserva -> identificador de usuario de Telegram que la creó.
  - operaciones_telegram: solicitud_id, huella de los datos autorizados y respuesta (recibo).
    Permite reconocer un reenvío de la misma operación sin repetir la escritura.

Reglas del negocio que reutiliza (las mismas de main.py):
  - Cada reserva ocupa UN cupo de una salida de fecha fija (viajes.py). No existe la hora.
  - Hay que reservar con la anticipación mínima del servicio (`minimo_dias_habiles`).
  - Un mismo cliente no puede tener dos viajes activos cuyos intervalos se solapen.
Cupos y cruce se comprueban DENTRO de la transacción de escritura (BEGIN IMMEDIATE), junto con el registro
de la propiedad y del recibo: o se guarda todo o no se guarda nada.
"""

import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from threading import local
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from almacen_sqlite import AgendaSQLite, ConflictoReserva, CruceReserva, ReservaNoEncontrada
from viajes import VIAJES, buscar_viaje, viajes_de


def huella(valor):
    """SHA-256 estable de un dato JSON. Sirve para detectar que una reserva cambió después de un resumen."""
    texto = json.dumps(valor, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


class DatosReserva(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cliente: str = Field(default="", max_length=120)
    servicio: str = Field(default="", max_length=100)
    fecha: str = Field(default="", max_length=10)
    codigo: str = Field(default="", max_length=64)


class Operacion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    solicitud_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    accion: Literal["crear", "modificar", "cancelar"]
    datos: DatosReserva
    referencia: str = Field(default="", max_length=64)
    confirmada: Literal[True]


class AgendaTelegram(AgendaSQLite):
    """AgendaSQLite + propiedad por usuario de Telegram + recibos de operación idempotentes."""

    def __init__(self, ruta, negocio, resolver_servicio, zona, clave_cliente=None):
        """`negocio` es el negocio.json; `resolver_servicio(texto)` devuelve la clave oficial o None."""
        self._hilo = local()
        self.negocio = negocio
        self.servicios = negocio["servicios"]
        self.resolver_servicio = resolver_servicio
        self.zona = zona
        if clave_cliente is None:
            super().__init__(ruta)
        else:
            super().__init__(ruta, clave_cliente=clave_cliente)
        with self.conexion(escritura=True) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS propietarios_telegram (
                codigo TEXT PRIMARY KEY,
                usuario_id INTEGER NOT NULL
            )""")
            con.execute("""CREATE TABLE IF NOT EXISTS operaciones_telegram (
                solicitud_id TEXT PRIMARY KEY,
                usuario_id INTEGER NOT NULL,
                huella TEXT NOT NULL,
                estado_http INTEGER NOT NULL,
                respuesta TEXT NOT NULL
            )""")

    @contextmanager
    def conexion(self, escritura=False):
        """Dentro de `operar` todos los métodos reutilizan la conexión (y la transacción) de esa operación."""
        compartida = getattr(self._hilo, "conexion", None)
        if compartida is not None:
            yield compartida
        else:
            with super().conexion(escritura) as con:
                yield con

    # ---------- validaciones de negocio (mismos mensajes que main.py) ----------

    def _servicio(self, texto):
        clave = self.resolver_servicio(texto) if texto else None
        if clave is None:
            raise ValueError("Servicio desconocido. Opciones: " + ", ".join(self.servicios))
        return clave

    @staticmethod
    def _fecha(texto):
        try:
            valor = date.fromisoformat(texto)
        except (TypeError, ValueError):
            raise ValueError("Fecha inválida: usa AAAA-MM-DD") from None
        if valor.isoformat() != texto:
            raise ValueError("Fecha inválida: usa AAAA-MM-DD")
        return valor

    @staticmethod
    def _cliente(texto):
        texto = " ".join((texto or "").split())
        if not 2 <= len(texto) <= 80:
            raise ValueError("El nombre del cliente debe tener entre 2 y 80 caracteres")
        return texto

    def _hoy(self):
        return datetime.now(self.zona).date()

    def _reservable(self, servicio, fecha):
        """Salida programada y todavía abierta. Lanza ValueError con el motivo; los cupos se miran en la transacción."""
        viaje = buscar_viaje(servicio, fecha)
        if viaje is None:
            proximas = ", ".join(v.fecha.isoformat() for v in viajes_de(servicio) if v.fecha >= self._hoy())
            raise ValueError(f"No hay un viaje a {servicio} programado el {fecha.isoformat()}. "
                             f"Fechas de salida: {proximas or 'ninguna próxima'}.")
        minimo = self.servicios[servicio]["minimo_dias_habiles"]
        limite = viaje.fecha - timedelta(days=minimo)
        if self._hoy() > limite:
            raise ValueError(f"Las reservas de este viaje cerraron el {limite.isoformat()} "
                             f"(se requieren {minimo} días de anticipación).")
        return viaje

    # ---------- propiedad ----------

    def _es_propia(self, con, codigo, usuario_id):
        fila = con.execute("SELECT usuario_id FROM propietarios_telegram WHERE codigo=?", (codigo,)).fetchone()
        return fila is not None and fila["usuario_id"] == usuario_id

    def _propia(self, con, codigo, usuario_id):
        """Reserva del usuario. Inexistente, ajena o antigua sin propietario dan el mismo mensaje (no revela nada)."""
        codigo = (codigo or "").strip().upper()
        if not self._es_propia(con, codigo, usuario_id):
            raise ReservaNoEncontrada("Reserva no disponible para este usuario")
        return self._obtener(con, codigo)

    def _motivo_cruce(self, con, error, cliente, usuario_id):
        """Mensaje del cruce. Solo se detalla la otra reserva si es del mismo usuario de Telegram."""
        otra = error.reserva
        if not self._es_propia(con, otra["codigo"], usuario_id):
            return (f"{cliente} ya tiene otra reserva activa cuyas fechas se cruzan con ese viaje: "
                    "dos viajes no pueden cruzarse. Elige una salida que empiece después de su regreso.")
        regreso = date.fromisoformat(otra["fecha"]) + timedelta(days=otra["duracion_viaje_dias"] - 1)
        return (f"{otra['cliente']} ya tiene la reserva {otra['codigo']} a {otra['servicio']} del "
                f"{otra['fecha']} al {regreso.isoformat()}: dos viajes no pueden cruzarse. "
                "Elige una salida que empiece después de ese regreso.")

    # ---------- lecturas ----------

    def consultar_propia(self, codigo, usuario_id):
        with self.conexion() as con:
            reserva = self._propia(con, codigo, usuario_id)
            return {"reserva": reserva, "referencia": huella(reserva)}

    def consultar_operacion(self, solicitud_id, usuario_id):
        with self.conexion() as con:
            fila = con.execute(
                "SELECT * FROM operaciones_telegram WHERE solicitud_id=? AND usuario_id=?",
                (solicitud_id, usuario_id),
            ).fetchone()
            if fila is None:
                raise ReservaNoEncontrada("Todavía no hay un resultado registrado para esa solicitud")
            return fila["estado_http"], json.loads(fila["respuesta"])

    def viajes(self, servicio=None):
        """Salidas futuras con cupos libres, igual que GET /viajes."""
        clave = None
        if servicio:
            clave = self._servicio(servicio)
        hoy = self._hoy()
        registros = self.listar()
        salida = []
        for v in sorted(VIAJES, key=lambda v: (v.servicio, v.fecha)):
            if (clave and v.servicio != clave) or v.fecha < hoy:
                continue
            info = self.servicios[v.servicio]
            cierre = v.fecha - timedelta(days=info["minimo_dias_habiles"])
            datos = v.resumen(registros)
            datos.update(nombre=info["nombre"], precio_cop=info["precio_cop"],
                         duracion_viaje_dias=info["duracion_viaje_dias"],
                         fecha_regreso=(v.fecha + timedelta(days=info["duracion_viaje_dias"] - 1)).isoformat(),
                         reservas_abiertas=hoy <= cierre, cierre_reservas=cierre.isoformat())
            salida.append(datos)
        return {"viajes": salida}

    def disponibilidad(self, fecha, servicio, cliente=None, usuario_id=0):
        """Cupos de una salida. Con `cliente` avisa si su viaje se cruzaría con otra reserva suya."""
        clave = self._servicio(servicio)
        dia = self._fecha(fecha)
        viaje = self._reservable(clave, dia)
        libres = viaje.cupos_libres(self.listar())
        respuesta = {"fecha": fecha, "servicio": clave, "disponible": libres > 0,
                     "cupos_disponibles": libres, "cupos_totales": viaje.cupos}
        if cliente and cliente.strip():
            duracion = self.servicios[clave]["duracion_viaje_dias"]
            with self.conexion() as con:
                cruce = self._cruce(con, self.clave_cliente(cliente), dia.isoformat(), duracion)
                if cruce:
                    respuesta["disponible"] = False
                    respuesta["motivo"] = self._motivo_cruce(con, CruceReserva(cruce), cliente.strip(), usuario_id)
        if libres <= 0:
            respuesta["motivo"] = "Ese viaje ya no tiene cupos disponibles."
        return respuesta

    # ---------- escritura ----------

    def operar(self, solicitud, usuario_id):
        """Ejecuta una operación confirmada. Devuelve (estado_http, contenido) y deja un recibo idempotente."""
        contenido = solicitud.model_dump()
        identificador = solicitud.solicitud_id
        firma = huella(contenido)
        accion = solicitud.accion
        datos = solicitud.datos
        with self.conexion(escritura=True) as con:
            self._hilo.conexion = con
            try:
                anterior = con.execute(
                    "SELECT * FROM operaciones_telegram WHERE solicitud_id=?", (identificador,)
                ).fetchone()
                if anterior is not None:
                    if anterior["usuario_id"] != usuario_id:
                        return 404, {"ok": False, "detalle": "Solicitud no disponible"}
                    if anterior["huella"] != firma:
                        return 409, {"ok": False, "detalle": "El identificador ya pertenece a otros datos"}
                    return anterior["estado_http"], json.loads(anterior["respuesta"])  # reenvío: mismo recibo

                con.execute("SAVEPOINT cambio_reserva")
                try:
                    if accion == "crear":
                        reserva = self._crear(con, datos, usuario_id)
                    else:
                        actual = self._propia(con, datos.codigo, usuario_id)
                        if not solicitud.referencia or huella(actual) != solicitud.referencia:
                            raise ConflictoReserva("La reserva cambió. Consúltala y prepara otro resumen")
                        if accion == "modificar":
                            reserva = self._modificar(con, actual, datos, usuario_id)
                        else:
                            reserva = self.cancelar(actual["codigo"], datetime.now(self.zona).isoformat())
                    estado = 201 if accion == "crear" else 200
                    respuesta = {"ok": True, "solicitud_id": identificador, "accion": accion,
                                 "reserva": reserva, "referencia": huella(reserva)}
                except (ReservaNoEncontrada, ConflictoReserva, ValueError) as error:
                    con.execute("ROLLBACK TO cambio_reserva")  # nada de esta operación queda guardado
                    estado = (404 if isinstance(error, ReservaNoEncontrada) else
                              409 if isinstance(error, ConflictoReserva) else 422)
                    detalle = str(error)
                    if isinstance(error, CruceReserva):
                        detalle = self._motivo_cruce(con, error, " ".join(datos.cliente.split()) or "El cliente",
                                                     usuario_id)
                    respuesta = {"ok": False, "solicitud_id": identificador, "accion": accion, "detalle": detalle}
                finally:
                    con.execute("RELEASE cambio_reserva")
                con.execute("INSERT INTO operaciones_telegram VALUES (?, ?, ?, ?, ?)",
                            (identificador, usuario_id, firma, estado, json.dumps(respuesta, ensure_ascii=False)))
                return estado, respuesta
            finally:
                self._hilo.conexion = None

    def _crear(self, con, datos, usuario_id):
        cliente = self._cliente(datos.cliente)
        servicio = self._servicio(datos.servicio)
        viaje = self._reservable(servicio, self._fecha(datos.fecha))
        info = self.servicios[servicio]
        registro = {"codigo": "PN-" + uuid4().hex[:12].upper(), "cliente": cliente, "servicio": servicio,
                    "fecha": viaje.fecha.isoformat(), "estado": "activa", "precio_cop": info["precio_cop"],
                    "duracion_viaje_dias": info["duracion_viaje_dias"],
                    "creada_en": datetime.now(self.zona).isoformat(), "cancelada_en": None, "modificada_en": None}
        reserva = self.crear(registro, viaje.cupos)  # cupos y cruce dentro de esta misma transacción
        con.execute("INSERT INTO propietarios_telegram VALUES (?, ?)", (reserva["codigo"], usuario_id))
        return reserva

    def _modificar(self, con, actual, datos, usuario_id):
        if actual["estado"] != "activa":
            raise ConflictoReserva("No se puede modificar una reserva cancelada.")
        cliente = self._cliente(datos.cliente) if datos.cliente.strip() else actual["cliente"]
        servicio = self._servicio(datos.servicio) if datos.servicio.strip() else actual["servicio"]
        fecha = self._fecha(datos.fecha).isoformat() if datos.fecha.strip() else actual["fecha"]
        if (cliente, servicio, fecha) == (actual["cliente"], actual["servicio"], actual["fecha"]):
            return actual  # sin cambios: no se escribe
        nuevo = {**actual, "cliente": cliente, "servicio": servicio, "fecha": fecha,
                 "modificada_en": datetime.now(self.zona).isoformat()}
        cambia_salida = (servicio, fecha) != (actual["servicio"], actual["fecha"])
        cupos = 1
        if cambia_salida:
            viaje = self._reservable(servicio, self._fecha(fecha))
            cupos = viaje.cupos
            info = self.servicios[servicio]
            nuevo.update(precio_cop=info["precio_cop"], duracion_viaje_dias=info["duracion_viaje_dias"])
        # Cupos, cruce y UPDATE en la misma transacción; si algo falla, la reserva conserva sus datos.
        return AgendaSQLite.modificar(self, actual["codigo"], nuevo, cupos)


def crear_router(agenda, clave):
    if not clave or len(clave) < 16 or not clave.isascii():
        raise ValueError("CHATBOT_API_KEY debe tener al menos 16 caracteres ASCII")
    router = APIRouter(prefix="/telegram", tags=["Telegram"])

    def autenticar(x_api_key: str = Header(default="")):
        if not secrets.compare_digest(clave.encode("utf-8"), x_api_key.encode("utf-8", "ignore")):
            raise HTTPException(401, "Acceso del servicio no autorizado")

    def identidad(x_telegram_user: int = Header(...), _=Depends(autenticar)):
        if x_telegram_user <= 0:
            raise HTTPException(422, "Identificador de usuario inválido")
        return x_telegram_user

    def leer(funcion, *args, **kwargs):
        try:
            return funcion(*args, **kwargs)
        except ReservaNoEncontrada as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except sqlite3.Error as error:
            raise HTTPException(503, "El almacenamiento no está disponible") from error

    @router.get("/servicios", dependencies=[Depends(autenticar)])
    def servicios():
        return agenda.negocio

    @router.get("/viajes", dependencies=[Depends(autenticar)])
    def viajes(servicio: str | None = None):
        return leer(agenda.viajes, servicio)

    @router.get("/disponibilidad")
    def disponibilidad(fecha: str, servicio: str, cliente: str | None = None,
                       usuario_id: int = Depends(identidad)):
        return leer(agenda.disponibilidad, fecha, servicio, cliente, usuario_id)

    @router.get("/reservas/{codigo}")
    def consultar(codigo: str, usuario_id: int = Depends(identidad)):
        return leer(agenda.consultar_propia, codigo, usuario_id)

    @router.post("/operaciones")
    def operar(solicitud: Operacion, usuario_id: int = Depends(identidad)):
        try:
            estado, contenido = agenda.operar(solicitud, usuario_id)
        except sqlite3.Error as error:
            raise HTTPException(503, "No se obtuvo un resultado verificable; consulta el estado") from error
        return JSONResponse(status_code=estado, content=contenido)

    @router.get("/operaciones/{solicitud_id}")
    def estado(solicitud_id: str, usuario_id: int = Depends(identidad)):
        codigo, contenido = leer(agenda.consultar_operacion, solicitud_id, usuario_id)
        return {"estado_http": codigo, "resultado": contenido}

    return router
