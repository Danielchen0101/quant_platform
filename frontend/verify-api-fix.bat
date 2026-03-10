@echo off
echo 🔍 验证 API 地址修复
echo ====================
echo.

echo 1. 检查 api.ts 配置:
echo   - baseURL 定义:
findstr /n "localhost:8889" src\services\api.ts
if %errorlevel% equ 0 (
    echo     ✅ 指向 localhost:8889
) else (
    echo     ❌ 未指向 localhost:8889
)

echo   - 使用 request-fixed.ts:
findstr /n "import.*request-fixed" src\services\api.ts
if %errorlevel% equ 0 (
    echo     ✅ 复用 request-fixed.ts 错误处理
) else (
    echo     ❌ 未复用 request-fixed.ts
)

echo.
echo 2. 检查 request-fixed.ts 配置:
echo   - baseURL 定义:
findstr /n "localhost:8889" src\services\request-fixed.ts
if %errorlevel% equ 0 (
    echo     ✅ 指向 localhost:8889
) else (
    echo     ❌ 未指向 localhost:8889
)

echo.
echo 3. 检查哪些模块使用 api.ts:
echo   - Dashboard:
findstr /n "import.*api" src\pages\Dashboard\index.tsx >nul
if %errorlevel% equ 0 (
    echo     ✅ 使用 api.ts
) else (
    echo     ❌ 未使用 api.ts
)

echo   - authSlice:
findstr /n "import.*api" src\store\slices\authSlice.ts >nul
if %errorlevel% equ 0 (
    echo     ✅ 使用 api.ts
) else (
    echo     ❌ 未使用 api.ts
)

echo   - dashboardSlice:
findstr /n "import.*api" src\store\slices\dashboardSlice.ts >nul
if %errorlevel% equ 0 (
    echo     ✅ 使用 api.ts
) else (
    echo     ❌ 未使用 api.ts
)

echo.
echo 4. 检查重复错误处理:
echo   - api.ts 错误处理:
findstr /n "message\.error\|notification\.error" src\services\api.ts
if %errorlevel% equ 0 (
    echo     ⚠️  有重复错误处理
) else (
    echo     ✅ 无重复错误处理
)

echo.
echo 📋 修复总结:
echo   - 统一后端地址: localhost:8889
echo   - 复用错误处理: api.ts 使用 request-fixed.ts
echo   - 消除重复: 所有请求使用同一实例
echo.
echo 🚀 重启前端后验证:
echo   1. 登录接口: POST http://localhost:8889/api/auth/login
echo   2. Dashboard: GET http://localhost:8889/api/dashboard
echo   3. Stocks: GET http://localhost:8889/api/stocks
echo.
echo 🔄 强制刷新浏览器: Ctrl+Shift+R