@echo off
echo ========================================
echo 🚀 启动专业量化交易平台
echo ========================================

REM 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 未找到Python，请先安装Python 3.8+
    pause
    exit /b 1
)

REM 检查Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 未找到Node.js，请先安装Node.js 16+
    pause
    exit /b 1
)

echo.
echo 📦 1. 启动后端API服务...
cd backend

REM 检查虚拟环境
if not exist "venv" (
    echo   创建虚拟环境...
    python -m venv venv
)

echo   激活虚拟环境...
call venv\Scripts\activate

echo   安装依赖...
pip install -r requirements.txt >nul 2>&1
if errorlevel 1 (
    echo   ❌ 依赖安装失败
    pause
    exit /b 1
)

echo   启动后端API...
start cmd /k "cd backend && call venv\Scripts\activate && python app.py"

echo.
echo 🎨 2. 启动前端开发服务器...
cd ..\frontend

echo   安装前端依赖...
npm install >nul 2>&1
if errorlevel 1 (
    echo   ❌ 前端依赖安装失败
    pause
    exit /b 1
)

echo   启动前端开发服务器...
start cmd /k "cd frontend && npm start"

echo.
echo ========================================
echo ✅ 平台启动完成！
echo ========================================
echo.
echo 🌐 访问地址:
echo   前端界面: http://localhost:3000
echo   后端API:  http://localhost:8889
echo.
echo 🔐 测试账号:
echo   admin / admin123 (管理员)
echo   trader / trader123 (交易员)
echo   analyst / analyst123 (分析师)
echo.
echo 📋 功能模块:
echo   - 仪表板: 资产总览和系统状态
echo   - 策略回测: Backtrader集成
echo   - 市场分析: Qlib AI分析
echo   - 风险管理: 实时监控和预警
echo.
echo ⚠️  按任意键关闭此窗口...
pause >nul