# Build frontend and run production-like single-process server on :8080
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "==> Build web"
Push-Location apps\web
pnpm install
pnpm build
Pop-Location

Write-Host "==> Start API + static on http://127.0.0.1:8080"
Push-Location apps\api
if (-not (Test-Path .venv)) {
  uv venv .venv
  uv pip install -e ".[dev]"
}
& .\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8080
Pop-Location
