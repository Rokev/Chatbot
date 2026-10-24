# Bitácora del segundo corte — ViajesYa

> **Estado del documento:** borrador integrado a partir del código entregado, las bitácoras `BITACORA_clase07.md` y `BITACORA_clase08.md`, la guía `index.html` y el documento *ViajesYa · Pruebas y evidencias*.  
> **Importante:** las fechas exactas de cada avance, los nombres de los integrantes y las capturas de ejecución deben completarse con información real del equipo. No se inventan en esta bitácora.

## 1. Identificación del proyecto

- **Proyecto:** ViajesYa.
- **Propósito:** chatbot para consultar viajes colombianos, revisar salidas y disponibilidad, y gestionar reservas.
- **Interfaz:** Gradio.
- **Backend:** API desarrollada con FastAPI.
- **Persistencia:** SQLite, mediante el archivo `reservas.db`.
- **Modelo conversacional:** servicio compatible con la API de chat completions de Groq, configurado mediante variables de entorno.
- **Integrantes:** Natalia Andrea Morales Navarrete, Miguel Angel Romero Osorio, Kevin Andres Parra
- **Asignatura y docente:** Electiva 2, Robert Erick Garcia Rey 
- **Repositorio:** https://github.com/Rokev/Chatbot.git
- **Periodo:** segundo corte.

## 2. Contexto, problema y alcance

ViajesYa ofrece salidas a destinos nacionales en fechas programadas y con un número limitado de cupos. La necesidad que atiende el proyecto es facilitar la consulta de destinos y la gestión de solicitudes de reserva mediante una conversación, sin depender de que toda la información se escriba en un único mensaje.

El chatbot permite recopilar los datos de una solicitud en varios turnos, mostrar un resumen y pedir confirmación antes de ejecutar la operación. La API aplica las reglas del negocio y SQLite conserva las reservas, incluso cuando se reinicia la conversación o el proceso de la API.

### Funcionalidades incluidas

- Consultar los destinos y las salidas programadas.
- Consultar cupos disponibles para una salida.
- Recopilar datos de una reserva a través de varios mensajes.
- Confirmar o descartar una solicitud pendiente.
- Crear, consultar, modificar y cancelar reservas.
- Evitar reservas cuando no hay cupos o cuando el intervalo de un cliente se cruza con otro viaje activo.
- Mantener separada la memoria de conversación de los registros permanentes de reservas.
- Reiniciar una conversación sin eliminar las reservas guardadas.
- Consultar los registros persistidos en SQLite.

### Límites y aspectos pendientes

Las salidas y sus cupos están definidos en `viajes.py`; por tanto, el calendario debe actualizarse cuando cambien las fechas o la oferta del negocio. El chatbot necesita una configuración válida del modelo y de la credencial de Groq para las pruebas conversacionales reales. La prueba en dos ventanas del navegador con Gradio y el modelo real figura como pendiente en la bitácora anterior y debe ejecutarse y documentarse en el equipo. Las capturas y las fechas reales de las pruebas también deben agregarse antes de la entrega final.

## 3. Arquitectura y organización de archivos

El sistema separa la conversación de las reglas del negocio y del almacenamiento. El recorrido general es:

1.  La persona escribe en la interfaz Gradio.
2.  `app_gradio.py` recibe el texto mediante `enviar()` y lo pasa a `turno()`.
3.  `turno()` trabaja con la sesión y llama a `Chat.responder()` en `chatbot_memoria.py`.
4.  El componente conversacional usa el modelo para interpretar el mensaje y mantener el contexto de la conversación.
5.  Cuando se requiere consultar o ejecutar una operación del negocio, el código llama a la API FastAPI; Gradio no modifica SQLite directamente.
6.  `main.py` valida la operación y usa `almacen_sqlite.py` para consultar o actualizar `reservas.db`.
7.  La API devuelve el resultado y el chatbot lo comunica a la persona.

| Archivo o componente  | Responsabilidad                                                                                               |
|:----------------------|:--------------------------------------------------------------------------------------------------------------|
| `app_gradio.py`       | Presenta la interfaz, recibe los mensajes, actualiza la pantalla y gestiona las acciones de los botones.      |
| `chatbot_memoria.py`  | Administra el historial, la solicitud pendiente, las respuestas del chatbot y el reinicio de la conversación. |
| `consulta_llm2.py`    | Contiene la integración utilizada para llamar a los endpoints de la API del negocio.                          |
| `main.py`             | Expone la API FastAPI, valida las solicitudes y coordina las operaciones.                                     |
| `almacen_sqlite.py`   | Implementa el almacenamiento SQLite, las consultas, las transacciones y las operaciones de reservas.          |
| `viajes.py`           | Define las salidas programadas, sus fechas y sus cupos.                                                       |
| `negocio.json`        | Contiene el catálogo de destinos, precios, duración, anticipación mínima, horarios y condiciones.             |
| `reservas.db`         | Base de datos persistente de las reservas.                                                                    |
| `probar_sqlite.py`    | Prueba almacenamiento, cupos, cruces, concurrencia, persistencia y migración en bases temporales.             |
| `probar_cruces.py`    | Prueba específicamente los intervalos, los cruces y los casos relacionados con disponibilidad.                |
| `BITACORA_clase07.md` | Registra el avance previo de conversación con historial.                                                      |
| `BITACORA_clase08.md` | Registra la integración de Gradio, SQLite y disponibilidad.                                                   |

### Direcciones de ejecución documentadas

- API FastAPI: `http://127.0.0.1:8011`
- Documentación interactiva de la API: `http://127.0.0.1:8011/docs`
- Interfaz Gradio: `http://127.0.0.1:7860`

Las rutas, carpetas y comandos definitivos deben verificarse con el `README.md` que acompañe la versión final del repositorio.

## 4. Consumo del modelo conversacional

El chatbot utiliza una API de chat completions de Groq. La integración se configura con variables de entorno, entre ellas `GROQ_API_KEY` y `GROQ_MODEL`. La dirección de la API del negocio se configura mediante `CHATBOT_API_URL` cuando corresponde.

La llamada al modelo envía una lista ordenada de mensajes. El historial conserva el mensaje de sistema y los turnos anteriores; la pregunta actual se añade al final para que el modelo pueda interpretar referencias a información que la persona ya proporcionó.

| Elemento     | Descripción                                                                                         |
|:-------------|:----------------------------------------------------------------------------------------------------|
| Servicio     | Endpoint de chat completions del proveedor Groq utilizado por el código.                            |
| Credenciales | `GROQ_API_KEY`, configurada como variable de entorno y no publicada en el repositorio.              |
| Modelo       | `GROQ_MODEL`, con el identificador que se haya configurado para la ejecución.                       |
| Entrada      | Lista `messages`, con el mensaje `system`, los mensajes anteriores y el mensaje actual del usuario. |
| Contexto     | Instrucciones del chatbot y datos de la conversación que se mantienen en el historial.              |
| Respuesta    | Contenido devuelto por el modelo, que el chatbot interpreta y muestra en la interfaz.               |

La clave real no debe incluirse en capturas, archivos versionados ni documentación. Los detalles exactos del payload y de los encabezados deben contrastarse con la versión final de la función que realiza la llamada al modelo antes de entregar; esta bitácora no reproduce credenciales ni supone valores que no están documentados.

El modelo ayuda a interpretar el lenguaje de la persona, pero las reglas de cupos, fechas, cruces y persistencia se verifican en la lógica de la aplicación y en la API. La respuesta del modelo, por sí sola, no confirma una reserva.

## 5. Conversación, historial y sesiones

### Historial

La memoria de la conversación se mantiene separada de la base de datos. En la versión de Gradio, cada pestaña mantiene una `Sesion` en `gr.State`; dentro de ella se encuentra `Sesion.chat.historial` y el estado de la solicitud pendiente. Esto permite que dos pestañas tengan conversaciones independientes.

El historial contiene mensajes con roles como `system`, `user` y `assistant`. Al reiniciar, el historial vuelve a contener únicamente el mensaje de sistema y se elimina la solicitud pendiente. Las reservas guardadas no se eliminan.

### Solicitud pendiente y confirmación

La persona puede indicar el destino, el nombre y la fecha en distintos mensajes. Cuando se reúnen los datos, el chatbot presenta un resumen y solicita confirmación. La operación no debe guardarse mientras la solicitud siga pendiente. Si la persona descarta la solicitud, no debe ejecutarse la creación de la reserva.

Las acciones de confirmar y descartar se gestionan a través de la interfaz. Una vez confirmada la operación, la API devuelve el resultado y, si la reserva fue aceptada, su código de referencia.

### Reinicio

El reinicio limpia la conversación y su solicitud pendiente. No borra filas de `reservas.db`, porque la memoria del chat y la persistencia del negocio son componentes diferentes.

## 6. API y persistencia en SQLite

La API FastAPI recibe las operaciones del negocio. Entre los endpoints documentados se encuentran:

| Operación                | Endpoint                                    | Función                                                                          |
|:-------------------------|:--------------------------------------------|:---------------------------------------------------------------------------------|
| Consultar catálogo       | `GET /viajes`                               | Devuelve los viajes programados y sus datos relevantes.                          |
| Consultar disponibilidad | `GET /disponibilidad`                       | Informa si una salida tiene cupos y si existe un cruce para el cliente indicado. |
| Crear reserva            | `POST /reservas`                            | Crea la reserva tras la confirmación y las validaciones.                         |
| Consultar reserva        | `GET /reservas/{codigo}`                    | Busca una reserva por su código.                                                 |
| Modificar reserva        | `PUT /reservas/{codigo}`                    | Cambia los datos de una reserva activa si el nuevo intervalo es válido.          |
| Cancelar reserva         | `DELETE /reservas/{codigo}?confirmado=true` | Cambia el estado de la reserva a cancelada.                                      |

### Tabla `reservas`

La tabla contiene los datos principales de cada reserva. Entre los campos utilizados por el proyecto están:

- `codigo`: identificador de la reserva.
- `cliente` y `cliente_clave`: nombre del cliente y clave normalizada usada para comparar clientes.
- `servicio`: destino reservado.
- `fecha`: fecha de salida.
- `estado`: estado de la reserva, por ejemplo `activa` o `cancelada`.
- `precio_cop`: precio de la reserva en pesos colombianos.
- `duracion_viaje_dias`: duración del viaje en días.
- `creada_en`: fecha y hora de creación.
- `modificada_en`: fecha y hora de la última modificación, cuando aplica.
- `cancelada_en`: fecha y hora de cancelación, cuando aplica.

SQLite conserva los registros en un archivo, por lo que no dependen de que el proceso de FastAPI permanezca activo. La base usada en ejecución es `reservas.db`; las pruebas automatizadas utilizan bases temporales para evitar modificar los datos reales de prueba.

### Transacciones

Las operaciones que escriben datos comprueban las reglas y guardan los cambios dentro de una transacción. En el método de creación se inicia con `BEGIN IMMEDIATE`, se revisan cupos y cruces y luego se inserta la fila. Si todo sale bien, se confirma con `COMMIT`; si ocurre un error, se revierte la operación.

La modificación repite las comprobaciones excluyendo la reserva que se está editando. Si el nuevo intervalo no es válido, `ROLLBACK` conserva los datos anteriores. La cancelación actualiza el estado y la fecha de cancelación; no elimina la fila.

Este diseño reduce el riesgo de que dos solicitudes ocupen simultáneamente el último cupo y evita que una modificación fallida deje la reserva en un estado parcial.

## 7. Reglas de disponibilidad y negocio

ViajesYa trabaja con salidas de fecha fija, no con citas de una hora. Cada reserva ocupa el intervalo:

`[fecha de salida, fecha de salida + duración del viaje)`

El día de salida se incluye y el día final del intervalo no se incluye. Por eso, si un viaje termina y otro comienza justo en el límite siguiente, no existe cruce.

Las reglas principales son:

1.  **Cupos limitados:** cada combinación de destino y fecha tiene un máximo de reservas activas. Si se agotan los cupos, la API rechaza la operación con HTTP 409.
2.  **Anticipación mínima:** cada destino exige reservar con una cantidad mínima de días de anticipación. Si no se cumple, la API rechaza la solicitud con HTTP 422.
3.  **Fecha programada:** solo se admiten las fechas configuradas en `viajes.py`; una fecha distinta se rechaza con HTTP 422.
4.  **Sin cruces para el mismo cliente:** dos viajes activos de una misma persona no pueden solaparse. El intento se rechaza con HTTP
    409. 
5.  **Confirmación:** crear, modificar y cancelar requieren confirmación explícita.
6.  **Cancelación lógica:** cancelar cambia el estado a `cancelada`, libera el cupo y deja de ocupar el intervalo, pero conserva la fila para consulta e historial.
7.  **Horario del negocio:** el documento de pruebas indica atención de lunes a viernes, de 08:00 a 18:00, en la zona horaria `America/Bogota`.

### Catálogo de destinos documentado

Los precios, duraciones y cupos siguientes proceden de la documentación de pruebas y de los archivos de configuración entregados. Las fechas son las programadas en la versión revisada y deben actualizarse cuando corresponda.

| Destino                     | Precio (COP) | Duración | Anticipación mínima | Salidas documentadas      |
|:----------------------------|-------------:|---------:|--------------------:|:--------------------------|
| Santa Marta                 |     \$50.000 |   2 días |      5 días hábiles | 13-nov-2026 y 18-dic-2026 |
| Caño Cristales              |  \$3.587.000 |   3 días |      2 días hábiles | 20-nov-2026 y 11-dic-2026 |
| Nuquí – Guachalito          |    \$975.000 |   4 días |      3 días hábiles | 27-nov-2026 y 08-ene-2027 |
| Manizales – Nevado del Ruiz |    \$830.000 |   3 días |      2 días hábiles | 14-nov-2026 y 05-dic-2026 |
| Amazonas                    |  \$1.485.000 |   4 días |      3 días hábiles | 04-dic-2026 y 15-ene-2027 |
| Capurganá y Sapzurro        |  \$1.130.000 |   4 días |      3 días hábiles | 12-dic-2026 y 22-ene-2027 |

## 8. Evolución del proyecto durante el corte

La siguiente secuencia integra los avances que describen las bitácoras anteriores. Deben añadirse las fechas reales y los nombres de quienes participaron en cada avance; no es posible deducirlos de los archivos entregados.

| Avance                             | Cambio realizado                                                                                 | Dificultad o decisión                                                                                              | Cómo se comprueba                                                |
|:-----------------------------------|:-------------------------------------------------------------------------------------------------|:-------------------------------------------------------------------------------------------------------------------|:-----------------------------------------------------------------|
| Integración inicial con el modelo  | Se creó la consulta al modelo y se configuró la conversación con instrucciones.                  | La credencial y el identificador del modelo deben configurarse sin exponer secretos.                               | Ejecutar una pregunta simple y verificar la respuesta.           |
| Conversación con historial         | Se incorporó `chatbot_memoria.py` para conservar mensajes entre turnos.                          | Un turno fallido no debe incorporarse como si hubiese respondido correctamente; el historial debe tener un límite. | Ingresar datos en varios mensajes y consultar el historial.      |
| Separación entre memoria y negocio | El reinicio limpia el historial y la solicitud pendiente, no las reservas.                       | Evitar confundir la memoria conversacional con los registros permanentes.                                          | Reiniciar el chat y comprobar que las reservas siguen en SQLite. |
| Interfaz Gradio                    | Se integró la conversación con una interfaz web y botones para confirmar, descartar y reiniciar. | Cada pestaña debe mantener su propia sesión.                                                                       | Probar las acciones de la interfaz y comparar los historiales.   |
| Fechas y cupos por viaje           | Se creó `viajes.py` para definir salidas fijas y capacidad.                                      | La lógica de viajes debe comprobar tanto la fecha como el cupo disponible.                                         | Consultar `/viajes` y `/disponibilidad`.                         |
| Persistencia con SQLite            | Se incorporó `almacen_sqlite.py` y la tabla `reservas`.                                          | Las comprobaciones y escrituras deben ejecutarse como una transacción.                                             | Ejecutar `probar_sqlite.py` y consultar las filas de prueba.     |
| Reglas de cruce                    | Se implementó la validación de intervalos activos por cliente.                                   | Las fechas diferentes también pueden solaparse si la duración de un viaje abarca la salida del siguiente.          | Ejecutar `probar_cruces.py` y revisar los códigos HTTP.          |
| Pruebas de operaciones             | Se documentaron creación, modificación, cancelación, descarte y reinicio.                        | La operación rechazada no debe dejar cambios parciales.                                                            | Revisar las respuestas de la API y los datos en SQLite.          |

### Registro cronológico que debe completar el equipo

| Fecha real     | Participantes | Actividad o cambio                     | Dificultad encontrada y solución | Evidencia o enlace            |
|:---------------|:--------------|:---------------------------------------|:---------------------------------|:------------------------------|
| [AAAA-MM-DD] | [nombres]   | Primera llamada al modelo              | [completar]                    | [captura, archivo o commit] |
| [AAAA-MM-DD] | [nombres]   | Historial de conversación              | [completar]                    | [captura, archivo o commit] |
| [AAAA-MM-DD] | [nombres]   | Integración de Gradio                  | [completar]                    | [captura, archivo o commit] |
| [AAAA-MM-DD] | [nombres]   | Integración de SQLite y disponibilidad | [completar]                    | [captura, archivo o commit] |
| [AAAA-MM-DD] | [nombres]   | Pruebas y correcciones finales         | [completar]                    | [captura, archivo o commit] |

## 9. Pruebas y resultados

Los archivos `BITACORA_clase08.md`, `probar_sqlite.py`, `probar_cruces.py` y el documento *ViajesYa · Pruebas y evidencias* describen pruebas de la lógica del sistema. La bitácora anterior reporta como correctas varias pruebas automatizadas; esto no significa que todas las pruebas manuales de Gradio se hayan ejecutado en el equipo. En particular, la prueba real con dos ventanas de navegador se mantiene pendiente según el registro previo.

| Prueba                              | Entrada o acción                                                                | Resultado esperado                                                                       | Estado respaldado por los archivos entregados                                                                                                                              |
|:------------------------------------|:--------------------------------------------------------------------------------|:-----------------------------------------------------------------------------------------|:---------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Consultar destinos y disponibilidad | Preguntar por viajes, salidas y cupos.                                          | Los destinos y cupos coinciden con la API.                                               | Incluida en la guía de pruebas; adjuntar captura de la ejecución manual.                                                                                                   |
| Solicitud en varios turnos          | Proporcionar destino, nombre y fecha en mensajes separados.                     | El bot reúne los datos y presenta una solicitud pendiente sin crear aún una fila.        | Reportada como OK en la bitácora de clase 08 usando Groq simulado; agregar evidencia de Gradio real.                                                                       |
| Confirmar reserva                   | Confirmar el resumen pendiente.                                                 | La API responde 201 y la reserva queda activa en SQLite.                                 | La prueba automatizada de SQLite incluye creación por API y consulta de la fila.                                                                                           |
| Rechazar un cruce                   | Intentar reservar un viaje que se solapa con otro del mismo cliente.            | HTTP 409 y ninguna fila nueva para el intento rechazado.                                 | Incluida en `probar_cruces.py` y `probar_sqlite.py`.                                                                                                                       |
| Viaje consecutivo                   | Iniciar el siguiente viaje justo al terminar el intervalo anterior.             | La reserva se acepta si no hay solape ni falta de cupos.                                 | Incluida en `probar_cruces.py`.                                                                                                                                            |
| Modificación válida e inválida      | Mover una reserva a un intervalo libre y luego a uno ocupado.                   | La modificación válida se guarda; la inválida devuelve 409 y conserva los datos previos. | Incluida en las pruebas automatizadas y en el plan de evidencias manuales.                                                                                                 |
| Cancelación                         | Cancelar una reserva activa.                                                    | La fila permanece con estado `cancelada`; se libera cupo e intervalo.                    | Incluida en las pruebas automatizadas.                                                                                                                                     |
| Descartar solicitud                 | Descartar una solicitud pendiente.                                              | No se crea una fila nueva.                                                               | Incluida en la guía manual; adjuntar captura y conteo antes/después.                                                                                                       |
| Reiniciar conversación              | Reiniciar con reservas ya guardadas.                                            | Historial limpio y reservas conservadas.                                                 | Descrito en la bitácora anterior; adjuntar evidencia manual.                                                                                                               |
| Dos sesiones y último cupo          | Confirmar dos solicitudes desde sesiones distintas para una salida con un cupo. | Solo una reserva se acepta; la otra recibe 409.                                          | La prueba de concurrencia automatizada reporta una aceptada y tres rechazadas entre cuatro intentos; la prueba en ventanas normal/privada con Gradio real sigue pendiente. |
| Reiniciar API                       | Detener y volver a iniciar FastAPI.                                             | Las filas guardadas siguen disponibles.                                                  | La prueba automatizada crea una nueva instancia de almacenamiento y verifica persistencia; completar además la captura manual si se exige.                                 |
| Migración desde JSON                | Importar reservas a SQLite.                                                     | La importación repetida no duplica datos y los errores revierten la transacción.         | Incluida en `probar_sqlite.py`.                                                                                                                                            |

### Evidencias que se deben incorporar

Guardar las capturas en una carpeta como `docs/evidencias/` y enlazarlas desde esta bitácora. Cada imagen debe tener un pie que explique qué se estaba probando, qué resultado apareció y qué demuestra.

- [ ] Captura de Gradio con la lista de destinos y salidas.
- [ ] Captura de consulta de cupos y respuesta equivalente de `/disponibilidad`.
- [ ] Conversación en varios turnos y resumen pendiente.
- [ ] Confirmación de reserva con código y fila correspondiente en SQLite.
- [ ] Rechazo HTTP 409 por cruce y ausencia de una fila nueva.
- [ ] Reserva consecutiva aceptada.
- [ ] Modificación válida y modificación rechazada con los datos anteriores conservados.
- [ ] Cancelación, estado `cancelada` y disponibilidad liberada.
- [ ] Solicitud descartada y conteo de filas antes/después.
- [ ] Historial antes y después del reinicio del chat.
- [ ] Dos ventanas con sesiones separadas y resultado del último cupo.
- [ ] API detenida y reiniciada, con la misma reserva consultable.
- [ ] Salida de `probar_sqlite.py` y `probar_cruces.py`.

## 10. Errores, decisiones y limitaciones

- **Memoria frente a persistencia:** se separó el historial del chat de las reservas para que reiniciar la conversación no borre operaciones ya confirmadas.
- **Fechas de salida:** se definieron en `viajes.py` para que el sistema solo permita fechas programadas. Esto facilita la validación, pero exige mantener el calendario actualizado.
- **Cupos y cruces:** las comprobaciones se hacen en la capa de negocio y almacenamiento, no se dejan únicamente a la respuesta del modelo.
- **Concurrencia:** la transacción SQLite evita que dos escrituras ocupen el mismo último cupo tras haberlo comprobado simultáneamente.
- **Pruebas con modelo:** la bitácora previa indica que algunas pruebas conversacionales se hicieron con Groq simulado y que el equipo se estaba quedando sin tokens. Por ello, deben diferenciarse las pruebas automatizadas de las realizadas con el modelo real.
- **Prueba pendiente:** confirmar manualmente la separación de sesiones en una ventana normal y otra privada con Gradio y el modelo real, y guardar las capturas.
- **Credenciales:** no deben guardarse claves reales en archivos compartidos ni capturas.
- **Datos de prueba:** utilizar nombres y datos ficticios al ejecutar las demostraciones.
- **Documentación consistente:** README, bitácora, presentación, código y capturas deben corresponder a la misma versión final.

## 11. Comparación con la versión anterior basada en Flowise y JSON

En los archivos entregados se documenta una evolución hacia una implementación en Python con Gradio, FastAPI y SQLite. La interfaz Gradio se ocupa de la interacción; `chatbot_memoria.py` gestiona el historial y las solicitudes pendientes; FastAPI centraliza las operaciones del negocio; y SQLite guarda los datos de las reservas.

La persistencia pasó a utilizar `reservas.db` para la operación normal. La bitácora de clase 08 señala que `reservas.json` queda como respaldo del origen y que puede importarse a SQLite. También se incorporaron pruebas automatizadas para verificar cupos, cruces, concurrencia, persistencia y migración.

Esta organización da al equipo control directo sobre las validaciones y las operaciones de almacenamiento. La comparación final debe limitarse a funciones que se puedan demostrar en las versiones del proyecto y debe apoyarse en capturas o commits de ambas versiones.

## 12. Conclusiones

El desarrollo de ViajesYa integra una interfaz conversacional con una API que aplica las reglas del negocio y una base SQLite que conserva las reservas. La separación entre historial y persistencia permite reiniciar una conversación sin perder las reservas confirmadas. La validación de cupos y de intervalos evita sobrepasar la capacidad programada y rechaza los viajes que se cruzan para un mismo cliente.

Las pruebas automatizadas descritas en los archivos del proyecto cubren los casos centrales de creación, modificación, cancelación, concurrencia, cruces, persistencia y migración. Para cerrar la entrega, el equipo debe agregar las fechas reales de trabajo, identificar a los participantes, guardar las evidencias visuales y completar la prueba manual de sesiones en ventanas normal y privada. También debe verificar que el README permita ejecutar una copia nueva y que la presentación PDF explique el sistema sin depender de una exposición oral.

## 13. Archivos y recursos relacionados

- `BITACORA_clase07.md`: avance de conversación con historial.
- `BITACORA_clase08.md`: integración de Gradio, SQLite y disponibilidad.
- `app_gradio.py`: interfaz de usuario.
- `chatbot_memoria.py`: conversación, historial y solicitudes pendientes.
- `consulta_llm2.py`: integración con la API del negocio.
- `main.py`: endpoints de FastAPI.
- `almacen_sqlite.py`: almacenamiento y transacciones SQLite.
- `viajes.py`: calendario y cupos.
- `negocio.json`: catálogo y reglas de ViajesYa.
- `probar_sqlite.py`: pruebas automatizadas de persistencia y concurrencia.
- `probar_cruces.py`: pruebas automatizadas de intervalos y disponibilidad.
- `docs/evidencias/`: carpeta recomendada para las capturas.
- `README.md`: instrucciones para instalar y ejecutar una copia nueva.
- `Presentacion_Segundo_Corte.pdf`: explicación autónoma del proyecto para la entrega.

## 14. Lista de revisión para la entrega

- [ ] Completar nombres, asignatura, docente y enlace del repositorio.
- [ ] Completar las fechas reales y participantes de cada avance.
- [ ] Ejecutar una instalación desde una copia nueva y actualizar el README.
- [ ] Confirmar la configuración de variables de entorno sin exponer credenciales.
- [ ] Ejecutar `probar_sqlite.py` y `probar_cruces.py` y conservar sus resultados.
- [ ] Completar la prueba manual de Gradio en ventana normal y privada.
- [ ] Añadir capturas con pies explicativos y enlaces válidos.
- [ ] Revisar que las fechas, precios, duraciones y cupos coincidan en código y documentos.
- [ ] Preparar la presentación PDF con el contexto, arquitectura, recorrido de una reserva, reglas, pruebas, evolución y limitaciones.
- [ ] Verificar que los integrantes puedan explicar cómo una solicitud pasa del chat a la API y termina guardada en SQLite.
