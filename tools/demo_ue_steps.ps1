# Sequential Unreal Remote Control demo. Parent runs this after 30010 is up.
# tools/ue.py has no --timeout CLI (HTTP default 180s); steps run in order.

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $RepoRoot

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$UePy = Join-Path $RepoRoot "tools\ue.py"

if (-not (Test-Path -LiteralPath $Python)) {
    Write-Host "python : fail (missing .venv\Scripts\python.exe)"
    exit 1
}

function Get-ShortText {
    param([string]$Text, [int]$Max = 180)
    if ([string]::IsNullOrWhiteSpace($Text)) { return "" }
    $one = (($Text -replace "\s+", " ").Trim())
    if ($one.Length -gt $Max) { return $one.Substring(0, $Max) + "..." }
    return $one
}

function Convert-JsonEasy {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return $null }
    $trim = $Text.Trim()
    $trim = $trim -replace "^LogPython:\s*", ""
    try {
        return ($trim | ConvertFrom-Json -ErrorAction Stop)
    } catch {
        return $null
    }
}

function Test-DocOkFalse {
    param($Doc)
    if ($null -eq $Doc) { return $false }
    if ($null -eq $Doc.PSObject) { return $false }
    if ($null -ne $Doc.PSObject.Properties["ok"] -and $Doc.ok -eq $false) {
        return $true
    }
    return $false
}

function Test-DocExecFailed {
    param($Doc)
    if ($null -eq $Doc -or $null -eq $Doc.PSObject) { return $false }
    if ($null -ne $Doc.PSObject.Properties["bSuccess"] -and $Doc.bSuccess -eq $false) {
        return $true
    }
    return $false
}

function Get-LogChunks {
    param($Doc)
    $chunks = New-Object System.Collections.Generic.List[string]
    if ($null -eq $Doc -or $null -eq $Doc.PSObject) { return $chunks }
    $logs = $null
    if ($null -ne $Doc.PSObject.Properties["LogOutput"]) { $logs = $Doc.LogOutput }
    if ($null -eq $logs) { return $chunks }
    foreach ($entry in @($logs)) {
        if ($entry -is [string]) {
            if (-not [string]::IsNullOrWhiteSpace($entry)) { $chunks.Add([string]$entry) }
            continue
        }
        if ($null -ne $entry -and $null -ne $entry.PSObject -and $null -ne $entry.PSObject.Properties["Output"]) {
            $s = [string]$entry.Output
            if (-not [string]::IsNullOrWhiteSpace($s)) { $chunks.Add($s) }
        }
    }
    return $chunks
}

function Test-UeOutputFailed {
    param([string]$Text)
    $root = Convert-JsonEasy $Text
    if ($null -eq $root) { return $false }

    $docs = New-Object System.Collections.Generic.List[object]
    $docs.Add($root)
    if ($null -ne $root.PSObject.Properties["ReturnValue"] -and $null -ne $root.ReturnValue) {
        $docs.Add($root.ReturnValue)
    }

    foreach ($doc in $docs) {
        if (Test-DocOkFalse $doc) { return $true }
        if (Test-DocExecFailed $doc) { return $true }

        if ($null -ne $doc.PSObject.Properties["CommandResult"]) {
            $cmd = $doc.CommandResult
            if ($cmd -is [string]) {
                $inner = Convert-JsonEasy $cmd
                if (Test-DocOkFalse $inner) { return $true }
            }
        }

        $chunks = Get-LogChunks $doc
        foreach ($chunk in $chunks) {
            $inner = Convert-JsonEasy $chunk
            if (Test-DocOkFalse $inner) { return $true }
        }
        if ($chunks.Count -gt 0) {
            $joined = [string]::Join("`n", $chunks.ToArray())
            $inner = Convert-JsonEasy $joined
            if (Test-DocOkFalse $inner) { return $true }
        }
    }
    return $false
}

function Invoke-UeStep {
    param(
        [string]$Name,
        [string]$RelPath,
        [switch]$Optional
    )

    $scriptPath = Join-Path $RepoRoot $RelPath
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        if ($Optional) {
            Write-Host "$Name : skipped (not found)"
            return
        }
        Write-Host "$Name : fail (missing $RelPath)"
        exit 1
    }

    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $stdout = & $Python $UePy --file $scriptPath 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev

    $text = ($stdout | Out-String)
    if ($code -ne 0) {
        Write-Host "$Name : fail (exit $code) $(Get-ShortText $text)"
        if ($code -gt 0) { exit $code }
        exit 1
    }
    if (Test-UeOutputFailed $text) {
        Write-Host "$Name : fail (ok:false) $(Get-ShortText $text)"
        exit 1
    }
    Write-Host "$Name : ok"
}

# Intended bounds: void 60s, import 180s, inspect 30s, forward 60s.
Invoke-UeStep -Name "void"    -RelPath "unreal\DroneBench\Scripts\demo_void.py"
Invoke-UeStep -Name "import"  -RelPath "unreal\DroneBench\Scripts\import_glb.py"
Invoke-UeStep -Name "inspect" -RelPath "unreal\DroneBench\Scripts\demo_inspect.py" -Optional
Invoke-UeStep -Name "forward" -RelPath "unreal\DroneBench\Scripts\demo_forward.py"

exit 0
