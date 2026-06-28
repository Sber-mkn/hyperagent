<#
.SYNOPSIS
    Отключает (или восстанавливает) автоматические обновления Windows.
    Полезно для машины, работающей как удалённый сервер: убирает авто-загрузку,
    авто-установку и, главное, авто-перезагрузку, которая прерывает долгие задачи.

.USAGE
    Запускать ОТ ИМЕНИ АДМИНИСТРАТОРА:
        powershell -ExecutionPolicy Bypass -File .\disable_windows_update.ps1
    Откатить (включить обновления обратно):
        powershell -ExecutionPolicy Bypass -File .\disable_windows_update.ps1 -Restore

.NOTES
    Что меняется:
      1) Политика HKLM ...\WindowsUpdate\AU: NoAutoUpdate=1, AUOptions=2 (только уведомлять),
         NoAutoRebootWithLoggedOnUsers=1.
      2) Службы wuauserv, UsoSvc, WaaSMedicSvc, BITS → Disabled и остановлены.
      3) Задачи планировщика \Microsoft\Windows\UpdateOrchestrator\ и \WindowsUpdate\ → Disabled.
    Чтобы поставить обновления вручную позже — запусти с -Restore, затем
    «Параметры → Центр обновления Windows → Проверить наличие обновлений».
#>
[CmdletBinding()]
param([switch]$Restore)

# --- авто-эскалация прав, если запущено без админа ---
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "Требуются права администратора — перезапускаю с повышением (подтверди UAC)..." -ForegroundColor Yellow
    $argList = @('-ExecutionPolicy','Bypass','-File',"`"$PSCommandPath`"")
    if ($Restore) { $argList += '-Restore' }
    Start-Process powershell -Verb RunAs -ArgumentList $argList
    return
}

$AUKey = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU"
$services = 'wuauserv','UsoSvc','WaaSMedicSvc','BITS'

if ($Restore) {
    Write-Host "=== ВОССТАНОВЛЕНИЕ автообновлений ===" -ForegroundColor Cyan
    if (Test-Path $AUKey) { Remove-Item $AUKey -Recurse -Force -ErrorAction SilentlyContinue }
    $defaults = @{ wuauserv='Manual'; UsoSvc='Manual'; WaaSMedicSvc='Manual'; BITS='Manual' }
    foreach ($s in $services) {
        try { Set-Service $s -StartupType $defaults[$s] -ErrorAction Stop; Write-Host " - $s → $($defaults[$s])" }
        catch { Write-Host " - $s → ошибка: $($_.Exception.Message)" -ForegroundColor Red }
    }
    $tasks = Get-ScheduledTask -TaskPath '\Microsoft\Windows\UpdateOrchestrator\','\Microsoft\Windows\WindowsUpdate\' -ErrorAction SilentlyContinue
    foreach ($t in $tasks) { try { Enable-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -ErrorAction Stop | Out-Null } catch {} }
    Write-Host "Готово. Обновления снова разрешены (установка — вручную через Параметры)." -ForegroundColor Green
    return
}

Write-Host "=== ОТКЛЮЧЕНИЕ автообновлений Windows ===" -ForegroundColor Cyan

# 1) Политика
New-Item -Path $AUKey -Force | Out-Null
Set-ItemProperty -Path $AUKey -Name NoAutoUpdate                  -Type DWord -Value 1
Set-ItemProperty -Path $AUKey -Name AUOptions                    -Type DWord -Value 2
Set-ItemProperty -Path $AUKey -Name NoAutoRebootWithLoggedOnUsers -Type DWord -Value 1
Write-Host " - Политика: NoAutoUpdate=1, AUOptions=2, NoAutoReboot=1"

# 2) Службы
foreach ($s in $services) {
    try {
        Stop-Service $s -Force -ErrorAction SilentlyContinue
        Set-Service  $s -StartupType Disabled -ErrorAction Stop
        Write-Host " - Служба $s → Disabled + остановлена"
    } catch { Write-Host " - Служба $s → не удалось: $($_.Exception.Message)" -ForegroundColor Red }
}

# 3) Задачи планировщика обновлений (best-effort)
$tasks = Get-ScheduledTask -TaskPath '\Microsoft\Windows\UpdateOrchestrator\','\Microsoft\Windows\WindowsUpdate\' -ErrorAction SilentlyContinue
$off = 0
foreach ($t in $tasks) { try { Disable-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -ErrorAction Stop | Out-Null; $off++ } catch {} }
Write-Host " - Отключено задач планировщика: $off из $($tasks.Count)"

Write-Host "`nГотово. Автообновления и авто-перезагрузка отключены." -ForegroundColor Green
Write-Host "Откат: запусти этот же скрипт с параметром -Restore." -ForegroundColor Green
Get-Service wuauserv,UsoSvc,WaaSMedicSvc 2>$null | Select-Object Name,Status,StartType | Format-Table -AutoSize
