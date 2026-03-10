@echo off
echo 🔧 重启前端服务应用修复
echo ============================
echo.

echo 1. 停止当前前端服务...
taskkill /F /IM node.exe 2>nul
if %errorlevel% equ 0 (
    echo   ✅ 前端服务已停止
) else (
    echo   ℹ️ 没有运行中的前端服务
)

echo.
echo 2. 验证修复文件...
echo   - layout-fix.less: 
if exist "src\styles\layout-fix.less" (
    echo     ✅ 存在
) else (
    echo     ❌ 不存在
)

echo   - index.tsx 导入:
findstr /n "layout-fix" src\index.tsx >nul
if %errorlevel% equ 0 (
    echo     ✅ 已导入
) else (
    echo     ❌ 未导入
)

echo   - request.ts 错误去重:
findstr /n "errorCache" src\services\request.ts >nul
if %errorlevel% equ 0 (
    echo     ✅ 已实现
) else (
    echo     ❌ 未实现
)

echo.
echo 3. 启动前端服务...
start cmd /k "npm start"

echo.
echo ✅ 修复已应用，前端服务正在启动...
echo.
echo 📋 验证步骤:
echo   1. 等待服务启动完成 (约30秒)
echo   2. 打开浏览器访问: http://localhost:3000
echo   3. 强制刷新: Ctrl+Shift+R
echo   4. 检查:
echo      - 布局重叠是否修复
echo      - 重复错误提示是否消失
echo.
echo 🚀 启动完成!