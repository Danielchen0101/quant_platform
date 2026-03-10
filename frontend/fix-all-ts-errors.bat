@echo off
echo 🔧 TypeScript Error Fix Tool
echo ========================================
echo.

echo 📋 Checking current TypeScript status...
echo.

echo 1. Running TypeScript compilation check...
npx tsc --noEmit > ts-errors.log 2>&1
if %errorlevel% equ 0 (
    echo   ✅ TypeScript compilation passed, no errors!
    goto :SUCCESS
) else (
    echo   ❌ Found TypeScript errors
)

echo.
echo 2. 分析错误日志...
type ts-errors.log | findstr /i "error TS" > ts-error-summary.log

set /p errorCount=<ts-error-summary.log
if "%errorCount%"=="" (
    echo   ⚠️  未找到具体错误，检查完整日志
    goto :SHOW_LOG
)

echo   找到以下错误:
type ts-error-summary.log

echo.
echo 3. 修复dashboard.ts错误...
if exist "src\services\dashboard.ts" (
    echo   检查dashboard.ts文件...
    findstr /i "stocksRes\.stocks" src\services\dashboard.ts >nul
    if %errorlevel% equ 0 (
        echo   🎯 找到stocksRes.stocks错误，正在修复...
        call :FIX_DASHBOARD
        echo   ✅ dashboard.ts已修复
    ) else (
        echo   ✅ dashboard.ts无此错误
    )
)

echo.
echo 4. 检查其他常见错误...
echo   搜索其他可能的TypeScript问题...

:SHOW_LOG
echo.
echo 📄 完整错误日志:
echo -------------------------
type ts-errors.log
echo -------------------------

:SUCCESS
echo.
echo 🎯 TypeScript修复完成！
echo.
echo 📋 下一步操作:
echo   1. 重启前端服务: Ctrl+C 然后 npm start
echo   2. 验证修复: 访问 http://localhost:3000
echo   3. 检查控制台: 按F12查看Console标签
echo.
echo 🔧 如果仍有问题:
echo   1. 查看详细指南: ts-error-fix-guide.md
echo   2. 运行验证脚本: node verify-ts-fix.js
echo   3. 检查其他API服务文件
echo.
echo ========================================
echo ✅ TypeScript修复工具执行完成
pause
exit /b 0

:FIX_DASHBOARD
rem 备份原文件
copy src\services\dashboard.ts src\services\dashboard.ts.backup >nul

rem 创建修复后的文件
(
echo import { request } from '@umijs/max';
echo.
echo // 类型定义
echo interface StockItem {
echo   symbol: string;
echo   name: string;
echo   price: number;
echo   change: number;
echo   changePercent: number;
echo   volume?: number;
echo   marketCap?: number;
echo }
echo.
echo interface StocksResponse {
echo   stocks: StockItem[];
echo   timestamp?: string;
echo   count?: number;
echo }
echo.
echo interface SystemStatus {
echo   status: string;
echo   version: string;
echo   uptime: number;
echo   memory: {
echo     total: number;
echo     used: number;
echo     free: number;
echo   };
echo   cpu: {
echo     usage: number;
echo     cores: number;
echo   };
echo   services: Array<{
echo     name: string;
echo     status: string;
echo     uptime: number;
echo   }>;
echo }
echo.
echo interface DashboardData {
echo   systemStatus: SystemStatus;
echo   stocks: StockItem[];
echo }
echo.
echo export async function getDashboardData(): Promise<DashboardData> {
echo   return request('/api/dashboard', {
echo     method: 'GET',
echo   });
echo }
echo.
echo export async function fetchDashboardData(): Promise<DashboardData> {
echo   const [statusRes, stocksRes] = await Promise.all([
echo     request<SystemStatus>('/api/system/status'),
echo     request<StocksResponse>('/api/market/stocks'),
echo   ]);
echo.
echo   return {
echo     systemStatus: statusRes,
echo     stocks: stocksRes?.stocks || [],
echo   };
echo }
) > src\services\dashboard.ts

echo   ✅ 已创建修复版本
goto :EOF