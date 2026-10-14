$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot
& '.\.venv\Scripts\python.exe' 'scripts/local_database.py' start
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL startup failed.' }
if (-not (Test-Path -LiteralPath 'web/dist/index.html')) { throw 'Run npm.cmd ci and npm.cmd run build in web first.' }
& '.\.venv\Scripts\python.exe' -m uvicorn 'gamepersona.web.app:create_app' --factory --host 127.0.0.1 --port 8000 --no-access-log
