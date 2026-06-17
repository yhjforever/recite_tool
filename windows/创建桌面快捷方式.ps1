# 在桌面创建“背诵稿生成器”快捷方式（双击即开，无黑窗）
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

$pw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $pw) { $pw = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $pw) { Write-Host '未找到 Python，请先安装并加入 PATH。'; exit 1 }

$desktop = [Environment]::GetFolderPath('Desktop')
$lnk = Join-Path $desktop '背诵稿生成器.lnk'

$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($lnk)
$s.TargetPath = $pw
$s.Arguments = '"' + (Join-Path $here 'app.pyw') + '"'
$s.WorkingDirectory = $here
$s.Description = '背诵稿生成器 recite_tool'
$ico = Join-Path $here 'icon.ico'
if (Test-Path $ico) { $s.IconLocation = $ico }
$s.Save()

Write-Host "已在桌面创建快捷方式：背诵稿生成器"
Write-Host "目标: $pw `"$(Join-Path $here 'app.pyw')`""
