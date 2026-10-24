"""Consulta reservas.db sin modificar nada. Funciona con cualquier Python 3.
Uso (desde cualquier carpeta):
    python ver_reservas.py
    python ver_reservas.py "SELECT * FROM reservas WHERE cliente='Natalia Morales'"
"""
import sqlite3
import sys
from pathlib import Path

RUTA = Path(__file__).resolve().parent / "reservas.db"   # la base junto a este script
SQL = sys.argv[1] if len(sys.argv) > 1 else (
    "SELECT codigo, cliente, servicio, fecha, estado, precio_cop, duracion_viaje_dias, creada_en "
    "FROM reservas ORDER BY rowid")

if not RUTA.exists():
    sys.exit(f"No existe {RUTA}")
con = sqlite3.connect(f"file:{RUTA.as_posix()}?mode=ro", uri=True)   # solo lectura
cur = con.execute(SQL)
cols = [d[0] for d in cur.description] if cur.description else []
filas = [[("" if v is None else str(v)) for v in f] for f in cur.fetchall()]
anchos = [max([len(c)] + [len(f[i]) for f in filas]) for i, c in enumerate(cols)]
linea = lambda v: " | ".join(x.ljust(anchos[i]) for i, x in enumerate(v))
if cols:
    print(linea(cols)); print("-+-".join("-" * a for a in anchos))
    for f in filas: print(linea(f))
print(f"\n{len(filas)} fila(s)")
con.close()