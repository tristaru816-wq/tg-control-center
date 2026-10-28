$ErrorActionPreference = 'Stop'
$startup = [Environment]::GetFolderPath('Startup')
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut((Join-Path $startup 'TG Desktop Worker.lnk'))
$link.TargetPath = Join-Path $PSScriptRoot 'start.cmd'
$link.WorkingDirectory = $PSScriptRoot
$link.Save()
Write-Output '已設定登入 Windows 後啟動。請先完成首次管理員及 TG 登入。'
