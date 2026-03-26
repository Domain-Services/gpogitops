<#
.SYNOPSIS
    Verifies GPO settings were applied correctly.

.DESCRIPTION
    Reads GPO XML files and verifies the registry settings match expected values.

.PARAMETER XmlPath
    Path to the GPO XML files directory

.EXAMPLE
    .\Verify-GPO.ps1
#>

[CmdletBinding()]
param(
    [Parameter()]
    [string]$XmlPath = "$PSScriptRoot\.."
)

$ErrorActionPreference = "Continue"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $color = switch ($Level) {
        "ERROR" { "Red" }
        "WARN"  { "Yellow" }
        "SUCCESS" { "Green" }
        "PASS" { "Green" }
        "FAIL" { "Red" }
        default { "White" }
    }
    Write-Host "[$timestamp] [$Level] $Message" -ForegroundColor $color
}

function Convert-RegistryValue {
    param([string]$Value, [string]$Type)

    switch ($Type) {
        "REG_DWORD" { return [convert]::ToInt32($Value, 16) }
        "REG_QWORD" { return [convert]::ToInt64($Value, 16) }
        default { return $Value }
    }
}

Write-Log "=========================================="
Write-Log "GPO Verification Script"
Write-Log "=========================================="

$xmlFiles = Get-ChildItem -Path $XmlPath -Filter "*.xml" -Recurse |
    Where-Object { $_.DirectoryName -notlike "*\.github*" -and $_.DirectoryName -notlike "*\scripts*" }

$passed = 0
$failed = 0
$skipped = 0

foreach ($file in $xmlFiles) {
    Write-Log "Verifying: $($file.Name)"
    [xml]$xml = Get-Content $file.FullName -Encoding UTF8

    foreach ($registry in $xml.Collection.Registry) {
        $props = $registry.Properties
        $name = $registry.name

        $hivePath = switch ($props.hive) {
            "HKEY_LOCAL_MACHINE" { "HKLM:" }
            "HKEY_CURRENT_USER"  { "HKCU:" }
            default              { "HKLM:" }
        }

        $fullPath = Join-Path $hivePath $props.key
        $valueName = $props.name
        $expectedValue = Convert-RegistryValue -Value $props.value -Type $props.type

        try {
            if (Test-Path $fullPath) {
                $actualValue = Get-ItemPropertyValue -Path $fullPath -Name $valueName -ErrorAction Stop

                if ($actualValue -eq $expectedValue) {
                    Write-Log "  [PASS] $name" -Level "PASS"
                    $passed++
                } else {
                    Write-Log "  [FAIL] $name - Expected: $expectedValue, Actual: $actualValue" -Level "FAIL"
                    $failed++
                }
            } else {
                Write-Log "  [SKIP] $name - Key does not exist: $fullPath" -Level "WARN"
                $skipped++
            }
        } catch {
            Write-Log "  [FAIL] $name - Error: $_" -Level "FAIL"
            $failed++
        }
    }
}

Write-Log ""
Write-Log "=========================================="
Write-Log "Verification Results"
Write-Log "Passed:  $passed"
Write-Log "Failed:  $failed"
Write-Log "Skipped: $skipped"
Write-Log "=========================================="

if ($failed -gt 0) {
    exit 1
}

exit 0
