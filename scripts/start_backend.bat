@echo off
echo 🔧 启动量化平台后端API服务...
echo.

cd /d "%~dp0backend"
echo 当前目录: %cd%
echo.

echo 启动Flask后端API (端口: 8889)...
echo ========================================
python app.py

if errorlevel 1 (
    echo ❌ 后端启动失败！
    echo 请检查:
    echo 1. Python是否安装: python --version
    echo 2. 依赖是否安装: pip install -r requirements.txt
    echo 3. 端口是否被占用: netstat -ano | findstr :8889
    pause
) else (
    echo ✅ 后端服务已启动
    echo 访问地址: http://localhost:8889
    echo API状态: http://localhost:8889/api/system/status
)