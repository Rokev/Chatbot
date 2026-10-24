@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo Asegurate de tener iniciar_api.bat abierto en otra ventana.
echo La API key se pide oculta; el ID del modelo se pide enseguida.
python chatbot_memoria.py || py chatbot_memoria.py
pause
