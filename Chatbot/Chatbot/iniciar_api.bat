@echo off
chcp 65001 >nul
cd /d "%~dp0Demos\Demostraciones_02_03"
if not exist .venv (
  echo Creando entorno virtual e instalando dependencias...
  python -m venv .venv || py -m venv .venv
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt
)
if not defined CHATBOT_API_KEY (
  echo Clave privada compartida con el bot de Telegram: minimo 16 caracteres ASCII, sin tildes.
  echo Debe ser EXACTAMENTE la misma que escribas en iniciar_telegram.bat. No es el token de BotFather ni la clave de Groq.
  for /f "usebackq delims=" %%K in (`.\.venv\Scripts\python.exe -c "import getpass; print(getpass.getpass('Clave privada de la API (oculta): '))"`) do set "CHATBOT_API_KEY=%%K"
)
echo FastAPI de ViajesYa en http://127.0.0.1:8011/docs  (Ctrl+C para detener)
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8011 --workers 1
pause
