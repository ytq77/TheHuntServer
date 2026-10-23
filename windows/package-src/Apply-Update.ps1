param([Parameter(Mandatory=$true)][string]$Plan, [switch]$Headless, [switch]$NoRestart)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$utf8 = New-Object Text.UTF8Encoding $false
$request = [IO.File]::ReadAllText([IO.Path]::GetFullPath($Plan)) | ConvertFrom-Json
$root = [IO.Path]::GetFullPath([string]$request.root).TrimEnd('\')
$client = $request.repository -eq 'TheHuntLauncher'
if (-not $client -and $request.repository -ne 'TheHuntServer') { throw 'Unknown update project' }
$entryName = if ($client) { 'BBSC-Launcher.exe' } else { 'Server.exe' }
if (-not (Test-Path -LiteralPath (Join-Path $root $entryName) -PathType Leaf)) { throw 'Update target is not an installed application' }
$session = Split-Path -Parent ([IO.Path]::GetFullPath($Plan))
$extract = Join-Path $session ('payload-' + [guid]::NewGuid().ToString('N'))
$lock = $null; $appMutex = $null; $mutexHeld = $false; $backup = $null; $applied = New-Object Collections.Generic.List[string]
$progress = $null; $form = $null; $status = $null
if (-not $Headless) {
    Add-Type -AssemblyName System.Windows.Forms,System.Drawing
    [Windows.Forms.Application]::EnableVisualStyles()
    $form = New-Object Windows.Forms.Form
    $form.Text = 'The Hunt · 正在更新'; $form.ClientSize = New-Object Drawing.Size(520,175)
    $form.StartPosition = 'CenterScreen'; $form.FormBorderStyle = 'FixedDialog'; $form.ControlBox = $false
    $form.BackColor = [Drawing.Color]::FromArgb(23,28,32); $form.ForeColor = [Drawing.Color]::Gainsboro
    $status = New-Object Windows.Forms.Label
    $status.Location = New-Object Drawing.Point(24,25); $status.Size = New-Object Drawing.Size(472,65)
    $status.Font = New-Object Drawing.Font('Microsoft YaHei UI',10)
    $progress = New-Object Windows.Forms.ProgressBar
    $progress.Location = New-Object Drawing.Point(24,112); $progress.Size = New-Object Drawing.Size(472,18)
    $form.Controls.AddRange(@($status,$progress)); $form.Show()
}
function Report([string]$message,[int]$value) {
    if ($form) { $status.Text=$message; $progress.Value=[Math]::Min(100,$value); [Windows.Forms.Application]::DoEvents() }
    Write-Output $message
}
function Hash([string]$path) {
    $algorithm = [Security.Cryptography.SHA256]::Create(); $stream = [IO.File]::OpenRead($path)
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}
function Safe-Relative([string]$name) {
    if (-not $name -or $name.Contains('\') -or $name.Contains(':') -or $name.StartsWith('/') -or $name.EndsWith('/')) { throw 'Unsafe package path' }
    foreach ($part in $name.Split('/')) {
        if ($part -in @('','.','..') -or $part -match '[. ]$|^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)') { throw 'Unsafe package filename' }
    }
    $private = @('.private','data','user','logs','captures','save-backups','save-conversion-backups','conversion-jobs','update-backups','guest-items','own-world','shared-progress','__pycache__','.git','backups')
    foreach ($part in $name.Split('/')) { if ($part -in $private) { throw 'Private state found in update package' } }
    if ($name -match '(^|/)(profile.json|account.clixml|features.json|server-admin.json|update-settings.json|launcher-state.json|settings-snapshot.json|conversion-current.json|save-transfer-result.json|last-exit.json|bbport.ini|input.ini|mods.json|patches.json|shadnet.cfg|\.env|\.save-import.lock|\.save-conversion.lock|\.update.lock)$' -or $name -match '^(normal|bbsc)/(db/|online-data.json$)') { throw 'Private configuration found in update package' }
    return $name.Replace('/',[IO.Path]::DirectorySeparatorChar)
}
function Check-Parents([string]$path) {
    $current = $path
    while ($current -and $current.Length -ge $root.Length) {
        if ((Test-Path -LiteralPath $current) -and ((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Update target contains a junction or symbolic link' }
        if ($current -eq $root) { break }
        $current = Split-Path -Parent $current
    }
}
try {
    Report '正在校验更新包……' 2
    if ($request.sha256 -notmatch '^[a-fA-F0-9]{64}$' -or (Hash $request.archive) -ne $request.sha256.ToLowerInvariant()) { throw 'Update archive hash mismatch' }
    [void][IO.Directory]::CreateDirectory($extract)
    $zip = [IO.Compression.ZipFile]::OpenRead([string]$request.archive)
    try {
        $names = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
        $top = $null; [long]$bytes = 0
        if ($zip.Entries.Count -gt 10000) { throw 'Too many package entries' }
        foreach ($item in $zip.Entries) {
            if (-not $item.Name) { continue }
            $slash = $item.FullName.IndexOf('/')
            if ($slash -lt 1) { throw 'Package must contain one application directory' }
            $folder = $item.FullName.Substring(0,$slash)
            if ($null -eq $top) { $top=$folder } elseif ($folder -cne $top) { throw 'Multiple application directories in package' }
            $relative = $item.FullName.Substring($slash+1)
            $safe = Safe-Relative $relative
            if (-not $names.Add($relative) -or (($item.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000) { throw 'Duplicate file or symbolic link in package' }
            $bytes += $item.Length
            if ($bytes -gt 4GB) { throw 'Expanded package is too large' }
            $target = Join-Path $extract $safe
            [void][IO.Directory]::CreateDirectory((Split-Path -Parent $target))
            [IO.Compression.ZipFileExtensions]::ExtractToFile($item,$target,$false)
        }
    } finally { $zip.Dispose() }
    $info = [IO.File]::ReadAllText((Join-Path $extract 'BUILD-INFO.json')) | ConvertFrom-Json
    $newVersion = if ($client) { $info.version } else { $info.label }
    if ($newVersion -cne $request.version) { throw 'Package version does not match the selected release' }
    $manifestName = if ($client) { 'file-sha256.json' } else { 'BUILD-INFO.json' }
    $manifest = if ($client) { [IO.File]::ReadAllText((Join-Path $extract $manifestName)) | ConvertFrom-Json } else { $info.files }
    $expected = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($field in $manifest.PSObject.Properties) {
        $relative = [string]$field.Name; $safe = Safe-Relative $relative
        if (-not $expected.Add($relative) -or [string]$field.Value -notmatch '^[a-fA-F0-9]{64}$' -or (Hash (Join-Path $extract $safe)) -ne ([string]$field.Value).ToLowerInvariant()) { throw 'Package manifest verification failed' }
    }
    [void]$expected.Add($manifestName)
    foreach ($file in $names) { if (-not $expected.Contains($file)) { throw ('Unlisted file in update package: ' + $file) } }
    if (-not $names.Contains($entryName) -or -not $names.Contains('Apply-Update.ps1')) { throw 'Required application files are absent' }
    Report '校验通过，正在等待原窗口退出……' 15
    $deadline = (Get-Date).AddSeconds(60)
    while ([int]$request.parent_pid -gt 0 -and (Get-Process -Id ([int]$request.parent_pid) -ErrorAction SilentlyContinue)) {
        if ((Get-Date) -gt $deadline) { throw 'Original application did not exit; no files replaced' }
        Start-Sleep -Milliseconds 200
        if ($form) { [Windows.Forms.Application]::DoEvents() }
    }
    Check-Parents $root
    $lock = [IO.File]::Open((Join-Path $root '.update.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $identityPath = if ($client) { $root } else { $root.ToLowerInvariant()+'\' }
        $identity = [BitConverter]::ToString($algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($identityPath)))
    } finally { $algorithm.Dispose() }
    $mutexName = if ($client) { 'Local\BBSCLauncher-'+$identity } else { 'Local\TheHuntServer-'+$identity.Replace('-','') }
    $appMutex = New-Object Threading.Mutex($false,$mutexName)
    try { $mutexHeld = $appMutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $mutexHeld = $true }
    if (-not $mutexHeld) { throw 'Another application window is still running; no files replaced' }
    $running = Get-Process -ErrorAction SilentlyContinue | Where-Object { try { $_.Path -and $_.Path.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase) } catch { $false } }
    if ($running) { throw 'Game or service processes are still running; no files replaced' }
    $backup = Join-Path $root ('update-backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8))
    [void][IO.Directory]::CreateDirectory((Join-Path $backup 'program'))
    $operations = @($names | Where-Object { -not (-not $client -and ($_ -eq 'server.json' -or $_ -match '^(normal|bbsc)/(worlds|scoreboards)\.cfg$') -and (Test-Path -LiteralPath (Join-Path $root $_))) } | Sort-Object)
    Report '正在备份将被替换的程序文件，账号与存档保持原位……' 20
    foreach ($relative in $operations) {
        $destination = Join-Path $root (Safe-Relative $relative); Check-Parents $destination
        if (Test-Path -LiteralPath $destination -PathType Leaf) {
            $old = Join-Path $backup ('program\'+$relative)
            [void][IO.Directory]::CreateDirectory((Split-Path -Parent $old)); [IO.File]::Copy($destination,$old,$false)
        } elseif (Test-Path -LiteralPath $destination) { throw 'A target file is occupied by a directory' }
    }
    [IO.File]::WriteAllText((Join-Path $backup 'update.json'),($request | ConvertTo-Json -Depth 5),$utf8)
    foreach ($relative in $operations) {
        $destination = Join-Path $root (Safe-Relative $relative)
        [void][IO.Directory]::CreateDirectory((Split-Path -Parent $destination))
        $temporary = $destination + '.update-' + [guid]::NewGuid().ToString('N')
        try {
            [IO.File]::Copy((Join-Path $extract $relative),$temporary,$false)
            if ([IO.File]::Exists($destination)) { [IO.File]::Replace($temporary,$destination,[NullString]::Value) } else { [IO.File]::Move($temporary,$destination) }
            $applied.Add($relative)
        } finally { if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) } }
        Report ('正在替换程序文件：'+$relative) (25+[int](70*$applied.Count/[Math]::Max(1,$operations.Count)))
    }
    [IO.File]::WriteAllText((Join-Path $backup 'result.json'),'{"success":true}',$utf8)
    Report '更新完成，正在重新打开程序。' 100
    $lock.Dispose(); $lock=$null
    $appMutex.ReleaseMutex(); $mutexHeld=$false; $appMutex.Dispose(); $appMutex=$null
    if (-not $NoRestart) { Start-Process -FilePath (Join-Path $root $entryName) -WorkingDirectory $root -WindowStyle Normal }
} catch {
    $reason = $_.Exception.Message
    $rollbackError = $null
    for ($i=$applied.Count-1; $i -ge 0; $i--) {
        try {
            $relative = $applied[$i]; $destination=Join-Path $root $relative; $old=Join-Path $backup ('program\'+$relative)
            if ([IO.File]::Exists($old)) { [IO.File]::Copy($old,$destination,$true) } else { [IO.File]::Delete($destination) }
        } catch { $rollbackError=$_.Exception.Message }
    }
    if ($backup) { try { [IO.File]::WriteAllText((Join-Path $backup 'result.json'),(@{success=$false;error=$reason;rollback_error=$rollbackError;applied=$applied.ToArray()} | ConvertTo-Json),$utf8) } catch { } }
    $message = "更新未完成：$reason`n账号和存档目录未参与替换。"
    if ($rollbackError) { $message += "`n部分程序文件未能自动恢复，请保留备份：$backup" }
    if ($Headless) { throw $message }
    [void][Windows.Forms.MessageBox]::Show($form,$message,'The Hunt 更新失败','OK','Error')
    exit 1
} finally {
    if ($lock) { $lock.Dispose() }
    if ($appMutex) { if ($mutexHeld) { $appMutex.ReleaseMutex() }; $appMutex.Dispose() }
    if ($form) { $form.Close(); $form.Dispose() }
}
