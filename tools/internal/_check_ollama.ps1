$ErrorActionPreference = 'Stop'
try {
    $r = Invoke-WebRequest -Uri 'http://localhost:11434/api/tags' -TimeoutSec 3 -UseBasicParsing
    Write-Output $r.Content
} catch {
    Write-Output ("ERROR: " + $_.Exception.Message)
}
