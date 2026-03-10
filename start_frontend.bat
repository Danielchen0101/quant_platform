@echo off
echo 🎨 启动量化平台前端React应用...
echo.

cd /d "%~dp0frontend"
echo 当前目录: %cd%
echo.

echo 检查Node.js版本...
node --version
if errorlevel 1 (
    echo ❌ Node.js未安装或未添加到PATH
    echo 请先安装Node.js: https://nodejs.org/
    pause
    exit /b 1
)

echo.
echo 安装依赖 (如果需要)...
call npm install
if errorlevel 1 (
    echo ❌ 依赖安装失败！
    pause
    exit /b 1
)

echo.
echo 启动React开发服务器 (端口: 3000)...
echo ========================================
npm start

if errorlevel 1 (
    echo ❌ 前端启动失败！
    echo 请检查:
    echo 1. 端口3000是否被占用
    echo 2. 依赖是否正确安装
    echo 3. 查看详细错误信息
    pause
) else (
    echo ✅ 前端服务已启动
    echo 访问地址: http://localhost:3000
    echo 登录账号: admin / admin123
)