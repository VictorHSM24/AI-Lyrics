$ErrorActionPreference = 'Stop'
$body = @{
    model = "qwen3:8b-q4_K_M"
    messages = @(
        @{ role = "system"; content = "Responda apenas com JSON." },
        @{ role = "user"; content = "Texto atual: O Senhor e meu pastor.`n`nResponda apenas com JSON: {`"intent`": `"show_reference`" | `"none`", `"candidates`": []}" }
    )
    stream = $false
    options = @{ temperature = 0.1; top_p = 0.9; num_predict = 300 }
    think = $false
} | ConvertTo-Json -Depth 10

$sw = [System.Diagnostics.Stopwatch]::StartNew()
try {
    $r = Invoke-WebRequest -Uri 'http://localhost:11434/api/chat' -Method Post `
        -Body $body -ContentType 'application/json; charset=utf-8' `
        -TimeoutSec 120 -UseBasicParsing
    $sw.Stop()
    Write-Output ("ELAPSED: " + $sw.Elapsed.TotalSeconds + "s")
    Write-Output $r.Content
} catch {
    $sw.Stop()
    Write-Output ("ERROR after " + $sw.Elapsed.TotalSeconds + "s: " + $_.Exception.Message)
}
