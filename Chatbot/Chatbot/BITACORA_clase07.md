# Bitácora · Clase 07 · Conversación con historial (ViajesYa)

**Archivo nuevo:** `chatbot_memoria.py` (junto a `consulta_llm2.py`).
**Evidencia automática:** `evidencia_clase07.txt` (la genera el propio programa; no contiene la API key).

## 1. Qué hace cada función

| Pregunta de la guía | Respuesta |
|---|---|
| ¿Qué función consulta Groq? | `consultar_groq()` en `chatbot_memoria.py`. Envía a `/chat/completions` la lista completa `messages` (system + turnos anteriores + pregunta actual). `turno()` la usa y arma el historial nuevo. |
| ¿Cuál llama a FastAPI? | `ejecutar()` de `consulta_llm2.py` (importada como `base.ejecutar`). Llama a `/servicios`, `/disponibilidad`, `/reservas` (POST, PUT, DELETE) en el puerto 8011. Groq nunca toca la API. |
| ¿Dónde vive la memoria? | En la lista de Python `historial`. Se crea con `nuevo_historial()` (solo `system`) y cada turno exitoso agrega un mensaje `user` y uno `assistant`. |

## 2. Por qué reiniciar el chat no borra las reservas

`REINICIAR` solo crea otra lista con el mensaje `system` (`historial = nuevo_historial()`).
Las reservas no están en esa lista: las guarda la FastAPI en `reservas.json`.
Son dos cosas separadas: el historial ayuda al modelo a interpretar lo que la persona quiere;
las reservas son datos del negocio. Reiniciar borra lo primero y conserva lo segundo.

## 3. Reglas implementadas (según la guía)

- **Orden de `messages`:** system → turnos anteriores → pregunta actual.
- **Turno fallido no se guarda:** `turno()` arma `candidatos` y solo devuelve el historial nuevo si Groq respondió bien. Si falla, el historial queda igual.
- **Confirmación con historial a la vista:** antes de crear, modificar o cancelar, el programa imprime el historial y pide `s/n`.
- **Resultado de la operación:** después de confirmar o descartar se agrega una nota `[Sistema] ...` al historial para que el modelo sepa que esa solicitud ya se cerró.
- **Límite de tamaño:** se conservan el `system` y los últimos 20 mensajes (`MAX_MENSAJES`).

## 4. Cómo ejecutarlo

```powershell
# Terminal 1 (FastAPI encendida)
python -m uvicorn main:app --host 127.0.0.1 --port 8011 --workers 1

# Terminal 2 (carpeta donde está consulta_llm2.py)
$env:GROQ_API_KEY = "tu_clave"
$env:GROQ_MODEL   = "id_del_modelo"
python chatbot_memoria.py
```

## 5. Evidencia de la prueba en dos turnos

Completar con tus capturas o con el contenido de `evidencia_clase07.txt`:

| Paso | Qué escribir | Qué debe verse |
|---|---|---|
| Turno 1 (dato pendiente) | `Quiero reservar un viaje a Manizales` | `Necesito: cliente, fecha` |
| Turno 2 (lo completa) | `Me llamo Laura, para el 2026-12-10` | Resumen con cliente, servicio y fecha; historial de 5 mensajes |
| Confirmación | `s` | Código `PN-...` devuelto por la FastAPI y registro en `reservas.json` |
| Historial | `HISTORIAL` | Lista con system, user, assistant... en orden |
| Reinicio | `REINICIAR` y luego `HISTORIAL` | Un solo mensaje `system`; la reserva sigue en `reservas.json` |
| Sin memoria | Después de reiniciar: `Confirma mi nombre` | El modelo ya no conoce «Laura» |

## 6. Observaciones

Se creó la clase viajes.py para tener fechas fijas y cupos por viaje. Adicionalmente se probaron las funcionalidades de la API en docs y las pruebas del chatbot estan funcionando sin embargo nos estamos quedando sin tokens
