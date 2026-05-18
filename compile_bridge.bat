@echo off
call "D:\software\VScode\VisualStudio\18\Community\VC\Auxiliary\Build\vcvarsall.bat" x64
cl.exe /nologo /LD /Ictp_bridge\include /Fectp_bridge\bin\ctp_bridge.dll ctp_bridge\src\ctp_bridge.cpp /link /OUT:ctp_bridge\bin\ctp_bridge.dll
echo EXIT_CODE=%errorlevel%
