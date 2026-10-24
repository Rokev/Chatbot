"""Prueba reproducible sin Groq ni Flowise. No modifica las reservas de la clase."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
import main
from almacen_sqlite import AgendaSQLite


def probar():
    with TemporaryDirectory() as carpeta:
        archivo = Path(carpeta) / 'reservas.json'
        archivo.write_text('[]', encoding='utf-8')
        original = main.ARCHIVO
        main.ARCHIVO = archivo
        agenda_original = main.agenda  # protege reservas.db: esta prueba antigua usa una base temporal
        main.agenda = AgendaSQLite(Path(carpeta) / 'reservas.db', clave_cliente=main._normalizar)
        main.SESIONES.clear()
        try:
            with TestClient(main.app) as api:
                fecha = datetime.now(main.ZONA).date() + timedelta(days=2)
                while fecha.weekday() == 6:
                    fecha += timedelta(days=1)
                dia = fecha.isoformat()
                datos = dict(cliente='Andrea', servicio='corte', fecha=dia, hora='09:00', confirmado=True)
                assert api.get('/servicios').status_code == 200
                assert '09:00' in api.get('/disponibilidad', params={'fecha': dia, 'servicio': 'corte'}).json()['horarios']
                assert api.post('/reservas', json={**datos, 'confirmado': False}).status_code == 422
                assert api.post('/reservas', json={**datos, 'hora': '25:00'}).status_code == 422
                assert api.post('/reservas', json={**datos, 'servicio': 'inventado'}).status_code == 422
                assert api.post('/reservas', json={**datos, 'hora': '18:00'}).status_code == 409
                assert api.post('/reservas', json={**datos, 'fecha': '2000-01-01'}).status_code == 422
                domingo = fecha + timedelta(days=(6-fecha.weekday()) % 7)
                assert api.get('/disponibilidad', params={'fecha': domingo.isoformat(), 'servicio': 'corte'}).json()['horarios'] == []
                # Dos peticiones compiten por el mismo horario: solo una se registra.
                with ThreadPoolExecutor(max_workers=2) as pool:
                    respuestas = list(pool.map(lambda _: api.post('/reservas', json=datos), range(2)))
                assert sorted(r.status_code for r in respuestas) == [201, 409]
                reserva = next(r.json() for r in respuestas if r.status_code == 201)
                codigo = reserva['codigo']
                assert len(json.loads(archivo.read_text(encoding='utf-8'))) == 1
                main.SESIONES.clear()  # La reserva sobrevive a perder el estado en memoria.
                assert api.get('/reservas/' + codigo).json()['estado'] == 'activa'
                assert api.delete('/reservas/' + codigo).status_code == 422
                assert api.get('/reservas/INEXISTENTE').status_code == 404
                libres = api.get('/disponibilidad', params={'fecha': dia, 'servicio': 'barba'}).json()['horarios']
                assert '09:00' not in libres and '09:30' in libres
                # Cruce de intervalos con distinta hora inicial.
                r = {**reserva, 'hora': '09:15'}
                libres = main.horarios_libres(fecha, 'corte', [r])
                assert '09:00' not in libres and '09:30' not in libres and '10:00' in libres
                assert api.delete('/reservas/' + codigo, params={'confirmado': True}).json()['estado'] == 'cancelada'
                assert api.delete('/reservas/' + codigo, params={'confirmado': True}).status_code == 200
                assert '09:00' in api.get('/disponibilidad', params={'fecha': dia, 'servicio': 'corte'}).json()['horarios']

                def chat(texto, extraccion=None, sesion='grupo-1'):
                    return api.post('/chat', json={'session_id': sesion, 'mensaje': texto, 'datos': extraccion or {}})

                extraccion = {k: v for k, v in datos.items() if k != 'confirmado'}
                extraccion['intencion'] = 'reservar'
                r = chat('Quiero reservar', extraccion).json()
                assert r['estado_sesion']['pendiente']['datos']['hora'] == '09:00'
                assert len(json.loads(archivo.read_text(encoding='utf-8'))) == 1
                assert 'No hay un resumen' in chat('CONFIRMAR', sesion='grupo-2').json()['respuesta']
                r = chat('Mejor a las 10:00', {'intencion': 'continuar', 'hora': '10:00'}).json()
                assert r['estado_sesion']['pendiente']['datos']['hora'] == '10:00'
                assert 'pendiente' in chat('Cuánto cuesta', {'intencion': 'informacion'}).json()['estado_sesion']
                assert 'pendiente' in chat('Sí', {}).json()['estado_sesion']  # Solo CONFIRMAR autoriza.
                r = chat('CONFIRMAR').json()
                assert 'Reserva registrada' in r['respuesta']
                codigo2 = r['estado_sesion']['ultimo_codigo']
                assert api.get('/reservas/' + codigo2).json()['hora'] == '10:00'
                assert 'No hay un resumen' in chat('CONFIRMAR').json()['respuesta']
                assert len(json.loads(archivo.read_text(encoding='utf-8'))) == 2
                chat('/reset')
                assert api.get('/reservas/' + codigo2).json()['estado'] == 'activa'
                chat('Cancelar ' + codigo2, {'intencion': 'cancelar', 'codigo': codigo2})
                assert api.get('/reservas/' + codigo2).json()['estado'] == 'activa'
                assert 'Reserva cancelada' in chat('CONFIRMAR').json()['respuesta']
                assert api.get('/reservas/' + codigo2).json()['estado'] == 'cancelada'
                assert chat('Datos maliciosos', {'intencion': 'continuar', 'confirmado': True}).status_code == 422

                # Un horario puede ocuparse entre el resumen y la confirmación.
                chat('Reservar', extraccion)
                assert api.post('/reservas', json=datos).status_code == 201
                assert chat('CONFIRMAR').status_code == 409
                assert 'pendiente' not in main.SESIONES['grupo-1']
                antes = archivo.read_text(encoding='utf-8')
                with patch.object(main.os, 'replace', side_effect=OSError('Prueba de disco')):
                    assert api.post('/reservas', json={**datos, 'hora': '11:00'}).status_code == 503
                assert archivo.read_text(encoding='utf-8') == antes
                archivo.write_text('{archivo incompleto', encoding='utf-8')
                assert api.post('/reservas', json={**datos, 'hora': '11:00'}).status_code == 503
                assert archivo.read_text(encoding='utf-8') == '{archivo incompleto'
                print('OK: API, JSON, confirmaciones, correcciones, sesiones, concurrencia, cancelación y fallos de almacenamiento.')
        finally:
            main.ARCHIVO = original
            main.agenda = agenda_original
            main.SESIONES.clear()


if __name__ == '__main__':
    probar()
