param([string]$InnoCompiler = '')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $taskRoot
$env:UV_CACHE_DIR = Join-Path $taskRoot '.cache\uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $taskRoot '.runtime'
$env:npm_config_cache = Join-Path $taskRoot '.cache\npm'
$env:MPLCONFIGDIR = Join-Path $taskRoot '.cache\matplotlib-build'
uv sync --frozen --extra desktop --extra ml --extra dev
if ($LASTEXITCODE) { throw 'Python dependencies failed' }
& .venv\Scripts\python scripts\install_models.py
if ($LASTEXITCODE) { throw 'Model installation failed' }
& .venv\Scripts\python scripts\install_engines.py
if ($LASTEXITCODE) { throw 'Engine installation failed' }
Push-Location frontend
try {
    npm ci
    if ($LASTEXITCODE) { throw 'npm ci failed' }
    npm run build
    if ($LASTEXITCODE) { throw 'UI build failed' }
} finally { Pop-Location }
& .venv\Scripts\python scripts\collect_notices.py
if ($LASTEXITCODE) { throw 'License collection failed' }
& .venv\Scripts\python scripts\create_icon.py
if ($LASTEXITCODE) { throw 'Icon and version preparation failed' }
& .venv\Scripts\python -m PyInstaller --noconfirm packaging\OpenPhoto.spec
if ($LASTEXITCODE) { throw 'Application packaging failed' }
if ($InnoCompiler) {
    & .venv\Scripts\python scripts\prepare_webview2.py
    if ($LASTEXITCODE) { throw 'WebView2 preparation failed' }
    $appReleaseVersion = & .venv\Scripts\python -c "import openphoto; print(openphoto.__version__)"
    & $InnoCompiler "/DAppVersion=$appReleaseVersion" packaging\OpenPhoto.iss
    if ($LASTEXITCODE) { throw 'Installer build failed' }
}
Write-Output 'Ready: dist\OpenPhoto\OpenPhoto.exe'
