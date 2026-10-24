"""Lógica del chatbot: Groq interpreta y la FastAPI ejecuta.

En esta clase se usa desde la terminal. Más adelante Gradio podrá llamar
interpretar() y ejecutar() sin cambiar la lógica del negocio.
Endpoints de la FastAPI de ViajesYa (Demos/Demostraciones_02_03/main.py):
    GET    /servicios
    GET    /viajes?servicio=...       salidas programadas (fecha fija) con sus cupos
    GET    /disponibilidad?fecha=AAAA-MM-DD&servicio=...&cliente=...   (cliente es opcional: avisa si sus viajes se cruzan)
    POST   /reservas                  {cliente, servicio, fecha, confirmado: true}
    PUT    /reservas/{codigo}         {cliente?, servicio?, fecha?, confirmado: true}
    DELETE /reservas/{codigo}?confirmado=true
Cada reserva ocupa un cupo de un Viaje (servicio + fecha de salida fija). No hay hora.
Un mismo cliente no puede tener dos viajes activos cuyas fechas se solapen (la API responde 409).
"""

import json
import os
from getpass import getpass
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

API_BASE = os.getenv("CHATBOT_API_URL", "http://127.0.0.1:8011").rstrip("/")
RUTAS = {
    "servicios": "/servicios",
    "viajes": "/viajes",
    "disponibilidad": "/disponibilidad",
    "reservas": "/reservas",
}
GROQ_BASE = os.getenv("GROQ_API_URL", "https://api.groq.com/openai/v1").rstrip("/")
GROQ_URL = GROQ_BASE + "/chat/completions"
GROQ_MODELOS_URL = GROQ_BASE + "/models"
# Modelos que existen en Groq pero NO sirven para /chat/completions (voz, moderación...).
NO_CHAT = ("whisper", "tts", "guard", "playai", "orpheus")
# User-Agent propio: el "Python-urllib" por defecto a veces es bloqueado por el proxy de Groq.
ENCABEZADOS_BASE = {"User-Agent": "chatbot-viajesya/1.0", "Accept": "application/json"}
ACCIONES = {"servicios", "viajes", "disponibilidad", "consultar", "crear", "modificar", "cancelar", "conversar", "fuera_de_alcance"}
CAMPOS = ("accion", "cliente", "servicio", "fecha", "codigo")
# En "modificar" el PUT solo exige el código; además debe venir al menos un dato nuevo.
CAMPOS_MODIFICABLES = ("cliente", "servicio", "fecha")
REQUERIDOS = {
    "disponibilidad": ("servicio", "fecha"),
    "consultar": ("codigo",),
    "crear": ("cliente", "servicio", "fecha"),
    "modificar": ("codigo",),
    "cancelar": ("codigo",),
}
INSTRUCCIONES = """
Identifica qué quiere hacer la persona con el negocio. Devuelve únicamente
un objeto JSON con estas claves: accion, cliente, servicio, fecha, codigo.
Las acciones posibles son:
- servicios: quiere ver el catálogo de destinos.
- viajes: pregunta por salidas, fechas o cupos de un destino (servicio opcional).
- disponibilidad: pregunta si hay cupo en una salida concreta (servicio y fecha).
- consultar: quiere ver los datos o el estado de una reserva que ya existe (codigo PN-...). Solo lectura.
- crear / modificar / cancelar: gestionar una reserva.
- conversar: saludos, gracias, charla, o preguntas sobre precios, duración, horarios o la agencia.
- fuera_de_alcance: nada que ver con viajes de la agencia.
Usa fecha AAAA-MM-DD. Cada viaje tiene fecha de salida fija y cupos limitados; no existe la hora.
La persona habla de forma natural: NO tiene que escribir el nombre exacto. Entiende sinónimos,
nombres parciales, tildes o errores de ortografía y mapea siempre al identificador exacto del catálogo.
En modificar, "servicio" y "fecha" son los valores NUEVOS que la persona quiere.
Si un dato no aparece en la conversación, usa una cadena vacía; no lo inventes.
No digas que hiciste una reserva: solo identifica la intención.
"""


def peticion_json(url, metodo="GET", datos=None, headers=None):
    cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8") if datos is not None else None
    encabezados = dict(ENCABEZADOS_BASE)
    if cuerpo is not None:
        encabezados["Content-Type"] = "application/json"
    encabezados.update(headers or {})
    solicitud = Request(url, data=cuerpo, headers=encabezados, method=metodo)
    with urlopen(solicitud, timeout=30) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


def origen_http(error):
    """Indica quién devolvió el error: Groq o la FastAPI local."""
    return "Groq" if str(getattr(error, "url", "")).startswith(GROQ_BASE) else "FastAPI"


def detalle_http(error):
    """Mensaje real del error. FastAPI usa {"detail": ...}; Groq usa {"error": {"message": ...}}."""
    sin_detalle = "El servidor no envió ningún detalle."
    try:
        crudo = error.read().decode("utf-8", errors="replace").strip()
    except (AttributeError, OSError):
        return sin_detalle
    try:
        cuerpo = json.loads(crudo)
    except ValueError:
        return crudo[:300] or sin_detalle
    if not isinstance(cuerpo, dict):
        return crudo[:300] or sin_detalle
    detalle = cuerpo.get("detail")
    if detalle is None and "error" in cuerpo:  # formato de Groq / OpenAI
        err = cuerpo["error"]
        if isinstance(err, dict):
            detalle = err.get("message") or err.get("code")
            if err.get("code") and err.get("code") not in str(detalle):
                detalle = f"{detalle} [{err['code']}]"
        else:
            detalle = err
    if isinstance(detalle, list):  # errores de validación de FastAPI/Pydantic
        detalle = "; ".join(
            f"{'.'.join(map(str, e.get('loc', [])[1:]))}: {e.get('msg')}" if isinstance(e, dict) else str(e)
            for e in detalle
        )
    return str(detalle or crudo[:300] or sin_detalle)


def obtener_servicios(api_base=API_BASE):
    """Identificadores exactos de servicio (claves de negocio.json) que acepta la API."""
    try:
        catalogo = peticion_json(api_base.rstrip("/") + RUTAS["servicios"])
        return list(catalogo["servicios"])
    except (URLError, HTTPError, TimeoutError, ValueError, KeyError, TypeError):
        return []


def obtener_catalogo(api_base=API_BASE):
    """Catálogo completo de negocio.json (nombre, horarios, servicios con precio/duración/alias)."""
    try:
        return peticion_json(api_base.rstrip("/") + RUTAS["servicios"])
    except (URLError, HTTPError, TimeoutError, ValueError, TypeError):
        return {}


def obtener_viajes(servicio="", api_base=API_BASE):
    """Salidas programadas con cupos en vivo. Lista vacía si la API no responde."""
    url = api_base.rstrip("/") + RUTAS["viajes"]
    if servicio:
        url += "?" + urlencode({"servicio": servicio})
    try:
        return peticion_json(url)["viajes"]
    except (URLError, HTTPError, TimeoutError, ValueError, KeyError, TypeError):
        return []


def listar_modelos(clave):
    """IDs de modelos que la cuenta puede usar (Groq: GET /models). Un modelo retirado NO aparece aquí."""
    datos = peticion_json(GROQ_MODELOS_URL, headers={"Authorization": f"Bearer {clave}"})
    return sorted(m["id"] for m in datos.get("data", []) if isinstance(m, dict) and m.get("id"))


def es_modelo_chat(modelo):
    return not any(marca in modelo.lower() for marca in NO_CHAT)


def extraer_json(texto):
    """Toma el objeto JSON aunque el modelo lo envuelva en ```json ... ``` o agregue texto."""
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fin <= inicio:
        raise ValueError("La respuesta del modelo no contiene un objeto JSON")
    return json.loads(texto[inicio:fin + 1])


def instrucciones(servicios=()):
    if not servicios:
        return INSTRUCCIONES
    return INSTRUCCIONES + (
        "El campo servicio debe ser exactamente uno de estos identificadores, sin modificarlos: "
        + ", ".join(servicios) + ". Si la persona nombra el destino de otra forma, "
        "asócialo al identificador correcto; si no puedes, usa una cadena vacía.\n"
    )


def formato_pesos(valor):
    return "$" + f"{int(valor):,}".replace(",", ".") + " COP"


DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def contexto_negocio(catalogo, viajes):
    """Texto con TODO lo que el modelo necesita saber: destinos, precios, horarios, salidas y cupos reales."""
    if not catalogo:
        return "No pude leer el catálogo de la FastAPI: no inventes datos del negocio.\n"
    lineas = [f"Agencia: {catalogo.get('nombre', 'ViajesYa')}. Dirección: {str(catalogo.get('ubicacion', '')).strip()}."]
    horarios = catalogo.get("horarios", {})
    if horarios:
        lineas.append("Atención en la agencia: " + "; ".join(
            f"{DIAS[int(d)]} {h[0]}-{h[1]}" for d, h in sorted(horarios.items(), key=lambda x: int(x[0]))) + ".")
    lineas.append("Condiciones: " + str(catalogo.get("condiciones", "")).strip())
    lineas.append("\nDestinos (id para el campo servicio | nombre comercial | también se le dice | precio | duración):")
    for clave, info in catalogo.get("servicios", {}).items():
        alias = ", ".join(info.get("alias", [])) or "-"
        lineas.append(f"- {clave} | {info['nombre']} | {alias} | {formato_pesos(info['precio_cop'])} | {info['duracion_viaje_dias']} días")
    lineas.append("\nSalidas programadas (fecha fija; cupos libres de totales):")
    if not viajes:
        lineas.append("- (no hay salidas disponibles o no pude consultarlas)")
    for v in viajes:
        estado = "" if v["reservas_abiertas"] else f" [reservas cerradas desde {v['cierre_reservas']}]"
        if v["cupos_disponibles"] == 0:
            estado += " [LLENO]"
        lineas.append(f"- {v['servicio']}: sale {v['fecha']}, regresa {v.get('fecha_regreso', v['fecha'])} "
                      f"({v['cupos_disponibles']} de {v['cupos_totales']} cupos){estado}")
    return "\n".join(lineas) + "\n"


def validar_plan(plan, api_base=API_BASE):
    """Antes de pedir confirmación: normaliza el servicio con la API y revisa fecha y cupos.

    Devuelve None si todo está bien, o un resultado {"tipo": "no_disponible", ...} con el motivo real.
    Modifica plan["servicio"] para dejarlo con el identificador oficial.
    """
    if plan["accion"] not in {"crear", "modificar", "disponibilidad"} or not plan.get("servicio"):
        return None
    try:
        url = api_base.rstrip("/") + RUTAS["viajes"] + "?" + urlencode({"servicio": plan["servicio"]})
        salidas = peticion_json(url)["viajes"]
    except HTTPError as error:
        if error.code == 422:
            return {"tipo": "no_disponible", "mensaje": detalle_http(error), "plan": plan}
        raise
    if salidas:
        plan["servicio"] = salidas[0]["servicio"]
    fecha = plan.get("fecha")
    if not fecha:
        return None
    con_cupo = ", ".join(f"{v['fecha']} ({v['cupos_disponibles']} cupos)" for v in salidas
                         if v["reservas_abiertas"] and v["cupos_disponibles"] > 0) or "ninguna por ahora"
    salida = next((v for v in salidas if v["fecha"] == fecha), None)
    motivo = None
    if salida is None:
        motivo = f"No hay un viaje a {plan['servicio']} el {fecha}."
    elif not salida["reservas_abiertas"]:
        motivo = f"Las reservas de la salida del {fecha} cerraron el {salida['cierre_reservas']}."
    elif salida["cupos_disponibles"] <= 0:
        motivo = f"La salida del {fecha} a {plan['servicio']} está llena."
    if motivo:
        return {"tipo": "no_disponible", "plan": plan, "mensaje": f"{motivo} Salidas con cupo: {con_cupo}."}
    if plan["accion"] == "crear" and plan.get("cliente"):
        # Un cliente no puede estar en dos viajes a la vez: se avisa antes de pedir la confirmación.
        parametros = urlencode({"fecha": fecha, "servicio": plan["servicio"], "cliente": plan["cliente"]})
        try:
            cruce = peticion_json(api_base.rstrip("/") + RUTAS["disponibilidad"] + "?" + parametros).get("cruce_con")
        except HTTPError as error:
            if error.code == 422:
                return {"tipo": "no_disponible", "mensaje": detalle_http(error), "plan": plan}
            raise
        if cruce:
            return {"tipo": "no_disponible", "plan": plan,
                    "mensaje": f"{plan['cliente']} ya tiene la reserva {cruce['codigo']} a {cruce['servicio']} "
                               f"del {cruce['fecha']} al {cruce['fecha_regreso']}: dos viajes no pueden cruzarse. "
                               f"Salidas con cupo: {con_cupo}."}
    return None


def interpretar(pregunta, clave, modelo, servicios=()):
    payload = {
        "model": modelo,
        "messages": [
            {"role": "system", "content": instrucciones(servicios)},
            {"role": "user", "content": pregunta},
        ],
        "temperature": 0,
        "stream": False,
    }
    respuesta = peticion_json(
        GROQ_URL, "POST", payload,
        {"Authorization": f"Bearer {clave}"},
    )
    texto = respuesta["choices"][0]["message"]["content"]
    plan = extraer_json(texto)
    if not isinstance(plan, dict) or plan.get("accion") not in ACCIONES:
        raise ValueError("Groq no devolvió una acción válida")
    return {campo: str(plan.get(campo) or "").strip() for campo in CAMPOS}


def ejecutar(plan, confirmar=False, api_base=API_BASE):
    accion = plan["accion"]
    if accion not in ACCIONES:
        raise ValueError("Acción no permitida")
    if accion == "fuera_de_alcance":
        return {"tipo": "mensaje", "mensaje": "Puedo ayudar con destinos, salidas, cupos y reservas."}
    if accion == "conversar":
        return {"tipo": "mensaje", "mensaje": ""}

    rechazo = validar_plan(plan, api_base)  # primero: así el servicio queda con su id oficial y se avisa pronto si algo no se puede
    if rechazo:
        return rechazo
    faltan = [campo for campo in REQUERIDOS.get(accion, ()) if not plan.get(campo)]
    if faltan:
        return {"tipo": "faltan_datos", "mensaje": "Necesito: " + ", ".join(faltan), "plan": plan, "faltan": faltan}
    cambios = {campo: plan[campo] for campo in CAMPOS_MODIFICABLES if plan.get(campo)}
    if accion == "modificar" and not cambios:
        return {"tipo": "faltan_datos", "plan": plan,
                "mensaje": "Necesito al menos un dato nuevo: " + ", ".join(CAMPOS_MODIFICABLES)}

    if accion in {"crear", "modificar", "cancelar"} and not confirmar:
        campos = ("codigo", *cambios) if accion == "modificar" else REQUERIDOS[accion]
        resumen = ", ".join(f"{campo}={plan[campo]}" for campo in campos)
        return {"tipo": "confirmacion", "mensaje": f"Voy a {accion} la reserva: {resumen}. ¿Confirmas?", "plan": plan}

    base = api_base.rstrip("/")
    reservas = RUTAS["reservas"]
    if accion == "servicios":
        datos = peticion_json(base + RUTAS["servicios"])
    elif accion == "viajes":
        filtro = "?" + urlencode({"servicio": plan["servicio"]}) if plan.get("servicio") else ""
        datos = peticion_json(base + RUTAS["viajes"] + filtro)
    elif accion == "disponibilidad":
        parametros = urlencode({"fecha": plan["fecha"], "servicio": plan["servicio"]})
        datos = peticion_json(base + RUTAS["disponibilidad"] + "?" + parametros)
    elif accion == "consultar":
        # Solo lectura: no pide confirmación. El código se normaliza igual que en la API (mayúsculas, sin espacios).
        codigo = plan["codigo"].strip().upper()
        try:
            datos = peticion_json(base + reservas + "/" + quote(codigo, safe=""))
        except HTTPError as error:
            if error.code == 404:
                return {"tipo": "no_encontrada", "mensaje": f"No existe ninguna reserva con el código {codigo}."}
            raise
    elif accion == "crear":
        cuerpo = {campo: plan[campo] for campo in ("cliente", "servicio", "fecha")}
        cuerpo["confirmado"] = True
        datos = peticion_json(base + reservas, "POST", cuerpo)
    elif accion == "modificar":
        # Solo se envían los campos que cambian; la API conserva los demás.
        cuerpo = {**cambios, "confirmado": True}
        datos = peticion_json(base + reservas + "/" + quote(plan["codigo"], safe=""), "PUT", cuerpo)
    else:
        # La API exige confirmado=true como parámetro de consulta en el DELETE.
        consulta = urlencode({"confirmado": "true"})
        datos = peticion_json(base + reservas + "/" + quote(plan["codigo"], safe="") + "?" + consulta, "DELETE")
    return {"tipo": "resultado", "accion": accion, "datos": datos}


def elegir_modelo(clave, modelo):
    """Comprueba la clave y el ID del modelo contra Groq antes de empezar el chat."""
    try:
        disponibles = listar_modelos(clave)
    except HTTPError as error:
        print(f"Error HTTP {error.code} de {origen_http(error)} al validar la API key: {detalle_http(error)}")
        return None
    except (URLError, TimeoutError):
        print("Aviso: no pude consultar la lista de modelos de Groq; sigo sin validar el ID.")
        return modelo
    if modelo in disponibles and es_modelo_chat(modelo):
        return modelo
    print(f"El modelo '{modelo}' no está disponible para chat en tu cuenta (¿mal escrito o retirado?).")
    print("Modelos de chat disponibles:")
    for m in filter(es_modelo_chat, disponibles):
        print("  -", m)
    modelo = input("\nEscribe uno de la lista: ").strip()
    return modelo if modelo in disponibles and es_modelo_chat(modelo) else None


def main():
    clave = os.getenv("GROQ_API_KEY", "").strip() or getpass("API key de Groq: ").strip()
    modelo = os.getenv("GROQ_MODEL", "").strip() or input("ID del modelo de Groq: ").strip()
    if not clave or not modelo:
        print("Necesito la API key y el ID del modelo.")
        return
    modelo = elegir_modelo(clave, modelo)
    if not modelo:
        print("No hay un modelo válido; no puedo continuar.")
        return
    print(f"Usando el modelo: {modelo}")
    servicios = obtener_servicios()
    if not servicios:
        print("Aviso: no pude leer /servicios de la FastAPI; el modelo no conocerá los destinos exactos.")
    print("Escribe una solicitud. Para terminar, escribe SALIR.")
    while True:
        pregunta = input("\nTú: ").strip()
        if pregunta.casefold() == "salir":
            break
        if not pregunta:
            continue
        try:
            plan = interpretar(pregunta, clave, modelo, servicios)
            resultado = ejecutar(plan)
            print("Chatbot:", resultado.get("mensaje") or json.dumps(resultado["datos"], ensure_ascii=False, indent=2))
            if resultado["tipo"] == "confirmacion" and input("Confirmar (s/n): ").strip().casefold() == "s":
                resultado = ejecutar(plan, confirmar=True)
                print("FastAPI:", json.dumps(resultado["datos"], ensure_ascii=False, indent=2))
        except HTTPError as error:
            print(f"Error HTTP {error.code} de {origen_http(error)}: {detalle_http(error)}")
        except (URLError, TimeoutError) as error:
            print(f"No pude conectar con Groq o con la FastAPI ({getattr(error, 'reason', error)}). Revisa ambos servicios.")
        except (ValueError, KeyError, IndexError, TypeError) as error:
            print(f"No pude interpretar la respuesta ({type(error).__name__}: {error}). Revisa el formato JSON y los datos solicitados.")


if __name__ == "__main__":
    main()