@echo off
REM ============================================================================
REM build_exe.bat — bundle prerender_gui.py into a standalone Windows .exe.
REM
REM Produces:
REM   dist\TTS_Converter.exe   single-file, ~30-50 MB
REM
REM Requirements:
REM   pip install pyinstaller
REM   plus the runtime deps from requirements.txt
REM
REM Usage:
REM   build_exe.bat         build .exe
REM   build_exe.bat clean   delete build artifacts
REM ============================================================================

setlocal

if /I "%~1"=="clean" goto :clean

where pyinstaller >NUL 2>&1
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    python -m pip install --upgrade pyinstaller
    if errorlevel 1 (
        echo ERROR: failed to install pyinstaller. Aborting.
        exit /b 1
    )
)

echo ----------------------------------------
echo Building TTS_Converter.exe
echo ----------------------------------------

REM --onefile          : single .exe instead of a folder
REM --windowed         : no console window when launched
REM --name             : output binary name
REM --hidden-import    : modules PyInstaller's static analysis often misses
REM --collect-submodules: pull in everything from packages with dynamic imports

pyinstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "TTS_Converter" ^
    --hidden-import edge_tts ^
    --hidden-import edge_tts.communicate ^
    --hidden-import edge_tts.constants ^
    --hidden-import edge_tts.drm ^
    --hidden-import edge_tts.exceptions ^
    --hidden-import edge_tts.list_voices ^
    --hidden-import edge_tts.submaker ^
    --hidden-import edge_tts.typing ^
    --hidden-import edge_tts.util ^
    --hidden-import edge_tts.tts_config ^
    --hidden-import certifi ^
    --hidden-import charset_normalizer ^
    --hidden-import docx ^
    --hidden-import pypdf ^
    --hidden-import ebooklib ^
    --hidden-import bs4 ^
    --collect-submodules edge_tts ^
    --collect-submodules docx ^
    --collect-submodules pypdf ^
    --collect-submodules ebooklib ^
    --collect-data certifi ^
    prerender_gui.py

if errorlevel 1 (
    echo.
    echo BUILD FAILED.
    exit /b 1
)

echo.
echo ----------------------------------------
echo Built: dist\TTS_Converter.exe
echo ----------------------------------------
echo Double-click dist\TTS_Converter.exe to launch.
echo The .exe is fully self-contained — no Python install needed
echo on machines you copy it to.
goto :eof

:clean
echo Removing build/ dist/ and TTS_Converter.spec ...
if exist build  rmdir /s /q build
if exist dist   rmdir /s /q dist
if exist TTS_Converter.spec del /q TTS_Converter.spec
echo done.
goto :eof
