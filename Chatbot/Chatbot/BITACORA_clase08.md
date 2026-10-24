# Bitácora · Clase 08–09 · Gradio, SQLite y disponibilidad (ViajesYa)

## 1. Recorrido de una solicitud

| Pregunta | Respuesta |
|---|---|
| ¿Qué función recibe el mensaje? | `enviar()` en `app_gradio.py`, que llama a `turno()` y este a `Chat.responder()` de `chatbot_memoria.py`. |
| ¿Dónde vive el historial? | En `Sesion.chat.historial` (una `Sesion` por pestaña, guardada en `gr.State`). Nada se comparte entre personas. |
| ¿Qué endpoint ejecuta la operación? | La FastAPI: `POST /reservas`, `PUT /reservas/{codigo}`, `DELETE /reservas/{codigo}`; `/viajes` y `/disponibilidad` para consultar. Gradio nunca toca la base. |
| ¿Qué sentencia SQL corresponde? | Ver la tabla de la sección 3. |
| ¿Por qué comprobar y guardar en la misma transacción? | Ver la sección 4. |

## 2. Qué es «intervalo» en ViajesYa

El negocio no trabaja con horas sino con **salidas de fecha fija y cupos**. El intervalo ocupado de una reserva es `[salida, salida + duracion_viaje_dias)`. Dos reglas, ambas comprobadas por SQLite:

- **Cupos:** cada salida (servicio + fecha) admite un máximo de reservas activas (`cupos` en `viajes.py`).
- **Cruce:** un mismo cliente no puede tener dos viajes activos que se solapen. Salir el día siguiente al regreso de otro viaje sí es válido.

Cancelar libera el cupo y el intervalo (la fila no se borra: el estado pasa a `cancelada`).

## 3. SQL que ejecuta cada operación (`almacen_sqlite.py`, tabla `reservas`)

| Operación | Método | Sentencias |
|---|---|---|
| Listar | `listar()` | `SELECT * FROM reservas ORDER BY rowid` |
| Consultar por código | `consultar(codigo)` | `SELECT * FROM reservas WHERE codigo=?` |
| Crear | `crear(registro, cupos)` | `BEGIN IMMEDIATE` → `SELECT COUNT(*) FROM reservas WHERE estado='activa' AND servicio=? AND fecha=?` (cupos) → `SELECT * FROM reservas WHERE estado='activa' AND cliente_clave=? AND fecha < date(?, '+'‖días‖' days') AND date(fecha, '+'‖duracion_viaje_dias‖' days') > ?` (cruce) → `INSERT INTO reservas ...` → `COMMIT` |
| Modificar | `modificar(codigo, registro, cupos)` | `BEGIN IMMEDIATE` → `SELECT` de la reserva → las mismas dos comprobaciones excluyendo `codigo<>?` → `UPDATE reservas SET cliente=?, servicio=?, fecha=?, precio_cop=?, duracion_viaje_dias=?, modificada_en=? WHERE codigo=?` → `COMMIT` (si falla algo: `ROLLBACK`) |
| Cancelar | `cancelar(codigo, ...)` | `BEGIN IMMEDIATE` → `SELECT` → `UPDATE reservas SET estado='cancelada', cancelada_en=? WHERE codigo=?` → `COMMIT` |
| Migrar JSON | `importar_json()` | una transacción con `SELECT` por código e `INSERT` por reserva nueva; si algo falla, `ROLLBACK` de todo |

## 4. ¿Por qué la comprobación y el guardado van en la misma transacción?

`BEGIN IMMEDIATE` bloquea la escritura en el archivo desde el principio. Entre contar los cupos, buscar el cruce e insertar, ninguna otra conexión puede escribir. Si comprobáramos y guardáramos por separado, dos personas podrían comprobar a la vez que queda un cupo, y las dos lo ocuparían (sobreventa); o dos solicitudes del mismo cliente podrían cruzarse. Si algo falla, `ROLLBACK` deja la reserva como estaba. Esto funciona incluso entre procesos distintos, algo que el `RLock` de `main.py` (solo dentro de un proceso) no garantiza.

## 5. Reiniciar el chat

Botón **Reiniciar conversación** (o escribir `reiniciar`): llama a `Chat.reiniciar()`, deja el historial solo con `system`, borra la solicitud pendiente y vacía la pantalla. No toca las reservas: están en `reservas.db`.

## 6. Migración

Al arrancar, si `reservas.db` está vacía y existe `reservas.json`, `main.py` importa el histórico (conserva los códigos; repetirlo no duplica). También se puede hacer a mano:

```powershell
python almacen_sqlite.py --migrar reservas.json --base reservas.db
```

`reservas.json` queda solo como copia de respaldo del origen: **ya no se lee ni se escribe en la operación normal**.

## 7. Pruebas realizadas

| Prueba (punto 11 del laboratorio) | Resultado |
|---|---|
| Consultar servicios y disponibilidad | OK (`probar_cruces.py`) |
| Solicitud en varios turnos y plan pendiente (Gradio con Groq simulado) | OK |
| Confirmar y comprobar la fila en SQLite | OK (`probar_sqlite.py` lee la fila con `sqlite3`) |
| Rechazo de un cruce de intervalos | OK: 409 y no queda fila |
| Salida justo al terminar el viaje anterior | OK: aceptada |
| Modificar a intervalo libre / ocupado (conserva los datos anteriores) | OK |
| Cancelar libera el cupo y el intervalo | OK |
| Descartar sin ejecutar no crea fila | OK |
| Reiniciar el chat: conversación nueva, reservas intactas | OK |
| Dos «procesos» compitiendo por el último cupo: solo uno gana | OK (4 hilos, 2 conexiones: 1 aceptada, 3 rechazadas) |
| Reiniciar la API: las reservas siguen en la base | OK (una instancia nueva de `AgendaSQLite` ve las mismas filas) |
| Migración: idempotente y con reversión si hay cruce o datos inválidos | OK |
| Ventana normal y privada en el navegador, con Gradio y Groq reales | **Pendiente: hacerlo en su equipo** |

Comandos: `python probar_sqlite.py` y `python probar_cruces.py` dentro de `Demos/Demostraciones_02_03` (usan bases temporales).
