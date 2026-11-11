"""Telegram de ViajesYa (clase 13): propuestas por chat y operaciones mediante la FastAPI del equipo.

Flujo: Groq interpreta el mensaje -> el bot arma una PROPUESTA (resumen + referencia de solicitud) ->
la persona pulsa Confirmar -> la API (rutas /telegram) comprueba propiedad, cupos, cruces y estado actual
antes de escribir. El bot nunca toca la base: solo habla con la API con X-API-Key y X-Telegram-User.

Antes de ejecutar:  iniciar_api.bat (FastAPI en el puerto 8011, con CHATBOT_API_KEY)  y luego  iniciar_telegram.bat
Variables opcionales: TELEGRAM_BOT_TOKEN, CHATBOT_API_KEY, GROQ_API_KEY, GROQ_MODEL, CHATBOT_API_URL
(si no están definidas, se piden por consola sin mostrarlas).
Comandos: /start /help /reserva /descartar /estado /reintentar /reset
"""

import asyncio
import json
import logging
import os
import re
from copy import deepcopy
from datetime import date, timedelta
from getpass import getpass
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from uuid import uuid4

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from consulta_llm2 import GROQ_URL, elegir_modelo, extraer_json, peticion_json

ACCIONES = {"servicios", "viajes", "disponibilidad", "consultar", "crear", "modificar", "cancelar",
            "conversar", "fuera_de_alcance"}
CAMPOS = ("accion", "cliente", "servicio", "fecha", "codigo")
ESCRITURAS = {"crear", "modificar", "cancelar"}
# En ViajesYa no hay hora: cada reserva ocupa un cupo de una salida (servicio + fecha fija).
REQUERIDOS = {"disponibilidad": ("servicio", "fecha"), "consultar": ("codigo",),
              "crear": ("cliente", "servicio", "fecha"), "modificar": ("codigo",), "cancelar": ("codigo",)}
INSTRUCCIONES = """Interpreta solicitudes de la agencia de viajes ViajesYa. Devuelve solamente un objeto JSON
con accion, cliente, servicio, fecha y codigo, todos como texto.
Acciones: servicios (catálogo, precios y duración), viajes (salidas y cupos de un destino),
disponibilidad (cupo de una salida concreta: servicio y fecha), consultar (una reserva por su código PN-...),
crear, modificar, cancelar, conversar (saludos o gracias) y fuera_de_alcance.
Cada viaje tiene fecha de salida fija y cupos limitados; no existe la hora. Usa fecha AAAA-MM-DD.
Usa el historial para completar datos. Si falta información, deja el campo vacío.
En modificar, servicio y fecha son los valores NUEVOS que la persona quiere; deja vacío lo que no cambia.
Si varias reservas podrían ser la solicitada, deja codigo vacío para pedir aclaración.
No inventes códigos, servicios, fechas ni disponibilidad. Nunca afirmes que ejecutaste una reserva.
Las decisiones de confirmar o descartar las procesa el programa mediante botones.
Las peticiones ajenas al negocio o de secretos (claves, tokens) usan fuera_de_alcance."""
BIENVENIDA = ("¡Hola! 👋 Soy el asistente virtual de ViajesYa. Puedo contarte sobre destinos, precios, salidas y cupos, "
              "y preparar reservas, modificaciones y cancelaciones.\n\n"
              "Escríbeme natural, por ejemplo: «soy Laura, quiero ir a la Macarena el 2026-12-11». Con /help ves los comandos.")
AYUDA = (
    "Puedes consultar destinos, precios, salidas con cupos y preparar reservas, modificarlas y cancelarlas.\n"
    "Revisa siempre el resumen antes de pulsar Confirmar: nada se registra sin tu confirmación.\n\n"
    "/reserva CODIGO: consultar una reserva propia.\n"
    "/descartar: retirar la propuesta vigente.\n"
    "/estado [REFERENCIA]: comprobar el resultado de una operación.\n"
    "/reintentar: reenviar una operación incierta con el mismo identificador.\n"
    "/reset: reiniciar esta conversación (tus reservas se conservan).\n"
    "/start: bienvenida.  /help: esta ayuda.\n\n"
    "Prueba:\n• ¿Qué salidas hay a Manizales?\n• ¿Cuánto cuesta Caño Cristales?\n"
    "• Soy Laura, quiero la salida de Santa Marta del 2026-12-18"
)
CATALOGO = {"servicios": {}, "texto": ""}  # se llena al iniciar con el catálogo de la API


def contexto_catalogo(negocio):
    """Texto para el modelo: identificadores exactos de servicio y los nombres con que la gente los llama."""
    lineas = ["Destinos (id exacto para el campo servicio | nombre | también se le dice):"]
    for clave, info in negocio.get("servicios", {}).items():
        lineas.append(f"- {clave} | {info.get('nombre', clave)} | {', '.join(info.get('alias', [])) or '-'}")
    lineas.append("El campo servicio debe ser exactamente uno de esos identificadores; si no puedes asociarlo, déjalo vacío.")
    return "\n".join(lineas)


def nuevo_historial():
    return [{"role": "system",
             "content": INSTRUCCIONES + f"\nFecha actual: {date.today().isoformat()}.\n" + CATALOGO["texto"]}]


def interpretar(pregunta, historial, clave, modelo):
    mensajes = historial[:1] + historial[1:][-24:] + [{"role": "user", "content": pregunta}]
    payload = {"model": modelo, "messages": mensajes, "temperature": 0, "stream": False}
    respuesta = peticion_json(GROQ_URL, "POST", payload, {"Authorization": f"Bearer {clave}"})
    plan = extraer_json(respuesta["choices"][0]["message"]["content"])
    if not isinstance(plan, dict) or plan.get("accion") not in ACCIONES:
        raise ValueError("Acción inválida en la respuesta del modelo")
    return {campo: str(plan.get(campo) or "").strip() for campo in CAMPOS}


def preparar_pendiente(plan, chat_id, usuario_id, referencia=""):
    return {"solicitud_id": uuid4().hex, "chat_id": chat_id, "usuario_id": usuario_id,
            "plan": deepcopy(plan), "referencia": referencia,
            "estado": "por_confirmar", "vence_en": monotonic() + 600}


def motivo_rechazo(pendiente, solicitud_id, chat_id, usuario_id, ahora):
    """None si la pulsación puede ejecutarse; si no, el motivo para la persona."""
    if pendiente is None:
        return "No hay una solicitud pendiente en esta conversación."
    if pendiente["chat_id"] != chat_id or pendiente["usuario_id"] != usuario_id:
        return "Esta confirmación no corresponde a tu conversación."
    if pendiente["solicitud_id"] != solicitud_id:
        return "Ese resumen ya no es el vigente."
    if pendiente["estado"] != "por_confirmar":
        return "La solicitud ya se está procesando o tiene un resultado por verificar."
    if ahora >= pendiente["vence_en"]:
        return "El resumen venció. Prepara y revisa una nueva solicitud."
    return None


def teclado_pendiente(pendiente):
    identificador = pendiente["solicitud_id"]
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Confirmar", callback_data=f"confirmar:{identificador}"),
        InlineKeyboardButton("Descartar", callback_data=f"descartar:{identificador}"),
    ]])


class FalloAPI(Exception):
    def __init__(self, estado, detalle, resultado=None):
        super().__init__(detalle)
        self.estado, self.detalle, self.resultado = estado, detalle, resultado


class ClienteAPI:
    """Peticiones protegidas a /telegram: X-API-Key identifica al bot y X-Telegram-User a quien actúa."""

    def __init__(self, base, clave):
        self.base, self.clave = base.rstrip("/"), clave

    def solicitar(self, ruta, usuario_id, metodo="GET", datos=None):
        headers = {"X-API-Key": self.clave, "X-Telegram-User": str(usuario_id)}
        try:
            return peticion_json(self.base + "/telegram" + ruta, metodo, datos, headers)
        except HTTPError as error:
            try:
                contenido = json.loads(error.read().decode("utf-8"))
            except (ValueError, UnicodeError):
                contenido = {}
            if not isinstance(contenido, dict):
                contenido = {}
            detalle = contenido.get("detalle") or contenido.get("detail") or "El servicio rechazó la petición"
            if not isinstance(detalle, str):
                detalle = "Revisa los datos enviados al servicio"
            raise FalloAPI(error.code, detalle, contenido) from error

    def leer(self, plan, usuario_id):
        accion = plan["accion"]
        if accion == "servicios":
            return self.solicitar("/servicios", usuario_id)
        if accion == "viajes":
            filtro = "?" + urlencode({"servicio": plan["servicio"]}) if plan["servicio"] else ""
            return self.solicitar("/viajes" + filtro, usuario_id)
        if accion == "disponibilidad":
            return self.disponibilidad(plan["fecha"], plan["servicio"], "", usuario_id)
        if accion == "consultar":
            return self.consultar(plan["codigo"], usuario_id)
        raise ValueError("Lectura no admitida")

    def disponibilidad(self, fecha, servicio, cliente, usuario_id):
        parametros = {"fecha": fecha, "servicio": servicio}
        if cliente:
            parametros["cliente"] = cliente
        return self.solicitar("/disponibilidad?" + urlencode(parametros), usuario_id)

    def consultar(self, codigo, usuario_id):
        return self.solicitar("/reservas/" + quote(codigo, safe=""), usuario_id)

    def ejecutar(self, pendiente):
        plan = pendiente["plan"]
        cuerpo = {"solicitud_id": pendiente["solicitud_id"], "accion": plan["accion"],
                  "datos": {campo: plan.get(campo, "") for campo in CAMPOS if campo != "accion"},
                  "referencia": pendiente["referencia"], "confirmada": True}
        return self.solicitar("/operaciones", pendiente["usuario_id"], "POST", cuerpo)

    def estado(self, identificador, usuario_id):
        return self.solicitar("/operaciones/" + quote(identificador, safe=""), usuario_id)


def registrar_turno(context, pregunta, resultado, plan=None):
    mensajes = context.chat_data.setdefault("historial", nuevo_historial())
    mensajes.extend([{"role": "user", "content": pregunta},
                     {"role": "assistant", "content": json.dumps(
                         {"plan": plan, "resultado": resultado}, ensure_ascii=False)}])


def pesos(valor):
    return "$" + f"{int(valor):,}".replace(",", ".") + " COP"


def describir_reserva(reserva):
    regreso = date.fromisoformat(reserva["fecha"]) + timedelta(days=reserva["duracion_viaje_dias"] - 1)
    return (f"Código: {reserva['codigo']}\nCliente: {reserva['cliente']}\n"
            f"Servicio: {reserva['servicio']}\nSalida: {reserva['fecha']} (regreso {regreso.isoformat()})\n"
            f"Precio: {pesos(reserva['precio_cop'])}\nEstado: {reserva['estado']}")


def formatear_lectura(accion, datos):
    if accion == "servicios":
        return "Destinos:\n" + "\n".join(
            f"• {nombre}: {pesos(v['precio_cop'])}, {v['duracion_viaje_dias']} días"
            for nombre, v in datos["servicios"].items())
    if accion == "viajes":
        if not datos["viajes"]:
            return "No hay salidas programadas próximas."
        return "Salidas (cupos libres de totales):\n" + "\n".join(
            f"• {v['servicio']}: sale {v['fecha']}, regresa {v['fecha_regreso']} "
            f"({v['cupos_disponibles']} de {v['cupos_totales']})"
            + ("" if v["reservas_abiertas"] else f" [reservas cerradas desde {v['cierre_reservas']}]")
            for v in datos["viajes"])
    if accion == "disponibilidad":
        texto = (f"{datos['servicio']}, salida {datos['fecha']}: {datos['cupos_disponibles']} de "
                 f"{datos['cupos_totales']} cupos libres.")
        return texto + (" " + datos["motivo"] if datos.get("motivo") else "")
    return describir_reserva(datos["reserva"])


async def enviar(mensaje, texto):
    for inicio in range(0, max(len(texto), 1), 4000):
        await mensaje.reply_text(texto[inicio:inicio + 4000] or "…")


async def quitar_controles(context, pendiente):
    if pendiente and pendiente.get("mensaje_id"):
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=pendiente["chat_id"], message_id=pendiente["mensaje_id"], reply_markup=None)
        except TelegramError:
            logging.warning("No se retiró el teclado; la validación del servidor sigue activa")


async def iniciar(update, context):
    context.chat_data.setdefault("historial", nuevo_historial())
    await enviar(update.effective_message, BIENVENIDA)


async def ayuda(update, context):
    await enviar(update.effective_message, AYUDA)


async def reiniciar(update, context):
    pendiente = context.chat_data.get("pendiente")
    if pendiente and pendiente["estado"] in {"ejecutando", "incierta"}:
        await enviar(update.effective_message,
                     "Primero verifica la operación con /estado. Conservo su referencia para evitar un reenvío accidental.")
        return
    await quitar_controles(context, pendiente)
    context.chat_data.clear()
    context.chat_data["historial"] = nuevo_historial()
    await enviar(update.effective_message,
                 "Reinicié esta conversación y retiré su propuesta. Las reservas registradas se conservan.")


async def descartar(update, context):
    pendiente = context.chat_data.get("pendiente")
    if pendiente and pendiente["estado"] != "por_confirmar":
        await enviar(update.effective_message,
                     "La operación necesita verificarse con /estado antes de retirar su referencia.")
        return
    await quitar_controles(context, pendiente)
    context.chat_data.pop("pendiente", None)
    registrar_turno(context, "/descartar", "La propuesta fue descartada sin ejecutar.")
    await enviar(update.effective_message, "Retiré la propuesta pendiente. Las reservas registradas se conservan.")


async def consultar_reserva(update, context):
    if len(context.args) != 1:
        await enviar(update.effective_message, "Usa /reserva CODIGO para consultar una reserva propia.")
        return
    try:
        datos = await asyncio.to_thread(context.bot_data["api"].consultar,
                                        context.args[0].strip().upper(), update.effective_user.id)
    except FalloAPI as error:
        await enviar(update.effective_message, error.detalle)
        return
    except (URLError, TimeoutError, ValueError):
        await enviar(update.effective_message, "No pude completar la consulta a la API.")
        return
    registrar_turno(context, update.effective_message.text, datos)
    await enviar(update.effective_message, describir_reserva(datos["reserva"]))


async def salidas_de(context, servicio, usuario_id):
    """Texto con las salidas de un destino para ayudar a completar la fecha. Vacío si no se puede consultar."""
    try:
        datos = await asyncio.to_thread(context.bot_data["api"].leer,
                                        {"accion": "viajes", "servicio": servicio}, usuario_id)
        return "\n" + formatear_lectura("viajes", datos)
    except (FalloAPI, URLError, TimeoutError, ValueError, KeyError, TypeError):
        return ""


async def recibir_texto(update, context):
    mensaje = update.effective_message
    pregunta = (mensaje.text or "").strip()
    if not pregunta:
        return
    usuario = update.effective_user.id
    api = context.bot_data["api"]
    pendiente = context.chat_data.get("pendiente")
    if pendiente and pendiente["estado"] in {"ejecutando", "incierta"}:
        await enviar(mensaje, "Hay una operación por verificar. Usa /estado o /reintentar; conservo su identificador.")
        return
    interprete = context.bot_data.get("interprete", interpretar)
    clave, modelo = context.bot_data.get("clave_modelo", ""), context.bot_data.get("modelo", "")
    if interprete is interpretar and (not clave or not modelo):
        await enviar(mensaje, "Configura GROQ_API_KEY y GROQ_MODEL en la terminal del bot.")
        return
    historial = context.chat_data.setdefault("historial", nuevo_historial())
    try:
        plan = await asyncio.to_thread(interprete, pregunta, historial, clave, modelo)
        if not isinstance(plan, dict) or plan.get("accion") not in ACCIONES:
            raise ValueError("Plan inválido")
        plan = {campo: str(plan.get(campo) or "").strip() for campo in CAMPOS}
        accion = plan["accion"]
        if accion in {"fuera_de_alcance", "conversar"}:
            texto = ("Puedo ayudarte con destinos, precios, salidas, cupos y tus reservas de ViajesYa."
                     if accion == "fuera_de_alcance" else
                     "¿En qué te ayudo? Puedo mostrarte destinos y salidas, o preparar una reserva. Usa /help para ver las opciones.")
            registrar_turno(context, pregunta, texto, plan)
            await enviar(mensaje, texto)
            return
        # El código solo se acepta si la persona lo escribió o es el único que ya conoce esta conversación.
        plan["codigo"] = plan["codigo"].upper()
        if accion in {"consultar", "modificar", "cancelar"}:
            conocidos = context.chat_data.get("codigos", set())
            explicito = plan["codigo"] and plan["codigo"].casefold() in pregunta.casefold()
            if not explicito and (len(conocidos) != 1 or plan["codigo"] not in conocidos):
                plan["codigo"] = ""
        else:
            plan["codigo"] = ""
        if accion in ESCRITURAS and pendiente:
            if accion != pendiente["plan"]["accion"] or plan["codigo"] != pendiente["plan"]["codigo"]:
                await enviar(mensaje, "Primero confirma o descarta la propuesta vigente para iniciar otra operación.")
                return
            await quitar_controles(context, pendiente)  # mismo tipo de operación: corrige datos y reemplaza el resumen
            context.chat_data.pop("pendiente", None)
        referencia = ""
        actual = None
        if accion in {"modificar", "cancelar"} and plan["codigo"]:
            datos_actuales = await asyncio.to_thread(api.consultar, plan["codigo"], usuario)
            referencia, actual = datos_actuales["referencia"], datos_actuales["reserva"]
            if actual["estado"] != "activa":
                texto = f"La reserva {actual['codigo']} está cancelada; no se puede {accion}."
                registrar_turno(context, pregunta, texto, plan)
                await enviar(mensaje, texto)
                return
            if accion == "modificar":
                for campo in ("cliente", "servicio", "fecha"):
                    plan[campo] = plan[campo] or actual[campo]
            else:
                for campo in ("cliente", "servicio", "fecha"):
                    plan[campo] = actual[campo]
        faltan = [campo for campo in REQUERIDOS.get(accion, ()) if not plan[campo]]
        if faltan:
            texto = "Necesito: " + ", ".join(faltan)
            if accion in {"crear", "disponibilidad"} and "fecha" in faltan and plan["servicio"]:
                texto += await salidas_de(context, plan["servicio"], usuario)
            registrar_turno(context, pregunta, texto, plan)
            await enviar(mensaje, texto)
            return
        if accion not in ESCRITURAS:
            datos = await asyncio.to_thread(api.leer, plan, usuario)
            registrar_turno(context, pregunta, datos, plan)
            await enviar(mensaje, formatear_lectura(accion, datos))
            return
        if accion in {"crear", "modificar"}:
            # Aviso temprano (la API vuelve a validar todo al confirmar): salida inexistente, cerrada, llena o cruce.
            salida_nueva = accion == "crear" or (plan["servicio"], plan["fecha"]) != (actual["servicio"], actual["fecha"])
            if salida_nueva:
                disp = await asyncio.to_thread(api.disponibilidad, plan["fecha"], plan["servicio"],
                                               plan["cliente"] if accion == "crear" else "", usuario)
                plan["servicio"] = disp["servicio"]  # identificador oficial
                salida_nueva = accion == "crear" or (plan["servicio"], plan["fecha"]) != (actual["servicio"], actual["fecha"])
                if salida_nueva and not disp["disponible"]:
                    texto = disp.get("motivo") or "Esa salida no tiene cupos disponibles."
                    registrar_turno(context, pregunta, texto, plan)
                    await enviar(mensaje, texto + " " + await salidas_de(context, plan["servicio"], usuario))
                    return
            if accion == "modificar" and all(plan[c] == actual[c] for c in ("cliente", "servicio", "fecha")):
                texto = "No veo cambios respecto a la reserva actual. Indica el nuevo destino, fecha o nombre."
                registrar_turno(context, pregunta, texto, plan)
                await enviar(mensaje, texto)
                return
        pendiente = preparar_pendiente(plan, update.effective_chat.id, usuario, referencia)
        context.chat_data["pendiente"] = pendiente
        precio = CATALOGO["servicios"].get(plan["servicio"], {}).get("precio_cop")
        resumen = (f"Acción: {accion}\n" + "\n".join(f"{campo}: {plan[campo]}" for campo in CAMPOS[1:] if plan[campo])
                   + (f"\nprecio: {pesos(precio)}" if precio is not None and accion != "cancelar" else "")
                   + f"\nReferencia de solicitud: {pendiente['solicitud_id']}\nRevisa los datos y elige una opción.")
        registrar_turno(context, pregunta, "Propuesta pendiente de confirmación", plan)
        enviado = await mensaje.reply_text(resumen, reply_markup=teclado_pendiente(pendiente))
        pendiente["mensaje_id"] = enviado.message_id
    except FalloAPI as error:
        await enviar(mensaje, error.detalle)
    except HTTPError:
        await enviar(mensaje, "El proveedor del modelo rechazó la consulta. Revisa su configuración.")
    except (URLError, TimeoutError):
        await enviar(mensaje, "No pude completar la conexión. Todavía no envié una escritura de reserva.")
    except (ValueError, KeyError, IndexError, TypeError):
        await enviar(mensaje, "La respuesta no tiene el formato esperado. Revisa o completa la solicitud.")


def validar_resultado(resultado, pendiente):
    """El recibo debe corresponder a ESTA solicitud y traer una reserva identificable."""
    if (not isinstance(resultado, dict) or resultado.get("ok") is not True
            or resultado.get("solicitud_id") != pendiente["solicitud_id"]
            or resultado.get("accion") != pendiente["plan"]["accion"]):
        raise ValueError("Resultado de escritura inesperado")
    reserva = resultado.get("reserva")
    if not isinstance(reserva, dict):
        raise ValueError("La respuesta no identifica la reserva")
    for campo in ("codigo", "cliente", "servicio", "fecha", "estado"):
        if not isinstance(reserva.get(campo), str):
            raise ValueError("La respuesta no identifica la reserva")
    if not isinstance(reserva.get("precio_cop"), int) or not isinstance(reserva.get("duracion_viaje_dias"), int):
        raise ValueError("La respuesta no identifica la reserva")


async def resultado_registrado(context, pendiente, resultado, mensaje):
    identificador = resultado["solicitud_id"]
    actual = context.chat_data.get("pendiente")
    if actual and actual["solicitud_id"] == identificador:
        context.chat_data.pop("pendiente", None)
    plan_resultado = (pendiente["plan"] if pendiente and pendiente["solicitud_id"] == identificador
                      else {"accion": resultado.get("accion"),
                            "codigo": resultado.get("reserva", {}).get("codigo", "")})
    registrar_turno(context, f"Resultado de solicitud {identificador}", resultado, plan_resultado)
    if resultado.get("ok"):
        reserva = resultado["reserva"]
        context.chat_data.setdefault("codigos", set()).add(reserva["codigo"])
        texto = f"Resultado registrado: {resultado['accion']}.\n" + describir_reserva(reserva)
        texto += f"\nReferencia: {identificador}\nEstado actual: /reserva {reserva['codigo']}"
    else:
        texto = "La API rechazó la operación: " + resultado.get("detalle", "Revisa los datos")
    await enviar(mensaje, texto)


async def ejecutar_confirmada(context, pendiente, mensaje):
    pendiente["estado"] = "ejecutando"
    context.chat_data["ultima_solicitud"] = pendiente["solicitud_id"]
    await quitar_controles(context, pendiente)
    try:
        resultado = await asyncio.to_thread(context.bot_data["api"].ejecutar, deepcopy(pendiente))
        validar_resultado(resultado, pendiente)
    except FalloAPI as error:
        if error.estado < 500:  # la API respondió y rechazó: hay un resultado definitivo
            respuesta = {"ok": False, "solicitud_id": pendiente["solicitud_id"],
                         "accion": pendiente["plan"]["accion"], "detalle": error.detalle}
            await resultado_registrado(context, pendiente, respuesta, mensaje)
            return
        pendiente["estado"] = "incierta"
    except (URLError, TimeoutError, ValueError, KeyError, TypeError):
        pendiente["estado"] = "incierta"  # no se sabe si la API llegó a escribir
    else:
        await resultado_registrado(context, pendiente, resultado, mensaje)
        return
    await enviar(mensaje, "No pude verificar el resultado. Conservo la misma referencia: "
                 + pendiente["solicitud_id"] + ". Usa /estado antes de preparar otra operación.")


async def atender_decision(update, context):
    consulta = update.callback_query
    await consulta.answer()
    chat = update.effective_chat
    if chat is None or chat.type != "private" or not isinstance(consulta.data, str):
        return
    accion, identificador = consulta.data.split(":", 1)
    pendiente = context.chat_data.get("pendiente")
    motivo = motivo_rechazo(pendiente, identificador, chat.id, consulta.from_user.id, monotonic())
    if motivo:
        if (pendiente and pendiente["solicitud_id"] == identificador
                and pendiente["usuario_id"] == consulta.from_user.id
                and pendiente["estado"] == "por_confirmar" and monotonic() >= pendiente["vence_en"]):
            await quitar_controles(context, pendiente)
            context.chat_data.pop("pendiente", None)
        await context.bot.send_message(chat.id, motivo)
        return
    if accion == "descartar":
        await quitar_controles(context, pendiente)
        context.chat_data.pop("pendiente", None)
        registrar_turno(context, f"Descartar {identificador}", "La propuesta no se ejecutó", pendiente["plan"])
        await context.bot.send_message(chat.id, "Descarté la propuesta. Las reservas registradas se conservan.")
        return
    if not isinstance(consulta.message, Message):
        await context.bot.send_message(chat.id, "Ese mensaje ya no está disponible. Revisa /estado o prepara otra solicitud.")
        return
    await ejecutar_confirmada(context, pendiente, consulta.message)


async def consultar_estado(update, context):
    pendiente = context.chat_data.get("pendiente")
    identificador = (context.args[0].strip().lower() if len(context.args) == 1 else
                     pendiente["solicitud_id"] if pendiente else context.chat_data.get("ultima_solicitud", ""))
    if not re.fullmatch(r"[0-9a-f]{32}", identificador):
        await enviar(update.effective_message, "Usa /estado REFERENCIA con la referencia del resumen.")
        return
    try:
        datos = await asyncio.to_thread(context.bot_data["api"].estado, identificador, update.effective_user.id)
        resultado = datos["resultado"]
        if resultado.get("solicitud_id") != identificador:
            raise ValueError("Referencia inesperada")
        if resultado.get("ok"):
            provisional = pendiente if pendiente and pendiente["solicitud_id"] == identificador else {
                "solicitud_id": identificador, "plan": {"accion": resultado.get("accion")}}
            validar_resultado(resultado, provisional)
    except FalloAPI as error:
        texto = ("Todavía no hay un resultado verificable. Conservo la referencia; no asumo que la escritura falló."
                 if error.estado == 404 else error.detalle)
        await enviar(update.effective_message, texto)
        return
    except (URLError, TimeoutError, ValueError, KeyError, TypeError):
        await enviar(update.effective_message, "No pude verificar el estado. Conservo la referencia de la operación.")
        return
    await resultado_registrado(context, pendiente, resultado, update.effective_message)


async def reintentar(update, context):
    pendiente = context.chat_data.get("pendiente")
    if not pendiente or pendiente["estado"] != "incierta":
        await enviar(update.effective_message, "No hay una operación incierta para reenviar.")
        return
    await ejecutar_confirmada(context, pendiente, update.effective_message)


async def desconocido(update, context):
    await enviar(update.effective_message, "Comando no disponible. Usa /help para ver las opciones.")


async def otro_mensaje(update, context):
    await enviar(update.effective_message, "Envíame una consulta escrita. Por ahora atiendo mensajes de texto.")


async def informar_error(update, context):
    # Solo la clase del error: el detalle podría incluir la URL del bot (contiene el token).
    logging.error("Error del bot: %s", type(context.error).__name__)


def registrar_handlers(aplicacion):
    privado = filters.ChatType.PRIVATE
    aplicacion.add_handler(CallbackQueryHandler(
        atender_decision, pattern=r"^(confirmar|descartar):[0-9a-f]{32}$", block=True))
    for nombre, funcion in (("start", iniciar), ("help", ayuda), ("reset", reiniciar),
                            ("descartar", descartar), ("reserva", consultar_reserva),
                            ("estado", consultar_estado), ("reintentar", reintentar)):
        aplicacion.add_handler(CommandHandler(nombre, funcion, filters=privado))
    aplicacion.add_handler(MessageHandler(privado & filters.TEXT & ~filters.COMMAND, recibir_texto))
    aplicacion.add_handler(MessageHandler(privado & filters.COMMAND, desconocido))
    aplicacion.add_handler(MessageHandler(privado & ~filters.TEXT, otro_mensaje))
    aplicacion.add_error_handler(informar_error)


def crear_aplicacion(token, api, clave_modelo="", modelo="", interprete=None, request=None):
    # concurrent_updates(False): una actualización a la vez, el estado de cada chat no se pisa a sí mismo.
    constructor = Application.builder().token(token).concurrent_updates(False)
    if request is not None:
        constructor = constructor.request(request).get_updates_request(request)
    aplicacion = constructor.build()
    aplicacion.bot_data.update(api=api, clave_modelo=clave_modelo, modelo=modelo)
    if interprete is not None:
        aplicacion.bot_data["interprete"] = interprete
    registrar_handlers(aplicacion)
    return aplicacion


def cargar_catalogo(api):
    """Catálogo de la API (ids de servicio, alias, precios) para el modelo y los resúmenes."""
    try:
        negocio = api.solicitar("/servicios", 0)
        CATALOGO["servicios"] = negocio["servicios"]
        CATALOGO["texto"] = contexto_catalogo(negocio)
        return True
    except (FalloAPI, URLError, TimeoutError, ValueError, KeyError, TypeError):
        return False


def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx imprime la URL con el token a nivel INFO
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or getpass("Token de BotFather (oculto): ").strip()
    clave_api = os.getenv("CHATBOT_API_KEY", "").strip() or getpass("Clave privada de la FastAPI (oculta): ").strip()
    clave_groq = os.getenv("GROQ_API_KEY", "").strip() or getpass("API key de Groq (oculta): ").strip()
    modelo = os.getenv("GROQ_MODEL", "").strip() or input("ID del modelo de Groq: ").strip()
    if not token or not clave_api:
        print("Configura el token y la clave de la API antes de iniciar.")
        return
    if clave_groq and modelo:
        modelo = elegir_modelo(clave_groq, modelo)
        if not modelo:
            print("No hay un modelo válido; no puedo continuar.")
            return
        print(f"Usando el modelo: {modelo}")
    else:
        print("Aviso: sin API key o modelo de Groq el bot no podrá interpretar mensajes (los comandos sí funcionan).")
    api = ClienteAPI(os.getenv("CHATBOT_API_URL", "http://127.0.0.1:8011"), clave_api)
    if not cargar_catalogo(api):
        print("Aviso: no pude leer /telegram/servicios. ¿Está encendida iniciar_api.bat y la clave es la misma?")
    try:
        aplicacion = crear_aplicacion(token, api, clave_groq, modelo)
        print("Bot en ejecución. Abre su chat privado. Para detenerlo: Ctrl+C.")
        aplicacion.run_polling(allowed_updates=["message", "callback_query"])
    except TelegramError as error:
        print(f"Telegram no completó el inicio: {type(error).__name__}.")


if __name__ == "__main__":
    main()
