$ErrorActionPreference = "Stop"

$AppName = "ReturnsShipmentBuilder"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

Set-Location $Root

& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt pyinstaller

Remove-Item -Recurse -Force ".\build" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force ".\dist" -ErrorAction SilentlyContinue
Remove-Item -Force ".\$AppName.spec" -ErrorAction SilentlyContinue

& $Python -m PyInstaller `
    --onefile `
    --noconsole `
    --name $AppName `
    --clean `
    --collect-all pandas `
    --collect-all openpyxl `
    --collect-all pypdf `
    --add-data "README_PACKAGED_APP.md;." `
    ".\shipment_csv_app.py"

$PackageDir = Join-Path $Root "dist\$AppName-package"
New-Item -ItemType Directory -Force $PackageDir | Out-Null
Copy-Item ".\dist\$AppName.exe" $PackageDir -Force
Copy-Item ".\README_PACKAGED_APP.md" (Join-Path $PackageDir "README.md") -Force

$ZipPath = Join-Path $Root "dist\$AppName.zip"
Remove-Item -Force $ZipPath -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $ZipPath -Force

Write-Host "Built executable: dist\$AppName.exe"
Write-Host "Built ZIP package: dist\$AppName.zip"
