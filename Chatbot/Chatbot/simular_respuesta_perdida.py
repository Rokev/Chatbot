"""Práctica T24: pierde una respuesta después de guardar en la API.

Ejecutar en lugar de bot_telegram.py, con la misma configuración.
Utilizar datos de práctica. La API permanece en ejecución.
"""

import bot_telegram


def main():
    original = bot_telegram.ClienteAPI.ejecutar
    pendiente = True

    def ejecutar_con_perdida(self, *args, **kwargs):
        nonlocal pendiente
        respuesta = original(self, *args, **kwargs)
        if pendiente:
            pendiente = False
            print("Práctica T24: la API respondió; se oculta una sola respuesta al bot.")
            raise TimeoutError("Respuesta perdida de forma controlada después de guardar")
        return respuesta

    bot_telegram.ClienteAPI.ejecutar = ejecutar_con_perdida
    try:
        print("Simulación de una respuesta perdida. Use reservas de práctica.")
        bot_telegram.main()
    finally:
        bot_telegram.ClienteAPI.ejecutar = original


if __name__ == "__main__":
    main()
