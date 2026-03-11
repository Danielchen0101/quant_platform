# PowerShell启动脚本 - 专业量化平台

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "🚀 启动专业量化交易平台" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 检查Python
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✅ Python版本: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ 未找到Python，请先安装Python 3.8+" -ForegroundColor Red
    exit 1
}

# 检查Node.js
try {
    $nodeVersion = node --version 2>&1
    Write-Host "✅ Node.js版本: $nodeVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ 未找到Node.js，请先安装Node.js 16+" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "📦 1. 启动后端API服务..." -ForegroundColor Yellow
Set-Location backend

# 检查虚拟环境
if (-not (Test-Path "venv")) {
    Write-Host "   创建虚拟环境..." -ForegroundColor Yellow
    python -m venv venv
}

Write-Host "   激活虚拟环境..." -ForegroundColor Yellow
& .\venv\Scripts\Activate.ps1

Write-Host "   安装依赖..." -ForegroundColor Yellow
pip install -r requirements.txt 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "   ❌ 依赖安装失败" -ForegroundColor Red
    exit 1
}

Write-Host "   启动后端API..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD'; .\venv\Scripts\Activate.ps1; python app.py" -WindowStyle Normal

Set-Location ..

Write-Host ""
Write-Host "🎨 2. 启动前端开发服务器..." -ForegroundColor Yellow
Set-Location frontend

Write-Host "   安装前端依赖..." -ForegroundColor Yellow
npm install 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "   ❌ 前端依赖安装失败" -ForegroundColor Red
    exit 1
}

Write-Host "   启动前端开发服务器..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD'; npm start" -WindowStyle Normal

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "✅ 平台启动完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "🌐 访问地址:" -ForegroundColor Yellow
Write-Host "   前端界面: http://localhost:3000" -ForegroundColor White
Write-Host "   后端API:  http://localhost:8889" -ForegroundColor White
Write-Host ""
Write-Host "🔐 测试账号:" -ForegroundColor Yellow
Write-Host "   admin / admin123 (管理员)" -ForegroundColor White
Write-Host "   trader / trader123 (交易员)" -ForegroundColor White
Write-Host "   analyst / analyst123 (分析师)" -ForegroundColor White
Write-Host ""
Write-Host "📋 功能模块:" -ForegroundColor Yellow
Write-Host "   - 仪表板: 资产总览和系统状态" -ForegroundColor White
Write-Host "   - 策略回测: Backtrader集成" -ForegroundColor White
Write-Host "   - 市场分析: Qlib AI分析" -ForegroundColor White
Write-Host "   - 风险管理: 实时监控和预警" -ForegroundColor White
Write-Host ""
Write-Host "⏳ 等待服务启动..." -ForegroundColor Yellow
Write-Host "   后端启动约需3秒，前端启动约需5秒" -ForegroundColor Gray
Write-Host ""
Write-Host "💡 提示: 按 Ctrl+C 停止所有服务" -ForegroundColor Magenta