<#
.SYNOPSIS
    Applies gpo-json-repo desired-state policies to the local Windows registry.

.DESCRIPTION
    Reads environments/<env>/desired-state.json, resolves referenced policy JSON files,
    and applies each setting to the local registry.

    This is LOCAL ONLY (no AD GPO writes).

.PARAMETER RepoRoot
    Path to gpo-json-repo root.

.PARAMETER Environment
    Environment folder name under environments/ (for desired-state.json).

.PARAMETER ManifestPath
    Optional explicit path to desired-state.json (overrides Environment).

.PARAMETER WhatIf
    Preview changes without writing.

.EXAMPLE
    .\Apply-DesiredStateLocal.ps1 -RepoRoot C:\src\gpo-json-repo -Environment dev -WhatIf

.EXAMPLE
    .\Apply-DesiredStateLocal.ps1 -RepoRoot C:\src\gpo-json-repo -Environment dev
#>

[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter()]
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,

    [Parameter()]
    [string]$Environment = "dev",

    [Parameter()]
    [string]$ManifestPath
)

$ErrorActionPreference = "Stop"

function Write-Log {
    param(
        [string]$Message,
        [ValidateSet("INFO", "WARN", "ERROR", "SUCCESS")]
        [string]$Level = "INFO"
    )

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $color = switch ($Level) {
        "ERROR"   { "Red" }
        "WARN"    { "Yellow" }
        "SUCCESS" { "Green" }
        default    { "White" }
    }

    Write-Host "[$timestamp] [$Level] $Message" -ForegroundColor $color
}

function Resolve-ManifestPath {
    param(
        [string]$RepoRoot,
        [string]$Environment,
        [string]$ManifestPath
    )

    if (-not [string]::IsNullOrWhiteSpace($ManifestPath)) {
        return (Resolve-Path $ManifestPath).Path
    }

    $candidate = Join-Path $RepoRoot "environments/$Environment/desired-state.json"
    if (-not (Test-Path $candidate)) {
        throw "Manifest not found: $candidate"
    }

    return (Resolve-Path $candidate).Path
}

function Convert-RegistryValue {
    param(
        [AllowNull()]
        $Value,
        [string]$ValueType
    )

    switch ($ValueType) {
        "REG_DWORD" {
            if ($Value -is [int] -or $Value -is [long]) { return [int]$Value }
            return [int]([Convert]::ToInt64([string]$Value, 10))
        }
        "REG_QWORD" {
            if ($Value -is [long]) { return [long]$Value }
            return [long]([Convert]::ToInt64([string]$Value, 10))
        }
        "REG_MULTI_SZ" {
            if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string]) {
                return @($Value)
            }
            if ($null -eq $Value) { return @() }
            return @([string]$Value)
        }
        "REG_BINARY" {
            if ($Value -is [byte[]]) { return $Value }

            # Supports hex string, e.g. "0A0B0C"
            $text = ([string]$Value).Replace(" ", "")
            if ($text.Length % 2 -ne 0) {
                throw "REG_BINARY value must have even-length hex string. Got: '$Value'"
            }

            $bytes = New-Object byte[] ($text.Length / 2)
            for ($i = 0; $i -lt $text.Length; $i += 2) {
                $bytes[$i / 2] = [Convert]::ToByte($text.Substring($i, 2), 16)
            }
            return $bytes
        }
        default {
            if ($null -eq $Value) { return "" }
            return [string]$Value
        }
    }
}

function Get-RegistryPropertyType {
    param([string]$ValueType)

    switch ($ValueType) {
        "REG_DWORD"     { return "DWord" }
        "REG_QWORD"     { return "QWord" }
        "REG_SZ"        { return "String" }
        "REG_EXPAND_SZ" { return "ExpandString" }
        "REG_MULTI_SZ"  { return "MultiString" }
        "REG_BINARY"    { return "Binary" }
        default          { return "String" }
    }
}

function Get-HivePrefix {
    param([string]$RegistryPath)

    switch -Regex ($RegistryPath) {
        "^HKEY_LOCAL_MACHINE\\"  { return "HKLM:" }
        "^HKEY_CURRENT_USER\\"   { return "HKCU:" }
        "^HKEY_CLASSES_ROOT\\"   { return "HKCR:" }
        "^HKEY_USERS\\"          { return "HKU:" }
        "^HKEY_CURRENT_CONFIG\\" { return "HKCC:" }
        default { throw "Unsupported registry hive in path: $RegistryPath" }
    }
}

function Split-RegistryPath {
    param([string]$RegistryPath)

    $prefix = Get-HivePrefix -RegistryPath $RegistryPath
    $subKey = $RegistryPath -replace "^HKEY_[^\\]+\\", ""

    if ([string]::IsNullOrWhiteSpace($subKey)) {
        throw "Invalid registry path: $RegistryPath"
    }

    return @($prefix, $subKey)
}

function Apply-Setting {
    param(
        [pscustomobject]$Setting,
        [string]$PolicyId,
        [string]$PolicyName
    )

    $registryPath = [string]$Setting.registry_path
    $valueName = [string]$Setting.value_name
    $valueType = [string]$Setting.value_type
    $rawValue = $Setting.value

    if ([string]::IsNullOrWhiteSpace($registryPath) -or
        [string]::IsNullOrWhiteSpace($valueName) -or
        [string]::IsNullOrWhiteSpace($valueType)) {
        throw "Invalid setting in policy '$PolicyId' ($PolicyName). Required: registry_path, value_name, value_type"
    }

    $parts = Split-RegistryPath -RegistryPath $registryPath
    $hive = $parts[0]
    $subKey = $parts[1]
    $fullPath = Join-Path $hive $subKey

    $converted = Convert-RegistryValue -Value $rawValue -ValueType $valueType
    $psType = Get-RegistryPropertyType -ValueType $valueType

    $target = "$fullPath\$valueName"
    $summary = "[$PolicyId] $PolicyName"

    if ($PSCmdlet.ShouldProcess($target, "Set $psType value ($summary)")) {
        if (-not (Test-Path $fullPath)) {
            New-Item -Path $fullPath -Force | Out-Null
            Write-Log "Created key: $fullPath" "SUCCESS"
        }

        Set-ItemProperty -Path $fullPath -Name $valueName -Value $converted -Type $psType -Force
        Write-Log "Applied: $target = '$rawValue' ($valueType) from $summary" "SUCCESS"
    }
}

Write-Log "Starting local desired-state apply"
Write-Log "RepoRoot: $RepoRoot"
Write-Log "Environment: $Environment"

$repoRootResolved = (Resolve-Path $RepoRoot).Path
$manifestResolved = Resolve-ManifestPath -RepoRoot $repoRootResolved -Environment $Environment -ManifestPath $ManifestPath

Write-Log "Manifest: $manifestResolved"

$manifest = Get-Content $manifestResolved -Raw -Encoding UTF8 | ConvertFrom-Json

if ($manifest.environment -ne $Environment -and [string]::IsNullOrWhiteSpace($ManifestPath)) {
    Write-Log "Manifest environment '$($manifest.environment)' differs from parameter '$Environment'" "WARN"
}

if (-not $manifest.policies -or $manifest.policies.Count -eq 0) {
    throw "No policies listed in manifest: $manifestResolved"
}

$applied = 0
$failed = 0

foreach ($relPolicyPath in $manifest.policies) {
    try {
        $candidate = Join-Path $repoRootResolved $relPolicyPath
        if (-not (Test-Path $candidate)) {
            throw "Policy file not found: $relPolicyPath"
        }

        $policyPath = (Resolve-Path $candidate).Path
        $policy = Get-Content $policyPath -Raw -Encoding UTF8 | ConvertFrom-Json

        if (-not $policy.settings -or $policy.settings.Count -eq 0) {
            throw "Policy has no settings: $relPolicyPath"
        }

        $policyId = [string]$policy.id
        $policyName = [string]$policy.name
        if ([string]::IsNullOrWhiteSpace($policyId)) { $policyId = [IO.Path]::GetFileNameWithoutExtension($policyPath) }
        if ([string]::IsNullOrWhiteSpace($policyName)) { $policyName = $policyId }

        Write-Log "Applying policy: $policyId ($policyName)"

        foreach ($setting in $policy.settings) {
            Apply-Setting -Setting $setting -PolicyId $policyId -PolicyName $policyName
            $applied++
        }
    }
    catch {
        $failed++
        Write-Log "Failed policy '$relPolicyPath': $($_.Exception.Message)" "ERROR"
    }
}

Write-Log "Completed. Applied: $applied, Failed policies: $failed"

if ($failed -gt 0) {
    exit 1
}

exit 0
