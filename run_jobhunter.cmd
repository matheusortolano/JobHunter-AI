@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"
set "QUEUE=%ROOT%src\ai_queue.py"
set "LOGDIR=%ROOT%data\logs"
set "LOG=%LOGDIR%\ai_queue.log"

if not exist "%PYTHON%" (
    echo ERRO: Python do ambiente virtual nao encontrado.
    exit /b 1
)

if not exist "%QUEUE%" (
    echo ERRO: ai_queue.py nao encontrado.
    exit /b 1
)

if "%~1"=="" goto status
if /I "%~1"=="--status" goto status
if /I "%~1"=="--run" goto run

echo Uso: run_jobhunter.cmd [--status ^| --run]
exit /b 2

:status
"%PYTHON%" -u "%QUEUE%" --status
exit /b %ERRORLEVEL%

:run
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

if not exist "%LOGDIR%" (
    echo ERRO: Nao foi possivel criar a pasta de logs.
    exit /b 1
)

echo.>> "%LOG%"
echo ===== Inicio: %date% %time% ===== >> "%LOG%"

"%PYTHON%" -u "%QUEUE%" --run >> "%LOG%" 2>&1
set "RESULTADO=%ERRORLEVEL%"

echo ===== Fim: %date% %time% ^| Codigo: %RESULTADO% ===== >> "%LOG%"

echo Execucao finalizada. Codigo: %RESULTADO%
echo Log: "%LOG%"

exit /b %RESULTADO%