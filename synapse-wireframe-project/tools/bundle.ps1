$baseDir = "c:\Tejaswi\Synapse\synapse-wireframe-project"
$htmlPath = "$baseDir\index.html"
$distPath = "$baseDir\dist\synapse-wireframe-single.html"

$html = Get-Content -Raw -Path $htmlPath

# Regex pattern for link tags
$cssPattern = '<link\s+rel="stylesheet"\s+href="([^"]+)">'
$html = [regex]::Replace($html, $cssPattern, {
    param($match)
    $cssFile = $match.Groups[1].Value
    $fullPath = Join-Path $baseDir $cssFile
    $content = Get-Content -Raw -Path $fullPath
    return "<style>`n$content`n</style>"
})

# Regex pattern for script tags
$jsPattern = '<script\s+src="([^"]+)"></script>'
$html = [regex]::Replace($html, $jsPattern, {
    param($match)
    $jsFile = $match.Groups[1].Value
    $fullPath = Join-Path $baseDir $jsFile
    $content = Get-Content -Raw -Path $fullPath
    return "<script>`n$content`n</script>"
})

Set-Content -Path $distPath -Value $html
Write-Host "Bundled successfully"
