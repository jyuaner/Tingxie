<#
.SYNOPSIS
    一键打包「听写」离线包：安装依赖 → 校验模型 → PyInstaller 打包 → 生成 zip。

.EXAMPLE
    pwsh -File scripts/build.ps1
    pwsh -File scripts/build.ps1 -SkipZip
#>
[CmdletBinding()]
param(
    [switch]$SkipZip,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $root

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

try {
    Step "环境检查"
    & $Python --version
    if ($LASTEXITCODE -ne 0) { throw "找不到 Python，请安装 3.10+ 并加入 PATH。" }

    Step "安装依赖"
    & $Python -m pip install --disable-pip-version-check -r requirements.txt pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "依赖安装失败。" }

    Step "校验离线模型"
    $modelDir = Join-Path $root "models\whisper-base"
    $required = @("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")
    if (-not (Test-Path $modelDir)) {
        Write-Host "缺少 models\whisper-base，尝试下载..." -ForegroundColor Yellow
        & $Python scripts\fetch_model.py
        if ($LASTEXITCODE -ne 0) { throw "模型准备失败，请手动放置四个模型文件。" }
    }
    foreach ($name in $required) {
        $path = Join-Path $modelDir $name
        if (-not (Test-Path $path) -or (Get-Item $path).Length -eq 0) {
            throw "模型文件缺失或为空：$path"
        }
    }
    $modelMb = [int](((Get-ChildItem $modelDir -File | Measure-Object Length -Sum).Sum) / 1MB)
    Write-Host "模型就绪（$modelMb MB）"

    Step "PyInstaller 打包"
    & $Python -m PyInstaller tingxie.spec --noconfirm
    if ($LASTEXITCODE -ne 0) { throw "打包失败。" }

    $dist = Join-Path $root "dist\Tingxie-windows-x64"
    if (-not (Test-Path (Join-Path $dist "Tingxie.exe"))) { throw "未找到 dist\Tingxie-windows-x64\Tingxie.exe" }

    # PyInstaller 6 会把 add-data 放进 _internal，启动脚本必须落在 dist 根目录
    $launcher = Join-Path $root "听写-全局输入.cmd"
    if (Test-Path $launcher) {
        Copy-Item $launcher $dist -Force
        Remove-Item (Join-Path $dist "_internal\听写-全局输入.cmd") -Force -ErrorAction SilentlyContinue
    }
    Write-Host "产物：$dist"

    if (-not $SkipZip) {
        Step "压缩离线包"
        $zip = Join-Path $root "dist\Tingxie-Windows-x64-offline.zip"
        if (Test-Path $zip) { Remove-Item $zip -Force }
        Compress-Archive -Path $dist -DestinationPath $zip -CompressionLevel Optimal
        $mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
        Write-Host "zip 就绪：$zip（$mb MB）"
        Get-FileHash $zip -Algorithm SHA256 | ForEach-Object { Write-Host "SHA256 $($_.Hash)" }
    }

    Step "完成"
    Write-Host "下一步：运行 dist\Tingxie-windows-x64\Tingxie.exe 做一次冒烟测试，再上传 Release。" -ForegroundColor Green
}
finally {
    Pop-Location
}