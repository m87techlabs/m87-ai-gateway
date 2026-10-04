@echo off
"%~dp0m87-gateway.exe" --stop %*
set "gateway_exit=%errorlevel%"
pause
exit /b %gateway_exit%
