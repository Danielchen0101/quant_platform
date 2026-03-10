@echo off
echo === Python环境检查 ===

REM 检查Python是否安装
where python >nul 2>nul
if %errorlevel% equ 0 (
    echo ✅ 找到Python
    python --version
    goto :check_deps
)

where python3 >nul 2>nul
if %errorlevel% equ 0 (
    echo ✅ 找到Python3
    python3 --version
    goto :check_deps
)

where py >nul 2>nul
if %errorlevel% equ 0 (
    echo ✅ 找到py命令
    py --version
    goto :check_deps
)

echo ❌ 未找到Python安装
echo.
echo === 安装建议 ===
echo 1. 下载Python: https://www.python.org/downloads/
echo 2. 安装时务必勾选 'Add Python to PATH'
echo 3. 安装完成后重启终端
echo.
echo === 验证安装 ===
echo 安装完成后运行: python --version
goto :end

:check_deps
echo.
echo === Python依赖检查 ===
echo 检查后端依赖...

REM 检查requirements.txt是否存在
if exist "backend\requirements.txt" (
    echo ✅ 找到requirements.txt
    
    echo 尝试安装Python依赖...
    python -m pip install -r backend\requirements.txt
    if %errorlevel% equ 0 (
        echo ✅ Python依赖安装完成
    ) else (
        echo ❌ 依赖安装失败
    )
) else (
    echo ⚠️ 未找到requirements.txt
)

echo.
echo === 后端启动测试 ===
echo 尝试启动简化版后端...
cd backend
python start_quant_backend.py

:end
pause