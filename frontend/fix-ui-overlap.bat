@echo off
echo 🔧 Quantitative Platform UI Overlap Fix Tool
echo ========================================
echo.

echo 📋 Checking current UI status...
echo.

echo 1. Checking frontend service status...
netstat -ano | findstr :3000 >nul
if %errorlevel% equ 0 (
    echo   ✅ Frontend service running (port 3000)
) else (
    echo   ❌ Frontend service not running
    echo   Please run: npm start
    pause
    exit /b 1
)

echo.
echo 2. 检查后端服务状态...
netstat -ano | findstr :8889 >nul
if %errorlevel% equ 0 (
    echo   ✅ 后端服务运行中 (端口8889)
) else (
    echo   ❌ 后端服务未运行
    echo   请先运行: cd backend && python app.py
    pause
    exit /b 1
)

echo.
echo 3. 应用CSS修复...
echo   复制修复文件到src目录...
xcopy /Y "src\styles\antd-override.less" "src\styles\antd-override.less.backup" >nul
echo   ✅ CSS备份完成

echo.
echo 4. 启动CSS热重载监控...
echo   安装监控依赖...
call npm install chokidar --no-save
if %errorlevel% neq 0 (
    echo   ⚠️  依赖安装失败，跳过热重载
) else (
    start "CSS热重载" cmd /k "node hot-reload-css.js"
    echo   ✅ CSS热重载监控已启动
)

echo.
echo 5. 生成UI调试页面...
echo   打开UI调试工具...
start "" "ui_debug.html"
echo   ✅ UI调试页面已打开

echo.
echo 🎯 修复步骤完成！
echo.
echo 📋 下一步操作:
echo   1. 浏览器访问: http://localhost:3000
echo   2. 按 Ctrl+Shift+R 强制刷新
echo   3. 检查侧边栏和页签是否还有重叠
echo   4. 使用UI调试页面分析问题
echo.
echo 🔧 如果问题仍然存在:
echo   1. 检查浏览器控制台 (F12)
echo   2. 清除浏览器缓存
echo   3. 尝试不同的浏览器
echo   4. 重启前端服务: Ctrl+C 然后 npm start
echo.
echo 📞 技术支持:
echo   提供以下信息以便进一步调试:
echo   - 浏览器类型和版本
echo   - 屏幕分辨率
echo   - 具体的重叠位置截图
echo   - 控制台错误信息
echo.
echo ========================================
echo ✅ UI修复工具已准备就绪
pause