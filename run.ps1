# Avvio locale da PowerShell/VS Code, senza GNU Make o attivazione del venv.
$ErrorActionPreference = 'Stop'
$mccPython = @('.venv\Scripts\python.exe', 'venv\Scripts\python.exe') |
    ForEach-Object { Join-Path $PSScriptRoot $_ } |
    Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1
if (-not $mccPython) {
    throw 'Ambiente Python mancante. Esegui: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt'
}

Push-Location $PSScriptRoot
try {
    & $mccPython -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
    $mccExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $mccExitCode
