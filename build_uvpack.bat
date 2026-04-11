@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"

set "SRC_DIR=%ROOT_DIR%\uvpack_cpp"
set "OUT_DIR=%ROOT_DIR%\uvpack_lib"
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
set "VCVARS="

if not exist "%SRC_DIR%\uvpack.cpp" (
    echo [ERROR] Arquivo fonte nao encontrado: "%SRC_DIR%\uvpack.cpp"
    exit /b 1
)

if not exist "%OUT_DIR%" (
    mkdir "%OUT_DIR%" || (
        echo [ERROR] Nao foi possivel criar a pasta de saida: "%OUT_DIR%"
        exit /b 1
    )
)

if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if not defined VCVARS if exist "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat"
if not defined VCVARS if exist "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat"
if not defined VCVARS if exist "C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"

if not defined VCVARS if exist "%VSWHERE%" (
    for /f "usebackq delims=" %%I in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do (
        if exist "%%I\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%%I\VC\Auxiliary\Build\vcvars64.bat"
    )
)

if not defined VCVARS (
    echo [ERROR] Visual Studio com ferramentas C++ nao foi encontrado.
    exit /b 1
)

if not exist "%VCVARS%" (
    echo [ERROR] Arquivo nao encontrado: "%VCVARS%"
    exit /b 1
)

echo [1/3] Preparando ambiente MSVC...
pushd "%SRC_DIR%" || (
    echo [ERROR] Nao foi possivel acessar "%SRC_DIR%"
    exit /b 1
)

echo [2/3] Compilando uvpack.cpp...
call "%VCVARS%" >nul && cl /std:c++17 /O2 /GL /EHsc /arch:AVX2 /LD uvpack.cpp /Fe:lib_uvpack.dll /link /LTCG
if errorlevel 1 (
    popd
    echo [ERROR] Falha ao preparar o ambiente do Visual Studio ou compilar uvpack.cpp.
    exit /b 1
)

echo [3/3] Copiando artefatos para uvpack_lib...
move /Y "lib_uvpack.dll" "%OUT_DIR%\lib_uvpack.dll" >nul || (
    popd
    echo [ERROR] Falha ao mover lib_uvpack.dll para "%OUT_DIR%"
    exit /b 1
)

if exist "lib_uvpack.lib" (
    move /Y "lib_uvpack.lib" "%OUT_DIR%\lib_uvpack.lib" >nul || (
        popd
        echo [ERROR] Falha ao mover lib_uvpack.lib para "%OUT_DIR%"
        exit /b 1
    )
)

if exist "lib_uvpack.exp" (
    move /Y "lib_uvpack.exp" "%OUT_DIR%\lib_uvpack.exp" >nul || (
        popd
        echo [ERROR] Falha ao mover lib_uvpack.exp para "%OUT_DIR%"
        exit /b 1
    )
)

popd

echo [OK] Build concluido com sucesso.
echo      DLL: "%OUT_DIR%\lib_uvpack.dll"
exit /b 0
