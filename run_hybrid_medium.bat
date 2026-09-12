@echo off
@chcp 65001 >nul
@echo off
@setlocal EnableExtensions EnableDelayedExpansion

rem ================================================================
rem EDIT ONLY THESE FOUR LINES
rem ================================================================

rem Enter one PDF file or a folder (all PDFs are processed recursively).
set "INPUT_PATH=C:\Users\NIU\Desktop\临时工作区\books"

rem Output root; leave empty to use the input folder. Each PDF gets its own subfolder.
set "OUTPUT_ROOT="

rem Choose local (this computer) or cloud (the official MinerU API).
set "RUN_MODE=local"

rem Token created at https://mineru.net/apiManage.
rem Required only for RUN_MODE=cloud; do not include the Bearer prefix.
set "MINERU_API_TOKEN="

rem ================================================================
rem FIXED SETTINGS BELOW - DO NOT EDIT
rem ================================================================

set "PYTHON_EXE=C:\Users\NIU\AppData\Local\Programs\Python\Python313\python.exe"
set "MINERU_API_BASE=https://mineru.net/api/v4"
set "POLL_SECONDS=10"
set "TIMEOUT_SECONDS=86400"
set "LOCAL_BACKEND=hybrid-engine"
set "LOCAL_EFFORT=medium"
set "LOCAL_VLM_ENGINE=transformers"
set "LOCAL_METHOD=auto"
set "LOCAL_LANGUAGE=ch"
rem Keep local task polling and result download aligned with the cloud timeout.
set "MINERU_TASK_RESULT_TIMEOUT_SECONDS=%TIMEOUT_SECONDS%"
set "MINERU_TASK_RESULT_DOWNLOAD_TIMEOUT_SECONDS=%TIMEOUT_SECONDS%"
set "MINERU_LOG_LEVEL=ERROR"
set "TF_CPP_MIN_LOG_LEVEL=3"
set "MINERU_API_DISABLE_ACCESS_LOG=1"
set "BATCH_LOG_FILE=%TEMP%\mineru-run-%RANDOM%.log"

cd /d "%~dp0"

if /I not "%RUN_MODE%"=="local" if /I not "%RUN_MODE%"=="cloud" (
    echo [ERROR] RUN_MODE must be local or cloud.
    set "EXIT_CODE=4"
    goto :finish
)

if /I "%RUN_MODE%"=="cloud" if not defined MINERU_API_TOKEN (
    echo [ERROR] Fill MINERU_API_TOKEN for cloud mode.
    echo         Token page: https://mineru.net/apiManage
    set "EXIT_CODE=4"
    goto :finish
)

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python interpreter not found:
    echo         %PYTHON_EXE%
    set "EXIT_CODE=2"
    goto :finish
)

if not exist "%~dp0mineru_process_guard.py" (
    echo [ERROR] Process guard not found:
    echo         %~dp0mineru_process_guard.py
    set "EXIT_CODE=2"
    goto :finish
)

if not exist "%INPUT_PATH%" if not exist "%INPUT_PATH%\*" (
    echo [ERROR] Input path not found:
    echo         %INPUT_PATH%
    set "EXIT_CODE=2"
    goto :finish
)

for %%I in ("%INPUT_PATH%") do (
    set "INPUT_ABS=%%~fI"
    set "INPUT_STEM=%%~nI"
    set "INPUT_DIR=%%~dpI"
)

if not defined OUTPUT_ROOT (
    if exist "%INPUT_PATH%\*" (
        set "OUTPUT_ROOT=%INPUT_ABS%"
    ) else (
        set "OUTPUT_ROOT=%INPUT_DIR%"
    )
)

rem A trailing backslash immediately before a closing quote is interpreted as
rem an escaped quote by Python's Windows argument parser. Add a path suffix
rem so both local and cloud commands receive a correctly terminated argument.
set "OUTPUT_ROOT_ARG=%OUTPUT_ROOT%"
if "%OUTPUT_ROOT_ARG:~-1%"=="\" set "OUTPUT_ROOT_ARG=%OUTPUT_ROOT_ARG%."

set "FOUND_COUNT=0"
set "FAILED_COUNT=0"
if exist "%BATCH_LOG_FILE%" del /q "%BATCH_LOG_FILE%" >nul 2>&1

if /I "%RUN_MODE%"=="cloud" (
    echo [RUN] cloud / vlm
) else (
    echo [RUN] local / %LOCAL_BACKEND% / %LOCAL_EFFORT%
)
echo [OUT] %OUTPUT_ROOT%
echo.

if exist "%INPUT_PATH%\*" (
    echo [RUN] folder mode: recursive PDF scan
    @for /r "%INPUT_PATH%" %%F in (*.pdf) do @call :run_one "%%~fF"
) else (
    @call :run_one "%INPUT_ABS%"
)

if "%FOUND_COUNT%"=="0" (
    echo [ERROR] No PDF files were found.
    set "EXIT_CODE=3"
    goto :finish
)

if not "%FAILED_COUNT%"=="0" (
    echo.
    echo [ERROR] %FAILED_COUNT% PDF file^(s^) failed. No fallback was attempted.
    set "EXIT_CODE=1"
    goto :finish
)

echo.
echo [OK] Completed %FOUND_COUNT% PDF file^(s^).
set "EXIT_CODE=0"
goto :finish

:finish
echo.
if "%EXIT_CODE%"=="0" (
    echo [STATUS] Finished successfully.
    if exist "%BATCH_LOG_FILE%" del /q "%BATCH_LOG_FILE%" >nul 2>&1
) else (
    echo [STATUS] Finished with errors. Exit code: %EXIT_CODE%
)
pause
exit /b %EXIT_CODE%

:run_one
set "PDF_PATH=%~1"
if /I not "%~x1"==".pdf" exit /b 0
set "PDF_STEM=%~n1"

set /a FOUND_COUNT+=1
echo.
echo [FILE %FOUND_COUNT%] %PDF_PATH%

if /I "%RUN_MODE%"=="cloud" goto :run_cloud

@"%PYTHON_EXE%" -B "%~dp0mineru_process_guard.py" -- -m mineru.cli.client ^
    -p "%PDF_PATH%" ^
    -o "%OUTPUT_ROOT_ARG%" ^
    -b "%LOCAL_BACKEND%" ^
    --effort "%LOCAL_EFFORT%" ^
    --vlm-engine "%LOCAL_VLM_ENGINE%" ^
    -m "%LOCAL_METHOD%" ^
    -l "%LOCAL_LANGUAGE%" >>"%BATCH_LOG_FILE%"
if errorlevel 1 goto :record_result
call :finalize_output
goto :record_result

:run_cloud
@"%PYTHON_EXE%" -B "%~dp0mineru_process_guard.py" -- "%~dp0mineru_cloud_api.py" ^
    --pdf "%PDF_PATH%" ^
    --output-root "%OUTPUT_ROOT_ARG%" ^
    --api-base "%MINERU_API_BASE%" ^
    --model-version vlm ^
    --method auto ^
    --poll-seconds "%POLL_SECONDS%" ^
    --timeout-seconds "%TIMEOUT_SECONDS%" >>"%BATCH_LOG_FILE%"
if errorlevel 1 goto :record_result
call :finalize_output
goto :record_result

:finalize_output
rem Keep one flat folder per PDF and retain the exact original filename.
set "PDF_OUTPUT_DIR=%OUTPUT_ROOT_ARG%\%PDF_STEM%"
set "PARSE_OUTPUT_DIR=%PDF_OUTPUT_DIR%\hybrid_auto"
if exist "%PARSE_OUTPUT_DIR%\" (
    robocopy "%PARSE_OUTPUT_DIR%" "%PDF_OUTPUT_DIR%" /E /MOVE /NFL /NDL /NJH /NJS /NP >nul
    if errorlevel 8 (
        >>"%BATCH_LOG_FILE%" echo [ERROR] Failed to flatten the MinerU result directory.
        exit /b 1
    )
    if exist "%PARSE_OUTPUT_DIR%\" rd /s /q "%PARSE_OUTPUT_DIR%" >nul 2>&1
)
copy /Y "%PDF_PATH%" "%PDF_OUTPUT_DIR%\" >nul
if errorlevel 1 (
    >>"%BATCH_LOG_FILE%" echo [ERROR] Failed to copy the original PDF into the output directory.
    exit /b 1
)
exit /b 0

:record_result
if errorlevel 1 (
    set /a FAILED_COUNT+=1
    echo [FAILED] %PDF_PATH%
    echo [DETAIL] Diagnostic log: %BATCH_LOG_FILE%
) else (
    echo [OK] %PDF_PATH%
)
exit /b 0
