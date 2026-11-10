param([switch]$InstallBuildTools)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    $wixPath = Join-Path $PSScriptRoot '.build\tools\wix.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run setup.ps1 first.' }
    $version = & $pythonPath -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '^\d+\.\d+\.\d+$') { throw 'Expected a numeric MAJOR.MINOR.PATCH project version.' }
    if ($InstallBuildTools) {
        & $pythonPath -m pip install -r packaging\requirements-build.txt
        if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }
        if (-not (Test-Path -LiteralPath $wixPath)) {
            dotnet tool install wix --version 5.0.2 --tool-path .build\tools
            if ($LASTEXITCODE -ne 0) { throw 'WiX installation failed.' }
        }
        & $wixPath extension add WixToolset.UI.wixext/5.0.2
        if ($LASTEXITCODE -ne 0) { throw 'WiX UI extension installation failed.' }
    }
    if (-not (Test-Path -LiteralPath $wixPath)) { throw 'Run build-msi.ps1 -InstallBuildTools once (requires .NET SDK and network).' }
    & $env:ComSpec /c native\build.cmd
    if ($LASTEXITCODE -ne 0) { throw 'Native WPD camera bridge build failed. Install the Visual C++ Build Tools and Windows SDK, or set VSDEVCMD.' }
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot '.build\pyinstaller-cache'
    $assetsPath = Join-Path $PSScriptRoot 'src\iro\assets'
    $bridgePath = Join-Path $PSScriptRoot 'src\iro\bin\wpd-bridge.exe'
    $appDist = Join-Path 'dist' $version
    $payloadPath = Join-Path $appDist 'Iro'
    & $pythonPath -m PyInstaller --noconfirm --clean --windowed --onedir --name Iro --paths (Join-Path $PSScriptRoot 'src') --icon (Join-Path $assetsPath 'app.ico') --add-data ($assetsPath + ':iro/assets') --add-binary ($bridgePath + ':iro/bin') --distpath $appDist --workpath .build\pyinstaller --specpath .build (Join-Path $PSScriptRoot 'desktop.py')
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
    foreach ($runtimeFile in @('_internal\_tkinter.pyd', '_internal\_tcl_data\init.tcl', '_internal\_tk_data\tk.tcl', '_internal\iro\bin\wpd-bridge.exe')) {
        if (-not (Test-Path -LiteralPath (Join-Path $payloadPath $runtimeFile))) {
            throw "Missing Tk runtime: $runtimeFile. Run the build from a normal Windows terminal outside restricted sandboxes."
        }
    }
    $pythonBase = & $pythonPath -c 'import sys; print(sys.base_prefix)'
    $pythonLicense = Join-Path $pythonBase 'LICENSE.txt'
    if (Test-Path -LiteralPath $pythonLicense) {
        Copy-Item -LiteralPath $pythonLicense -Destination (Join-Path $payloadPath 'Python-LICENSE.txt')
    }
    Copy-Item -LiteralPath 'THIRD_PARTY_NOTICES.md' -Destination (Join-Path $payloadPath 'THIRD_PARTY_NOTICES.md')
    Copy-Item -LiteralPath 'LICENSE' -Destination (Join-Path $payloadPath 'LICENSE.txt')
    & $pythonPath packaging\harvest.py $payloadPath .build\Files.wxs
    if ($LASTEXITCODE -ne 0) { throw 'Payload harvesting failed.' }
    $installerPath = Join-Path 'dist' "Iro-$version-x64.msi"
    & $wixPath build -arch x64 -ext WixToolset.UI.wixext -d "ProductVersion=$version" -o $installerPath packaging\Product.wxs .build\Files.wxs
    if ($LASTEXITCODE -ne 0) { throw 'MSI build failed.' }
    Get-FileHash -Algorithm SHA256 -LiteralPath $installerPath
} finally {
    Pop-Location
}
