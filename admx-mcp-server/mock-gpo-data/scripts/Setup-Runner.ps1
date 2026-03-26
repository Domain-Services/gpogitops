<#
.SYNOPSIS
    Sets up a GitHub Actions self-hosted runner for GPO deployment.

.DESCRIPTION
    Downloads and configures a GitHub Actions runner on a Windows server
    for deploying GPO-as-Code changes.

.PARAMETER GitHubOrg
    GitHub organization name

.PARAMETER GitHubRepo
    GitHub repository name

.PARAMETER RunnerToken
    Runner registration token from GitHub

.PARAMETER Environment
    Environment label (staging or production)

.EXAMPLE
    .\Setup-Runner.ps1 -GitHubOrg "myorg" -GitHubRepo "gpo-policies" -RunnerToken "ABCD1234" -Environment "staging"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$GitHubOrg,

    [Parameter(Mandatory)]
    [string]$GitHubRepo,

    [Parameter(Mandatory)]
    [string]$RunnerToken,

    [Parameter(Mandatory)]
    [ValidateSet("staging", "production")]
    [string]$Environment,

    [Parameter()]
    [string]$InstallPath = "C:\actions-runner"
)

$ErrorActionPreference = "Stop"

Write-Host "=========================================="
Write-Host "GitHub Actions Runner Setup"
Write-Host "=========================================="
Write-Host "Organization: $GitHubOrg"
Write-Host "Repository: $GitHubRepo"
Write-Host "Environment: $Environment"
Write-Host "Install Path: $InstallPath"
Write-Host ""

# Check prerequisites
Write-Host "Checking prerequisites..."

# Check for admin rights
if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    throw "This script must be run as Administrator"
}

# Check for RSAT (for AD GPO management)
$rsatFeature = Get-WindowsCapability -Online | Where-Object { $_.Name -like "*RSAT*GroupPolicy*" }
if ($rsatFeature -and $rsatFeature.State -ne "Installed") {
    Write-Host "Installing RSAT Group Policy Management Tools..."
    Add-WindowsCapability -Online -Name $rsatFeature.Name
}

# Create directories
Write-Host "Creating directories..."
$directories = @(
    $InstallPath,
    "C:\GPO-Deploy",
    "C:\GPO-Backups"
)

foreach ($dir in $directories) {
    if (!(Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "  Created: $dir"
    }
}

# Download runner
Write-Host "Downloading GitHub Actions Runner..."
$runnerVersion = "2.311.0"  # Update to latest version
$runnerZip = "$env:TEMP\actions-runner.zip"
$runnerUrl = "https://github.com/actions/runner/releases/download/v$runnerVersion/actions-runner-win-x64-$runnerVersion.zip"

Invoke-WebRequest -Uri $runnerUrl -OutFile $runnerZip
Expand-Archive -Path $runnerZip -DestinationPath $InstallPath -Force
Remove-Item $runnerZip

# Configure runner
Write-Host "Configuring runner..."
Set-Location $InstallPath

$configArgs = @(
    "--url", "https://github.com/$GitHubOrg/$GitHubRepo",
    "--token", $RunnerToken,
    "--name", "$env:COMPUTERNAME-$Environment",
    "--labels", "self-hosted,windows,gpo-$Environment",
    "--work", "_work",
    "--runasservice"
)

& .\config.cmd @configArgs

# Install and start service
Write-Host "Installing runner service..."
& .\svc.cmd install

Write-Host "Starting runner service..."
& .\svc.cmd start

Write-Host ""
Write-Host "=========================================="
Write-Host "Runner Setup Complete!"
Write-Host "=========================================="
Write-Host ""
Write-Host "Runner Name: $env:COMPUTERNAME-$Environment"
Write-Host "Labels: self-hosted, windows, gpo-$Environment"
Write-Host ""
Write-Host "Next Steps:"
Write-Host "1. Verify runner appears in GitHub: Settings > Actions > Runners"
Write-Host "2. Push changes to your GPO repository to trigger deployment"
Write-Host ""
