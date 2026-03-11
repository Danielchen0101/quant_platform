# Python环境检查脚本
Write-Host "=== Python环境检查 ===" -ForegroundColor Cyan

# 检查Python是否安装
$pythonPaths = @("python", "python3", "py")
$pythonFound = $false

foreach ($cmd in $pythonPaths) {
    try {
        $result = Get-Command $cmd -ErrorAction Stop
        Write-Host "✅ 找到Python: $($result.Source)" -ForegroundColor Green
        $pythonFound = $true
        
        # 检查Python版本
        $version = & $cmd --version 2>&1
        Write-Host "   Python版本: $version"
        break
    } catch {
        # 继续检查下一个命令
    }
}

if (-not $pythonFound) {
    Write-Host "❌ 未找到Python安装" -ForegroundColor Red
    Write-Host ""
    Write-Host "=== 安装建议 ===" -ForegroundColor Yellow
    Write-Host "1. 下载Python: https://www.python.org/downloads/"
    Write-Host "2. 安装时务必勾选 'Add Python to PATH'"
    Write-Host "3. 安装完成后重启终端"
    Write-Host ""
    Write-Host "=== 验证安装 ==="
    Write-Host "安装完成后运行: python --version"
} else {
    Write-Host ""
    Write-Host "=== Python依赖检查 ===" -ForegroundColor Cyan
    Write-Host "检查后端依赖..."
    
    # 检查requirements.txt是否存在
    $requirementsPath = "backend\requirements.txt"
    if (Test-Path $requirementsPath) {
        Write-Host "✅ 找到requirements.txt" -ForegroundColor Green
        
        # 尝试安装依赖
        Write-Host "尝试安装Python依赖..."
        try {
            & python -m pip install -r $requirementsPath
            Write-Host "✅ Python依赖安装完成" -ForegroundColor Green
        } catch {
            Write-Host "❌ 依赖安装失败: $_" -ForegroundColor Red
        }
    } else {
        Write-Host "⚠️ 未找到requirements.txt" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "=== 后端启动测试 ===" -ForegroundColor Cyan
if ($pythonFound) {
    try {
        Write-Host "尝试启动简化版后端..."
        Set-Location backend
        & python start_quant_backend.py
    } catch {
        Write-Host "❌ 后端启动失败: $_" -ForegroundColor Red
    }
} else {
    Write-Host "需要先安装Python才能启动后端" -ForegroundColor Red
}