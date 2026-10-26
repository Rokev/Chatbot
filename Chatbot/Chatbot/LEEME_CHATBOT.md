# Demos + chatbot con memoria (Clase 07) + interfaz Gradio (Clase 08)

1. Doble clic en `iniciar_api.bat` (la primera vez crea el entorno e instala dependencias). Déjala abierta.
2. Doble clic en `iniciar_chatbot.bat`. Escribe tu API key de Groq (no se muestra) y el ID del modelo.
   Si el modelo no existe en tu cuenta, el programa lista los disponibles.
3. Habla como con una persona, sin nombres exactos. Por ejemplo:
   - `hola, quiero ir a la macarena`  -> el bot entiende "Viaje a Caño Cristales" y te pregunta lo que falta
   - `soy Laura, la salida de noviembre` -> te resume la reserva y pregunta si confirmas
   - `sí` / `dale` -> se registra (la confirmación la decide Python, no el modelo)
   Cada viaje tiene fecha fija y cupos limitados: pregunta `¿qué salidas hay a Manizales?` o `¿quedan cupos?`.
4. Comandos: `HISTORIAL`, `REINICIAR`, `SALIR`. Con `CHATBOT_DEBUG=1` se muestra el plan JSON y el historial en cada turno.

Archivos: `chatbot_memoria.py` (nuevo), `consulta_llm2.py` (Groq + FastAPI),
`Demos/Demostraciones_02_03/` (FastAPI, negocio.json, reservas.db), `BITACORA_clase07.md`.
La API key nunca se guarda en archivos. Se genera `evidencia_clase07.txt` al usar el chat.

Viajes (fecha fija y cupos): se editan en `Demos/Demostraciones_02_03/viajes.py` (lista `VIAJES`).
Prueba de la API: `python probar_viajes.py` dentro de `Demos/Demostraciones_02_03` (con el entorno de la API activo).

## Interfaz web con Gradio (Clase 08)

1. Deja `iniciar_api.bat` abierto (FastAPI en el puerto 8011).
2. Doble clic en `iniciar_gradio.bat` (la primera vez instala `gradio`). Escribe la API key de Groq (no se muestra) y el ID del modelo.
3. Abre http://127.0.0.1:7860. Botones: **Enviar**, **Confirmar** y **Descartar** (se activan cuando hay una solicitud por confirmar; también sirve escribir "sí" / "no") y **Reiniciar conversación**.
4. **Reiniciar** deja la conversación como nueva (historial solo con el mensaje `system`, sin solicitud pendiente, pantalla vacía). Las reservas guardadas por la API no se tocan. También funciona escribiendo `reiniciar` en la caja de texto. En la terminal sigue existiendo el comando `REINICIAR`.
5. Cada pestaña del navegador tiene su propia conversación (`Sesion` en `app_gradio.py`): dos personas no mezclan datos.

Archivos nuevos: `app_gradio.py`, `iniciar_gradio.bat`, `requirements.txt`, `BITACORA_clase08.md`, `Demos/Demostraciones_02_03/probar_cruces.py`, `almacen_sqlite.py`, `probar_sqlite.py`.

**Regla nueva (intervalos):** cada viaje ocupa de su fecha de salida hasta su regreso (`duracion_viaje_dias`). Una misma persona no puede tener dos reservas activas cuyos viajes se solapen (la API responde 409; el chatbot lo avisa antes de pedir confirmación). Salir el día siguiente al regreso de otro viaje sí se permite. Prueba: `python probar_cruces.py` dentro de `Demos/Demostraciones_02_03`.

**Almacenamiento SQLite:** las reservas se guardan en `Demos/Demostraciones_02_03/reservas.db` (`almacen_sqlite.py`). Cupos y cruces se comprueban y guardan en una sola transacción. La primera vez que arranca la API importa `reservas.json` (histórico) a la base; después `reservas.json` ya no se usa. Pruebas: `python probar_sqlite.py`. Para ver las filas (Python 3.12+), desde esa carpeta:

```powershell
python -m sqlite3 reservas.db "SELECT codigo, cliente, servicio, fecha, estado FROM reservas;"
```


## Canal de Telegram

1. Crea el bot con @BotFather en Telegram y guarda el token (no lo pegues en archivos ni lo subas a Git).
2. Deja `iniciar_api.bat` abierto (FastAPI en el puerto 8011).
3. Doble clic en `iniciar_telegram.bat` (la primera vez instala `python-telegram-bot`). Pide, ocultos, el token de BotFather y la API key de Groq, y luego el ID del modelo. También sirven las variables `TELEGRAM_BOT_TOKEN`, `GROQ_API_KEY` y `GROQ_MODEL`.
4. Abre tu bot en Telegram y escribe `/start`. Comandos: `/start`, `/help`, `/reset`.
5. Reutiliza `Chat` de `chatbot_memoria.py`, igual que la terminal y Gradio. Cada chat de Telegram tiene su propio historial. Cuando hay una solicitud por confirmar aparecen los botones **Confirmar** / **Descartar** (también sirve escribir "sí" / "no"). `/reset` reinicia la conversación y no toca las reservas.
6. Solo atiende chats privados. Los errores técnicos se muestran en la consola, no en Telegram.

Archivos nuevos: `bot_telegram.py`, `iniciar_telegram.bat`.