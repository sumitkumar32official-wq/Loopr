# Usage (from backend/):  .\dev.ps1 setup | test | run | seed
param([Parameter(Mandatory = $true)][ValidateSet("setup", "test", "run", "seed")][string]$Task)
$py = ".\.venv\Scripts\python.exe"
switch ($Task) {
    "setup" {
        if (-not (Test-Path $py)) { py -3.12 -m venv .venv }
        & $py -m pip install -q -r requirements.txt
        Write-Host "Environment ready."
    }
    "test" { & $py -m pytest -q }
    "seed" { & $py seed.py }
    # 0.0.0.0 so a physical iPhone on the same Wi-Fi can reach it; allow port 8000 in Windows Firewall.
    "run"  { & $py seed.py; & $py -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 }
}
