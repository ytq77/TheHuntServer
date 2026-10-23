param([Parameter(Mandatory=$true)][string]$AssemblyPath, [switch]$Live)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase
[void][Reflection.Assembly]::LoadFrom([IO.Path]::GetFullPath($AssemblyPath))
function Assert-Update($condition, [string]$message) { if (-not $condition) { throw $message } }
Assert-Update ([HuntUpdates]::CompareVersions('0.1.0-preview.10','v0.1.0-preview.9') -gt 0) 'Numeric prerelease comparison failed'
Assert-Update ([HuntUpdates]::CompareVersions('0.1.0','0.1.0-preview.99') -gt 0) 'Stable release ordering failed'
Assert-Update ([HuntUpdates]::CompareVersions('1.0.0','0.99.99') -gt 0) 'Major version ordering failed'
Assert-Update ([HuntUpdates]::CompareVersions('v0.1.0-preview.2','0.1.0-preview.2') -eq 0) 'Tag normalization failed'
Assert-Update ([HuntUpdates]::ValidatePrefix('https://accelerator.example/path') -eq 'https://accelerator.example/path/') 'Prefix normalization failed'
foreach ($value in @('http://accelerator.example/','https://user:secret@accelerator.example/','https://accelerator.example/?token=secret','javascript:alert(1)')) {
    $rejected = $false
    try { [void][HuntUpdates]::ValidatePrefix($value) } catch { $rejected = $true }
    Assert-Update $rejected 'Unsafe accelerator URL accepted'
}
foreach ($repository in @('TheHuntLauncher','TheHuntServer')) {
    function Release([string]$version, [bool]$preview) {
        $name = if ($repository -eq 'TheHuntLauncher') { "BBSC-Launcher-$version-windows-x64.zip" } else { "TheHuntServer-Windows-v$version.zip" }
        return @{ tag_name="v$version"; draft=$false; prerelease=$preview; body='中文更新说明'; assets=@(@{
            name=$name; state='uploaded'; browser_download_url="https://github.com/ytq77/$repository/releases/download/v$version/$name"
        }) }
    }
    $stable = Release '0.1.0' $false
    $preview = Release '0.2.0-preview.10' $true
    $draft = Release '9.0.0' $false; $draft.draft = $true
    $wrongHost = Release '8.0.0' $false; $wrongHost.assets[0].browser_download_url = 'https://unrelated.example/payload.zip'
    $incomplete = Release '7.0.0' $false; $incomplete.assets[0].state = 'new'
    $json = ConvertTo-Json -InputObject @($stable, $draft, $wrongHost, $preview, $incomplete) -Depth 6
    $result = [HuntUpdates]::SelectRelease($json, $repository, $false)
    Assert-Update ($result.Version -eq '0.1.0') 'Stable-only selection failed'
    $result = [HuntUpdates]::SelectRelease($json, $repository, $true)
    Assert-Update ($result.Version -eq '0.2.0-preview.10') 'Preview selection or upload/url filtering failed'
    Assert-Update ($result.Notes -eq '中文更新说明') 'Chinese release notes damaged'
    $rejected = $false
    try { [void][HuntUpdates]::SelectRelease('{}',$repository,$true) } catch { $rejected = $true }
    Assert-Update $rejected 'Invalid API response accepted'
    $rejected = $false
    try { [void][HuntUpdates]::Check($repository,$true,'invalid-proxy','') } catch { $rejected = $true }
    Assert-Update $rejected 'Invalid HTTP proxy accepted'
    if ($Live) {
        $result = [HuntUpdates]::Check($repository,$true,'','')
        Write-Output ("LIVE: $repository => " + $result.Version + ' ' + $result.Download)
    }
}
Write-Output 'PASS: version ordering, preview channels, completed Windows assets, repository URL restrictions, Chinese notes and accelerator/proxy validation.'

# Run a real WPF dispatcher with a delayed offline query to verify startup never blocks.
$case = Join-Path ([IO.Path]::GetTempPath()) ('TheHuntStartupCheck-' + [Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($case)
$framework = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319'
$references = @('PresentationCore.dll','PresentationFramework.dll','WindowsBase.dll') | ForEach-Object {
    '/reference:' + (Join-Path $framework ('WPF\' + $_))
}
$references += '/reference:' + (Join-Path $framework 'System.Xaml.dll')
$references += '/reference:' + [IO.Path]::GetFullPath($AssemblyPath)
$executable = Join-Path $case 'StartupCheckTest.exe'
& (Join-Path $framework 'csc.exe') /nologo /target:exe /codepage:65001 $references ('/out:' + $executable) (Join-Path $PSScriptRoot 'startup-check-test.cs')
if ($LASTEXITCODE) { throw 'Startup update regression compilation failed.' }
Copy-Item -LiteralPath $AssemblyPath -Destination $case
$process = Start-Process -FilePath $executable -Wait -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $case 'stdout.txt') -RedirectStandardError (Join-Path $case 'stderr.txt')
Get-Content -LiteralPath (Join-Path $case 'stdout.txt')
if ($process.ExitCode) {
    Get-Content -LiteralPath (Join-Path $case 'stderr.txt')
    throw 'Startup update dispatcher regression failed.'
}
