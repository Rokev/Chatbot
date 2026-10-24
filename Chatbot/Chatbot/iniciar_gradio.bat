@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python -c "import gradio" 2>nul || python -m pip install "gradio>=6,<7"
echo Asegurate de tener iniciar_api.bat abierto en otra ventana.
echo La API key se pide oculta; el ID del modelo se pide enseguida.
echo Cuando diga "Running on local URL" abre http://127.0.0.1:7860
python app_gradio.py || py app_gradio.py
pause
