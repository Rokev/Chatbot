@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python -c "import sys, telegram; sys.exit(0 if int(telegram.__version__.split('.')[0]) >= 22 else 1)" 2>nul || python -m pip install "python-telegram-bot>=22,<23"
echo Asegurate de tener iniciar_api.bat abierto en otra ventana.
echo Se piden ocultos: token de BotFather, clave privada de la API (la MISMA de iniciar_api.bat) y API key de Groq. Luego, el ID del modelo.
echo Cuando diga "Bot en ejecucion" abre tu bot en Telegram y escribe /start
python bot_telegram.py || py bot_telegram.py
pause
