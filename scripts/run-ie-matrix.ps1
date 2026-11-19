# The Ghi -> Học -> Chạy matrix on a real Internet Explorer, on the TouchPoint look-alike (task 11.2), in document modes 8 and 9.
# Run it after any change to recording or learning. It opens its own hidden IE windows and never touches another one.
#
#   .\scripts\run-ie-matrix.ps1            both modes
#   .\scripts\run-ie-matrix.ps1 -Modes 9   one mode
param([string[]]$Modes = @("8", "9"))
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo "server\.venv\Scripts\python.exe"
$failed = $false
Push-Location (Join-Path $repo "windows-agent")
try {
    $env:ROOKIE_REAL_IE = "1"
    foreach ($mode in $Modes) {
        $env:RK_DOCMODE = $mode
        Write-Host "== chế độ tài liệu $mode"
        & $python -m pytest -q -p no:cacheprovider tests/test_ie_matrix.py
        if ($LASTEXITCODE -ne 0) { $failed = $true }
    }
} finally {
    Remove-Item Env:ROOKIE_REAL_IE -ErrorAction SilentlyContinue
    Pop-Location
}
if ($failed) { Write-Host "Ma trận có kịch bản lỗi." -ForegroundColor Red; exit 1 }
Write-Host "Ma trận qua ở mọi chế độ." -ForegroundColor Green
