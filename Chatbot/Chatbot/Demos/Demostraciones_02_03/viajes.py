"""Viajes programados: cada Viaje es una salida con fecha fija ("quemada") y cupos limitados.

Para agregar o cambiar salidas basta con editar la lista VIAJES.
`servicio` debe ser una clave de negocio.json (ej. "Viaje a Caño Cristales").
Un cupo = una reserva activa de un cliente.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Viaje:
    servicio: str   # clave del servicio en negocio.json
    fecha: date     # fecha de salida (fija)
    cupos: int      # máximo de clientes que pueden reservar esta salida

    @property
    def id(self) -> str:
        return f"{self.servicio}|{self.fecha.isoformat()}"

    def ocupados(self, registros) -> int:
        """Reservas activas de esta salida (se compara por servicio y fecha)."""
        return sum(
            1 for r in registros
            if r["estado"] == "activa" and r["servicio"] == self.servicio and r["fecha"] == self.fecha.isoformat()
        )

    def cupos_libres(self, registros) -> int:
        return max(self.cupos - self.ocupados(registros), 0)

    def resumen(self, registros) -> dict:
        return {"servicio": self.servicio, "fecha": self.fecha.isoformat(),
                "cupos_totales": self.cupos, "cupos_disponibles": self.cupos_libres(registros)}


# Fechas y cupos quemados. Actualízalos cuando pasen las fechas.
# Tienen forma servicio, fecha, cupos
VIAJES = [
    Viaje("Santa Marta", date(2026, 11, 13), 10), 
    Viaje("Santa Marta", date(2026, 12, 18), 10),
    Viaje("Caño Cristales", date(2026, 11, 20), 8),
    Viaje("Caño Cristales", date(2026, 12, 11), 8),
    Viaje("Nuquí", date(2026, 11, 15), 6),
    Viaje("Nuquí", date(2027, 1, 8),   6),
    Viaje("Manizales", date(2026, 11, 14), 12),
    Viaje("Manizales", date(2026, 12, 5),  12),
    Viaje("Amazonas", date(2026, 12, 4),  8),
    Viaje("Amazonas", date(2027, 1, 15),  8),
    Viaje("Capurganá", date(2026, 12, 12), 6),
    Viaje("Capurganá", date(2027, 1, 22), 1),
]


def viajes_de(servicio: str) -> list[Viaje]:
    return sorted((v for v in VIAJES if v.servicio == servicio), key=lambda v: v.fecha)


def buscar_viaje(servicio: str, fecha: date) -> Viaje | None:
    return next((v for v in VIAJES if v.servicio == servicio and v.fecha == fecha), None)
