Write-Host "🔍 Searching TypeScript Error: stocksRes.stocks" -ForegroundColor Cyan
Write-Host "=========================================="
Write-Host ""

# Search for specific patterns
$pattern1 = "stocksRes\.stocks"
$pattern2 = "Promise\.all"
$pattern3 = "systemStatus.*stocks"

Write-Host "📁 Searching files..." -ForegroundColor Yellow

# 获取所有TypeScript文件
$tsFiles = Get-ChildItem -Path "src" -Recurse -Include "*.ts", "*.tsx"

Write-Host "找到 $($tsFiles.Count) 个TypeScript文件" -ForegroundColor Green
Write-Host ""

$foundFiles = @()

foreach ($file in $tsFiles) {
    $content = Get-Content $file.FullName -Raw
    
    # 检查是否包含错误模式
    if ($content -match $pattern1 -or $content -match $pattern2 -and $content -match "stocks") {
        $foundFiles += $file
        
        Write-Host "🎯 找到可能的问题文件: $($file.FullName)" -ForegroundColor Green
        
        # 显示相关行
        $lines = Get-Content $file.FullName
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match "stocksRes" -or $lines[$i] -match "Promise\.all") {
                Write-Host "   行 $($i+1): $($lines[$i].Trim())" -ForegroundColor Gray
                
                # 显示上下文
                $start = [Math]::Max(0, $i - 2)
                $end = [Math]::Min($lines.Count - 1, $i + 4)
                
                Write-Host "   上下文:" -ForegroundColor DarkGray
                for ($j = $start; $j -le $end; $j++) {
                    $prefix = if ($j -eq $i) { ">>> " } else { "    " }
                    Write-Host "$prefix$($j+1): $($lines[$j])" -ForegroundColor DarkGray
                }
                Write-Host ""
            }
        }
    }
}

if ($foundFiles.Count -eq 0) {
    Write-Host "⚠️  未找到包含错误模式的文件" -ForegroundColor Yellow
    Write-Host ""
    
    # 尝试其他搜索
    Write-Host "🔄 尝试其他搜索模式..." -ForegroundColor Yellow
    
    # 搜索包含axios调用的文件
    $axiosFiles = Get-ChildItem -Path "src" -Recurse -Include "*.ts", "*.tsx" | 
        Where-Object { (Get-Content $_.FullName -Raw) -match "axios" }
    
    Write-Host "找到 $($axiosFiles.Count) 个包含axios的文件" -ForegroundColor Green
    
    foreach ($file in $axiosFiles) {
        $content = Get-Content $file.FullName -Raw
        if ($content -match "\.stocks\s*\|") {
            Write-Host "🔍 找到可能的相关文件: $($file.FullName)" -ForegroundColor Green
            $foundFiles += $file
        }
    }
}

Write-Host ""
Write-Host "🔧 修复建议:" -ForegroundColor Cyan
Write-Host "=========================================="

if ($foundFiles.Count -gt 0) {
    Write-Host ""
    Write-Host "1. 问题分析:" -ForegroundColor Yellow
    Write-Host "   - 错误: TS2339: Property 'stocks' does not exist on type 'AxiosResponse<any, any, {}>'" -ForegroundColor White
    Write-Host "   - 原因: TypeScript无法确定AxiosResponse的data属性类型" -ForegroundColor White
    Write-Host "   - 位置: 上述找到的文件中" -ForegroundColor White
    
    Write-Host ""
    Write-Host "2. 解决方案:" -ForegroundColor Yellow
    
    Write-Host "   A. 添加类型定义接口:" -ForegroundColor Green
    Write-Host "      ```typescript" -ForegroundColor Gray
    Write-Host "      interface DashboardData {" -ForegroundColor Gray
    Write-Host "        systemStatus: any;" -ForegroundColor Gray
    Write-Host "        stocks: Array<{" -ForegroundColor Gray
    Write-Host "          symbol: string;" -ForegroundColor Gray
    Write-Host "          name: string;" -ForegroundColor Gray
    Write-Host "          price: number;" -ForegroundColor Gray
    Write-Host "          change: number;" -ForegroundColor Gray
    Write-Host "          changePercent: number;" -ForegroundColor Gray
    Write-Host "        }>;" -ForegroundColor Gray
    Write-Host "      }" -ForegroundColor Gray
    Write-Host "      ```" -ForegroundColor Gray
    
    Write-Host ""
    Write-Host "   B. 修复API调用:" -ForegroundColor Green
    Write-Host "      ```typescript" -ForegroundColor Gray
    Write-Host "      const [statusRes, stocksRes] = await Promise.all([" -ForegroundColor Gray
    Write-Host "        axios.get('/api/system/status')," -ForegroundColor Gray
    Write-Host "        axios.get<{ stocks: Stock[] }>('/api/market/stocks')" -ForegroundColor Gray
    Write-Host "      ]);" -ForegroundColor Gray
    Write-Host "      " -ForegroundColor Gray
    Write-Host "      return {" -ForegroundColor Gray
    Write-Host "        systemStatus: statusRes.data," -ForegroundColor Gray
    Write-Host "        stocks: stocksRes.data.stocks || []" -ForegroundColor Gray
    Write-Host "      };" -ForegroundColor Gray
    Write-Host "      ```" -ForegroundColor Gray
    
    Write-Host ""
    Write-Host "   C. 快速修复（类型断言）:" -ForegroundColor Green
    Write-Host "      ```typescript" -ForegroundColor Gray
    Write-Host "      const stocks = (stocksRes as any).stocks || [];" -ForegroundColor Gray
    Write-Host "      // 或" -ForegroundColor Gray
    Write-Host "      const stocks = (stocksRes.data as any).stocks || [];" -ForegroundColor Gray
    Write-Host "      ```" -ForegroundColor Gray
    
    Write-Host ""
    Write-Host "3. 检查的具体文件:" -ForegroundColor Yellow
    foreach ($file in $foundFiles) {
        Write-Host "   - $($file.FullName)" -ForegroundColor White
    }
} else {
    Write-Host "✅ 未找到明显的错误文件" -ForegroundColor Green
    Write-Host ""
    Write-Host "建议手动检查以下位置:" -ForegroundColor Yellow
    Write-Host "   - src/services/ 目录" -ForegroundColor White
    Write-Host "   - src/pages/ 目录中的API调用" -ForegroundColor White
    Write-Host "   - 任何包含dashboard或market数据的组件" -ForegroundColor White
}

Write-Host ""
Write-Host "🚀 快速修复命令:" -ForegroundColor Cyan
Write-Host "=========================================="
Write-Host "1. 运行TypeScript检查:" -ForegroundColor White
Write-Host "   npx tsc --noEmit" -ForegroundColor Gray
Write-Host ""
Write-Host "2. 查找所有API调用:" -ForegroundColor White
Write-Host "   Get-ChildItem src -Recurse -Include *.ts, *.tsx | Select-String 'axios\.get' | Select Path, LineNumber" -ForegroundColor Gray
Write-Host ""
Write-Host "3. 直接修复（如果找到文件）:" -ForegroundColor White
Write-Host "   # 将 stocksRes.stocks 改为 stocksRes.data.stocks" -ForegroundColor Gray
Write-Host "   # 或添加类型定义" -ForegroundColor Gray