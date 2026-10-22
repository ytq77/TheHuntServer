$ErrorActionPreference = 'Stop'
$framework = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319'
$output = Join-Path $PSScriptRoot 'build-ui'
[void][IO.Directory]::CreateDirectory($output)
& (Join-Path $PSScriptRoot 'make-icon.ps1') -OutputDirectory $output
if ($LASTEXITCODE) { throw 'Icon generation failed.' }
$references = @('PresentationCore.dll','PresentationFramework.dll','WindowsBase.dll') | ForEach-Object {
    '/reference:' + (Join-Path $framework ('WPF\' + $_))
}
$references += '/reference:' + (Join-Path $framework 'System.Xaml.dll')
$references += '/reference:System.Web.Extensions.dll'
& (Join-Path $framework 'csc.exe') /nologo /target:winexe /utf8output /codepage:65001 $references `
    ('/win32icon:' + (Join-Path $output 'TheHunt.ico')) `
    ('/resource:' + (Join-Path $PSScriptRoot 'gui\ServerWindow.xaml') + ',TheHuntServer.Window.xaml') `
    ('/out:' + (Join-Path $output 'Server.exe')) (Join-Path $PSScriptRoot 'gui\ServerWindow.cs')
if ($LASTEXITCODE) { throw 'Desktop window compilation failed.' }
$process = Start-Process -FilePath (Join-Path $output 'Server.exe') -ArgumentList '--validate' -Wait -PassThru -WindowStyle Hidden
if ($process.ExitCode) { throw 'WPF window validation failed.' }
Write-Output 'Native WPF manager compiled and validated.'
