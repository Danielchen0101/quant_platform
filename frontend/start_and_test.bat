@echo off
echo 🚀 启动量化平台前端并测试UI修复
echo ========================================
echo.

echo 📦 安装依赖...
call npm install
if %errorlevel% neq 0 (
    echo ❌ 依赖安装失败
    pause
    exit /b 1
)

echo.
echo 🎨 启动开发服务器...
echo.
echo ⚠️  注意: 请在新窗口中保持此服务运行
echo.

start "量化平台前端" cmd /k "npm start"

echo.
echo ⏳ 等待服务器启动...
timeout /t 10 /nobreak >nul

echo.
echo 🔍 测试UI访问...
echo.
echo 🌐 请打开浏览器访问: http://localhost:3000
echo.
echo 🔐 测试账号:
echo   用户名: admin
echo   密码: admin123
echo.
echo 📋 UI修复检查清单:
echo   1. ✅ 侧边栏菜单项不重叠
echo   2. ✅ 白色页签与侧边栏有足够间距
echo   3. ✅ 内容区域布局正常
echo   4. ✅ 响应式布局正常
echo.
echo 🛠️ 如果仍有重叠问题:
echo   1. 按 Ctrl+Shift+R 强制刷新页面
echo   2. 检查浏览器控制台是否有错误
echo   3. 尝试清除浏览器缓存
echo.
echo ========================================
echo ✅ UI修复已完成，请检查页面效果
pause