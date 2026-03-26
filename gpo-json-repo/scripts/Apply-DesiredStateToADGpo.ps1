<#
.SYNOPSIS
    Applies desired-state JSON policies to an Active Directory GPO.

.DESCRIPTION
    Reads environments/<env>/desired-state.json and referenced policy JSON files,
    then writes registry-based settings into a domain GPO using Set-GPRegistryValue.

    NOTE:
    - Must run on Windows with RSAT GroupPolicy module.
    - Must run with permissions to edit GPOs in the domain.

.PARAMETER RepoRoot
    Path to gpo-json-repo root.

.PARAMETER Environment
    Environment name under environments/ (default: dev).

.PARAMETER ManifestPath
    Optional explicit desired-state.json path.

.PARAMETER GpoName
    Target GPO name. If not provided, uses "GPO-<environment>-DesiredState".

.PARAMETER CreateIfMissing
    Create the GPO if it does not exist.

.PARAMETER LinkToTargetOU
    If set, link the GPO to target_ou from desired-state.json.

.PARAMETER WhatIf
    Preview changes only.

.EXAMPLE
    .\Apply-DesiredStateToADGpo.ps1 -RepoRoot C:\src\gpo-json-repo -Environment dev -GpoName "Dev Baseline" -WhatIf

.EXAMPLE
    .\Apply-DesiredStateToADGpo.ps1 -RepoRoot C:\src\gpo-json-repo -Environment dev -GpoName "Dev Baseline" -CreateIfMissing -LinkToTargetOU
#>

[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter()]
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,

    [Parameter()]
    [string]$Environment = "dev",

    [Parameter()]
    [string]$ManifestPath,

    [Parameter()]
    [string]$GpoName,

    [Parameter()]
    [switch]$CreateIfMissing,

    [Parameter()]
    [switch]$LinkToTargetOU
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

function Convert-ToGpType {
    param([string]$ValueType)

    switch ($ValueType) {
        "REG_DWORD"     { return "DWord" }
        "REG_QWORD"     { return "QWord" }
        "REG_SZ"        { return "String" }
        "REG_EXPAND_SZ" { return "ExpandString" }
        "REG_MULTI_SZ"  { return "MultiString" }
        "REG_BINARY"    { return "Binary" }
        default {
            throw "Unsupported value_type for Set-GPRegistryValue: $ValueType"
        }
    }
}

function Split-ForGpKey {
    param([string]$RegistryPath)

    # Input example: HKEY_LOCAL_MACHINE\Software\Policies\...
    # Output key example: HKLM\Software\Policies\...
    if ($RegistryPath -match '^HKEY_LOCAL_MACHINE\\(.+)$') {
        return "HKLM\$($Matches[1])"
    }
    if ($RegistryPath -match '^HKEY_CURRENT_USER\\(.+)$') {
        return "HKCU\$($Matches[1])"
    }

    throw "Only HKEY_LOCAL_MACHINE/HKEY_CURRENT_USER are supported for AD GPO registry settings. Got: $RegistryPath"
}

function Convert-ValueForGp {
    param(
        $Value,
        [string]$ValueType
    )

    switch ($ValueType) {
        "REG_DWORD" { return [int64]$Value }
        "REG_QWORD" { return [int64]$Value }
        "REG_MULTI_SZ" {
            if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string]) {
                return @($Value)
            }
            return @([string]$Value)
        }
        default { return $Value }
    }
}

# Preconditions
if (-not (Get-Module -ListAvailable -Name GroupPolicy)) {
    throw "GroupPolicy module not found. Install RSAT Group Policy Management tools."
}
Import-Module GroupPolicy

$repoRootResolved = (Resolve-Path $RepoRoot).Path
$manifestResolved = Resolve-ManifestPath -RepoRoot $repoRootResolved -Environment $Environment -ManifestPath $ManifestPath
$manifest = Get-Content $manifestResolved -Raw -Encoding UTF8 | ConvertFrom-Json

if ([string]::IsNullOrWhiteSpace($GpoName)) {
    $GpoName = "GPO-$Environment-DesiredState"
}

Write-Log "Manifest: $manifestResolved"
Write-Log "Target GPO: $GpoName"

$gpo = Get-GPO -Name $GpoName -ErrorAction SilentlyContinue
if (-not $gpo) {
    if (-not $CreateIfMissing) {
        throw "GPO '$GpoName' not found. Use -CreateIfMissing to create it."
    }

    if ($PSCmdlet.ShouldProcess($GpoName, "Create new GPO")) {
        $gpo = New-GPO -Name $GpoName
        Write-Log "Created GPO: $GpoName" "SUCCESS"
    }
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

        $policy = Get-Content $candidate -Raw -Encoding UTF8 | ConvertFrom-Json
        $policyId = [string]$policy.id
        $policyName = [string]$policy.name
        if ([string]::IsNullOrWhiteSpace($policyId)) { $policyId = [IO.Path]::GetFileNameWithoutExtension($candidate) }
        if ([string]::IsNullOrWhiteSpace($policyName)) { $policyName = $policyId }

        foreach ($setting in $policy.settings) {
            $registryPath = [string]$setting.registry_path
            $valueName = [string]$setting.value_name
            $valueType = [string]$setting.value_type
            $rawValue = $setting.value

            $key = Split-ForGpKey -RegistryPath $registryPath
            $gpType = Convert-ToGpType -ValueType $valueType
            $gpValue = Convert-ValueForGp -Value $rawValue -ValueType $valueType

            $target = "$GpoName :: $key\$valueName"
            if ($PSCmdlet.ShouldProcess($target, "Set-GPRegistryValue [$policyId] $policyName")) {
                Set-GPRegistryValue -Name $GpoName -Key $key -ValueName $valueName -Type $gpType -Value $gpValue
                Write-Log "Applied to GPO: $target = '$rawValue' ($valueType)" "SUCCESS"
            }

            $applied++
        }
    }
    catch {
        $failed++
        Write-Log "Failed policy '$relPolicyPath': $($_.Exception.Message)" "ERROR"
    }
}

if ($LinkToTargetOU -and -not [string]::IsNullOrWhiteSpace([string]$manifest.target_ou)) {
    $ou = [string]$manifest.target_ou
    if ($PSCmdlet.ShouldProcess("$GpoName -> $ou", "Link GPO to OU")) {
        New-GPLink -Name $GpoName -Target $ou -Enforced:$false -ErrorAction Stop | Out-Null
        Write-Log "Linked GPO '$GpoName' to '$ou'" "SUCCESS"
    }
}

Write-Log "Completed. Applied settings: $applied, Failed policies: $failed"

if ($failed -gt 0) { exit 1 }
exit 0
