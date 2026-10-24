"""Interfaz web (Gradio) del chatbot de ViajesYa. Clase 08.

Reutiliza la clase Chat de chatbot_memoria.py, así que la lógica es la misma que en la terminal:
Groq interpreta, la FastAPI manda sobre los datos y la confirmación la decide Python.
Gradio solo pone la pantalla, los botones y una conversación propia por sesión del navegador.

Antes de ejecutar:  iniciar_api.bat  (FastAPI en el puerto 8011)  y luego  iniciar_gradio.bat
o, a mano:          python app_gradio.py     ->  http://127.0.0.1:7860
Variables opcionales: GROQ_API_KEY, GROQ_MODEL, CHATBOT_API_URL (si no están, se piden por consola).
"""

import os
import threading
import traceback
from getpass import getpass

import gradio as gr

from chatbot_memoria import ERRORES, Chat, base, historial_como_texto, registrar
from urllib.error import HTTPError, URLError

CONFIG = {
    "clave": os.getenv("GROQ_API_KEY", "").strip(),
    "modelo": os.getenv("GROQ_MODEL", "").strip(),
}
PALABRAS_REINICIO = {"reiniciar", "/reiniciar", "reset", "/reset"}
AVISO_PENDIENTE = "Hay una solicitud por confirmar: pulsa **Confirmar** o **Descartar** (o escribe sí / no)."


class Sesion:
    """Todo lo que pertenece a UNA persona: su Chat (historial + solicitud pendiente) y lo que ve en pantalla.

    Gradio crea una Sesion por cada pestaña del navegador, así que dos personas nunca mezclan conversaciones.
    Las reservas no viven aquí: las guarda la FastAPI. Reiniciar borra la conversación, no las reservas.
    """

    def __init__(self):
        self.chat = Chat(CONFIG["clave"], CONFIG["modelo"])
        self.pantalla = []
        self.lock = threading.Lock()  # evita solapar envío, confirmación y reinicio de la misma sesión


def texto_error(error):
    if isinstance(error, HTTPError):
        return f"Error HTTP {error.code} de {base.origen_http(error)}: {base.detalle_http(error)}"
    if isinstance(error, (URLError, TimeoutError)):
        return "No pude conectar con Groq o con la FastAPI. Revisa que ambos estén disponibles."
    return f"No pude interpretar la respuesta del modelo ({type(error).__name__}: {str(error)[:300]}). Intenta de nuevo."


def historial_visible(historial):
    """Historial para el acordeón de revisión (el mensaje system es enorme: se recorta)."""
    return [{"role": m["role"], "content": m["content"] if len(m["content"]) <= 300 else m["content"][:300] + "…"}
            for m in historial]


def vista(sesion, aviso, caja=""):
    """Salida común de todos los botones: pantalla, estado, caja de texto, aviso, botones y historial."""
    hay_pendiente = sesion.chat.pendiente is not None
    return (sesion.pantalla, sesion, caja, aviso,
            gr.update(interactive=hay_pendiente), gr.update(interactive=hay_pendiente),
            historial_visible(sesion.chat.historial))


def rechazar(sesion, texto, caja=""):
    """Avisa de un problema SIN lanzar gr.Error (que tapa toda la pantalla con chips rojos).
    La conversación queda intacta y lo que la persona escribió se conserva en la caja."""
    gr.Warning(texto)
    return vista(sesion, "⚠️ " + texto, caja)


def turno(texto, etiqueta, sesion, requiere_pendiente=False):
    """Un turno completo del chat. `texto` va al Chat; `etiqueta` es lo que se muestra como mensaje de la persona."""
    if not CONFIG["clave"] or not CONFIG["modelo"]:
        return rechazar(sesion, "Falta GROQ_API_KEY o GROQ_MODEL. Configúralos e inicia de nuevo.", texto)
    with sesion.lock:
        if requiere_pendiente and sesion.chat.pendiente is None:
            return rechazar(sesion, "No hay ninguna solicitud pendiente.")
        try:
            respuesta = sesion.chat.responder(texto)
        except ERRORES as error:  # el historial no cambió; el texto escrito se conserva en la caja
            registrar("TURNO FALLIDO (Gradio, el historial no cambió)", f"pregunta: {texto}\nerror: {type(error).__name__}: {error}")
            traceback.print_exc()  # el detalle completo queda en la consola donde corre app_gradio.py
            return rechazar(sesion, texto_error(error), texto if etiqueta == texto else "")
        sesion.pantalla = sesion.pantalla + [{"role": "user", "content": etiqueta},
                                             {"role": "assistant", "content": respuesta}]
    return vista(sesion, AVISO_PENDIENTE if sesion.chat.pendiente else "Listo.")


def enviar(mensaje, sesion):
    mensaje = (mensaje or "").strip()
    if not mensaje:
        return rechazar(sesion, "Escribe un mensaje antes de enviarlo.")
    if mensaje.casefold() in PALABRAS_REINICIO:  # igual que el comando REINICIAR de la terminal
        return reiniciar(sesion)
    return turno(mensaje, mensaje, sesion)


def confirmar(sesion):
    # "sí" lo interpreta Python (es_afirmacion), no el modelo: el botón es solo un atajo para escribirlo.
    return turno("sí", "✅ Confirmar", sesion, requiere_pendiente=True)


def descartar(sesion):
    return turno("no", "❌ Descartar", sesion, requiere_pendiente=True)


def reiniciar(sesion):
    """Conversación nueva: historial solo con system, sin solicitud pendiente y pantalla vacía.
    Las reservas ya guardadas en la FastAPI no se tocan."""
    with sesion.lock:
        sesion.chat.reiniciar()
        sesion.pantalla = []
    registrar("REINICIO (Gradio)", historial_como_texto(sesion.chat.historial))
    return vista(sesion, "Conversación reiniciada. Las reservas guardadas se conservan.")


def crear_interfaz(titulo="ViajesYa · Asistente de reservas"):
    with gr.Blocks(title=titulo) as demo:
        gr.Markdown(f"## {titulo}\nConsulta destinos, salidas y cupos, y gestiona tus reservas. "
                    "Con **Reiniciar conversación** empiezas de cero; tus reservas ya guardadas se conservan.")
        estado = gr.State(value=Sesion)  # una Sesion nueva por cada pestaña del navegador
        pantalla = gr.Chatbot(label="Conversación", height=420, buttons=[])
        entrada = gr.Textbox(label="Tu mensaje", placeholder="Ej.: quiero ir a la Macarena en diciembre",
                             elem_id="mensaje_chat")
        aviso = gr.Markdown("Listo para comenzar.")

        with gr.Row():
            boton_enviar = gr.Button("Enviar", variant="primary", elem_id="enviar_chat")
            boton_confirmar = gr.Button("Confirmar", interactive=False, elem_id="confirmar_chat")
            boton_descartar = gr.Button("Descartar", interactive=False, elem_id="descartar_chat")
            boton_reiniciar = gr.Button("Reiniciar conversación", elem_id="reiniciar_chat")

        with gr.Accordion("Revisar historial (mensajes que se envían a Groq)", open=False):
            historial_debug = gr.JSON(label="Historial de esta sesión")

        salidas = [pantalla, estado, entrada, aviso, boton_confirmar, boton_descartar, historial_debug]
        boton_enviar.click(enviar, inputs=[entrada, estado], outputs=salidas)
        entrada.submit(enviar, inputs=[entrada, estado], outputs=salidas)
        boton_confirmar.click(confirmar, inputs=[estado], outputs=salidas)
        boton_descartar.click(descartar, inputs=[estado], outputs=salidas)
        boton_reiniciar.click(reiniciar, inputs=[estado], outputs=salidas)
        pantalla.clear(reiniciar, inputs=[estado], outputs=salidas)

    return demo


def main():
    clave = CONFIG["clave"] or getpass("API key de Groq: ").strip()
    modelo = CONFIG["modelo"] or input("ID del modelo de Groq: ").strip()
    if not clave or not modelo:
        print("Necesito la API key y el ID del modelo.")
        return
    modelo = base.elegir_modelo(clave, modelo)
    if not modelo:
        print("No hay un modelo válido; no puedo continuar.")
        return
    CONFIG.update(clave=clave, modelo=modelo)
    print(f"Usando el modelo: {modelo}")
    if not base.obtener_servicios():
        print("Aviso: no pude leer /servicios de la FastAPI. ¿Está encendida iniciar_api.bat?")
    registrar("INICIO DE GRADIO", f"modelo={modelo}")
    crear_interfaz().queue(default_concurrency_limit=8).launch(server_name="127.0.0.1", server_port=7860)


if __name__ == "__main__":
    main()
