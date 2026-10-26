@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python -c "import telegram" 2>nul || python -m pip install "python-telegram-bot>=21"
echo Asegurate de tener iniciar_api.bat abierto en otra ventana.
echo El token de BotFather y la API key de Groq se piden ocultos; el ID del modelo se pide enseguida.
echo Cuando diga "Bot en ejecucion" abre tu bot en Telegram y escribe /start
python bot_telegram.py || py bot_telegram.py
pause