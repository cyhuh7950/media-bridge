@echo off
setlocal
set "MEDIA_BRIDGE_HOME=%~dp0"
set "PYTHONPATH=%MEDIA_BRIDGE_HOME%app"
set "MEDIA_BRIDGE_HTTP_HOST=127.0.0.1"
set "MEDIA_BRIDGE_HTTP_PORT=8765"
"%MEDIA_BRIDGE_HOME%runtime\Scripts\python.exe" -c "from media_bridge.entrypoints import run_http; run_http()"
endlocal
