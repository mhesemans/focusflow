$ErrorActionPreference = "Stop"

Write-Host "Creating virtual environment..."
py -3 -m venv .venv

Write-Host "Installing dependencies..."
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements.txt pyinstaller

Write-Host "Building FocusFlow.exe..."
.\.venv\Scripts\pyinstaller.exe `
  --noconfirm `
  --clean `
  --windowed `
  --name FocusFlow `
  --icon assets\focusflow.ico `
  --add-data "assets;assets" `
  --paths src `
  run.py

Write-Host ""
Write-Host "Build complete. Your app is here:"
Write-Host "  dist\FocusFlow\FocusFlow.exe"
Write-Host ""
Write-Host "You can run that exe directly, create a shortcut, or use the optional Inno Setup script to make an installer."
