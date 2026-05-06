#!/usr/bin/env pwsh
<#
Test render API with background overlay enabled
#>

$baseUrl = "http://localhost:5080"

# First, get takers to find a takerId
Write-Host "[TEST] Getting takers list..."
try {
    $takersResponse = Invoke-WebRequest -Uri "$baseUrl/api/takers" -TimeoutSec 15
    $takers = $takersResponse.Content | ConvertFrom-Json
    Write-Host "Found $($takers.Count) takers"
    if ($takers.Count -gt 0) {
        $firstTaker = $takers[0]
        Write-Host "  Using first taker: $($firstTaker.name) (id=$($firstTaker.id))"
    } else {
        Write-Host "[ERROR] No takers found"
        exit 1
    }
} catch {
    Write-Host "[ERROR] Failed to get takers: $_"
    exit 1
}

# Now test render with background=1
$takerId = $firstTaker.id
$params = @{
    takerId = $takerId
    mode = 1
    background = 1
}

$query = $params.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" } | Join-String -Separator "&"
$renderUrl = "$baseUrl/api/render?$query"

Write-Host "`n[TEST] Calling $renderUrl"

try {
    $response = Invoke-WebRequest -Uri $renderUrl -OutFile render_output.png -PassThru -TimeoutSec 120
    Write-Host "[OK] Request completed with status $($response.StatusCode)"
    Write-Host "  PNG saved: render_output.png"
    Write-Host "  PNG size: $((Get-Item render_output.png).Length) bytes"
    
    # Extract headers from response
    Write-Host "`nKey response headers:"
    foreach ($hdr in $response.Headers.Keys) {
        if ($hdr -like "X-*" -and ($hdr -like "*Background*" -or $hdr -like "*Debug*")) {
            $val = $response.Headers[$hdr]
            if ($val -is [array]) { $val = $val -join ", " }
            Write-Host "  $hdr`: $val"
        }
    }
} catch {
    Write-Host "[ERROR] Render request failed!"
    Write-Host $_.Exception.Message
    exit 1
}
