<#
.SYNOPSIS
    Deploys GPO XML settings to Windows Group Policy.

.DESCRIPTION
    This script reads GPO XML collection files and applies the registry settings
    to the local system or Active Directory Group Policy Objects.

.PARAMETER Environment
    Target environment: Staging or Production

.PARAMETER XmlPath
    Path to the GPO XML files directory

.PARAMETER GpoName
    Name of the GPO to create/update (for AD deployment)

.PARAMETER WhatIf
    Preview changes without applying

.EXAMPLE
    .\Deploy-GPO.ps1 -Environment Staging -WhatIf
    .\Deploy-GPO.ps1 -Environment Production -GpoName "Security Baseline"
#>

[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Staging", "Production")]
    [string]$Environment,

    [Parameter()]
    [string]$XmlPath = "$PSScriptRoot\..",

    [Parameter()]
    [string]$GpoName = "GPO-as-Code-$Environment",

    [Parameter()]
    [switch]$LocalOnly,

    [Parameter()]
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

# Logging
function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $color = switch ($Level) {
        "ERROR" { "Red" }
        "WARN"  { "Yellow" }
        "SUCCESS" { "Green" }
        default { "White" }
    }
    Write-Host "[$timestamp] [$Level] $Message" -ForegroundColor $color
}

# Parse GPO XML file
function Parse-GpoXml {
    param([string]$FilePath)

    Write-Log "Parsing: $FilePath"
    [xml]$xml = Get-Content $FilePath -Encoding UTF8

    $settings = @()
    $collectionName = $xml.Collection.name

    foreach ($registry in $xml.Collection.Registry) {
        $props = $registry.Properties

        $setting = [PSCustomObject]@{
            CollectionName = $collectionName
            Name           = $registry.name
            UID            = $registry.uid
            Description    = $registry.desc
            Hive           = $props.hive
            Key            = $props.key
            ValueName      = $props.name
            ValueType      = $props.type
            Value          = $props.value
            Action         = $props.action
            FilePath       = $FilePath
        }

        $settings += $setting
    }

    return $settings
}

# Convert value based on registry type
function Convert-RegistryValue {
    param(
        [string]$Value,
        [string]$Type
    )

    switch ($Type) {
        "REG_DWORD" {
            return [convert]::ToInt32($Value, 16)
        }
        "REG_QWORD" {
            return [convert]::ToInt64($Value, 16)
        }
        "REG_SZ" {
            return $Value
        }
        "REG_EXPAND_SZ" {
            return $Value
        }
        "REG_MULTI_SZ" {
            return $Value -split "`0"
        }
        "REG_BINARY" {
            $bytes = @()
            for ($i = 0; $i -lt $Value.Length; $i += 2) {
                $bytes += [convert]::ToByte($Value.Substring($i, 2), 16)
            }
            return [byte[]]$bytes
        }
        default {
            return $Value
        }
    }
}

# Get PowerShell registry type
function Get-RegistryPropertyType {
    param([string]$Type)

    switch ($Type) {
        "REG_DWORD" { return "DWord" }
        "REG_QWORD" { return "QWord" }
        "REG_SZ" { return "String" }
        "REG_EXPAND_SZ" { return "ExpandString" }
        "REG_MULTI_SZ" { return "MultiString" }
        "REG_BINARY" { return "Binary" }
        default { return "String" }
    }
}

# Apply setting to local registry
function Apply-LocalSetting {
    param([PSCustomObject]$Setting)

    $hivePath = switch ($Setting.Hive) {
        "HKEY_LOCAL_MACHINE" { "HKLM:" }
        "HKEY_CURRENT_USER"  { "HKCU:" }
        "HKEY_CLASSES_ROOT"  { "HKCR:" }
        "HKEY_USERS"         { "HKU:" }
        default              { "HKLM:" }
    }

    $fullPath = Join-Path $hivePath $Setting.Key
    $valueName = $Setting.ValueName
    $value = Convert-RegistryValue -Value $Setting.Value -Type $Setting.ValueType
    $type = Get-RegistryPropertyType -Type $Setting.ValueType

    Write-Log "  Registry: $fullPath\$valueName = $value ($type)"

    if ($WhatIf) {
        Write-Log "  [WhatIf] Would set $fullPath\$valueName" -Level "WARN"
        return
    }

    # Create key if it doesn't exist
    if (!(Test-Path $fullPath)) {
        New-Item -Path $fullPath -Force | Out-Null
        Write-Log "  Created key: $fullPath" -Level "SUCCESS"
    }

    # Set the value
    Set-ItemProperty -Path $fullPath -Name $valueName -Value $value -Type $type -Force
    Write-Log "  Applied: $($Setting.Name)" -Level "SUCCESS"
}

# Apply settings to Active Directory GPO
function Apply-AdGpoSetting {
    param(
        [PSCustomObject]$Setting,
        [string]$GpoName
    )

    # Requires GroupPolicy module (RSAT)
    if (!(Get-Module -ListAvailable -Name GroupPolicy)) {
        Write-Log "GroupPolicy module not available. Install RSAT." -Level "ERROR"
        return
    }

    Import-Module GroupPolicy

    # Create GPO if it doesn't exist
    $gpo = Get-GPO -Name $GpoName -ErrorAction SilentlyContinue
    if (!$gpo) {
        if ($WhatIf) {
            Write-Log "[WhatIf] Would create GPO: $GpoName" -Level "WARN"
        } else {
            $gpo = New-GPO -Name $GpoName
            Write-Log "Created GPO: $GpoName" -Level "SUCCESS"
        }
    }

    # Determine context (Computer or User)
    $context = if ($Setting.Hive -eq "HKEY_CURRENT_USER") { "User" } else { "Computer" }

    $keyPath = $Setting.Key
    $valueName = $Setting.ValueName
    $value = Convert-RegistryValue -Value $Setting.Value -Type $Setting.ValueType
    $type = Get-RegistryPropertyType -Type $Setting.ValueType

    Write-Log "  GPO Setting: $keyPath\$valueName = $value"

    if ($WhatIf) {
        Write-Log "  [WhatIf] Would set in GPO $GpoName" -Level "WARN"
        return
    }

    # Set registry preference in GPO
    Set-GPRegistryValue -Name $GpoName -Key "HKLM\$keyPath" -ValueName $valueName -Value $value -Type $type
    Write-Log "  Applied to GPO: $($Setting.Name)" -Level "SUCCESS"
}

# Main execution
Write-Log "=========================================="
Write-Log "GPO Deployment Script"
Write-Log "Environment: $Environment"
Write-Log "XML Path: $XmlPath"
Write-Log "Local Only: $LocalOnly"
Write-Log "WhatIf: $WhatIf"
Write-Log "=========================================="

# Find all XML files
$xmlFiles = Get-ChildItem -Path $XmlPath -Filter "*.xml" -Recurse | Where-Object { $_.DirectoryName -notlike "*\.github*" -and $_.DirectoryName -notlike "*\scripts*" }

if ($xmlFiles.Count -eq 0) {
    Write-Log "No GPO XML files found in $XmlPath" -Level "WARN"
    exit 0
}

Write-Log "Found $($xmlFiles.Count) GPO XML files"

$allSettings = @()
foreach ($file in $xmlFiles) {
    $settings = Parse-GpoXml -FilePath $file.FullName
    $allSettings += $settings
    Write-Log "  - $($file.Name): $($settings.Count) settings"
}

Write-Log "Total settings to apply: $($allSettings.Count)"
Write-Log ""

# Apply settings
$applied = 0
$failed = 0

foreach ($setting in $allSettings) {
    try {
        Write-Log "Processing: $($setting.Name) [$($setting.CollectionName)]"

        if ($LocalOnly) {
            Apply-LocalSetting -Setting $setting
        } else {
            # Try AD GPO first, fall back to local
            try {
                Apply-AdGpoSetting -Setting $setting -GpoName $GpoName
            } catch {
                Write-Log "  AD GPO failed, applying locally: $_" -Level "WARN"
                Apply-LocalSetting -Setting $setting
            }
        }

        $applied++
    } catch {
        Write-Log "  Failed to apply $($setting.Name): $_" -Level "ERROR"
        $failed++
    }
}

Write-Log ""
Write-Log "=========================================="
Write-Log "Deployment Complete"
Write-Log "Applied: $applied"
Write-Log "Failed: $failed"
Write-Log "=========================================="

if ($failed -gt 0) {
    exit 1
}

exit 0
