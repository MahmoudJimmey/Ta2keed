param([string]$pptx, [string]$outdir)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $outdir | Out-Null
$app = New-Object -ComObject PowerPoint.Application
$pres = $app.Presentations.Open($pptx, $true, $false, $false)
$i = 1
foreach ($s in $pres.Slides) { $s.Export((Join-Path $outdir ("slide{0:D2}.png" -f $i)), "PNG", 1600, 900); $i++ }
$pdf = [System.IO.Path]::GetFullPath([System.IO.Path]::ChangeExtension($pptx, ".pdf"))
$pres.SaveAs($pdf, 32)
$pres.Close()
$app.Quit()
Write-Output "rendered $($i-1) slides; pdf $pdf"
