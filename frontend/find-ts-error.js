const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

console.log('🔍 Searching TypeScript Error: Property \'stocks\' does not exist');
console.log('===================================================\n');

// 搜索目录
const searchDir = path.join(__dirname, 'src');

// 读取所有TypeScript文件
function findTypeScriptFiles(dir) {
  const files = [];
  
  function traverse(currentDir) {
    const items = fs.readdirSync(currentDir, { withFileTypes: true });
    
    for (const item of items) {
      const fullPath = path.join(currentDir, item.name);
      
      if (item.isDirectory()) {
        traverse(fullPath);
      } else if (item.isFile() && (item.name.endsWith('.ts') || item.name.endsWith('.tsx'))) {
        files.push(fullPath);
      }
    }
  }
  
  traverse(dir);
  return files;
}

// 搜索错误模式
function searchForErrorPattern(files) {
  const errorPatterns = [
    /stocksRes\.stocks/,
    /Promise\.all.*systemStatus/,
    /AxiosResponse.*stocks/,
    /\.stocks\s*\|/,
    /return\s*{[\s\S]*?stocks:/
  ];
  
  console.log(`📁 搜索 ${files.length} 个TypeScript文件...\n`);
  
  let foundFiles = [];
  
  for (const file of files) {
    try {
      const content = fs.readFileSync(file, 'utf8');
      const lines = content.split('\n');
      
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        
        // 检查是否包含错误行号模式
        if (line.includes('stocks:') && i > 0 && lines[i-1].includes('systemStatus:')) {
          console.log(`🎯 找到可能的问题文件: ${path.relative(__dirname, file)}`);
          console.log(`   行 ${i}: ${line.trim()}`);
          
          // 显示上下文
          const start = Math.max(0, i - 3);
          const end = Math.min(lines.length - 1, i + 3);
          
          console.log('   上下文:');
          for (let j = start; j <= end; j++) {
            const prefix = j === i ? '>>> ' : '    ';
            console.log(`${prefix}${j + 1}: ${lines[j]}`);
          }
          console.log();
          
          foundFiles.push({
            file,
            line: i + 1,
            context: lines.slice(start, end + 1)
          });
        }
      }
    } catch (err) {
      console.error(`❌ 读取文件失败: ${file}`, err.message);
    }
  }
  
  return foundFiles;
}

// 运行TypeScript编译检查
function runTypeScriptCheck() {
  console.log('🚀 运行TypeScript编译检查...\n');
  
  try {
    const result = execSync('npx tsc --noEmit', { 
      cwd: __dirname,
      encoding: 'utf8',
      stdio: 'pipe'
    });
    
    console.log('✅ TypeScript编译通过');
    return null;
  } catch (error) {
    const output = error.stdout.toString() + error.stderr.toString();
    
    // 提取错误信息
    const errors = output.split('\n').filter(line => 
      line.includes('error TS') || 
      line.includes('stocks') ||
      line.includes('AxiosResponse')
    );
    
    if (errors.length > 0) {
      console.log('❌ 找到TypeScript错误:');
      errors.forEach(err => console.log(`   ${err}`));
      return errors;
    }
    
    return null;
  }
}

// 主函数
async function main() {
  // 1. 查找TypeScript文件
  const tsFiles = findTypeScriptFiles(searchDir);
  
  // 2. 搜索错误模式
  const found = searchForErrorPattern(tsFiles);
  
  if (found.length === 0) {
    console.log('⚠️  未找到明显的错误模式，尝试编译检查...\n');
  }
  
  // 3. 运行TypeScript检查
  const errors = runTypeScriptCheck();
  
  // 4. 提供修复建议
  console.log('\n🔧 修复建议:');
  console.log('===================================================');
  
  if (found.length > 0 || errors) {
    console.log('\n1. 问题分析:');
    console.log('   - 错误: TS2339: Property \'stocks\' does not exist on type \'AxiosResponse<any, any, {}>\'');
    console.log('   - 原因: TypeScript无法推断AxiosResponse的data属性类型');
    console.log('   - 位置: 可能在某个API服务文件中');
    
    console.log('\n2. 解决方案:');
    console.log('   A. 添加类型定义:');
    console.log('      ```typescript');
    console.log('      interface StocksResponse {');
    console.log('        stocks: Array<{');
    console.log('          symbol: string;');
    console.log('          price: number;');
    console.log('          change: number;');
    console.log('        }>;');
    console.log('      }');
    console.log('      ```');
    
    console.log('\n   B. 使用类型断言:');
    console.log('      ```typescript');
    console.log('      const stocksRes = response as AxiosResponse<StocksResponse>;');
    console.log('      // 或者');
    console.log('      const stocks = (stocksRes as any).stocks || [];');
    console.log('      ```');
    
    console.log('\n   C. 使用可选链和类型守卫:');
    console.log('      ```typescript');
    console.log('      const stocks = stocksRes?.data?.stocks || [];');
    console.log('      ```');
    
    console.log('\n3. 查找具体文件:');
    console.log('   - 检查 src/services/ 目录');
    console.log('   - 检查 src/api/ 目录');
    console.log('   - 检查包含API调用的页面组件');
    
    console.log('\n4. 快速修复命令:');
    console.log('   ```bash');
    console.log('   # 查找所有包含stocks的API调用');
    console.log('   grep -r "axios.*stocks" src/ --include="*.ts" --include="*.tsx"');
    console.log('   ```');
  } else {
    console.log('✅ 未找到明显的TypeScript错误');
    console.log('   可能需要检查特定的API服务文件');
  }
}

main().catch(console.error);