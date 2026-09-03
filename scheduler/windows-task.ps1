# Windows: register a weekly scheduled task for the updater.
# Run this once from an elevated PowerShell prompt, after editing the two paths.

$Python  = "C:\path\to\ambaar\.venv\Scripts\python.exe"
$Project = "C:\path\to\ambaar"

$action  = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "-m ambaar.updater --force" `
    -WorkingDirectory $Project

$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 4am

# StartWhenAvailable catches up if the machine was off at 4am Sunday.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask `
    -TaskName "Ambaar engine update" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Updates yt-dlp weekly, verifies it works, rolls back on regression."

# Test it immediately:
#   Start-ScheduledTask -TaskName "Ambaar engine update"
# Read the result:
#   Get-Content $env:APPDATA\ambaar\updater.log -Tail 40
