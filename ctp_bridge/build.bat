@echo off
call "D:\software\VScode\VisualStudio\18\Community\VC\Auxiliary\Build\vcvarsall.bat" x64
cl.exe /nologo /LD /Ictp_bridge\include /Fectp_bridge\bin\ctp_bridge.dll ctp_bridge\src\ctp_bridge.cpp /link /DEF:ctp_bridge\src\ctp_bridge.def /OUT:ctp_bridge\bin\ctp_bridge.dll
if %errorlevel% neq 0 (
    echo BUILD FAILED
    exit /b %errorlevel%
)
echo BUILD SUCCESS
