Param(
    [Parameter(Mandatory = $true)]
    [string]$DomainController,

    [Parameter(Mandatory = $true)]
    [string]$DomainName,

    [Parameter(Mandatory = $false)]
    [string]$ExpectedGpoName,

    [Parameter(Mandatory = $false)]
    [string]$OutputPath = ".\\cloud-dc-gpo-validation.json"
)

$ErrorActionPreference = 'Stop'

function Add-CheckResult {
    Param(
        [hashtable]$Results,
        [string]$Name,
        [bool]$Passed,
        [string]$Details
    )

    $Results.checks += @{
        name = $Name
        passed = $Passed
        details = $Details
        timestamp = (Get-Date).ToString("o")
    }
}

$results = @{
    domainController = $DomainController
    domainName = $DomainName
    checks = @()
    overallPassed = $true
    generatedAt = (Get-Date).ToString("o")
}

try {
    # 1) DNS resolution
    try {
        Resolve-DnsName -Name $DomainController -ErrorAction Stop | Out-Null
        Add-CheckResult -Results $results -Name "dns_resolution" -Passed $true -Details "Resolved $DomainController"
    }
    catch {
        Add-CheckResult -Results $results -Name "dns_resolution" -Passed $false -Details $_.Exception.Message
    }

    # 2) ICMP reachability
    try {
        $ping = Test-Connection -ComputerName $DomainController -Count 1 -Quiet -ErrorAction Stop
        Add-CheckResult -Results $results -Name "icmp_reachability" -Passed ([bool]$ping) -Details "Ping result: $ping"
    }
    catch {
        Add-CheckResult -Results $results -Name "icmp_reachability" -Passed $false -Details $_.Exception.Message
    }

    # 3) SYSVOL availability (SMB path)
    $sysvolPath = "\\$DomainController\\SYSVOL"
    try {
        $sysvol = Test-Path $sysvolPath
        Add-CheckResult -Results $results -Name "sysvol_access" -Passed ([bool]$sysvol) -Details "Path checked: $sysvolPath"
    }
    catch {
        Add-CheckResult -Results $results -Name "sysvol_access" -Passed $false -Details $_.Exception.Message
    }

    # 4) Required modules
    $gpModule = Get-Module -ListAvailable -Name GroupPolicy
    $adModule = Get-Module -ListAvailable -Name ActiveDirectory
    Add-CheckResult -Results $results -Name "module_group_policy" -Passed ([bool]$gpModule) -Details "GroupPolicy module available"
    Add-CheckResult -Results $results -Name "module_active_directory" -Passed ([bool]$adModule) -Details "ActiveDirectory module available"

    if ($ExpectedGpoName) {
        try {
            Import-Module GroupPolicy -ErrorAction Stop
            $gpo = Get-GPO -Name $ExpectedGpoName -Domain $DomainName -Server $DomainController -ErrorAction Stop
            Add-CheckResult -Results $results -Name "expected_gpo_exists" -Passed $true -Details "Found GPO '$ExpectedGpoName' with ID $($gpo.Id)"
        }
        catch {
            Add-CheckResult -Results $results -Name "expected_gpo_exists" -Passed $false -Details $_.Exception.Message
        }
    }

    foreach ($check in $results.checks) {
        if (-not $check.passed) {
            $results.overallPassed = $false
            break
        }
    }
}
catch {
    $results.overallPassed = $false
    Add-CheckResult -Results $results -Name "unexpected_error" -Passed $false -Details $_.Exception.Message
}

$results | ConvertTo-Json -Depth 6 | Out-File -FilePath $OutputPath -Encoding utf8
Write-Host "Validation report written to $OutputPath"

if (-not $results.overallPassed) {
    Write-Error "Cloud DC / GPO validation failed"
    exit 1
}

Write-Host "Cloud DC / GPO validation passed"
exit 0
