Write-Host "🔧 Applying Layout Overlap Fix" -ForegroundColor Cyan
Write-Host "=================================="
Write-Host ""

# Check if frontend is running
Write-Host "📋 Checking frontend status..." -ForegroundColor Yellow
$frontendProcess = Get-Process -Name "node" -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*npm*" }

if ($frontendProcess) {
    Write-Host "✅ Frontend is running (PID: $($frontendProcess.Id))" -ForegroundColor Green
    Write-Host "   Stopping frontend to apply fixes..." -ForegroundColor Yellow
    
    # Stop frontend
    Stop-Process -Id $frontendProcess.Id -Force
    Write-Host "   Frontend stopped" -ForegroundColor Green
} else {
    Write-Host "ℹ️  Frontend is not running" -ForegroundColor Gray
}

# Apply layout fix
Write-Host ""
Write-Host "🎯 Applying layout fixes..." -ForegroundColor Yellow

# Check if layout-fix.less exists
$layoutFixFile = "src\styles\layout-fix.less"
if (Test-Path $layoutFixFile) {
    $fileSize = (Get-Item $layoutFixFile).Length
    Write-Host "✅ Layout fix file found: $layoutFixFile ($fileSize bytes)" -ForegroundColor Green
    
    # Check CSS rules count
    $content = Get-Content $layoutFixFile -Raw
    $ruleCount = ($content | Select-String -Pattern "{" -AllMatches).Matches.Count
    Write-Host "   CSS rules: $ruleCount" -ForegroundColor Gray
} else {
    Write-Host "❌ Layout fix file not found!" -ForegroundColor Red
    exit 1
}

# Check if App.tsx imports the fix
$appFile = "src\App.tsx"
if (Test-Path $appFile) {
    $appContent = Get-Content $appFile -Raw
    if ($appContent -match "layout-fix\.less") {
        Write-Host "✅ App.tsx imports layout-fix.less" -ForegroundColor Green
    } else {
        Write-Host "❌ App.tsx does not import layout-fix.less" -ForegroundColor Red
        Write-Host "   Adding import..." -ForegroundColor Yellow
        
        # Add import if missing
        $newContent = $appContent -replace "import './styles/antd-override\.less';", "import './styles/antd-override.less';`r`nimport './styles/layout-fix.less';"
        Set-Content -Path $appFile -Value $newContent
        Write-Host "   Import added" -ForegroundColor Green
    }
}

# Start frontend
Write-Host ""
Write-Host "🚀 Starting frontend with fixes..." -ForegroundColor Yellow

# Start npm in background
$npmProcess = Start-Process -FilePath "npm" -ArgumentList "start" -PassThru -NoNewWindow

if ($npmProcess) {
    Write-Host "✅ Frontend started (PID: $($npmProcess.Id))" -ForegroundColor Green
    Write-Host "   Waiting for server to be ready..." -ForegroundColor Yellow
    
    # Wait for server to start
    Start-Sleep -Seconds 10
    
    # Test if server is responding
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:3000" -TimeoutSec 5 -ErrorAction Stop
        Write-Host "✅ Frontend server is responding" -ForegroundColor Green
    } catch {
        Write-Host "⚠️  Frontend server may still be starting..." -ForegroundColor Yellow
    }
} else {
    Write-Host "❌ Failed to start frontend" -ForegroundColor Red
}

Write-Host ""
Write-Host "🎯 Next Steps:" -ForegroundColor Cyan
Write-Host "=============="
Write-Host "1. Open browser: http://localhost:3000" -ForegroundColor White
Write-Host "2. Force refresh: Ctrl+Shift+R" -ForegroundColor White
Write-Host "3. Test layout fix: Open test-layout-fix.html" -ForegroundColor White
Write-Host "4. Verify fixes:" -ForegroundColor White
Write-Host "   - Sidebar visible and not overlapped" -ForegroundColor Gray
Write-Host "   - Cards aligned horizontally" -ForegroundColor Gray
Write-Host "   - First card not misaligned" -ForegroundColor Gray
Write-Host "   - Header, sidebar, content boundaries aligned" -ForegroundColor Gray

Write-Host ""
Write-Host "🔧 Created Tools:" -ForegroundColor Cyan
Write-Host "================="
Write-Host "• layout-fix.less - Comprehensive layout fixes" -ForegroundColor Gray
Write-Host "• test-layout-fix.html - Visual test tool" -ForegroundColor Gray
Write-Host "• apply-layout-fix.ps1 - This automation script" -ForegroundColor Gray

Write-Host ""
Write-Host "✅ Layout fix applied successfully!" -ForegroundColor Green
Write-Host "   Refresh your dashboard to see the changes." -ForegroundColor White