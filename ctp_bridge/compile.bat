@echo on
set VCDIR=D:\software\VScode\VisualStudio\18\Community
call "%VCDIR%\VC\Auxiliary\Build\vcvarsall.bat" x64
echo === Compiling ===
cl.exe /nologo /LD /Ictp_bridge\include /Fectp_bridge\bin\ctp_bridge.dll ctp_bridge\src\ctp_bridge.cpp /link /DEF:ctp_bridge\src\ctp_bridge.def /OUT:ctp_bridge\bin\ctp_bridge.dll
echo EXIT CODE: %errorlevel%
pause
