<#
.SYNOPSIS
    Exports ADMX/ADML policy definitions to a searchable JSON dictionary.

.DESCRIPTION
    Parses Windows ADMX (policy definitions) and ADML (localized strings) files
    to create a comprehensive dictionary of all Group Policy settings with
    human-readable names and descriptions.

.PARAMETER ADMXPath
    Path to ADMX files. Default: C:\Windows\PolicyDefinitions

.PARAMETER Language
    Language code for ADML files. Default: en-US

.PARAMETER OutputPath
    Output JSON file path. Default: ./admx-dictionary.json

.PARAMETER SkipFullPolicies
    If set, only exports indexes without full policy objects (smaller output)

.EXAMPLE
    ./Export-ADMXtoJSON.ps1 -OutputPath ./admx-dictionary.json
#>

param(
    [string]$ADMXPath = "C:\Windows\PolicyDefinitions",
    [string]$Language = "en-US",
    [string]$OutputPath = "./admx-dictionary.json",
    [switch]$SkipFullPolicies
)

$ErrorActionPreference = "Stop"

function Parse-ADMLStrings {
    param([string]$ADMLPath)

    $strings = @{}

    if (-not (Test-Path -LiteralPath $ADMLPath)) {
        Write-Warning "ADML file not found: $ADMLPath"
        return $strings
    }

    [xml]$adml = Get-Content -LiteralPath $ADMLPath -Raw -Encoding UTF8

    # Setup namespace manager
    $ns = New-Object System.Xml.XmlNamespaceManager($adml.NameTable)
    $nsUri = $adml.DocumentElement.NamespaceURI
    $px = ""

    if ($nsUri) {
        $ns.AddNamespace("r", $nsUri)
        $px = "r:"
    }

    # Parse string table
    $stringNodes = if ($nsUri) {
        $adml.SelectNodes("//${px}stringTable/${px}string", $ns)
    } else {
        $adml.SelectNodes("//stringTable/string")
    }
    foreach ($string in $stringNodes) {
        $id = $string.GetAttribute("id")
        if ($id) {
            $strings["string.$id"] = $string.InnerText
        }
    }

    # Parse presentation table - store only InnerText, not full node
    $presentationNodes = if ($nsUri) {
        $adml.SelectNodes("//${px}presentationTable/${px}presentation", $ns)
    } else {
        $adml.SelectNodes("//presentationTable/presentation")
    }
    foreach ($presentation in $presentationNodes) {
        $id = $presentation.GetAttribute("id")
        if ($id) {
            $strings["presentation.$id"] = $presentation.InnerText
        }
    }

    return $strings
}

function Resolve-StringReference {
    param(
        [string]$Reference,
        [hashtable]$Strings
    )

    if ([string]::IsNullOrEmpty($Reference)) {
        return $null
    }

    $ref = $Reference.Trim()

    # Format: $(string.stringId) or $(presentation.presentationId)
    if ($ref -match '^\$\((string|presentation)\.(.+)\)$') {
        $type = $Matches[1]
        $id = $Matches[2]
        $key = "$type.$id"
        if ($Strings.ContainsKey($key)) {
            return $Strings[$key]
        }
    }

    # Handle embedded references: "Some text $(string.X) more text"
    $resolved = $ref
    $pattern = '\$\((string|presentation)\.([^)]+)\)'
    $allMatches = [regex]::Matches($ref, $pattern)
    foreach ($match in $allMatches) {
        $type = $match.Groups[1].Value
        $id = $match.Groups[2].Value
        $key = "$type.$id"
        if ($Strings.ContainsKey($key)) {
            $resolved = $resolved.Replace($match.Value, $Strings[$key])
        }
    }

    if ($resolved -ne $ref) {
        return $resolved
    }

    return $Reference
}

function Parse-SupportedOnDefinitions {
    param(
        $ADMX,
        $NamespaceManager,
        [string]$Prefix
    )

    $supportedOn = @{}

    $px = if ($Prefix) { "${Prefix}:" } else { "" }
    $xpath = "//${px}supportedOn/${px}definitions/${px}definition"

    $definitions = if ($Prefix) {
        $ADMX.SelectNodes($xpath, $NamespaceManager)
    } else {
        $ADMX.SelectNodes($xpath)
    }

    foreach ($def in $definitions) {
        $name = $def.GetAttribute("name")
        $displayName = $def.GetAttribute("displayName")
        if ($name -and $displayName) {
            $supportedOn[$name] = $displayName
        }
    }

    return $supportedOn
}

function Parse-PolicyElements {
    param(
        $Policy,
        $NamespaceManager,
        [string]$Prefix,
        [hashtable]$Strings
    )

    $elements = @()

    $px = if ($Prefix) { "${Prefix}:" } else { "" }

    # Guard against null elements
    $elementsNode = if ($Prefix) {
        $Policy.SelectSingleNode("${px}elements", $NamespaceManager)
    } else {
        $Policy.SelectSingleNode("elements")
    }

    if (-not $elementsNode) {
        return $elements
    }

    $elementTypes = @('decimal', 'boolean', 'text', 'enum', 'list', 'multiText', 'longDecimal')

    foreach ($elementType in $elementTypes) {
        $policyElements = if ($Prefix) {
            $elementsNode.SelectNodes("${px}$elementType", $NamespaceManager)
        } else {
            $elementsNode.SelectNodes($elementType)
        }

        foreach ($element in $policyElements) {
            $elementDef = @{
                type = $elementType
                id = $element.GetAttribute("id")
                key = $element.GetAttribute("key")
                valueName = $element.GetAttribute("valueName")
            }

            # Handle enum values with resolved displayNames
            if ($elementType -eq 'enum') {
                $items = if ($Prefix) {
                    $element.SelectNodes("${px}item", $NamespaceManager)
                } else {
                    $element.SelectNodes("item")
                }

                if ($items -and $items.Count -gt 0) {
                    $elementDef.options = @()
                    foreach ($item in $items) {
                        $rawDisplayName = $item.GetAttribute("displayName")
                        $option = @{
                            displayName = Resolve-StringReference -Reference $rawDisplayName -Strings $Strings
                        }

                        # Get value from nested value element
                        $valueNode = if ($Prefix) {
                            $item.SelectSingleNode("${px}value", $NamespaceManager)
                        } else {
                            $item.SelectSingleNode("value")
                        }

                        if ($valueNode) {
                            $decimalNode = if ($Prefix) {
                                $valueNode.SelectSingleNode("${px}decimal", $NamespaceManager)
                            } else {
                                $valueNode.SelectSingleNode("decimal")
                            }
                            $stringNode = if ($Prefix) {
                                $valueNode.SelectSingleNode("${px}string", $NamespaceManager)
                            } else {
                                $valueNode.SelectSingleNode("string")
                            }

                            if ($decimalNode) {
                                $val = $decimalNode.GetAttribute("value")
                                if ($val) { $option.value = [long]$val }
                            }
                            elseif ($stringNode) {
                                $option.value = $stringNode.InnerText
                            }
                        }

                        $elementDef.options += $option
                    }
                }
            }

            # Handle decimal ranges (use [long] for large values like 4294967295)
            if ($elementType -eq 'decimal' -or $elementType -eq 'longDecimal') {
                $minVal = $element.GetAttribute("minValue")
                $maxVal = $element.GetAttribute("maxValue")
                if ($minVal) { $elementDef.minValue = [long]$minVal }
                if ($maxVal) { $elementDef.maxValue = [long]$maxVal }
            }

            $elements += $elementDef
        }
    }

    return $elements
}

function Parse-ADMXFile {
    param(
        [string]$ADMXPath,
        [hashtable]$Strings
    )

    $policies = @()

    [xml]$admx = Get-Content -LiteralPath $ADMXPath -Raw -Encoding UTF8

    # Setup namespace manager
    $ns = New-Object System.Xml.XmlNamespaceManager($admx.NameTable)
    $nsUri = $admx.DocumentElement.NamespaceURI
    $prefix = ""
    $px = ""

    if ($nsUri) {
        $ns.AddNamespace("p", $nsUri)
        $prefix = "p"
        $px = "p:"
    }

    $fileName = [System.IO.Path]::GetFileNameWithoutExtension($ADMXPath)

    # Get namespace from target - use GetAttribute for reliability
    $namespaceNode = if ($prefix) {
        $admx.SelectSingleNode("//${px}policyNamespaces/${px}target", $ns)
    } else {
        $admx.SelectSingleNode("//policyNamespaces/target")
    }
    $namespace = if ($namespaceNode) { $namespaceNode.GetAttribute("namespace") } else { $fileName }
    if ([string]::IsNullOrEmpty($namespace)) { $namespace = $fileName }

    # Parse supportedOn definitions
    $supportedOnDefs = Parse-SupportedOnDefinitions -ADMX $admx -NamespaceManager $ns -Prefix $prefix

    # Parse categories
    $categories = @{}
    $categoryNodes = if ($prefix) {
        $admx.SelectNodes("//${px}categories/${px}category", $ns)
    } else {
        $admx.SelectNodes("//categories/category")
    }

    foreach ($category in $categoryNodes) {
        $catName = $category.GetAttribute("name")
        $catDisplayName = $category.GetAttribute("displayName")

        $parentRef = if ($prefix) {
            $category.SelectSingleNode("${px}parentCategory", $ns)
        } else {
            $category.SelectSingleNode("parentCategory")
        }

        $categories[$catName] = @{
            name = $catName
            displayName = Resolve-StringReference -Reference $catDisplayName -Strings $Strings
            parent = if ($parentRef) { $parentRef.GetAttribute("ref") } else { $null }
        }
    }

    # Parse policies
    $policyNodes = if ($prefix) {
        $admx.SelectNodes("//${px}policies/${px}policy", $ns)
    } else {
        $admx.SelectNodes("//policies/policy")
    }

    foreach ($policy in $policyNodes) {
        # Get attributes using GetAttribute for reliability
        $policyName = $policy.GetAttribute("name")
        $policyDisplayName = $policy.GetAttribute("displayName")
        $policyExplainText = $policy.GetAttribute("explainText")
        $policyClass = $policy.GetAttribute("class")
        $policyKey = $policy.GetAttribute("key")
        $policyValueName = $policy.GetAttribute("valueName")

        # Get parent category ref
        $parentCatNode = if ($prefix) {
            $policy.SelectSingleNode("${px}parentCategory", $ns)
        } else {
            $policy.SelectSingleNode("parentCategory")
        }
        $parentCatRef = if ($parentCatNode) { $parentCatNode.GetAttribute("ref") } else { $null }

        # Get supportedOn ref
        $supportedOnNode = if ($prefix) {
            $policy.SelectSingleNode("${px}supportedOn", $ns)
        } else {
            $policy.SelectSingleNode("supportedOn")
        }
        $supportedOnRef = if ($supportedOnNode) { $supportedOnNode.GetAttribute("ref") } else { $null }

        # Resolve supportedOn
        $supportedOnDisplay = $null
        if ($supportedOnRef) {
            # Try local definition first
            if ($supportedOnDefs.ContainsKey($supportedOnRef)) {
                $supportedOnDisplay = Resolve-StringReference -Reference $supportedOnDefs[$supportedOnRef] -Strings $Strings
            }
            else {
                # Try as string reference
                $supportedOnDisplay = Resolve-StringReference -Reference $supportedOnRef -Strings $Strings
            }
        }

        $displayName = Resolve-StringReference -Reference $policyDisplayName -Strings $Strings
        $explainText = Resolve-StringReference -Reference $policyExplainText -Strings $Strings

        $policyDef = @{
            name = $policyName
            namespace = $namespace
            fileName = $fileName
            displayName = $displayName
            explainText = $explainText
            class = $policyClass  # Machine or User
            key = $policyKey
            valueName = $policyValueName
            category = $parentCatRef
            categoryPath = @()
            categoryPathDisplay = ""
            supportedOn = $supportedOnDisplay
        }

        # Build category path
        $currentCat = $parentCatRef
        $visited = @{}  # Prevent infinite loops
        while ($currentCat -and $categories.ContainsKey($currentCat) -and -not $visited.ContainsKey($currentCat)) {
            $visited[$currentCat] = $true
            $catDisplayName = $categories[$currentCat].displayName
            if ($catDisplayName) {
                $policyDef.categoryPath = @($catDisplayName) + $policyDef.categoryPath
            }
            $currentCat = $categories[$currentCat].parent
        }
        $policyDef.categoryPathDisplay = $policyDef.categoryPath -join " > "

        # Parse enabled/disabled values
        $enabledValueNode = if ($prefix) {
            $policy.SelectSingleNode("${px}enabledValue", $ns)
        } else {
            $policy.SelectSingleNode("enabledValue")
        }

        if ($enabledValueNode) {
            $decimalNode = if ($prefix) {
                $enabledValueNode.SelectSingleNode("${px}decimal", $ns)
            } else {
                $enabledValueNode.SelectSingleNode("decimal")
            }
            $stringNode = if ($prefix) {
                $enabledValueNode.SelectSingleNode("${px}string", $ns)
            } else {
                $enabledValueNode.SelectSingleNode("string")
            }

            if ($decimalNode) {
                $val = $decimalNode.GetAttribute("value")
                if ($val) {
                    $policyDef.enabledValue = @{
                        type = "decimal"
                        value = [long]$val
                    }
                }
            }
            elseif ($stringNode) {
                $policyDef.enabledValue = @{
                    type = "string"
                    value = $stringNode.InnerText
                }
            }
        }

        $disabledValueNode = if ($prefix) {
            $policy.SelectSingleNode("${px}disabledValue", $ns)
        } else {
            $policy.SelectSingleNode("disabledValue")
        }

        if ($disabledValueNode) {
            $decimalNode = if ($prefix) {
                $disabledValueNode.SelectSingleNode("${px}decimal", $ns)
            } else {
                $disabledValueNode.SelectSingleNode("decimal")
            }
            $stringNode = if ($prefix) {
                $disabledValueNode.SelectSingleNode("${px}string", $ns)
            } else {
                $disabledValueNode.SelectSingleNode("string")
            }

            if ($decimalNode) {
                $val = $decimalNode.GetAttribute("value")
                if ($val) {
                    $policyDef.disabledValue = @{
                        type = "decimal"
                        value = [long]$val
                    }
                }
            }
            elseif ($stringNode) {
                $policyDef.disabledValue = @{
                    type = "string"
                    value = $stringNode.InnerText
                }
            }
        }

        # Parse additional elements
        $policyDef.elements = Parse-PolicyElements -Policy $policy -NamespaceManager $ns -Prefix $prefix -Strings $Strings

        # Build comprehensive searchText
        $searchParts = @(
            $displayName,
            $explainText,
            ($policyDef.categoryPath -join " "),
            $policyKey,
            $policyValueName,
            $policyName,
            $supportedOnDisplay
        )

        # Add element options to searchText
        foreach ($elem in $policyDef.elements) {
            if ($elem.id) { $searchParts += $elem.id }
            if ($elem.valueName) { $searchParts += $elem.valueName }
            if ($elem.options) {
                foreach ($opt in $elem.options) {
                    if ($opt.displayName) { $searchParts += $opt.displayName }
                }
            }
        }

        $policyDef.searchText = (($searchParts | Where-Object { $_ }) -join " ").ToLower()

        $policies += $policyDef
    }

    return $policies
}

function Add-ToIndexArray {
    param(
        [hashtable]$Index,
        [string]$Key,
        [string]$Value,
        [switch]$PreserveCase
    )

    if ([string]::IsNullOrEmpty($Key)) { return }

    $indexKey = if ($PreserveCase) { $Key } else { $Key.ToLower() }
    if (-not $Index.ContainsKey($indexKey)) {
        $Index[$indexKey] = @()
    }
    if ($Value -notin $Index[$indexKey]) {
        $Index[$indexKey] += $Value
    }
}

# Main execution
Write-Host "ADMX to JSON Exporter v3" -ForegroundColor Cyan
Write-Host "========================" -ForegroundColor Cyan
Write-Host ""
Write-Host "ADMX Path: $ADMXPath"
Write-Host "Language: $Language"
Write-Host "Output: $OutputPath"
Write-Host "Skip full policies: $SkipFullPolicies"
Write-Host ""

# Validate paths
if (-not (Test-Path -LiteralPath $ADMXPath)) {
    throw "ADMX path not found: $ADMXPath"
}

$admlPath = Join-Path $ADMXPath $Language
if (-not (Test-Path -LiteralPath $admlPath)) {
    Write-Warning "Language folder not found: $admlPath"
    Write-Warning "Falling back to en-US"
    $admlPath = Join-Path $ADMXPath "en-US"
}

# Get all ADMX files
$admxFiles = Get-ChildItem -LiteralPath $ADMXPath -Filter "*.admx"
Write-Host "Found $($admxFiles.Count) ADMX files" -ForegroundColor Green

$allPolicies = @()
$processedCount = 0
$errorCount = 0

foreach ($admxFile in $admxFiles) {
    $processedCount++
    $percentComplete = [math]::Round(($processedCount / $admxFiles.Count) * 100)
    Write-Progress -Activity "Parsing ADMX files" -Status "$($admxFile.Name)" -PercentComplete $percentComplete

    try {
        # Find corresponding ADML file
        $admlFile = Join-Path $admlPath ($admxFile.BaseName + ".adml")
        $strings = Parse-ADMLStrings -ADMLPath $admlFile

        # Parse ADMX
        $policies = Parse-ADMXFile -ADMXPath $admxFile.FullName -Strings $strings
        $allPolicies += $policies

        Write-Verbose "Parsed $($policies.Count) policies from $($admxFile.Name)"
    }
    catch {
        $errorCount++
        Write-Warning "Error parsing $($admxFile.Name): $_"
    }
}

Write-Progress -Activity "Parsing ADMX files" -Completed

# Build output structure
$output = @{
    metadata = @{
        exportDate = (Get-Date -Format "o")
        admxPath = $ADMXPath
        language = $Language
        totalPolicies = $allPolicies.Count
        totalFiles = $admxFiles.Count
        errorCount = $errorCount
        version = "3.0"
    }
    index = @{
        byKey = @{}              # lowercase for search
        byCategory = @{}         # preserve case for display
        byCategoryLower = @{}    # lowercase for search
        byFileName = @{}
    }
}

# Only include full policies if not skipped
if (-not $SkipFullPolicies) {
    $output.policies = $allPolicies
}

# Build indexes for fast lookup (using arrays to handle collisions)
foreach ($policy in $allPolicies) {
    $policyId = "$($policy.namespace)::$($policy.name)"

    # Index by registry key (policy level) - lowercase
    if ($policy.key) {
        Add-ToIndexArray -Index $output.index.byKey -Key $policy.key -Value $policyId

        if ($policy.valueName) {
            $fullKeyPath = "$($policy.key)\$($policy.valueName)"
            Add-ToIndexArray -Index $output.index.byKey -Key $fullKeyPath -Value $policyId
        }
    }

    # Index by element keys/values
    foreach ($element in $policy.elements) {
        $elemKey = if ($element.key) { $element.key } else { $policy.key }
        if ($elemKey -and $element.valueName) {
            $elemKeyPath = "$elemKey\$($element.valueName)"
            Add-ToIndexArray -Index $output.index.byKey -Key $elemKeyPath -Value $policyId
        }
    }

    # Index by category - preserve case for display
    if ($policy.categoryPathDisplay) {
        Add-ToIndexArray -Index $output.index.byCategory -Key $policy.categoryPathDisplay -Value $policyId -PreserveCase
        Add-ToIndexArray -Index $output.index.byCategoryLower -Key $policy.categoryPathDisplay -Value $policyId
    }

    # Index by file
    Add-ToIndexArray -Index $output.index.byFileName -Key $policy.fileName -Value $policyId
}

# Export to JSON
Write-Host ""
Write-Host "Exporting to JSON..." -ForegroundColor Yellow

$jsonContent = $output | ConvertTo-Json -Depth 15 -Compress:$false
[System.IO.File]::WriteAllText($OutputPath, $jsonContent, [System.Text.Encoding]::UTF8)

$fileSize = [math]::Round((Get-Item -LiteralPath $OutputPath).Length / 1MB, 2)

Write-Host ""
Write-Host "Export complete!" -ForegroundColor Green
Write-Host "  Total policies: $($allPolicies.Count)"
Write-Host "  Files processed: $($admxFiles.Count)"
Write-Host "  Errors: $errorCount"
Write-Host "  Output file: $OutputPath"
Write-Host "  File size: $fileSize MB"
Write-Host ""
Write-Host "Sample categories:" -ForegroundColor Cyan
$output.index.byCategory.Keys | Sort-Object | Select-Object -First 15 | ForEach-Object {
    $count = $output.index.byCategory[$_].Count
    Write-Host "  $_ ($count policies)"
}
if ($output.index.byCategory.Count -gt 15) {
    Write-Host "  ... and $($output.index.byCategory.Count - 15) more categories"
}
