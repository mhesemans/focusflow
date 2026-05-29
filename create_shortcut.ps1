$ErrorActionPreference = "Stop"
$ExePath = Join-Path $PSScriptRoot "dist\FocusFlow\FocusFlow.exe"
if (!(Test-Path $ExePath)) {
  throw "FocusFlow.exe was not found. Run .\build_windows.ps1 first."
}
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "FocusFlow.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $ExePath
$Shortcut.WorkingDirectory = Split-Path $ExePath
$Shortcut.IconLocation = $ExePath
$Shortcut.Save()
Write-Host "Shortcut created on your desktop: $ShortcutPath"
Write-Host "To pin it: right-click the shortcut or running taskbar icon, then choose Pin to taskbar."
