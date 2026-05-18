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

REM Find a working Python launcher. Prefer 'python' (most common on Windows
REM after the python.org installer with PATH enabled), fall back to 'py'
REM (the launcher Microsoft Store / older python.org installs ship).
set PY=python
where python >NUL 2>&1
if errorlevel 1 set PY=py

%PY% --version >NUL 2>&1
if errorlevel 1 (
    echo ERROR: Python not found on PATH (tried 'python' and 'py').
    echo Install from python.org with "Add Python to PATH" checked,
    echo or from the Microsoft Store, then close+reopen PowerShell and re-run.
    exit /b 1
)

REM Make sure PyInstaller is importable. We invoke it via "python -m PyInstaller"
REM rather than the bare 'pyinstaller' command — the latter requires the Python
REM Scripts folder to be on PATH, which often isn't the case on default Windows
REM Python installs and is what produced the "'pyinstaller' is not recognized"
REM error people hit when running this script.
%PY% -c "import PyInstaller" >NUL 2>&1
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    %PY% -m pip install --upgrade pyinstaller
    if errorlevel 1 (
        echo ERROR: failed to install pyinstaller. Aborting.
        exit /b 1
    )
)

echo ----------------------------------------
echo Building TTS_Converter.exe  (using %PY% -m PyInstaller)
echo ----------------------------------------

REM --onefile          : single .exe instead of a folder
REM --windowed         : no console window when launched
REM --name             : output binary name
REM --icon             : .ico embedded as the exe + window resource
REM --add-data         : also bundle the icons/ folder so the runtime
REM                      iconbitmap call can find the file inside _MEIPASS
REM --hidden-import    : modules PyInstaller's static analysis often misses
REM --collect-submodules: pull in everything from packages with dynamic imports

%PY% -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "TTS_Converter" ^
    --icon "icons/headphones.ico" ^
    --add-data "icons/headphones.ico;icons" ^
    --add-data "icons/headphones-192.png;icons" ^
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
    --hidden-import deep_translator ^
    --hidden-import deep_translator.google ^
    --hidden-import deep_translator.constants ^
    --hidden-import deep_translator.exceptions ^
    --hidden-import faster_whisper ^
    --hidden-import ctranslate2 ^
    --hidden-import tokenizers ^
    --hidden-import huggingface_hub ^
    --hidden-import av ^
    --collect-submodules edge_tts ^
    --collect-submodules docx ^
    --collect-submodules pypdf ^
    --collect-submodules ebooklib ^
    --collect-submodules deep_translator ^
    --collect-all faster_whisper ^
    --collect-all ctranslate2 ^
    --collect-data certifi ^
    --exclude-module onnxruntime ^
    --exclude-module onnxruntime_extensions ^
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
