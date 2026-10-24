// Este código ya está incluido en Demo_03_Flowise_FastAPI.json.
// Flowise en Docker Desktop, API ejecutada en Windows:
const API_URL = 'http://localhost:3000';
// Si Flowise se ejecuta con npm en Windows: http://127.0.0.1:8011
const fetch = require('node-fetch');
const mensaje = String($input || '').trim();
const session_id = $flow.sessionId || $flow.chatId;
if (!session_id) return 'No se recibió una sesión. Abre una conversación nueva.';
let datos = {};
if (!['confirmar', 'abortar', 'no', '/reset'].includes(mensaje.toLowerCase())) {
    try {
        datos = typeof $extraccion === 'string'
            ? JSON.parse($extraccion.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, ''))
            : $extraccion;
        if (!datos || Array.isArray(datos) || typeof datos !== 'object') throw new Error('Formato');
    } catch (_) {
        return 'No pude interpretar los datos. Prueba: Quiero reservar un corte para 2026-09-18 a las 16:00, me llamo Laura.';
    }
}
try {
    const response = await fetch(API_URL + '/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({session_id, mensaje, datos}),
        timeout: 8000
    });
    const resultado = await response.json();
    if (typeof resultado.respuesta === 'string') return resultado.respuesta;
    if (response.status === 422) return 'La API rechazó los datos. Usa una fecha AAAA-MM-DD, una hora HH:MM y un servicio válido.';
    return 'La API no devolvió un resultado válido. Revisa su terminal antes de repetir la operación.';
} catch (_) {
    return 'No pude verificar el resultado en la API. Revisa que esté iniciada y su dirección. Antes de repetir una confirmación, verifica reservas.db.';
}
