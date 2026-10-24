"""Chatbot de ViajesYa con historial (messages[]) y respuestas en lenguaje natural.

Cómo funciona cada turno (Groq nunca toca la API; la FastAPI manda sobre los datos):
  1. INTERPRETAR  Groq lee el historial + catálogo + cupos reales y devuelve un JSON con la intención.
  2. EJECUTAR     Python consulta/valida con la FastAPI (consulta_llm2.ejecutar).
  3. REDACTAR     Groq escribe la respuesta amable usando SOLO el resultado real del paso 2.
Crear / modificar / cancelar siguen exigiendo confirmación: la decide Python (palabras como "sí", "dale"),
nunca el modelo.

Comandos:  HISTORIAL · REINICIAR · SALIR      (CHATBOT_DEBUG=1 muestra el plan JSON y el historial)
Antes de ejecutar:  python -m uvicorn main:app --port 8011 --workers 1   (FastAPI encendida)
"""

import json
import os
import re
import unicodedata
from datetime import date, datetime
from getpass import getpass
from pathlib import Path
from urllib.error import HTTPError, URLError

try:
    import consulta_llm2 as base
except ImportError:  # por si el archivo se llama consulta_llm.py
    import consulta_llm as base

EVIDENCIA = Path(__file__).with_name("evidencia_clase07.txt")
MAX_MENSAJES = 20  # además del "system": evita que el historial crezca sin límite
DEBUG = os.getenv("CHATBOT_DEBUG") == "1"
ERRORES = (HTTPError, URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError)

INSTRUCCIONES_INTERPRETE = """
Eres el intérprete de un chatbot de una agencia de viajes. Lees la conversación y devuelves SOLO un JSON
con las claves: accion, cliente, servicio, fecha, codigo (cadena vacía si no hay dato).

Acciones: servicios (ver catálogo), viajes (fechas/cupos de un destino o de todos), disponibilidad (¿hay cupo
en esa salida? requiere servicio y fecha), consultar (ver una reserva YA creada; requiere codigo), crear, modificar, cancelar, conversar (saludos, gracias, dudas sobre
precios, duración, horarios, la agencia, "¿qué me recomiendas?"), fuera_de_alcance (nada que ver con viajes).

Reglas:
- La persona habla natural. NO tiene que escribir nombres exactos: entiende sinónimos, nombres parciales,
  tildes faltantes y errores de ortografía ("la macarena", "cano cristales", "el nevado").
  En "servicio" pon SIEMPRE el id exacto del catálogo de abajo.
- Cada viaje sale en una fecha fija con cupos limitados. En "fecha" usa AAAA-MM-DD. Resuelve expresiones como
  "el 12 de diciembre", "la de diciembre", "la primera", "la última" usando la lista de salidas, lo que dijo
  antes el asistente y la fecha de hoy. Si el destino solo tiene una salida con cupo y la persona quiere ir, úsala.
- Usa TODA la conversación: si ya dio cliente, servicio o fecha y no los cambia, consérvalos al crear.
  Si corrige un dato, usa el nuevo. Un "sí", "esa" o "dale" se interpreta con el último mensaje del asistente.
- Si solo pregunta precio, duración o compara destinos, es conversar (no crear).
- Si la persona da un código PN-... y quiere ver/revisar/verificar su reserva (o solo lo escribe), la acción es consultar
  con ese código en "codigo", sin mayúsculas ni espacios distintos al original. No es crear.
- En modificar, servicio y fecha son los valores NUEVOS; codigo es el código de la reserva (PN-...).
- No inventes datos. No digas que algo quedó reservado: solo identificas la intención.
"""

INSTRUCCIONES_REDACTOR = """
Eres el asistente virtual de ViajesYa, una agencia de viajes en Armenia, Colombia. Hablas en español, cálido,
natural y cercano, como una asesora real por chat: frases cortas (2 a 5), sin sonar a formulario ni a robot,
sin JSON ni nombres de campos técnicos, sin repetir saludos en cada mensaje. Puedes usar algún emoji ocasional.

Reglas de oro:
- Usa SOLO el catálogo, las salidas con cupos y el "Resultado del sistema" que te doy. No inventes precios,
  fechas, cupos, promociones, códigos ni servicios incluidos que no estén ahí. Si no lo sabes, dilo.
- Nunca afirmes que una reserva quedó registrada, modificada o cancelada salvo que el resultado diga que se hizo.
  Si hay un código de reserva en el resultado, dáselo.
- Si faltan datos, pide solo lo que falta (uno o dos datos a la vez), de forma conversacional.
- Si el resultado es una solicitud por confirmar, resume claro: destino, fecha de salida, precio, a nombre de quién,
  y pregunta si la confirma (que responda "sí" o "no"). Aclara que todavía no está reservada.
- Si algo no está disponible (fecha sin viaje, lleno, cerradas), explícalo simple y ofrece las alternativas reales.
- Precios en pesos colombianos con puntos de miles (ej. $830.000 COP). Fechas legibles (ej. 5 de diciembre de 2026).
- Si preguntan algo ajeno a la agencia, responde amable en una frase y reconduce a viajes.
- Puedes recomendar entre destinos usando solo los datos del catálogo (precio, duración, fechas).
"""


# ---------- utilidades de texto ----------

def normalizar(texto):
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join("".join(c if c.isalnum() else " " for c in sin_tildes.lower()).split())


AFIRMA = {"s", "si", "sii", "siii", "dale", "ok", "okay", "listo", "confirmo", "confirmar", "confirmado", "claro",
          "de", "una", "va", "vale", "perfecto", "correcto", "hagale", "adelante", "yes", "y", "por", "favor",
          "gracias", "muy", "bien", "eso", "es", "asi", "reserva", "reservala", "registrala", "hazlo"}
NIEGA = {"no", "nop", "nel", "nada", "abortar", "aborta", "descartar", "descarta", "mejor", "gracias", "por", "ahora",
         "todavia", "aun"}


def es_afirmacion(texto):
    palabras = normalizar(texto).split()
    return bool(palabras) and len(palabras) <= 5 and all(p in AFIRMA for p in palabras)


def es_negacion(texto):
    palabras = normalizar(texto).split()
    return bool(palabras) and len(palabras) <= 4 and palabras[0] in {"no", "nop", "nel", "abortar", "aborta", "descartar"} \
        and all(p in NIEGA for p in palabras)


# ---------- historial ----------

def recortar(historial):
    """Conserva el system y los últimos MAX_MENSAJES mensajes."""
    if len(historial) <= MAX_MENSAJES + 1:
        return historial
    return historial[:1] + historial[-MAX_MENSAJES:]


def mostrar_historial(historial):
    print(f"--- historial: {len(historial)} mensajes ---")
    for i, m in enumerate(historial):
        texto = m["content"].replace("\n", " ")
        if m["role"] == "system":
            texto = texto[:70] + "..."
        print(f"{i}. [{m['role']}] {texto}")
    print("--- fin del historial ---")


def registrar(titulo, contenido=""):
    """Guarda evidencia en evidencia_clase07.txt. Nunca escribe la API key."""
    with EVIDENCIA.open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {titulo}\n{contenido}\n\n")


def historial_como_texto(historial):
    return "\n".join(f"{i}. [{m['role']}] {m['content'][:200]}" for i, m in enumerate(historial))


# ---------- Groq ----------

def llamar_groq(mensajes, clave, modelo, temperatura):
    payload = {"model": modelo, "messages": mensajes, "temperature": temperatura, "stream": False}
    respuesta = base.peticion_json(base.GROQ_URL, "POST", payload, {"Authorization": f"Bearer {clave}"})
    return respuesta["choices"][0]["message"]["content"]


def consultar_groq(mensajes, clave, modelo):
    """Paso 1: el modelo devuelve la intención como JSON (temperatura 0)."""
    texto = llamar_groq(mensajes, clave, modelo, 0) or ""
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.S)  # modelos que "piensan" en voz alta antes del JSON
    try:
        plan = base.extraer_json(texto)
    except ValueError as error:
        raise ValueError(f"el modelo no devolvió un JSON válido. Respondió: {texto.strip()[:200]!r}") from error
    if not isinstance(plan, dict):
        raise ValueError(f"el modelo no devolvió un objeto JSON. Respondió: {texto.strip()[:200]!r}")
    accion = str(plan.get("accion") or "").strip().lower()
    if accion not in base.ACCIONES:
        raise ValueError(f"acción no válida {accion!r}; se esperaba una de: {', '.join(sorted(base.ACCIONES))}")
    plan["accion"] = accion
    return {campo: str(plan.get(campo) or "").strip() for campo in base.CAMPOS}


# ---------- el chat ----------

class Chat:
    def __init__(self, clave, modelo):
        self.clave, self.modelo = clave, modelo
        self.catalogo = {}
        self.reiniciar()

    def reiniciar(self):
        """Conversación nueva. Las reservas viven en la FastAPI y no se tocan."""
        self.historial = [{"role": "system", "content": ""}]
        self.pendiente = None   # plan que espera un "sí"
        self.en_curso = {}      # datos recogidos de la reserva que se está armando
        self.refrescar()

    def refrescar(self):
        """Trae catálogo y cupos reales de la FastAPI y actualiza el mensaje system."""
        self.catalogo = base.obtener_catalogo() or self.catalogo
        self.contexto = base.contexto_negocio(self.catalogo, base.obtener_viajes())
        estado = ""
        if self.en_curso:
            estado += "\nDatos ya recogidos de la reserva en curso: " + json.dumps(self.en_curso, ensure_ascii=False) + "\n"
        if self.pendiente:
            estado += ("Se le pidió confirmar esta solicitud y respondió otra cosa (puede estar corrigiéndola): "
                       + json.dumps(self.pendiente, ensure_ascii=False) + "\n")
        sistema = (INSTRUCCIONES_INTERPRETE + f"\nHoy es {date.today().isoformat()}.\n\n" + self.contexto + estado)
        self.historial[0] = {"role": "system", "content": sistema}

    # --- paso 3: redactar ---
    def redactar(self, pregunta, resultado, fallback):
        sistema = INSTRUCCIONES_REDACTOR + f"\nHoy es {date.today().isoformat()}.\n\n" + self.contexto
        mensajes = ([{"role": "system", "content": sistema}] + self.historial[1:]
                    + [{"role": "user", "content": pregunta},
                       {"role": "system", "content": "Resultado del sistema (datos reales): "
                        + json.dumps(resultado, ensure_ascii=False)}])
        try:
            texto = llamar_groq(mensajes, self.clave, self.modelo, 0.5).strip()
            return texto or fallback
        except ERRORES:
            return fallback  # si falla la redacción, se muestra el texto simple pero correcto

    def _guardar(self, pregunta, respuesta):
        self.historial = recortar(self.historial + [{"role": "user", "content": pregunta},
                                                    {"role": "assistant", "content": respuesta}])

    # --- un turno completo ---
    def responder(self, pregunta):
        """Devuelve el texto para el cliente. Si Groq (interpretación) falla, lanza error y el historial NO cambia."""
        self.refrescar()
        previo = self.pendiente
        if self.pendiente:
            plan, self.pendiente = self.pendiente, None
            if es_afirmacion(pregunta):
                return self._confirmar(plan, pregunta)
            if es_negacion(pregunta):
                self.en_curso.clear()
                registrar("OPERACIÓN DESCARTADA", json.dumps(plan, ensure_ascii=False))
                texto = self.redactar(pregunta, {"tipo": "descartada", "nota": "No se cambió ninguna reserva."},
                                      "Listo, no hice ningún cambio. ¿Te ayudo con otra cosa?")
                self._guardar(pregunta, texto)
                return texto
            self.refrescar()  # respondió otra cosa: se interpreta como mensaje normal

        try:
            plan = consultar_groq(self.historial + [{"role": "user", "content": pregunta}], self.clave, self.modelo)
        except ERRORES:
            self.pendiente = previo  # turno fallido: no se pierde la confirmación pendiente
            raise
        self._completar_con_en_curso(plan)
        if DEBUG:
            print("[plan]", json.dumps(plan, ensure_ascii=False))

        resultado = base.ejecutar(plan)
        if plan["accion"] == "crear" and plan["servicio"]:
            self.en_curso["servicio"] = plan["servicio"]  # ya viene con el id oficial
        if resultado["tipo"] == "no_disponible":
            self.en_curso.pop("fecha", None)  # esa fecha no sirve: se volverá a pedir
        if resultado["tipo"] == "confirmacion":
            self.pendiente = plan
        datos = {k: v for k, v in resultado.items() if k != "plan"}
        texto = self.redactar(pregunta, datos, self._texto_simple(resultado))
        registrar("TURNO", f"pregunta: {pregunta}\nplan: {json.dumps(plan, ensure_ascii=False)}\nrespuesta: {texto}")
        self._guardar(pregunta, texto)
        return texto

    def _completar_con_en_curso(self, plan):
        """Respaldo en Python: si el modelo olvidó un dato de la reserva en curso, se recupera."""
        if plan["accion"] != "crear":
            return
        if plan["servicio"] and self.en_curso.get("servicio") not in (None, plan["servicio"]) \
                and plan["fecha"] == self.en_curso.get("fecha"):
            plan["fecha"] = ""  # cambió de destino: la fecha anterior ya no aplica
        for campo in ("cliente", "servicio", "fecha"):
            if not plan[campo] and self.en_curso.get(campo):
                plan[campo] = self.en_curso[campo]
        self.en_curso.update({c: plan[c] for c in ("cliente", "servicio", "fecha") if plan[c]})

    def _confirmar(self, plan, pregunta):
        """El cliente dijo que sí: se ejecuta en la FastAPI y se redacta con el resultado real."""
        try:
            final = base.ejecutar(plan, confirmar=True)
            if final["tipo"] != "resultado":  # p. ej. el cupo se agotó mientras confirmaba
                self.en_curso.pop("fecha", None)
                texto = self.redactar(pregunta, {k: v for k, v in final.items() if k != "plan"},
                                      final.get("mensaje", "No pude completar la operación."))
                self._guardar(pregunta, texto)
                return texto
            resultado = {"tipo": "operacion_realizada", "accion": plan["accion"], "datos": final["datos"]}
            registrar("RESULTADO FASTAPI", json.dumps(final["datos"], ensure_ascii=False))
            fallback = "Listo, la operación quedó realizada. " + json.dumps(final["datos"], ensure_ascii=False)
            self.en_curso.clear()
        except (HTTPError, URLError, TimeoutError) as error:
            detalle = base.detalle_http(error) if isinstance(error, HTTPError) else "no hubo conexión con la FastAPI"
            registrar("ERROR EN FASTAPI", detalle)
            resultado = {"tipo": "error", "mensaje": detalle, "nota": "No se registró nada."}
            fallback = f"No pude completar la operación: {detalle} No se registró nada."
            self.en_curso.pop("fecha", None)
        texto = self.redactar(pregunta, resultado, fallback)
        self._guardar(pregunta, texto)
        return texto

    @staticmethod
    def _texto_simple(resultado):
        """Respuesta de respaldo (sin LLM) si falla la redacción."""
        if resultado.get("mensaje"):
            return resultado["mensaje"] + (" (responde sí o no)" if resultado["tipo"] == "confirmacion" else "")
        datos = resultado.get("datos", {})
        if "codigo" in datos and "estado" in datos:  # una reserva (consultar)
            return (f"Reserva {datos['codigo']}: {datos['cliente']}, {datos['servicio']}, salida {datos['fecha']} "
                    f"({datos['duracion_viaje_dias']} días). Estado: {datos['estado']}.")
        if "viajes" in datos:
            return "\n".join(f"- {v['servicio']}: {v['fecha']} ({v['cupos_disponibles']} cupos)" for v in datos["viajes"])
        return json.dumps(datos, ensure_ascii=False, indent=2)


def imprimir_error(error):
    if isinstance(error, HTTPError):
        print(f"Error HTTP {error.code} de {base.origen_http(error)}: {base.detalle_http(error)}")
    elif isinstance(error, (URLError, TimeoutError)):
        print(f"No pude conectar con Groq o con la FastAPI ({getattr(error, 'reason', error)}). Revisa ambos servicios.")
    else:
        print(f"No pude interpretar la respuesta ({type(error).__name__}: {error}).")


def main():
    clave = os.getenv("GROQ_API_KEY", "").strip() or getpass("API key de Groq: ").strip()
    modelo = os.getenv("GROQ_MODEL", "").strip() or input("ID del modelo de Groq: ").strip()
    if not clave or not modelo:
        print("Necesito la API key y el ID del modelo.")
        return
    modelo = base.elegir_modelo(clave, modelo)
    if not modelo:
        print("No hay un modelo válido; no puedo continuar.")
        return
    print(f"Usando el modelo: {modelo}")
    if not base.obtener_servicios():
        print("Aviso: no pude leer /servicios de la FastAPI; el modelo no conocerá los destinos ni los cupos.")

    chat = Chat(clave, modelo)
    registrar("INICIO DE SESIÓN", f"modelo={modelo}\n{historial_como_texto(chat.historial)}")
    print("Hola, escríbeme lo que necesites sobre nuestros viajes. (Comandos: HISTORIAL, REINICIAR, SALIR)")

    while True:
        pregunta = input("\nTú: ").strip()
        comando = pregunta.casefold()
        if comando == "salir":
            break
        if not pregunta:
            continue
        if comando == "historial":
            mostrar_historial(chat.historial)
            continue
        if comando == "reiniciar":
            chat.reiniciar()
            print("Conversación reiniciada: el historial tiene solo el mensaje system. Las reservas se conservan.")
            registrar("REINICIO", historial_como_texto(chat.historial))
            continue
        try:
            print("\nChatbot:", chat.responder(pregunta))
            if DEBUG:
                mostrar_historial(chat.historial)
        except ERRORES as error:
            imprimir_error(error)
            registrar("TURNO FALLIDO (el historial no cambió)", f"pregunta: {pregunta}\nerror: {type(error).__name__}")


if __name__ == "__main__":
    main()
