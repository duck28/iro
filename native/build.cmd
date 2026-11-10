@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
if not exist "%PROJECT_ROOT%\src\iro\bin" mkdir "%PROJECT_ROOT%\src\iro\bin"
if not exist "%PROJECT_ROOT%\.build\native" mkdir "%PROJECT_ROOT%\.build\native"
if defined VSDEVCMD set "DEVTOOLS=%VSDEVCMD%"
if not defined DEVTOOLS if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" (
  for /f "usebackq tokens=*" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "DEVTOOLS=%%i\Common7\Tools\VsDevCmd.bat"
)
if not defined DEVTOOLS set "DEVTOOLS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat"
if not exist "%DEVTOOLS%" (
  echo Set VSDEVCMD to the Visual Studio developer command script. Requires C++ build tools and Windows SDK.
  exit /b 1
)
call "%DEVTOOLS%" -arch=x64 -host_arch=x64 >nul
if errorlevel 1 exit /b %errorlevel%
cl /nologo /W4 /EHsc /std:c++17 /MT /utf-8 /O2 "%~dp0wpd_bridge.cpp" /Fo"%PROJECT_ROOT%\.build\native\wpd_bridge.obj" /Fe"%PROJECT_ROOT%\src\iro\bin\wpd-bridge.exe" /link ole32.lib oleaut32.lib propsys.lib portabledeviceguids.lib
exit /b %errorlevel%
