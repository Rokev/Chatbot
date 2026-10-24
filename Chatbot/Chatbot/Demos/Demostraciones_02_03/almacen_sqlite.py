"""Reservas de ViajesYa en SQLite. Cada operación utiliza su propia conexión.

Modelo del negocio (igual que main.py y viajes.py):
  - Cada reserva ocupa UN cupo de una salida (servicio + fecha de salida fija).
  - Cada viaje ocupa el intervalo de días [fecha, fecha + duracion_viaje_dias).
  - Un mismo cliente no puede tener dos viajes activos cuyos intervalos se solapen.

La comprobación (cupos y cruce) y el guardado se hacen en UNA sola transacción `BEGIN IMMEDIATE`:
SQLite bloquea la escritura desde el BEGIN, así que nadie puede ocupar el último cupo ni crear un cruce
entre que se comprueba y se guarda, ni siquiera desde otro proceso.

Uso desde la terminal (migrar el histórico de reservas.json a reservas.db):
    python almacen_sqlite.py --migrar reservas.json --base reservas.db
"""

import json
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date
from pathlib import Path

CAMPOS = ("codigo", "cliente", "servicio", "fecha", "estado", "precio_cop",
          "duracion_viaje_dias", "creada_en", "cancelada_en", "modificada_en")
ESTADOS = {"activa", "cancelada"}


class ConflictoReserva(ValueError):
    """La operación choca con otra reserva (cupos, cruce o estado). La API la convierte en HTTP 409."""


class SinCupos(ConflictoReserva):
    pass


class CruceReserva(ConflictoReserva):
    def __init__(self, reserva):
        super().__init__("El viaje se cruza con otra reserva activa del mismo cliente")
        self.reserva = reserva  # la reserva con la que se cruza


class ReservaNoEncontrada(ValueError):
    """No existe una reserva con ese código. La API la convierte en HTTP 404."""


def _clave_por_defecto(texto):
    """Minúsculas, sin tildes ni signos: 'Laura  Gómez' -> 'laura gomez' (igual que _normalizar de main.py)."""
    sin_tildes = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return " ".join("".join(c if c.isalnum() else " " for c in sin_tildes.lower()).split())


class AgendaSQLite:
    def __init__(self, ruta, clave_cliente=_clave_por_defecto):
        """`clave_cliente` normaliza el nombre para saber si dos reservas son del mismo cliente."""
        self.ruta = Path(ruta).resolve()
        self.clave_cliente = clave_cliente
        with self.conexion(escritura=True) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS reservas (
                codigo TEXT PRIMARY KEY,
                cliente TEXT NOT NULL,
                cliente_clave TEXT NOT NULL,
                servicio TEXT NOT NULL,
                fecha TEXT NOT NULL,
                estado TEXT NOT NULL CHECK (estado IN ('activa', 'cancelada')),
                precio_cop INTEGER NOT NULL CHECK (precio_cop >= 0),
                duracion_viaje_dias INTEGER NOT NULL CHECK (duracion_viaje_dias > 0),
                creada_en TEXT NOT NULL,
                cancelada_en TEXT,
                modificada_en TEXT
            )""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_salida ON reservas(servicio, fecha, estado)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_cliente ON reservas(cliente_clave, estado)")

    @contextmanager
    def conexion(self, escritura=False):
        con = sqlite3.connect(self.ruta, timeout=10, isolation_level=None)
        con.row_factory = sqlite3.Row
        try:
            if escritura:
                # Desde aquí nadie más escribe: comprobar y guardar son una sola operación.
                con.execute("BEGIN IMMEDIATE")
            yield con
            if escritura:
                con.commit()
        except Exception:
            if escritura:
                con.rollback()
            raise
        finally:
            con.close()

    # ---------- lectura ----------

    @staticmethod
    def _fila(fila):
        return {campo: fila[campo] for campo in CAMPOS}

    def vacia(self):
        with self.conexion() as con:
            return con.execute("SELECT COUNT(*) FROM reservas").fetchone()[0] == 0

    def listar(self):
        with self.conexion() as con:
            return [self._fila(f) for f in con.execute("SELECT * FROM reservas ORDER BY rowid")]

    def _obtener(self, con, codigo):
        fila = con.execute("SELECT * FROM reservas WHERE codigo=?", (codigo,)).fetchone()
        if fila is None:
            raise ReservaNoEncontrada("Reserva no encontrada")
        return self._fila(fila)

    def consultar(self, codigo):
        with self.conexion() as con:
            return self._obtener(con, codigo)

    # ---------- comprobaciones (se llaman DENTRO de la transacción) ----------

    @staticmethod
    def _cupos_ocupados(con, servicio, fecha, excluir=""):
        return con.execute(
            "SELECT COUNT(*) FROM reservas WHERE estado='activa' AND servicio=? AND fecha=? AND codigo<>?",
            (servicio, fecha, excluir),
        ).fetchone()[0]

    @staticmethod
    def _cruce(con, clave, fecha, duracion, excluir=""):
        """Reserva activa del mismo cliente cuyo intervalo [fecha, fecha+duración) se solapa con el nuevo."""
        # Las fechas ISO se comparan como texto. Dos intervalos se solapan si cada uno empieza antes de que termine el otro.
        fila = con.execute(
            """SELECT * FROM reservas
               WHERE estado='activa' AND cliente_clave=? AND codigo<>?
                 AND fecha < date(?, '+' || ? || ' days')
                 AND date(fecha, '+' || duracion_viaje_dias || ' days') > ?""",
            (clave, excluir, fecha, duracion, fecha),
        ).fetchone()
        return AgendaSQLite._fila(fila) if fila else None

    def _comprobar(self, con, registro, cupos, excluir="", revisar_cupos=True):
        if revisar_cupos and self._cupos_ocupados(con, registro["servicio"], registro["fecha"], excluir) >= cupos:
            raise SinCupos("Ese viaje ya no tiene cupos disponibles")
        cruce = self._cruce(con, self.clave_cliente(registro["cliente"]), registro["fecha"],
                            registro["duracion_viaje_dias"], excluir)
        if cruce:
            raise CruceReserva(cruce)

    # ---------- escritura ----------

    def crear(self, registro, cupos):
        """Guarda una reserva nueva si la salida tiene cupo y no hay cruce. `registro` trae todos los CAMPOS."""
        with self.conexion(escritura=True) as con:
            self._comprobar(con, registro, cupos)
            con.execute(
                "INSERT INTO reservas (codigo, cliente, cliente_clave, servicio, fecha, estado, precio_cop,"
                " duracion_viaje_dias, creada_en, cancelada_en, modificada_en) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (registro["codigo"], registro["cliente"], self.clave_cliente(registro["cliente"]),
                 registro["servicio"], registro["fecha"], registro["estado"], registro["precio_cop"],
                 registro["duracion_viaje_dias"], registro["creada_en"], registro.get("cancelada_en"),
                 registro.get("modificada_en")),
            )
            return self._obtener(con, registro["codigo"])

    def modificar(self, codigo, registro, cupos):
        """Reemplaza cliente, servicio, fecha, precio y duración de una reserva ACTIVA tras volver a comprobar.

        Si la comprobación falla, la transacción se revierte y la reserva conserva sus datos anteriores.
        """
        with self.conexion(escritura=True) as con:
            actual = self._obtener(con, codigo)
            if actual["estado"] != "activa":
                raise ConflictoReserva("No se puede modificar una reserva cancelada.")
            cambio_de_salida = (registro["servicio"], registro["fecha"]) != (actual["servicio"], actual["fecha"])
            # La propia reserva no ocupa cupo ni se cruza consigo misma (excluir=codigo).
            self._comprobar(con, registro, cupos, excluir=codigo, revisar_cupos=cambio_de_salida)
            con.execute(
                "UPDATE reservas SET cliente=?, cliente_clave=?, servicio=?, fecha=?, precio_cop=?,"
                " duracion_viaje_dias=?, modificada_en=? WHERE codigo=?",
                (registro["cliente"], self.clave_cliente(registro["cliente"]), registro["servicio"],
                 registro["fecha"], registro["precio_cop"], registro["duracion_viaje_dias"],
                 registro["modificada_en"], codigo),
            )
            return self._obtener(con, codigo)

    def cancelar(self, codigo, cancelada_en):
        """Cambia el estado a 'cancelada' (no borra la fila). Cancelar dos veces devuelve la reserva sin cambios."""
        with self.conexion(escritura=True) as con:
            actual = self._obtener(con, codigo)
            if actual["estado"] == "activa":
                con.execute("UPDATE reservas SET estado='cancelada', cancelada_en=? WHERE codigo=?",
                            (cancelada_en, codigo))
                actual = self._obtener(con, codigo)
            return actual

    # ---------- migración ----------

    def importar_json(self, ruta, servicio_canonico=None):
        """Importa reservas.json (lista de registros, o {'reservas': [...]}), conservando códigos e histórico.

        Si algo es inválido, un código ya existe con datos distintos o dos reservas activas del mismo cliente
        se cruzan, se detiene y se revierten todas las inserciones de este intento.
        Repetir una importación idéntica no duplica registros. Los cupos no se revisan: es histórico.
        """
        registros = json.loads(Path(ruta).read_text(encoding="utf-8-sig"))
        if isinstance(registros, dict):
            registros = registros.get("reservas")
        if not isinstance(registros, list):
            raise ValueError("Se esperaba una lista de reservas o {'reservas': [...]}")
        nuevos = existentes = 0
        with self.conexion(escritura=True) as con:
            for crudo in registros:
                if not isinstance(crudo, dict):
                    raise ValueError("Cada reserva debe ser un objeto")
                faltan = [c for c in ("codigo", "cliente", "servicio", "fecha", "estado", "precio_cop",
                                      "duracion_viaje_dias", "creada_en") if c not in crudo]
                if faltan:
                    raise ValueError(f"A la reserva {crudo.get('codigo', '?')} le faltan campos: {', '.join(faltan)}")
                fila = {c: crudo.get(c) for c in CAMPOS}
                if servicio_canonico:
                    fila["servicio"] = servicio_canonico(fila["servicio"])
                if fila["estado"] not in ESTADOS:
                    raise ValueError(f"Estado inválido en {fila['codigo']}: debe ser activa o cancelada")
                if date.fromisoformat(fila["fecha"]).isoformat() != fila["fecha"]:
                    raise ValueError(f"Fecha inválida en {fila['codigo']}: usa AAAA-MM-DD")
                if type(fila["duracion_viaje_dias"]) is not int or fila["duracion_viaje_dias"] <= 0:
                    raise ValueError(f"Duración inválida en {fila['codigo']}")
                if type(fila["precio_cop"]) is not int or fila["precio_cop"] < 0:
                    raise ValueError(f"Precio inválido en {fila['codigo']}")
                if any(not isinstance(fila[c], str) or not fila[c].strip()
                       for c in ("codigo", "cliente", "servicio", "creada_en")):
                    raise ValueError("Código, cliente, servicio y creada_en deben ser textos no vacíos")
                previa = con.execute("SELECT * FROM reservas WHERE codigo=?", (fila["codigo"],)).fetchone()
                if previa is not None:
                    if self._fila(previa) != fila:
                        raise ConflictoReserva(
                            f"El código {fila['codigo']} ya existe con datos distintos; revisa la migración")
                    existentes += 1
                    continue
                if fila["estado"] == "activa":
                    cruce = self._cruce(con, self.clave_cliente(fila["cliente"]), fila["fecha"],
                                        fila["duracion_viaje_dias"])
                    if cruce:
                        raise ConflictoReserva(
                            f"{fila['codigo']} se cruza con la reserva activa {cruce['codigo']} del mismo cliente")
                con.execute(
                    "INSERT INTO reservas (codigo, cliente, cliente_clave, servicio, fecha, estado, precio_cop,"
                    " duracion_viaje_dias, creada_en, cancelada_en, modificada_en) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (fila["codigo"], fila["cliente"], self.clave_cliente(fila["cliente"]), fila["servicio"],
                     fila["fecha"], fila["estado"], fila["precio_cop"], fila["duracion_viaje_dias"],
                     fila["creada_en"], fila["cancelada_en"], fila["modificada_en"]),
                )
                nuevos += 1
        return {"importadas": nuevos, "ya_existentes": existentes}


if __name__ == "__main__":
    import argparse

    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Importar reservas JSON a SQLite")
    parser.add_argument("--migrar", required=True, type=Path, help="ruta de reservas.json")
    parser.add_argument("--base", type=Path, default=base / "reservas.db")
    args = parser.parse_args()
    try:
        print(json.dumps(AgendaSQLite(args.base).importar_json(args.migrar), ensure_ascii=False, indent=2))
    except (ValueError, OSError) as error:
        parser.exit(1, f"Migración detenida: {error}\n")
