Write-Host "🔍 Checking for Chinese characters in code files" -ForegroundColor Cyan
Write-Host "=================================================="
Write-Host ""

$searchPath = "."
$filePatterns = @("*.js", "*.ts", "*.tsx", "*.less", "*.css", "*.md", "*.html", "*.bat", "*.ps1", "*.py", "*.txt")
$chinesePattern = "[一-龥]"

Write-Host "📁 Searching for files with Chinese characters..." -ForegroundColor Yellow
Write-Host ""

$filesWithChinese = @()

foreach ($pattern in $filePatterns) {
    $files = Get-ChildItem -Path $searchPath -Recurse -Include $pattern -ErrorAction SilentlyContinue
    
    foreach ($file in $files) {
        try {
            $content = Get-Content $file.FullName -Raw -ErrorAction Stop
            
            if ($content -match $chinesePattern) {
                $filesWithChinese += $file
                
                # Count Chinese characters
                $chineseCount = ($content | Select-String -Pattern $chinesePattern -AllMatches).Matches.Count
                
                Write-Host "❌ Found Chinese in: $($file.FullName)" -ForegroundColor Red
                Write-Host "   Chinese characters: $chineseCount" -ForegroundColor Gray
                
                # Show sample lines
                $lines = Get-Content $file.FullName
                $sampleLines = @()
                
                for ($i = 0; $i -lt $lines.Count; $i++) {
                    if ($lines[$i] -match $chinesePattern) {
                        $sampleLines += "   Line $($i+1): $($lines[$i].Trim())"
                        if ($sampleLines.Count -ge 3) { break }
                    }
                }
                
                if ($sampleLines.Count -gt 0) {
                    Write-Host "   Sample lines:" -ForegroundColor DarkGray
                    $sampleLines | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray }
                }
                
                Write-Host ""
            }
        } catch {
            Write-Host "⚠️  Could not read: $($file.FullName)" -ForegroundColor Yellow
        }
    }
}

Write-Host ""
Write-Host "📊 Summary:" -ForegroundColor Cyan
Write-Host "==========="

if ($filesWithChinese.Count -eq 0) {
    Write-Host "✅ All code files are in English!" -ForegroundColor Green
} else {
    Write-Host "❌ Found $($filesWithChinese.Count) files with Chinese characters" -ForegroundColor Red
    Write-Host ""
    Write-Host "🔧 Recommended fix commands:" -ForegroundColor Yellow
    Write-Host "   # Check specific file" -ForegroundColor Gray
    Write-Host "   Get-Content file.js | Select-String '[一-龥]'" -ForegroundColor Gray
    Write-Host ""
    Write-Host "   # Replace Chinese with English" -ForegroundColor Gray
    Write-Host "   (Get-Content file.js) -replace '中文', 'English' | Set-Content file.js" -ForegroundColor Gray
}

Write-Host ""
Write-Host "🎯 File types checked:" -ForegroundColor Cyan
$filePatterns | ForEach-Object { Write-Host "   - $_" -ForegroundColor Gray }

Write-Host ""
Write-Host "🚀 Verification complete!" -ForegroundColor Green