Remove-Item (Join-Path ([Environment]::GetFolderPath('Startup')) 'TG Desktop Worker.lnk') -ErrorAction SilentlyContinue
Write-Output '已取消登入 Windows 後自動啟動。'
