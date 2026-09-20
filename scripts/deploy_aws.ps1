[CmdletBinding()]
param(
    [string]$StackName = "sentinel-aml-demo",
    [string]$Region = "ap-south-1",
    [string]$InvestigationTableName = "SentinelInvestigationsAws",
    [string]$LocalFrontendOrigin = "http://localhost:5173",
    [switch]$SkipSeed
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$FrontendRoot = Join-Path $ProjectRoot "frontend"
$SeedDatabase = Join-Path $ProjectRoot "dataset\aml.duckdb"

function Resolve-CommandPath {
    param([string]$Name, [string[]]$Fallbacks)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in $Fallbacks) {
        $expanded = [Environment]::ExpandEnvironmentVariables($candidate)
        if (Test-Path $expanded) { return $expanded }
    }
    throw "$Name is not installed or is not available on PATH."
}

$Aws = Resolve-CommandPath "aws" @(
    "%LOCALAPPDATA%\Programs\Amazon\AWSCLIV2\aws.exe",
    "%ProgramFiles%\Amazon\AWSCLIV2\aws.exe"
)
$Sam = Resolve-CommandPath "sam" @("%ProgramFiles%\Amazon\AWSSAMCLI\bin\sam.cmd")
$Docker = Resolve-CommandPath "docker" @("%ProgramFiles%\Docker\Docker\resources\bin\docker.exe")
$Node = Resolve-CommandPath "node" @("%ProgramFiles%\nodejs\node.exe")

# SAM delegates image publishing to Docker, which resolves the Desktop credential
# helper by name. Ensure Docker's install directory is available even when the
# current PowerShell session was opened before Docker Desktop was installed.
$DockerBin = Split-Path -Parent $Docker
if (($env:Path -split ";") -notcontains $DockerBin) {
    $env:Path = "$DockerBin;$env:Path"
}

Push-Location $ProjectRoot
try {
    & $Aws sts get-caller-identity --region $Region | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "AWS identity check failed." }

    & $Docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Desktop is installed but its Linux engine is not running. Start Docker Desktop and retry."
    }

    $env:SAM_CLI_TELEMETRY = "0"
    & $Sam validate --lint --region $Region
    if ($LASTEXITCODE -ne 0) { throw "SAM validation failed." }

    & $Sam build
    if ($LASTEXITCODE -ne 0) { throw "SAM build failed." }

    & $Sam deploy `
        --stack-name $StackName `
        --region $Region `
        --capabilities CAPABILITY_IAM `
        --resolve-s3 `
        --resolve-image-repos `
        --no-confirm-changeset `
        --no-fail-on-empty-changeset `
        --parameter-overrides `
            "FrontendOrigin=$LocalFrontendOrigin" `
            "InvestigationTableName=$InvestigationTableName"
    if ($LASTEXITCODE -ne 0) { throw "SAM deployment failed." }

    $stack = (& $Aws cloudformation describe-stacks --stack-name $StackName --region $Region | ConvertFrom-Json).Stacks[0]
    $outputs = @{}
    foreach ($output in $stack.Outputs) { $outputs[$output.OutputKey] = $output.OutputValue }

    if (-not $SkipSeed) {
        if (-not (Test-Path $SeedDatabase)) { throw "Seed database not found: $SeedDatabase" }
        & $Aws s3 cp $SeedDatabase "s3://$($outputs.BucketName)/state/workspace.duckdb" --region $Region
        if ($LASTEXITCODE -ne 0) { throw "Workspace seed upload failed." }
    }

    $env:VITE_API_BASE_URL = $outputs.ApiUrl
    $env:VITE_MAX_UPLOAD_MB = "4"
    Push-Location $FrontendRoot
    try {
        & $Node ".\node_modules\typescript\bin\tsc" -b
        if ($LASTEXITCODE -ne 0) { throw "Frontend TypeScript build failed." }
        & $Node ".\node_modules\vite\bin\vite.js" build
        if ($LASTEXITCODE -ne 0) { throw "Frontend Vite build failed." }
    }
    finally {
        Pop-Location
    }

    $distRoot = Join-Path $FrontendRoot "dist"
    & $Aws s3 sync $distRoot "s3://$($outputs.FrontendBucketName)" --delete --exclude "index.html" --cache-control "public,max-age=31536000,immutable" --region $Region
    if ($LASTEXITCODE -ne 0) { throw "Frontend asset upload failed." }

    # The entry document must be revalidated so browsers discover each new hashed bundle.
    & $Aws s3 cp (Join-Path $distRoot "index.html") "s3://$($outputs.FrontendBucketName)/index.html" --content-type "text/html" --cache-control "no-cache,no-store,must-revalidate" --region $Region
    if ($LASTEXITCODE -ne 0) { throw "Frontend upload failed." }

    Write-Host ""
    Write-Host "Deployment complete" -ForegroundColor Green
    Write-Host "Frontend: $($outputs.FrontendUrl)"
    Write-Host "API:      $($outputs.ApiUrl)"
    Write-Host "Bucket:   $($outputs.BucketName)"
    Write-Host "Table:    $($outputs.TableName)"
    Write-Host "SNS:      $($outputs.TopicArn)"
    Write-Host "Lambda:   $($outputs.FunctionName)"
}
finally {
    Pop-Location
}
