@echo off
echo 🔧 启动量化交易平台
echo ========================================
echo.

echo 📊 启动后端API服务...
echo.
cd backend
start "量化平台后端" cmd /k "python app.py"
timeout /t 3 /nobreak >nul

echo.
echo 🎨 启动前端React应用...
echo.
cd ..\frontend
start "量化平台前端" cmd /k "npm start"
timeout /t 5 /nobreak >nul

echo.
echo ✅ 平台启动完成！
echo.
echo 🌐 访问地址:
echo   前端界面: http://localhost:3000
echo   后端API:  http://localhost:8889
echo.
echo 🔐 测试账号:
echo   用户名: admin
echo   密码: admin123
echo.
echo 📋 验证命令:
echo   curl http://localhost:8889/api/health
echo   curl http://localhost:8889/api/system/status
echo.
echo ⚠️  注意: 请确保两个窗口都保持打开状态
echo ========================================
pause