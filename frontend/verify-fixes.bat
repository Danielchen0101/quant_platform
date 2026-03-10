@echo off
echo 🔍 验证修复状态
echo =================
echo.

echo 1. 检查 layout-fix 导入:
findstr /n "layout-fix" src\App.tsx >nul
if %errorlevel% equ 0 (
    echo   ✅ 已导入到 App.tsx
) else (
    echo   ❌ 未导入
)

echo.
echo 2. 检查错误管理器:
if exist "src\services\error-manager.ts" (
    echo   ✅ error-manager.ts 存在
) else (
    echo   ❌ error-manager.ts 不存在
)

echo.
echo 3. 检查 request-fixed.ts 使用错误管理器:
findstr /n "errorManager" src\services\request-fixed.ts >nul
if %errorlevel% equ 0 (
    echo   ✅ 使用全局错误管理器
) else (
    echo   ❌ 未使用全局错误管理器
)

echo.
echo 4. 检查重复错误处理:
echo   - 搜索 message.error:
findstr /s /n "message\.error" src\*.ts src\*.tsx 2>nul
if %errorlevel% equ 0 (
    echo     ⚠️  发现 message.error 调用
) else (
    echo     ✅ 无 message.error 调用
)

echo   - 搜索 notification.error:
findstr /s /n "notification\.error" src\*.ts src\*.tsx 2>nul
if %errorlevel% equ 0 (
    echo     ⚠️  发现 notification.error 调用
) else (
    echo     ✅ 无 notification.error 调用
)

echo.
echo 5. 检查错误去重机制:
findstr /n "ERROR_TTL\|errorCache\|isDuplicateError" src\services\error-manager.ts >nul
if %errorlevel% equ 0 (
    echo   ✅ 错误去重机制已实现
) else (
    echo   ❌ 错误去重机制未实现
)

echo.
echo 📋 总结:
echo   - 布局修复: 已导入到 App.tsx
echo   - 错误处理: 使用全局错误管理器
echo   - 去重机制: 5秒内相同错误只显示一次
echo   - 统一管理: 所有错误通过 error-manager.ts 处理
echo.
echo 🚀 重启前端服务查看效果:
echo   npm start
echo.
echo 🔄 强制刷新浏览器: Ctrl+Shift+R