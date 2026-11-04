param([string]$BuildToolsPath = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $BuildToolsPath) {
    $localInstance = Join-Path $PSScriptRoot 'buildtools'
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (Test-Path -LiteralPath (Join-Path $localInstance 'VC\Auxiliary\Build\vcvars64.bat')) {
        $BuildToolsPath = $localInstance
    } elseif (Test-Path -LiteralPath $vswhere) {
        $BuildToolsPath = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    }
}
if (-not $BuildToolsPath) { throw 'Install Visual Studio 2022 Build Tools with MSVC, Windows SDK and CMake first.' }
$cmake = Join-Path $BuildToolsPath 'Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
$ctest = Join-Path $BuildToolsPath 'Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\ctest.exe'
if (-not (Test-Path -LiteralPath $cmake)) { throw 'C++ CMake component is missing.' }
& $cmake -S (Join-Path $projectRoot 'native') -B (Join-Path $projectRoot 'native\build') -G 'Visual Studio 17 2022' -A x64 "-DCMAKE_GENERATOR_INSTANCE=$BuildToolsPath"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $cmake --build (Join-Path $projectRoot 'native\build') --config Release
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $ctest --test-dir (Join-Path $projectRoot 'native\build') -C Release --output-on-failure
exit $LASTEXITCODE
