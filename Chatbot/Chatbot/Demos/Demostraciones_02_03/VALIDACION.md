# Validación del paquete

Revisión realizada el 6 de septiembre de 2026.

- Importación de ambos archivos JSON en una instancia aislada de **Flowise 2.2.8** mediante su API de chatflows.
- Ejecución de los nodos reales de Flowise con un **servidor de respuestas de modelo simulado**, sin credenciales reales ni solicitudes a Groq.
- Demo 2: contexto enviado al modelo, historial conservado y separación de una conversación nueva.
- Demo 3: extracción recibida, petición HTTP desde Docker a FastAPI, resumen, corrección de hora, confirmación, registro, consulta y cancelación.
- API: prueba reproducible de disponibilidad, servicios inválidos, fechas pasadas, domingo cerrado, horario fuera de atención y cruce de intervalos.
- Persistencia: dos solicitudes concurrentes al mismo horario producen un registro y un rechazo; la cancelación conserva el registro y libera el espacio.
- Estado: separación de sesiones, reinicio sin borrar reservas, confirmación pendiente, invalidación por cambio de datos y rechazo de confirmación repetida.
- Errores: registro rechazado si el horario se ocupa después del resumen; archivo corrupto y fallo de escritura no se convierten en confirmaciones exitosas.

Ejecutar `python probar_demo.py` en un entorno con las dependencias instaladas para repetir las pruebas de la API. Las pruebas utilizan un archivo temporal y no modifican `reservas.json` del paquete.

**Pendiente de configuración por el docente:** seleccionar una credencial real de Groq y un modelo habilitado en su cuenta. La prueba simulada valida la integración, pero no certifica la calidad de extracción ni las respuestas del modelo real. Ensayar los mensajes del LEEME antes de la clase.
