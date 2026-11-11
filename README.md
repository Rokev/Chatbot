# ViajesYa — chatbot de reservas de viajes

Chatbot en español para consultar viajes colombianos, ver salidas y cupos, y crear, consultar, modificar o cancelar reservas. La conversación se hace en una interfaz web (Gradio), en la terminal o en **Telegram**; las reglas del negocio las aplica una API (FastAPI) y las reservas se guardan en SQLite (`reservas.db`). El modelo de lenguaje (Groq) solo interpreta lo que escribe la persona y redacta las respuestas: nunca toca la base de datos ni confirma reservas por sí mismo.

**Integrantes:** Natalia Andrea Morales Navarrete, Miguel Angel Romero Osorio, Kevin Andres Parra
**Repositorio:** https://github.com/Rokev/Chatbot.git

---

## 1. Qué necesitas antes de empezar

| Requisito | Detalle |
|---|---|
| Sistema operativo | Windows (los archivos de arranque son `.bat`). |
| Python | **3.10 o superior**, instalado con la opción **Add python.exe to PATH** marcada. Para comprobarlo abre `cmd` y ejecuta `python --version`. |
| Conexión a internet | La primera vez, para instalar dependencias; siempre, para llamar a Groq. |
| Cuenta de Telegram (solo para el canal de Telegram) | Una cuenta para crear el bot con @BotFather y, para probar con dos personas, una segunda cuenta. |
| Cuenta de Groq | Una **API key** (se crea en <https://console.groq.com/keys>) y el **ID de un modelo de chat** habilitado en tu cuenta. |

No necesitas instalar nada más a mano: los `.bat` crean el entorno virtual de la API e instalan las dependencias. (Para Telegram, `iniciar_telegram.bat` instala `python-telegram-bot` 22.)

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
├── iniciar_telegram.bat     ← arranca el bot de Telegram (ventana 2, ver apartado 8)
├── bot_telegram.py          ← bot de Telegram (Clase 13)
├── bot_telegram_anterior.py ← versión anterior del bot (respaldo)
├── simular_respuesta_perdida.py ← práctica T24 (resultado incierto)
├── probar_telegram.py       ← pruebas automáticas del canal de Telegram
├── Matriz_25_Pruebas.md     ← matriz de 25 pruebas
├── BITACORA_clase13.md      ← bitácora de la Clase 13
├── app_gradio.py            ← interfaz Gradio
├── chatbot_memoria.py       ← historial y solicitud pendiente
├── consulta_llm2.py         ← llamadas a Groq y a la API
├── requirements.txt         ← dependencias de Gradio y Telegram
├── requirements_telegram.txt← dependencias del canal y de la API
└── Demos\Demostraciones_02_03\
    ├── main.py              ← API FastAPI (incluye las rutas /telegram)
    ├── api_telegram.py      ← rutas protegidas de Telegram y AgendaTelegram
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
| `iniciar_api.bat` | Entra a `Demos\Demostraciones_02_03`; **si no existe `.venv`**, lo crea e instala `requirements.txt` (`fastapi`, `uvicorn`, `httpx`, `tzdata`); luego inicia la API en `http://127.0.0.1:8011`. | Siempre primero. Déjalo abierto. **Desde la Clase 13 pide también la clave privada del canal de Telegram** (ver apartado 8); sin ella la API no inicia. |
| `iniciar_gradio.bat` | Si Gradio no está instalado, ejecuta `pip install "gradio>=6,<7"`; pide la API key y el modelo (si no están configurados); inicia la interfaz en `http://127.0.0.1:7860`. | Segundo, en otra ventana. |
| `iniciar_chatbot.bat` | Igual que el anterior, pero el chat se usa en la terminal (comandos `HISTORIAL`, `REINICIAR`, `SALIR`). | Opcional, en lugar de Gradio. |
| `iniciar_telegram.bat` | Instala `python-telegram-bot` 22 si hace falta; pide el token de BotFather, la clave privada de la API, la API key de Groq y el modelo; inicia el bot. | Para Telegram, en otra ventana y con la API abierta. |

> **Importante:** `iniciar_gradio.bat` instala Gradio en el Python que encuentre en el `PATH` (no en el `.venv` de la API). Si prefieres aislarlo, mira el apartado 7.

## 3. Configuración

El programa lee estas variables de entorno. **La clave real nunca debe escribirse en un archivo del repositorio ni en capturas de pantalla.**

| Variable | Obligatoria | Para qué sirve | Valor por defecto |
|---|---|---|---|
| `GROQ_API_KEY` | Sí | Clave de la API de Groq. | Si no está definida, el programa la pide por consola (la escritura queda oculta). |
| `GROQ_MODEL` | Sí | ID del modelo de chat de Groq, por ejemplo `llama-3.3-70b-versatile` (verifica que esté habilitado en tu cuenta). | Si no está definida, el programa lo pide. Si el ID no existe en tu cuenta, imprime la lista de modelos disponibles para que elijas uno. |
| `CHATBOT_API_KEY` | Sí, para Telegram | Clave privada compartida entre la API y el bot de Telegram (mínimo 16 caracteres ASCII, sin tildes). **Debe ser idéntica en ambos procesos.** Sin ella la API no inicia. | `iniciar_api.bat` y el bot la piden por consola (oculta). |
| `TELEGRAM_BOT_TOKEN` | Solo Telegram | Token que entrega @BotFather. | Si no está definida, el bot lo pide por consola (oculto). |
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
   Si `CHATBOT_API_KEY` no está definida, el `.bat` pide la **clave privada** (no se muestra al escribirla). Para usar solo Gradio puedes inventar una cualquiera de 16 o más caracteres; para Telegram anótala, porque el bot debe usar la misma.
3. Cuando aparezca el mensaje `FastAPI de ViajesYa en http://127.0.0.1:8011/docs` y uvicorn indique que la aplicación arrancó, la API está lista. **Deja esta ventana abierta.**
4. Para detenerla: `Ctrl+C` en esa ventana.

La documentación interactiva de la API está en <http://127.0.0.1:8011/docs>. Las rutas `/telegram/...` aparecen ahí y exigen la clave privada.

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

> Las fechas de arriba pueden haber pasado o cerrado ya (cada destino exige anticipación mínima). Edita `viajes.py` si hace falta. `Capurganá` del 22-ene-2027 solo tiene 1 cupo y puede estar ocupado en tu `reservas.db`.

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

Para el canal de Telegram hay una tercera prueba automática (no necesita Telegram ni Groq; usa API real, base temporal y Telegram simulado). Desde la carpeta `Chatbot`, con `python-telegram-bot`, `fastapi` y `uvicorn` instalados:

```bat
python probar_telegram.py
```

Termina con `23 de 23 grupos de pruebas correctos.` y tampoco toca `reservas.db`.

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
| La API no inicia y menciona `CHATBOT_API_KEY` | Falta la clave privada o tiene menos de 16 caracteres ASCII. | Escríbela cuando `iniciar_api.bat` la pida (sin tildes ni ñ). |
| El bot de Telegram responde «no autorizado» (HTTP 401) | La clave del bot no coincide con la de la API. | Reinicia el bot con la misma clave que usaste en `iniciar_api.bat`. |
| Telegram: `Token inválido` | Token mal copiado o revocado. | Copia de nuevo el token de @BotFather. |
| Telegram: el bot no responde o los botones no hacen nada | Hay dos procesos con el mismo token. | Deja un solo `iniciar_telegram.bat` abierto y reinícialo. |
| Telegram: «Reserva no disponible para este usuario» | Código incorrecto o la reserva no se creó desde esa cuenta de Telegram. | Crea la reserva desde esa misma cuenta. |
| Salen caracteres raros (tildes) en la ventana | Fuente de la consola. | Los `.bat` ya usan `chcp 65001`; prueba con Windows Terminal. |

## 6. Cómo funciona un mensaje (resumen)

1. La persona escribe en Gradio (`app_gradio.py`).
2. `chatbot_memoria.py` guarda el historial y pide al modelo de Groq que interprete la intención.
3. Si hay que consultar o ejecutar algo, el código llama a la API FastAPI (`main.py`); Gradio nunca escribe en SQLite.
4. La API valida cupos, fechas y cruces, y guarda en `reservas.db` dentro de una transacción.
5. El chatbot comunica el resultado real. Crear, modificar o cancelar requieren confirmación explícita.

Por Telegram el flujo es el mismo con una diferencia: el bot (`bot_telegram.py`) arma una propuesta con una **referencia de solicitud** y botones; al pulsar **Confirmar** llama a las rutas `/telegram` de la API, que comprueban propiedad de la reserva, cupos, cruces y estado actual antes de escribir. Detalle en `BITACORA_clase13.md`.

## 7. Opcional: aislar Gradio en un entorno virtual

Desde `cmd`, en la carpeta `Chatbot`:

```bat
python -m venv .venv
.venv\Scripts\activate.bat
iniciar_gradio.bat
```

Con el entorno activado, el `python` que usa `iniciar_gradio.bat` es el del entorno, así que Gradio se instala ahí. (También puedes instalarlo con `python -m pip install -r requirements.txt`). Debes repetir `.venv\Scripts\activate.bat` en cada ventana nueva. La carpeta `.venv` ya está en `.gitignore`.

## 8. Canal de Telegram (Clase 13)

Con esta integración el bot de Telegram **solo prepara propuestas**: nada se registra sin que la persona pulse Confirmar, y cada persona solo ve y modifica las reservas que creó desde su cuenta.

```
Persona (Telegram) -> bot_telegram.py -> Groq (interpreta)
                           |
                           +-> FastAPI /telegram/... -> SQLite (reservas.db)
                               (X-API-Key + X-Telegram-User)
```

### 8.1 Crear el bot en @BotFather

1. En Telegram busca **@BotFather** (el verificado) y escribe `/newbot`.
2. Escribe un nombre para mostrar (por ejemplo `ViajesYa Asistente`).
3. Escribe un usuario único que termine en `bot` (por ejemplo `viajesya_equipo_bot`).
4. Copia el **token** que te entrega (parece `123456789:AA...`) y guárdalo en privado.
5. Desde cada cuenta de prueba abre `t.me/<usuario_del_bot>` y pulsa **Iniciar**.

> El token da control total del bot. No lo pegues en archivos del proyecto, capturas ni Git. Si se filtra, usa `/revoke` en BotFather.

### 8.2 La clave privada

Es una contraseña compartida entre el bot y la API: la API solo atiende las rutas `/telegram` si la petición trae esa clave, así nadie más puede hacerse pasar por tu bot. Mínimo **16 caracteres ASCII** (sin tildes ni ñ), por ejemplo `Viajes#2026-clave-privada`. No es el token de BotFather ni la clave de Groq. Debe ser **idéntica** al iniciar la API y al iniciar el bot.

### 8.3 Arrancar (dos ventanas)

1. **Ventana 1:** doble clic en `iniciar_api.bat` y escribe la clave privada cuando la pida. Comprueba en <http://127.0.0.1:8011/docs> que aparecen las rutas `/telegram`. Déjala abierta.
2. **Ventana 2:** doble clic en `iniciar_telegram.bat` y escribe, sin que se vean: el token de BotFather, **la misma clave privada** y la API key de Groq; luego el ID del modelo.
3. Cuando diga `Bot en ejecución`, abre el bot en Telegram y escribe `/start`.
4. Para detener cada ventana: `Ctrl+C`. Mantén **un solo** proceso del bot por token.

Alternativa por PowerShell, en dos terminales:

```powershell
# Terminal 1 (desde Chatbot\Demos\Demostraciones_02_03)
$c = Read-Host "Clave privada de la API" -AsSecureString
$env:CHATBOT_API_KEY = [System.Net.NetworkCredential]::new('', $c).Password
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8011 --workers 1

# Terminal 2 (desde Chatbot)
python -m pip install -r requirements.txt      # primera vez
$env:CHATBOT_API_URL = "http://127.0.0.1:8011"
$env:GROQ_MODEL = "ID_DEL_MODELO"
$env:CHATBOT_API_KEY = "<la misma clave privada>"
$t = Read-Host "Token de BotFather" -AsSecureString
$env:TELEGRAM_BOT_TOKEN = [System.Net.NetworkCredential]::new('', $t).Password
$g = Read-Host "API key de Groq" -AsSecureString
$env:GROQ_API_KEY = [System.Net.NetworkCredential]::new('', $g).Password
python bot_telegram.py
```

Tras cambiar una variable de entorno, detén el proceso y vuelve a iniciarlo desde esa terminal.

### 8.4 Cómo usar el bot

Escribe natural: «¿Qué salidas hay a Manizales?», «¿Cuánto cuesta la Macarena?», «Soy Laura, quiero la Macarena el 2026-12-11». Antes de registrar, modificar o cancelar, el bot muestra un resumen con **Referencia de solicitud** y los botones **Confirmar** / **Descartar**. Cada viaje tiene fecha fija y cupos limitados; no existe la hora.

| Comando | Qué hace |
|---|---|
| `/start`, `/help` | Bienvenida y ayuda |
| `/reserva CODIGO` | Consulta una reserva **propia** |
| `/descartar` | Retira la propuesta vigente |
| `/estado [REFERENCIA]` | Recupera el resultado de una operación (también tras reiniciar el bot) |
| `/reintentar` | Reenvía una operación incierta con el mismo identificador |
| `/reset` | Reinicia la conversación; las reservas se conservan |

El **código de reserva** (`PN-...`) identifica la reserva; la **referencia de solicitud** identifica la operación. Las propuestas vencen a los 10 minutos.

### 8.5 Pruebas manuales con dos cuentas

Sigue `Matriz_25_Pruebas.md` con dos cuentas (por ejemplo Laura y Andrés) y llena los resultados con evidencia. Para T24 (respuesta perdida): detén el bot normal y, con la API encendida y la misma configuración, ejecuta `python simular_respuesta_perdida.py`; al terminar, vuelve a `iniciar_telegram.bat`.

### 8.6 Límites y seguridad

- Las reservas creadas antes de la Clase 13 (Gradio, terminal, Flowise) **no tienen propietario de Telegram**: desde Telegram no se pueden consultar, modificar ni cancelar. Crea los datos de prueba desde las cuentas de Telegram que vas a usar.
- Las rutas anteriores (`/reservas`, `/chat`...) siguen **sin autenticación**: la API es solo local. No la publiques en Internet sin protegerlas.
- El historial y las propuestas del bot viven en memoria; al reiniciar Python se pierden, pero las reservas y los recibos permanecen en `reservas.db`.
- Nunca subas tokens ni claves al repositorio ni a las capturas.