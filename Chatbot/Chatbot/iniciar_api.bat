@echo off
chcp 65001 >nul
cd /d "%~dp0Demos\Demostraciones_02_03"
if not exist .venv (
  echo Creando entorno virtual e instalando dependencias...
  python -m venv .venv || py -m venv .venv
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt
)
echo FastAPI de ViajesYa en http://127.0.0.1:8011/docs  (Ctrl+C para detener)
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8011 --workers 1
pause
