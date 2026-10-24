# ViajesYa — chatbot de reservas de viajes

Chatbot en español para consultar viajes colombianos, ver salidas y cupos, y crear, consultar, modificar o cancelar reservas. La conversación se hace en una interfaz web (Gradio); las reglas del negocio las aplica una API (FastAPI) y las reservas se guardan en SQLite (`reservas.db`). El modelo de lenguaje (Groq) solo interpreta lo que escribe la persona y redacta las respuestas: nunca toca la base de datos ni confirma reservas por sí mismo.

**Integrantes:** Natalia Andrea Morales Navarrete, Miguel Angel Romero Osorio, Kevin Andres Parra
**Repositorio:** https://github.com/Rokev/Chatbot.git

---

## 1. Qué necesitas antes de empezar

| Requisito | Detalle |
|---|---|
| Sistema operativo | Windows (los archivos de arranque son `.bat`). |
| Python | **3.10 o superior**, instalado con la opción **Add python.exe to PATH** marcada. Para comprobarlo abre `cmd` y ejecuta `python --version`. |
| Conexión a internet | La primera vez, para instalar dependencias; siempre, para llamar a Groq. |
| Cuenta de Groq | Una **API key** (se crea en <https://console.groq.com/keys>) y el **ID de un modelo de chat** habilitado en tu cuenta. |

No necesitas instalar nada más a mano: los `.bat` crean el entorno virtual de la API e instalan las dependencias.

## 2. Instalación desde una copia nueva

1. Obtén el proyecto:
   - **Con Git:** `git clone <URL-del-repositorio>`
   - **Sin Git:** descarga el ZIP y extráelo completo (clic derecho → *Extraer todo*).
2. Entra a la carpeta **`Chatbot`**, la que contiene `iniciar_api.bat`, `iniciar_gradio.bat` y `app_gradio.py`. Todos los pasos siguientes se hacen desde ahí.

Estructura que debes ver en esa carpeta:

```
Chatbot\
├── iniciar_api.bat          ← arranca la API (ventana 1)
├── iniciar_gradio.bat       ← arranca la interfaz web (ventana 2)
├── iniciar_chatbot.bat      ← alternativa: chatbot por terminal, sin interfaz web
├── app_gradio.py            ← interfaz Gradio
├── chatbot_memoria.py       ← historial y solicitud pendiente
├── consulta_llm2.py         ← llamadas a Groq y a la API
├── requirements.txt         ← dependencias de Gradio
└── Demos\Demostraciones_02_03\
    ├── main.py              ← API FastAPI
    ├── almacen_sqlite.py    ← acceso a SQLite
    ├── viajes.py            ← salidas, fechas y cupos
    ├── negocio.json         ← catálogo, precios y reglas
    ├── reservas.db          ← base de datos SQLite
    ├── requirements.txt     ← dependencias de la API
    ├── ver_reservas.py      ← muestra las filas de reservas.db
    ├── probar_sqlite.py     ← prueba automática de SQLite
    └── probar_cruces.py     ← prueba automática de cruces de fechas
```

### Qué hace cada `.bat`

| Archivo | Qué hace | Cuándo usarlo |
|---|---|---|
| `iniciar_api.bat` | Entra a `Demos\Demostraciones_02_03`; **si no existe `.venv`**, lo crea e instala `requirements.txt` (`fastapi`, `uvicorn`, `httpx`, `tzdata`); luego inicia la API en `http://127.0.0.1:8011`. | Siempre primero. Déjalo abierto. |
| `iniciar_gradio.bat` | Si Gradio no está instalado, ejecuta `pip install "gradio>=6,<7"`; pide la API key y el modelo (si no están configurados); inicia la interfaz en `http://127.0.0.1:7860`. | Segundo, en otra ventana. |
| `iniciar_chatbot.bat` | Igual que el anterior, pero el chat se usa en la terminal (comandos `HISTORIAL`, `REINICIAR`, `SALIR`). | Opcional, en lugar de Gradio. |

> **Importante:** `iniciar_gradio.bat` instala Gradio en el Python que encuentre en el `PATH` (no en el `.venv` de la API). Si prefieres aislarlo, mira el apartado 7.

## 3. Configuración

El programa lee estas variables de entorno. **La clave real nunca debe escribirse en un archivo del repositorio ni en capturas de pantalla.**

| Variable | Obligatoria | Para qué sirve | Valor por defecto |
|---|---|---|---|
| `GROQ_API_KEY` | Sí | Clave de la API de Groq. | Si no está definida, el programa la pide por consola (la escritura queda oculta). |
| `GROQ_MODEL` | Sí | ID del modelo de chat de Groq, por ejemplo `llama-3.3-70b-versatile` (verifica que esté habilitado en tu cuenta). | Si no está definida, el programa lo pide. Si el ID no existe en tu cuenta, imprime la lista de modelos disponibles para que elijas uno. |
| `CHATBOT_API_URL` | No | Dirección de la API FastAPI. | `http://127.0.0.1:8011` |
| `GROQ_API_URL` | No | Dirección base de la API de Groq. | `https://api.groq.com/openai/v1` |
| `CHATBOT_DEBUG` | No | Con valor `1`, muestra el plan JSON y el historial en cada turno (modo terminal). | Desactivado |

Hay dos formas de configurar la clave y el modelo:

**Opción A — Que el `.bat` los pida (la más simple).** Haz doble clic en `iniciar_gradio.bat`. En la ventana negra escribe la API key (no se muestra mientras escribes) y pulsa Enter; luego escribe el ID del modelo y pulsa Enter.

**Opción B — Definirlas antes de ejecutar el `.bat`.** Abre una ventana de `cmd` en la carpeta `Chatbot` y ejecuta, **en esa misma ventana** (el doble clic no hereda estas variables):

```bat
set GROQ_API_KEY=pega_aqui_tu_clave
set GROQ_MODEL=id_del_modelo
iniciar_gradio.bat
```

En PowerShell sería:

```powershell
$env:GROQ_API_KEY = "pega_aqui_tu_clave"
$env:GROQ_MODEL   = "id_del_modelo"
.\iniciar_gradio.bat
```

Las variables solo viven mientras esa ventana esté abierta.

**Dirección de FastAPI:** `iniciar_api.bat` usa siempre `127.0.0.1:8011` y el chatbot apunta ahí por defecto, así que normalmente no tienes que tocar nada. Si cambias el puerto en `iniciar_api.bat`, define también `CHATBOT_API_URL` con el puerto nuevo antes de iniciar Gradio.

## 4. Datos y ejecución (dos ventanas)

### 4.1 Base de datos SQLite

- El proyecto ya incluye `Demos\Demostraciones_02_03\reservas.db` con reservas de prueba ficticias.
- Si `reservas.db` no existe, la API lo **crea sola** al arrancar y, si encuentra `reservas.json`, importa ese histórico (la importación no duplica datos).
- Para ver las reservas guardadas (desde `Demos\Demostraciones_02_03`, con la API ya instalada):

  ```bat
  .\.venv\Scripts\python.exe ver_reservas.py
  ```

  También acepta una consulta SQL: `.\.venv\Scripts\python.exe ver_reservas.py "SELECT * FROM reservas WHERE estado='activa'"`. Solo lee; no modifica nada.
- Para empezar con una base vacía: cierra la API, borra `reservas.db` y cambia el contenido de `reservas.json` por `[]` (si no, se volverán a importar las reservas antiguas).

### 4.2 Iniciar la API (ventana 1)

1. Haz doble clic en **`iniciar_api.bat`**.
2. La primera vez verás `Creando entorno virtual e instalando dependencias...` (tarda un par de minutos).
3. Cuando aparezca el mensaje `FastAPI de ViajesYa en http://127.0.0.1:8011/docs` y uvicorn indique que la aplicación arrancó, la API está lista. **Deja esta ventana abierta.**
4. Para detenerla: `Ctrl+C` en esa ventana.

La documentación interactiva de la API está en <http://127.0.0.1:8011/docs>.

### 4.3 Iniciar la interfaz Gradio (ventana 2)

1. Con la API ya abierta, haz doble clic en **`iniciar_gradio.bat`** (o ejecútalo desde `cmd`, como en la Opción B del apartado 3).
2. La primera vez instalará Gradio.
3. Introduce la API key y el modelo si te los pide.
4. Espera la línea `Usando el modelo: ...` y luego `Running on local URL: http://127.0.0.1:7860`.
5. Abre <http://127.0.0.1:7860> en el navegador.

Botones de la interfaz: **Enviar**, **Confirmar** y **Descartar** (se activan cuando hay una solicitud pendiente; también sirve escribir «sí» o «no») y **Reiniciar conversación** (limpia el historial; **no** borra las reservas guardadas). Cada pestaña del navegador tiene su propia conversación.

### 4.4 Direcciones de acceso

| Qué | Dirección |
|---|---|
| Interfaz de chat (Gradio) | <http://127.0.0.1:7860> |
| API FastAPI | <http://127.0.0.1:8011> |
| Documentación interactiva de la API | <http://127.0.0.1:8011/docs> |

### 4.5 Calendario de salidas y datos de prueba

Las salidas y sus cupos están definidos en `Demos\Demostraciones_02_03\viajes.py` (lista `VIAJES`). Solo se aceptan esas fechas. Cuando pasen, edita ese archivo y reinicia la API (cierra la ventana o `Ctrl+C` y vuelve a abrir `iniciar_api.bat`).

| Destino | Salidas configuradas | Cupos por salida |
|---|---|---|
| Santa Marta | 13-nov-2026 · 18-dic-2026 | 10 |
| Caño Cristales | 20-nov-2026 · 11-dic-2026 | 8 |
| Nuquí | 15-nov-2026 · 08-ene-2027 | 6 |
| Manizales | 14-nov-2026 · 05-dic-2026 | 12 |
| Amazonas | 04-dic-2026 · 15-ene-2027 | 8 |
| Capurganá | 12-dic-2026 · 22-ene-2027 | 6 · 1 |

Usa **nombres ficticios** para probar (por ejemplo, «Laura Prueba»). Cada destino exige una anticipación mínima de días hábiles (definida en `negocio.json`) y un mismo cliente no puede tener dos viajes activos que se solapen.

## 5. Comprobación inicial

### Prueba 1 — La API responde (sin Groq)

Con `iniciar_api.bat` abierto, abre <http://127.0.0.1:8011/viajes> en el navegador.
**Resultado esperado:** un JSON con la clave `viajes`, que contiene las salidas programadas; cada una incluye servicio, fecha, fecha de regreso, `cupos_totales` y `cupos_disponibles`. La página <http://127.0.0.1:8011/docs> debe cargar con la lista de endpoints (`/servicios`, `/viajes`, `/disponibilidad`, `/reservas`…).

### Prueba 2 — Pruebas automáticas (sin Groq)

Desde `cmd`, en la carpeta `Chatbot`:

```bat
cd Demos\Demostraciones_02_03
.\.venv\Scripts\python.exe probar_sqlite.py
.\.venv\Scripts\python.exe probar_cruces.py
```

**Resultado esperado:** cada script termina sin errores e imprime una línea que empieza por `OK:`:

```
OK: SQLite (transacción única, concurrencia, persistencia, migración, API)
OK: cruces de viaje por cliente (crear, modificar, disponibilidad, chat)
```

Usan bases temporales: no modifican `reservas.db`.

### Prueba 3 — Conversación real en Gradio (con Groq)

Con las dos ventanas abiertas y la página <http://127.0.0.1:7860> cargada, escribe en este orden:

1. `¿Qué salidas hay a Manizales?` → debe listar las fechas 14-nov-2026 y 5-dic-2026 con sus cupos disponibles.
2. `Quiero ir a Caño Cristales el 11 de diciembre` → el bot pide el dato que falta (tu nombre). Responde `Soy Laura Prueba`.
3. El bot muestra un **resumen pendiente** (destino, fecha, precio de $3.587.000 y 3 días) y pide confirmación. **Todavía no se guarda nada.**
4. Pulsa **Confirmar** (o escribe `sí`) → el bot responde con un **código de reserva** que empieza por `PN-`.
5. Comprueba que quedó guardada: ejecuta `ver_reservas.py` (apartado 4.1); debe aparecer la fila de «Laura Prueba» con estado `activa`.
6. Pulsa **Reiniciar conversación** y vuelve a ejecutar `ver_reservas.py`: la reserva sigue ahí.

El texto exacto de las respuestas puede variar porque lo redacta el modelo; lo que no varía es el resumen previo, la confirmación y el código.

### Errores frecuentes

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `'python' no se reconoce como un comando` | Python no está instalado o no está en el `PATH`. | Instala Python 3.10+ marcando *Add python.exe to PATH* y abre una ventana nueva. |
| `iniciar_api.bat` falla instalando dependencias | Sin internet o instalación interrumpida. | Borra la carpeta `Demos\Demostraciones_02_03\.venv` y vuelve a ejecutar `iniciar_api.bat`. |
| `Aviso: no pude leer /servicios de la FastAPI. ¿Está encendida iniciar_api.bat?` | La API no está abierta o usa otro puerto. | Abre `iniciar_api.bat` y espera a que arranque; revisa `CHATBOT_API_URL`. |
| El puerto 8011 o 7860 ya está en uso | Otra instancia sigue abierta. | Cierra la ventana anterior del `.bat` (o `Ctrl+C`) y vuelve a ejecutarlo. |
| `Necesito la API key y el ID del modelo.` / `Falta GROQ_API_KEY o GROQ_MODEL` | No se escribieron los datos. | Reinicia `iniciar_gradio.bat` y escríbelos, o defínelos como en la Opción B. |
| Error HTTP 401 desde Groq | API key incorrecta, vencida o con espacios. | Genera una clave nueva y vuelve a pegarla. |
| `El modelo '...' no está disponible para chat en tu cuenta` | ID mal escrito o modelo retirado. | Elige uno de la lista que imprime el programa. |
| Error 429 desde Groq | Límite de uso o de tokens alcanzado. | Espera unos minutos o usa otro modelo. |
| HTTP 422 de la API | Servicio o fecha no válidos, o falta la anticipación mínima. | Usa una fecha de la tabla del apartado 4.5. |
| HTTP 409 de la API | Sin cupos o cruce con otro viaje activo del mismo cliente. | Es una regla del negocio, no un fallo: elige otra salida u otro nombre. |
| HTTP 503 de la API | No se pudo usar `reservas.db`. | Cierra la API, comprueba que el archivo no esté abierto en otro programa y reinicia. |
| Salen caracteres raros (tildes) en la ventana | Fuente de la consola. | Los `.bat` ya usan `chcp 65001`; prueba con Windows Terminal. |

## 6. Cómo funciona un mensaje (resumen)

1. La persona escribe en Gradio (`app_gradio.py`).
2. `chatbot_memoria.py` guarda el historial y pide al modelo de Groq que interprete la intención.
3. Si hay que consultar o ejecutar algo, el código llama a la API FastAPI (`main.py`); Gradio nunca escribe en SQLite.
4. La API valida cupos, fechas y cruces, y guarda en `reservas.db` dentro de una transacción.
5. El chatbot comunica el resultado real. Crear, modificar o cancelar requieren confirmación explícita.

## 7. Opcional: aislar Gradio en un entorno virtual

Desde `cmd`, en la carpeta `Chatbot`:

```bat
python -m venv .venv
.venv\Scripts\activate.bat
iniciar_gradio.bat
```

Con el entorno activado, el `python` que usa `iniciar_gradio.bat` es el del entorno, así que Gradio se instala ahí. (También puedes instalarlo con `python -m pip install -r requirements.txt`). Debes repetir `.venv\Scripts\activate.bat` en cada ventana nueva. La carpeta `.venv` ya está en `.gitignore`.
