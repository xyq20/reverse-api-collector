$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $projectRoot "src"
Push-Location $projectRoot
try {
    python -m compileall -q src tests
    python -m unittest discover -s tests -v
}
finally {
    Pop-Location
}

