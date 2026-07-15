[CmdletBinding()]
param(
    [string]$OutputPath,
    [string]$SevenZipPath,
    [ValidateRange(0, 9)]
    [int]$CompressionLevel = 9
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path

function Find-SevenZip {
    param([string]$ExplicitPath)

    if ($ExplicitPath) {
        return (Resolve-Path -LiteralPath $ExplicitPath -ErrorAction Stop).Path
    }

    foreach ($commandName in @("7z", "7zz")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }

    $programFilesRoots = @(
        $env:ProgramFiles
        ${env:ProgramFiles(x86)}
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

    foreach ($root in $programFilesRoots) {
        $candidate = Join-Path $root "7-Zip\7z.exe"
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "未找到本机 7-Zip。请安装 7-Zip，或通过 -SevenZipPath 指定 7z.exe。"
}

function Read-PackageIdentity {
    $metadataPath = Join-Path $RepoRoot "metadata.yaml"
    $metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8
    $nameMatch = [regex]::Match($metadata, "(?m)^name:\s*[`"']?([^`"'\r\n]+)")
    $versionMatch = [regex]::Match($metadata, "(?m)^version:\s*[`"']?([^`"'\r\n]+)")

    if (-not $nameMatch.Success -or -not $versionMatch.Success) {
        throw "无法从 metadata.yaml 读取 name 和 version。"
    }

    return @{
        Name = $nameMatch.Groups[1].Value.Trim()
        Version = $versionMatch.Groups[1].Value.Trim()
    }
}

$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    throw "未找到 Git；该脚本需要 Git 解析 .gitignore。"
}

$sevenZip = Find-SevenZip -ExplicitPath $SevenZipPath
$identity = Read-PackageIdentity

if (-not $OutputPath) {
    $archiveName = "{0}-{1}.zip" -f $identity.Name, $identity.Version
    $OutputPath = Join-Path $RepoRoot (Join-Path "dist" $archiveName)
} elseif (-not [IO.Path]::IsPathRooted($OutputPath)) {
    $OutputPath = Join-Path $RepoRoot $OutputPath
}

if ([IO.Path]::GetExtension($OutputPath) -ne ".zip") {
    throw "输出文件必须使用 .zip 扩展名。"
}

$archivePath = [IO.Path]::GetFullPath($OutputPath)
$outputDirectory = Split-Path -Parent $archivePath
[IO.Directory]::CreateDirectory($outputDirectory) | Out-Null

$relativeFiles = @(
    & $git.Source -c core.quotepath=false -C $RepoRoot `
        ls-files --cached --others --exclude-standard
)
if ($LASTEXITCODE -ne 0) {
    throw "Git 无法生成打包文件列表。"
}

$packageFiles = @(
    foreach ($relativePath in $relativeFiles) {
        if ([string]::IsNullOrWhiteSpace($relativePath)) {
            continue
        }

        $fullPath = [IO.Path]::GetFullPath((Join-Path $RepoRoot $relativePath))
        if ([string]::Equals(
            $fullPath,
            $archivePath,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            continue
        }
        if (Test-Path -LiteralPath $fullPath -PathType Leaf) {
            $relativePath.Replace("\", "/")
        }
    }
)

if ($packageFiles.Count -eq 0) {
    throw "没有可打包的文件。"
}

$temporaryId = [Guid]::NewGuid().ToString("N")
$listPath = Join-Path $outputDirectory ".package-files-$temporaryId.txt"
$temporaryArchive = Join-Path $outputDirectory ".package-$temporaryId.zip"

try {
    [IO.File]::WriteAllLines(
        $listPath,
        $packageFiles,
        [Text.UTF8Encoding]::new($false)
    )

    Push-Location $RepoRoot
    try {
        & $sevenZip a -tzip $temporaryArchive "@$listPath" `
            "-mx=$CompressionLevel" -scsUTF-8 -y
        if ($LASTEXITCODE -ne 0) {
            throw "7-Zip 打包失败，退出码：$LASTEXITCODE。"
        }
    } finally {
        Pop-Location
    }

    Move-Item -LiteralPath $temporaryArchive -Destination $archivePath -Force
} finally {
    Remove-Item -LiteralPath $listPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $temporaryArchive -Force -ErrorAction SilentlyContinue
}

$archive = Get-Item -LiteralPath $archivePath
$hash = Get-FileHash -LiteralPath $archivePath -Algorithm SHA256

Write-Host "打包完成"
Write-Host "  文件数：$($packageFiles.Count)"
Write-Host "  压缩包：$($archive.FullName)"
Write-Host "  大小：$($archive.Length) bytes"
Write-Host "  SHA256：$($hash.Hash)"
