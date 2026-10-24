"""Demo local de un solo negocio. Ejecutar con UN worker; usar datos ficticios."""

import difflib
import json
import sqlite3
import unicodedata
from datetime import date, datetime, time, timedelta
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from almacen_sqlite import AgendaSQLite, ConflictoReserva, CruceReserva, ReservaNoEncontrada, SinCupos
from viajes import VIAJES, buscar_viaje, viajes_de

BASE = Path(__file__).resolve().parent
ARCHIVO = BASE / "reservas.json"  # solo es el origen de la migración inicial
BASE_DATOS = BASE / "reservas.db"
NEGOCIO = json.loads((BASE / "negocio.json").read_text(encoding="utf-8-sig"))
ZONA = ZoneInfo(NEGOCIO["zona_horaria"])
for _viaje in VIAJES:
    if _viaje.servicio not in NEGOCIO["servicios"] or _viaje.cupos <= 0:
        raise ValueError(f"Viaje mal configurado en viajes.py: {_viaje}")
if any(
    s["duracion_viaje_dias"] <= 0
    or s["dias_habiles"] <= 0
    or s["minimo_dias_habiles"] <= 0
    or s["precio_cop"] < 0
    for s in NEGOCIO["servicios"].values()
):
    raise ValueError("Revisar precios y duraciones del negocio.")

# Las reservas viven en SQLite: cupos y cruces se comprueban y guardan en una sola transacción (almacen_sqlite.py).
# LOCK solo ordena las operaciones dentro de este proceso (y las sesiones de /chat, que viven en memoria).
LOCK = RLock()
SESIONES: dict[str, dict] = {}
app = FastAPI(title="ViajesYa", version="1.0.0",
              description="Datos ficticios. API local sin autenticación; no publicar en Internet.")


def _normalizar(texto):
    """Minúsculas, sin tildes ni signos: 'Caño-Cristales!' -> 'cano cristales'."""
    sin_tildes = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return " ".join("".join(c if c.isalnum() else " " for c in sin_tildes.lower()).split())


_RELLENO = {"viaje", "viajes", "a", "al", "de", "del", "la", "el", "los", "las", "y", "en", "paquete",
            "plan", "paseo", "tour", "ir", "quiero", "para", "por", "un", "una"}


def _candidatos(clave, info):
    """Textos con los que la gente puede nombrar un servicio: clave, nombre y alias."""
    return {_normalizar(t) for t in (clave, info.get("nombre", ""), *info.get("alias", [])) if t}


def resolver_servicio(texto):
    """Devuelve la clave de negocio.json que corresponde al texto, o None.

    Acepta mayúsculas/tildes distintas, nombres parciales ('macarena'), el nombre largo
    ('La Macarena - Caño Cristales') y errores de tipeo leves. Si es ambiguo devuelve None.
    """
    consulta = _normalizar(texto)
    if not consulta:
        return None
    servicios = NEGOCIO["servicios"]
    cand = {k: _candidatos(k, v) for k, v in servicios.items()}
    exactos = [k for k, c in cand.items() if consulta in c]
    if len(exactos) == 1:
        return exactos[0]
    palabras = [w for w in consulta.split() if w not in _RELLENO]
    if palabras:
        coinciden = [k for k, c in cand.items()
                     if any(set(palabras) <= set(" ".join(c_).split()) for c_ in c)]
        if len(coinciden) == 1:
            return coinciden[0]
        if len(coinciden) > 1:
            return None
        todas = {t: k for k, c in cand.items() for t in c}
        cercanas = difflib.get_close_matches(" ".join(palabras), list(todas), n=3, cutoff=0.75)
        claves = {todas[t] for t in cercanas}
        if len(claves) == 1:
            return claves.pop()
    return None


def _servicio_canonico(valor):
    clave = resolver_servicio(valor)
    if clave is None:
        raise ValueError("Servicio desconocido. Opciones: " + ", ".join(NEGOCIO["servicios"]))
    return clave


class DatosReserva(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    cliente: str = Field(min_length=2, max_length=80)
    servicio: str = Field(min_length=1, max_length=60)
    fecha: date

    @field_validator("servicio")
    @classmethod
    def _canonizar_servicio(cls, v):
        return _servicio_canonico(v)

class CrearReserva(DatosReserva):
    confirmado: Literal[True]


class ModificarReserva(BaseModel):
    """Cambios sobre una reserva activa. Los campos omitidos conservan su valor actual."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    cliente: str | None = Field(default=None, min_length=2, max_length=80)
    servicio: str | None = Field(default=None, min_length=1, max_length=60)
    fecha: date | None = None
    confirmado: Literal[True]

    @field_validator("servicio")
    @classmethod
    def _canonizar_servicio(cls, v):
        return None if v is None else _servicio_canonico(v)


class Registro(DatosReserva):
    codigo: str
    estado: Literal["activa", "cancelada"]
    precio_cop: int
    duracion_viaje_dias: int = Field(gt=0)
    creada_en: str
    cancelada_en: str | None = None
    modificada_en: str | None = None


class Extraccion(BaseModel):
    """La interpretación del LLM es entrada no confiable: se valida antes de usarla."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    intencion: Literal["informacion", "reservar", "consultar", "cancelar", "continuar", "fuera"] = "continuar"
    cliente: str | None = Field(default=None, min_length=2, max_length=80)
    servicio: str | None = Field(default=None, max_length=60)
    fecha: date | None = None
    codigo: str | None = Field(default=None, max_length=50)


class Mensaje(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=150)
    mensaje: str = Field(min_length=1, max_length=2000)
    datos: Extraccion = Field(default_factory=Extraccion)


def almacen(operacion, *args):
    """Llama al almacén SQLite y traduce sus errores a HTTP: 404 si no existe, 503 si la base falla."""
    try:
        return operacion(*args)
    except ReservaNoEncontrada as exc:
        raise HTTPException(404, "No existe una reserva con ese código.") from exc
    except sqlite3.Error as exc:
        raise HTTPException(503, "No se pudo usar reservas.db. No se confirmó la operación.") from exc


def leer():
    return [Registro.model_validate(r).model_dump(mode="json") for r in almacen(agenda.listar)]


def conflicto(error, sufijo):
    """409 con el motivo real: cruce de viajes del cliente o salida sin cupos."""
    motivo = mensaje_cruce(error.reserva) if isinstance(error, CruceReserva) else "Ese viaje ya no tiene cupos disponibles."
    raise HTTPException(409, f"{motivo} {sufijo}") from error


agenda = AgendaSQLite(BASE_DATOS, clave_cliente=_normalizar)
if agenda.vacia() and ARCHIVO.exists():
    # Primera vez con SQLite: se importa el histórico de reservas.json (conserva códigos). Es idempotente.
    try:
        agenda.importar_json(ARCHIVO, servicio_canonico=lambda v: _servicio_canonico(v))
    except (ValueError, OSError) as _exc:
        raise SystemExit(f"No se pudo migrar reservas.json a reservas.db: {_exc}") from _exc


def servicio_valido(servicio):
    clave = resolver_servicio(servicio) if servicio else None
    if clave is None:
        raise HTTPException(422, "Servicio desconocido. Opciones: " + ", ".join(NEGOCIO["servicios"]))
    return NEGOCIO["servicios"][clave]


def fecha_valida(fecha, servicio, registros):
    """True si existe un viaje de ese servicio en esa fecha y aún tiene cupos.

    Lanza 422 si no hay salida programada ese día o si ya cerró la reserva (anticipación mínima).
    Devuelve False si la salida existe pero está llena.
    """
    clave = resolver_servicio(servicio)
    info = servicio_valido(servicio)
    viaje = buscar_viaje(clave, fecha)
    if viaje is None:
        proximas = ", ".join(v.fecha.isoformat() for v in viajes_de(clave) if v.fecha >= datetime.now(ZONA).date())
        raise HTTPException(
            422,
            f"No hay un viaje a {clave} programado el {fecha.isoformat()}. "
            f"Fechas de salida: {proximas or 'ninguna próxima'}.",
        )
    limite = viaje.fecha - timedelta(days=info["minimo_dias_habiles"])
    if datetime.now(ZONA).date() > limite:
        raise HTTPException(
            422,
            f"Las reservas de este viaje cerraron el {limite.isoformat()} "
            f"(se requieren {info['minimo_dias_habiles']} días de anticipación).",
        )
    return viaje.cupos_libres(registros) > 0


def fecha_regreso(fecha, duracion_dias):
    """Último día del viaje: una salida de 3 días que sale el 10 regresa el 12."""
    return fecha + timedelta(days=duracion_dias - 1)


def cruce_cliente(registros, cliente, duracion_dias, fecha, excluir=""):
    """Reserva activa del MISMO cliente cuyo viaje se solapa con el nuevo; None si no hay.

    Cada viaje ocupa el intervalo [salida, salida + duración): una persona no puede estar en dos viajes
    a la vez. Salir el día siguiente al regreso de otro viaje sí es válido (no hay solape).
    `excluir` es el código de la reserva que se está modificando, para no compararla consigo misma.
    """
    inicio, fin = fecha, fecha + timedelta(days=duracion_dias)
    nombre = _normalizar(cliente)
    for r in registros:
        if r["estado"] != "activa" or r["codigo"] == excluir or _normalizar(r["cliente"]) != nombre:
            continue
        otro_inicio = date.fromisoformat(r["fecha"])
        if inicio < otro_inicio + timedelta(days=r["duracion_viaje_dias"]) and otro_inicio < fin:
            return r
    return None


def datos_cruce(r):
    ini = date.fromisoformat(r["fecha"])
    return {"codigo": r["codigo"], "servicio": r["servicio"], "fecha": r["fecha"],
            "fecha_regreso": fecha_regreso(ini, r["duracion_viaje_dias"]).isoformat()}


def mensaje_cruce(r):
    d = datos_cruce(r)
    return (f"{r['cliente']} ya tiene la reserva {d['codigo']} a {d['servicio']} del {d['fecha']} al "
            f"{d['fecha_regreso']}: dos viajes no pueden cruzarse. "
            "Elige una salida que empiece después de ese regreso.")


def listar_viajes(servicio=None):
    """Salidas próximas con cupos libres/ocupados (solo las que aún se pueden reservar o están llenas)."""
    clave = resolver_servicio(servicio) if servicio else None
    if servicio and clave is None:
        servicio_valido(servicio)  # lanza 422 con las opciones
    hoy = datetime.now(ZONA).date()
    registros = leer()
    salida = []
    for v in sorted(VIAJES, key=lambda v: (v.servicio, v.fecha)):
        if clave and v.servicio != clave:
            continue
        if v.fecha < hoy:
            continue
        info = NEGOCIO["servicios"][v.servicio]
        cierre = v.fecha - timedelta(days=info["minimo_dias_habiles"])
        datos = v.resumen(registros)
        datos.update(nombre=info["nombre"], precio_cop=info["precio_cop"],
                     duracion_viaje_dias=info["duracion_viaje_dias"],
                     fecha_regreso=fecha_regreso(v.fecha, info["duracion_viaje_dias"]).isoformat(),
                     reservas_abiertas=hoy <= cierre, cierre_reservas=cierre.isoformat())
        salida.append(datos)
    return salida


@app.get("/servicios")
def servicios():
    return NEGOCIO


@app.get("/viajes")
def viajes(servicio: str | None = None):
    """Salidas programadas con sus cupos. Filtro opcional por servicio (acepta nombres aproximados)."""
    with LOCK:
        return {"viajes": listar_viajes(servicio)}


@app.get("/disponibilidad")
def disponibilidad(fecha: date, servicio: str, cliente: str | None = None):
    """Cupos de una salida. Con `cliente`, avisa además si su viaje se cruzaría con otra reserva suya."""
    with LOCK:
        registros = leer()
        disponible = fecha_valida(fecha, servicio, registros)
        viaje = buscar_viaje(resolver_servicio(servicio), fecha)
        respuesta = {"fecha": fecha.isoformat(), "servicio": viaje.servicio, "disponible": disponible,
                     "cupos_disponibles": viaje.cupos_libres(registros), "cupos_totales": viaje.cupos}
        if cliente:
            duracion = NEGOCIO["servicios"][viaje.servicio]["duracion_viaje_dias"]
            cruce = cruce_cliente(registros, cliente, duracion, fecha)
            respuesta["cruce_con"] = datos_cruce(cruce) if cruce else None
            if cruce:
                respuesta["disponible"] = False
                respuesta["motivo"] = mensaje_cruce(cruce)
        return respuesta


@app.post("/reservas", status_code=201)
def crear(datos: CrearReserva):
    with LOCK:
        registros = leer()
        if not fecha_valida(datos.fecha, datos.servicio, registros):
            raise HTTPException(409, "Ese viaje ya no tiene cupos disponibles. La reserva no se registró.")
        servicio = servicio_valido(datos.servicio)
        registro = Registro(**datos.model_dump(exclude={"confirmado"}),
                            codigo="PN-" + uuid4().hex[:12].upper(), estado="activa",
                            precio_cop=servicio["precio_cop"], duracion_viaje_dias=servicio["duracion_viaje_dias"],
                            creada_en=datetime.now(ZONA).isoformat()).model_dump(mode="json")
        cupos = buscar_viaje(datos.servicio, datos.fecha).cupos
        try:
            # La comprobación definitiva (cupos y cruce) y el INSERT ocurren en la misma transacción.
            return almacen(agenda.crear, registro, cupos)
        except ConflictoReserva as exc:
            conflicto(exc, "La reserva no se registró.")


@app.get("/reservas/{codigo}")
def consultar(codigo: str):
    with LOCK:
        return almacen(agenda.consultar, codigo.strip().upper())


@app.put("/reservas/{codigo}")
def modificar(codigo: str, datos: ModificarReserva):
    """Actualiza cliente, servicio y/o fecha de una reserva activa (requiere confirmado=true)."""
    cambios = datos.model_dump(mode="json", exclude={"confirmado"}, exclude_none=True)
    if not cambios:
        raise HTTPException(422, "Indica al menos un dato a modificar: cliente, servicio o fecha.")
    codigo = codigo.strip().upper()
    with LOCK:
        r = almacen(agenda.consultar, codigo)
        if r["estado"] != "activa":
            raise HTTPException(409, "No se puede modificar una reserva cancelada.")
        nuevo = {k: r[k] for k in ("cliente", "servicio", "fecha")} | cambios
        if nuevo == {k: r[k] for k in nuevo}:
            return r  # Nada cambió: no se escribe en la base.
        actualizado = {**r, **nuevo, "modificada_en": datetime.now(ZONA).isoformat()}
        info = servicio_valido(nuevo["servicio"])
        if nuevo["servicio"] != r["servicio"] or nuevo["fecha"] != r["fecha"]:
            # La propia reserva no ocupa cupo en el viaje nuevo: se compara solo contra las demás.
            otras = [x for x in leer() if x["codigo"] != codigo]
            if not fecha_valida(date.fromisoformat(nuevo["fecha"]), nuevo["servicio"], otras):
                raise HTTPException(409, "Ese viaje ya no tiene cupos disponibles. La reserva no se modificó.")
            if nuevo["servicio"] != r["servicio"]:
                # Al cambiar de destino se toman el precio y la duración del nuevo servicio.
                actualizado.update(precio_cop=info["precio_cop"], duracion_viaje_dias=info["duracion_viaje_dias"])
        actualizado = Registro.model_validate(actualizado).model_dump(mode="json")
        cupos = buscar_viaje(actualizado["servicio"], date.fromisoformat(actualizado["fecha"])).cupos
        try:
            # Cupos, cruce y UPDATE en una transacción: si algo falla, la reserva conserva sus datos anteriores.
            return almacen(agenda.modificar, codigo, actualizado, cupos)
        except ConflictoReserva as exc:
            conflicto(exc, "La reserva no se modificó.")


@app.delete("/reservas/{codigo}")
def cancelar(codigo: str, confirmado: bool = Query(False)):
    if not confirmado:
        raise HTTPException(422, "Se requiere confirmación para cancelar.")
    with LOCK:
        # No se borra la fila: el estado pasa a 'cancelada' y el cupo y el intervalo quedan libres.
        return almacen(agenda.cancelar, codigo.strip().upper(), datetime.now(ZONA).isoformat())


def resumen(r):
    return f"{r['cliente']}: {r['servicio']}, salida {r['fecha']} ({r['duracion_viaje_dias']} días)"


def pesos(valor):
    return f"   {valor:,}".replace(",", ".") + " COP"


def responder(estado, texto):
    return {"respuesta": texto, "estado_sesion": estado.copy()}


@app.post("/chat")
def chat(entrada: Mensaje):
    """Puente de Flowise. El estado y la confirmación se controlan aquí, sin agentes."""
    with LOCK:
        estado = SESIONES.setdefault(entrada.session_id, {})
        mensaje = entrada.mensaje.strip().casefold()
        if mensaje == "/reset":
            estado.clear()
            return responder(estado, "Solicitud reiniciada. Las reservas registradas se conservan.")
        if mensaje in {"no", "abortar"}:
            estado.clear()
            return responder(estado, "Solicitud descartada. No se cambió ninguna reserva.")
        try:
            # Solo la palabra exacta confirma el resumen guardado: el LLM no puede autorizarlo.
            if mensaje == "confirmar":
                pendiente = estado.get("pendiente")
                if not pendiente:
                    return responder(estado, "No hay un resumen pendiente. Primero completa la solicitud.")
                if pendiente["accion"] == "crear":
                    resultado = crear(CrearReserva(**pendiente["datos"], confirmado=True))
                    texto = "Reserva registrada. " + resumen(resultado)
                else:
                    resultado = cancelar(pendiente["codigo"], confirmado=True)
                    texto = "Reserva cancelada. " + resumen(resultado)
                estado.clear()
                estado["ultimo_codigo"] = resultado["codigo"]
                return responder(estado, texto + ". Código: " + resultado["codigo"])

            datos = entrada.datos.model_dump(mode="json", exclude_none=True)
            intencion = datos.pop("intencion")
            if intencion == "fuera":
                return responder(estado, f"Puedo ayudarte con información y reservas de {NEGOCIO['nombre']}.")
            if intencion == "informacion":
                catalogo = "\n".join(
                    f"- **{s['nombre']}**: {pesos(s['precio_cop'])}, {s['duracion_viaje_dias']} días"
                    for s in NEGOCIO["servicios"].values()
                )
                dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
                horarios = "\n".join(
                    f"- {dias[int(dia)].capitalize()}: {horas[0]} a {horas[1]}"
                    for dia, horas in NEGOCIO["horarios"].items()
                )
                texto = (
                    "Destinos disponibles:\n" + catalogo
                    + f"\n\n📍 {NEGOCIO['ubicacion']}"
                    + "\n\n**Horarios de atención:**\n" + horarios
                    + f"\n\n{NEGOCIO['condiciones']}"
                )
                if estado.get("servicio") or estado.get("fecha") or estado.get("cliente"):
                    texto += "\n\nSi estabas reservando, conservé tus datos."
                return responder(estado, texto)
            if intencion in {"reservar", "consultar", "cancelar"}:
                if estado.get("intencion") != intencion:
                    estado.clear()
                estado["intencion"] = intencion
            if not estado.get("intencion"):
                estado["intencion"] = "reservar" if datos else "inicio"
            if estado["intencion"] == "inicio":
                estado.clear()
                return responder(estado, "Hola. Puedo informar, reservar, consultar o cancelar. ¿Qué necesitas?")
            if any(estado.get(k) != v for k, v in datos.items()):
                estado.pop("pendiente", None)
            estado.update(datos)
            accion = estado["intencion"]
            if accion in {"consultar", "cancelar"}:
                if not estado.get("codigo"):
                    return responder(estado, "Escribe el código de la reserva, por ejemplo PN-...")
                r = consultar(estado["codigo"])
                if accion == "consultar":
                    return responder(estado, resumen(r) + ". Estado: " + r["estado"] + ". Código: " + r["codigo"])
                if r["estado"] == "cancelada":
                    return responder(estado, "Esta reserva ya está cancelada.")
                estado["pendiente"] = {"accion": "cancelar", "codigo": r["codigo"]}
                return responder(estado, "Vas a cancelar: " + resumen(r) + ". Escribe CONFIRMAR o ABORTAR.")

            if not estado.get("servicio"):
                return responder(estado, "¿Qué viaje te interesa? Opciones: " + ", ".join(NEGOCIO["servicios"]))
            servicio_valido(estado["servicio"])
            if not estado.get("fecha"):
                return responder(estado, "Indica la fecha de salida (AAAA-MM-DD). Fechas: " + ", ".join(v["fecha"] + f" ({v['cupos_disponibles']} cupos)" for v in listar_viajes(estado["servicio"])))
            fecha = date.fromisoformat(estado["fecha"])
            if not fecha_valida(fecha, estado["servicio"], leer()):
                estado.pop("pendiente", None)
                estado.pop("fecha", None)
                return responder(estado, "Ese viaje no tiene cupos para esa fecha. Indica otra fecha de salida.")
            if not estado.get("cliente"):
                return responder(estado, "¿A nombre de quién preparo la reserva?")
            solicitud = DatosReserva(**{k: estado[k] for k in DatosReserva.model_fields}).model_dump(mode="json")
            info_servicio = servicio_valido(solicitud["servicio"])
            cruce = cruce_cliente(leer(), solicitud["cliente"], info_servicio["duracion_viaje_dias"], fecha)
            if cruce:
                estado.pop("pendiente", None)
                estado.pop("fecha", None)
                return responder(estado, mensaje_cruce(cruce))
            estado["pendiente"] = {"accion": "crear", "datos": solicitud}
            vista_previa = {**solicitud, "duracion_viaje_dias": info_servicio["duracion_viaje_dias"]}
            return responder(
                estado,
                "Solicitud: " + resumen(vista_previa) + f". Precio: {pesos(info_servicio['precio_cop'])}. "
                "Escribe CONFIRMAR para registrar o ABORTAR. Aún no se ha guardado."
            )
        except HTTPException as exc:
            estado.pop("pendiente", None)
            return JSONResponse(status_code=exc.status_code, content=responder(estado, exc.detail))
        except (ValidationError, ValueError):
            estado.pop("pendiente", None)
            return JSONResponse(status_code=422, content=responder(estado, "Revisa los datos: fecha AAAA-MM-DD y hora HH:MM."))