param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\.build')
)

# Original The Hunt bell mark by iytq. Draw each icon size independently so
# the small Windows title-bar image remains a clear silhouette.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationCore, WindowsBase
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
[IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null

function Brush([string]$Color) {
    return [Windows.Media.BrushConverter]::new().ConvertFromString($Color)
}
function Geometry([string]$Path) {
    return [Windows.Media.Geometry]::Parse($Path)
}

$silver = Brush '#D3D0C5'
$shade = Brush '#A29F95'
$dark = Brush '#141517'
$edge = Brush '#64665F'
$sizes = @(16, 24, 32, 48, 64, 128, 256)
$images = @()
foreach ($size in $sizes) {
    $visual = [Windows.Media.DrawingVisual]::new()
    $drawing = $visual.RenderOpen()
    $drawing.PushTransform([Windows.Media.ScaleTransform]::new($size / 256.0, $size / 256.0))
    $drawing.DrawRoundedRectangle($dark, $null, [Windows.Rect]::new(4, 4, 248, 248), 46, 46)
    if ($size -ge 32) {
        $drawing.DrawEllipse($null, [Windows.Media.Pen]::new($edge, 2),
            [Windows.Point]::new(128, 128), 105, 105)
        $drawing.DrawGeometry($shade, $null,
            (Geometry 'M128,19 L133,26 128,33 123,26 Z M128,223 L133,230 128,237 123,230 Z'))
        $drawing.DrawGeometry($null, [Windows.Media.Pen]::new($edge, 2),
            (Geometry 'M18,128 L32,128 M224,128 L238,128'))
    }
    # The hanging loop and the broad bell shoulder are also visible at 16px.
    $drawing.DrawEllipse($silver, $null, [Windows.Point]::new(128, 57), 17, 18)
    $drawing.DrawEllipse($dark, $null, [Windows.Point]::new(128, 55), 7, 8)
    $drawing.DrawGeometry($silver, $null,
        (Geometry 'M111,72 L145,72 L151,85 C170,103 164,137 184,158 L194,172 C166,192 90,192 62,172 L72,158 C92,137 86,103 105,85 Z'))
    $drawing.DrawGeometry($dark, $null,
        (Geometry 'M72,170 C98,181 158,181 184,170 L183,175 C155,188 101,188 73,175 Z'))
    $drawing.DrawGeometry($silver, $null,
        (Geometry 'M120,185 L136,185 L136,194 C149,212 107,212 120,194 Z'))
    if ($size -ge 32) {
        $drawing.DrawGeometry($null, [Windows.Media.Pen]::new($shade, 2),
            (Geometry 'M105,91 C117,96 139,96 151,91 M94,127 C114,134 142,134 162,127 M82,157 C108,169 148,169 174,157'))
        $drawing.DrawGeometry($null, [Windows.Media.Pen]::new($shade, 2),
            (Geometry 'M113,94 C104,117 111,137 94,160 M126,98 L123,166 M139,96 C149,119 143,140 160,160'))
    }
    if ($size -ge 64) {
        $drawing.DrawGeometry($null, [Windows.Media.Pen]::new($shade, 1.5),
            (Geometry 'M102,110 L108,105 M100,121 L109,113 M98,132 L109,121 M94,144 L106,133 M90,154 L103,142 M149,111 L158,119 M149,123 L161,134 M151,136 L167,151'))
    }
    $drawing.Pop()
    $drawing.Close()
    $bitmap = [Windows.Media.Imaging.RenderTargetBitmap]::new(
        $size, $size, 96, 96, [Windows.Media.PixelFormats]::Pbgra32)
    $bitmap.Render($visual)
    $encoder = [Windows.Media.Imaging.PngBitmapEncoder]::new()
    $encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
    $stream = [IO.MemoryStream]::new()
    $encoder.Save($stream)
    $images += ,$stream.ToArray()
    $stream.Dispose()
}

# ICONDIR followed by ICONDIRENTRY records and lossless PNG image frames.
$icoPath = Join-Path $OutputDirectory 'TheHunt.ico'
$file = [IO.File]::Create($icoPath)
$writer = [IO.BinaryWriter]::new($file)
try {
    $writer.Write([uint16]0)
    $writer.Write([uint16]1)
    $writer.Write([uint16]$sizes.Count)
    $offset = 6 + 16 * $sizes.Count
    for ($i = 0; $i -lt $sizes.Count; $i++) {
        $dimension = if ($sizes[$i] -eq 256) { 0 } else { $sizes[$i] }
        $writer.Write([byte]$dimension)
        $writer.Write([byte]$dimension)
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]32)
        $writer.Write([uint32]$images[$i].Length)
        $writer.Write([uint32]$offset)
        $offset += $images[$i].Length
    }
    foreach ($image in $images) { $writer.Write([byte[]]$image) }
} finally {
    $writer.Dispose()
    $file.Dispose()
}
[IO.File]::WriteAllBytes((Join-Path $OutputDirectory 'the-hunt-icon.png'), $images[-1])
Write-Output "Created $icoPath (16, 24, 32, 48, 64, 128, 256px)"
