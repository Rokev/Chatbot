"""Canal de Telegram del chatbot de ViajesYa.

Reutiliza la clase Chat de chatbot_memoria.py, igual que app_gradio.py y la terminal, así que la lógica es la misma:
Groq interpreta, la FastAPI manda sobre los datos y la confirmación la decide Python ("sí" / "no").
Telegram solo pone la pantalla: una conversación propia por chat (chat_data) y botones Confirmar / Descartar.

Antes de ejecutar:  iniciar_api.bat  (FastAPI en el puerto 8011)  y luego  iniciar_telegram.bat
o, a mano:          python bot_telegram.py
Variables opcionales: TELEGRAM_BOT_TOKEN, GROQ_API_KEY, GROQ_MODEL, CHATBOT_API_URL (si no están, se piden por consola).
Comandos del bot:   /start · /help · /reset
"""

import asyncio
import logging
import os
import traceback
from getpass import getpass
from urllib.error import HTTPError, URLError

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import InvalidToken, NetworkError, TelegramError
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

from chatbot_memoria import ERRORES, Chat, base, historial_como_texto, registrar

BIENVENIDA = (
    "¡Hola! 👋 Soy el asistente virtual de ViajesYa. "
    "Puedo contarte sobre nuestros destinos, fechas de salida y cupos, y ayudarte a reservar, "
    "consultar, modificar o cancelar un viaje.\n\n"
    "Escríbeme natural, por ejemplo: «quiero ir a la Macarena en diciembre». Con /help ves los comandos."
)
AYUDA = (
    "/start: mostrar la bienvenida.\n"
    "/help: ver esta ayuda.\n"
    "/reset: reiniciar esta conversación (tus reservas guardadas se conservan).\n\n"
    "Prueba:\n"
    "• ¿Qué salidas hay a Manizales?\n"
    "• ¿Quedan cupos para Caño Cristales?\n"
    "• Soy Laura, quiero la salida de noviembre\n\n"
    "Antes de registrar, modificar o cancelar una reserva te pediré confirmación: "
    "usa los botones o responde «sí» / «no»."
)
AVISO_PENDIENTE = "Hay una solicitud por confirmar. Pulsa un botón o responde «sí» / «no»."
LIMITE_TELEGRAM = 4000  # Telegram admite 4096 caracteres por mensaje
CONFIG = {"clave": "", "modelo": ""}
TECLADO_CONFIRMACION = InlineKeyboardMarkup([[
    InlineKeyboardButton("✅ Confirmar", callback_data="confirmar"),
    InlineKeyboardButton("❌ Descartar", callback_data="descartar"),
]])


class ServicioNoDisponible(Exception):
    """Falta GROQ_API_KEY o GROQ_MODEL en el servidor del bot."""


def texto_error(error):
    """Mensaje para la persona. El detalle técnico va a la consola, nunca a Telegram (podría incluir datos internos)."""
    if isinstance(error, ServicioNoDisponible):
        return "El asistente no está configurado todavía (faltan datos del modelo en el servidor del bot)."
    if isinstance(error, HTTPError):
        return f"Hubo un problema con {base.origen_http(error)} ({error.code}). Intenta de nuevo en un momento."
    if isinstance(error, (URLError, TimeoutError)):
        return "No pude conectar con Groq o con la FastAPI. Intenta de nuevo en un momento."
    return "No pude interpretar la respuesta del modelo. Intenta de nuevo o escríbelo con otras palabras."


async def enviar_texto(mensaje, texto, teclado=None):
    """Envía texto plano en trozos; el teclado (si hay) va solo en el último trozo."""
    trozos = [texto[i:i + LIMITE_TELEGRAM] for i in range(0, len(texto), LIMITE_TELEGRAM)] or ["…"]
    for i, trozo in enumerate(trozos):
        await mensaje.reply_text(trozo, reply_markup=teclado if i == len(trozos) - 1 else None)


def obtener_chat(context):
    """Chat de ViajesYa de ESTE chat de Telegram (historial + solicitud pendiente). Se crea la primera vez."""
    chat = context.chat_data.get("chat")
    if chat is None:
        if not CONFIG["clave"] or not CONFIG["modelo"]:
            raise ServicioNoDisponible()
        chat = Chat(CONFIG["clave"], CONFIG["modelo"])  # consulta catálogo y cupos a la FastAPI
        context.chat_data["chat"] = chat
    return chat


async def ejecutar_turno(update, context, texto):
    """Un turno completo: pasa `texto` a Chat.responder y responde con botones si queda algo por confirmar."""
    mensaje = update.effective_message
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        chat = await asyncio.to_thread(obtener_chat, context)
        respuesta = await asyncio.to_thread(chat.responder, texto)  # llamadas bloqueantes: fuera del bucle de eventos
    except (ServicioNoDisponible, *ERRORES) as error:  # el historial no cambió: se puede reintentar
        if not isinstance(error, ServicioNoDisponible):
            registrar("TURNO FALLIDO (Telegram, el historial no cambió)",
                      f"pregunta: {texto}\nerror: {type(error).__name__}: {error}")
            traceback.print_exc()
        await enviar_texto(mensaje, texto_error(error))
        return
    await enviar_texto(mensaje, respuesta, TECLADO_CONFIRMACION if chat.pendiente else None)


async def iniciar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message is not None:
        await enviar_texto(update.effective_message, BIENVENIDA)


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message is not None:
        await enviar_texto(update.effective_message, AYUDA)


async def reiniciar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Conversación nueva: historial solo con system y sin solicitud pendiente. Las reservas viven en la FastAPI."""
    if update.effective_message is None:
        return
    chat = context.chat_data.get("chat")
    if chat is not None:
        await asyncio.to_thread(chat.reiniciar)
        registrar("REINICIO (Telegram)", historial_como_texto(chat.historial))
    await enviar_texto(update.effective_message,
                       "Conversación reiniciada. Cuéntame qué necesitas. Tus reservas guardadas se conservan.")


async def recibir_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = update.effective_message
    if mensaje is None or not mensaje.text or not mensaje.text.strip():
        return
    await ejecutar_turno(update, context, mensaje.text.strip())


async def pulsar_boton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirmar / Descartar: atajo para escribir «sí» / «no». La decisión sigue siendo de Python (es_afirmacion)."""
    consulta = update.callback_query
    if consulta is None:
        return
    await consulta.answer()
    chat = context.chat_data.get("chat")
    if chat is None or chat.pendiente is None:
        await consulta.edit_message_reply_markup(reply_markup=None)  # botón viejo: ya no hay nada por confirmar
        await enviar_texto(consulta.message, "No hay ninguna solicitud pendiente.")
        return
    await consulta.edit_message_reply_markup(reply_markup=None)  # evita pulsar dos veces
    await ejecutar_turno(update, context, "sí" if consulta.data == "confirmar" else "no")


async def comando_desconocido(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await enviar_texto(update.effective_message, "No conozco ese comando. Usa /start, /help o /reset.")


async def otro_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await enviar_texto(update.effective_message, "Por ahora recibo mensajes de texto. Escríbeme tu consulta.")


async def informar_error(update, context):
    # Registramos la clase del error sin imprimir credenciales ni la URL del bot (contiene el token).
    logging.error("Error del bot: %s", type(context.error).__name__)


def registrar_handlers(aplicacion):
    privado = filters.ChatType.PRIVATE
    aplicacion.add_handler(CommandHandler("start", iniciar, filters=privado))
    aplicacion.add_handler(CommandHandler("help", ayuda, filters=privado))
    aplicacion.add_handler(CommandHandler("reset", reiniciar, filters=privado))
    aplicacion.add_handler(CallbackQueryHandler(pulsar_boton, pattern="^(confirmar|descartar)$"))
    aplicacion.add_handler(MessageHandler(privado & filters.TEXT & ~filters.COMMAND, recibir_texto))
    aplicacion.add_handler(MessageHandler(privado & filters.COMMAND, comando_desconocido))
    aplicacion.add_handler(MessageHandler(privado & ~filters.TEXT & ~filters.COMMAND, otro_mensaje))
    aplicacion.add_error_handler(informar_error)


def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx imprime la URL con el token a nivel INFO
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or getpass("Token de BotFather (oculto): ").strip()
    clave = os.getenv("GROQ_API_KEY", "").strip() or getpass("API key de Groq (oculta): ").strip()
    modelo = os.getenv("GROQ_MODEL", "").strip() or input("ID del modelo de Groq: ").strip()
    if not token or not clave or not modelo:
        print("Necesito el token de Telegram, la API key de Groq y el ID del modelo.")
        return
    modelo = base.elegir_modelo(clave, modelo)
    if not modelo:
        print("No hay un modelo válido; no puedo continuar.")
        return
    CONFIG.update(clave=clave, modelo=modelo)
    print(f"Usando el modelo: {modelo}")
    if not base.obtener_servicios():
        print("Aviso: no pude leer /servicios de la FastAPI. ¿Está encendida iniciar_api.bat?")
    try:
        aplicacion = Application.builder().token(token).build()
        registrar_handlers(aplicacion)
        registrar("INICIO DE TELEGRAM", f"modelo={modelo}")
        print("Bot en ejecución. Abre su conversación en Telegram. Para detenerlo: Ctrl+C.")
        aplicacion.run_polling(allowed_updates=["message", "callback_query"])
    except InvalidToken:
        print("Token inválido. Comprueba la credencial entregada por BotFather.")
    except NetworkError:
        print("No fue posible iniciar la conexión con Telegram. Revisa Internet e inténtalo otra vez.")
    except TelegramError as error:
        print(f"Telegram no completó el inicio: {type(error).__name__}.")


if __name__ == "__main__":
    main()