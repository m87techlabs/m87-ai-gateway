@echo off
"%~dp0m87-gateway.exe" --open-browser %*
set "gateway_exit=%errorlevel%"
pause
exit /b %gateway_exit%
