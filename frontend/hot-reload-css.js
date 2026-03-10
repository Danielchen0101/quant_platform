/**
 * CSS热重载脚本
 * 用于在不重启开发服务器的情况下应用CSS修复
 * 使用方法: node hot-reload-css.js
 */

const fs = require('fs');
const path = require('path');
const chokidar = require('chokidar');

console.log('🎨 CSS Hot Reload Monitor Started');
console.log('Monitoring directory: src/styles/');
console.log('Press Ctrl+C to stop monitoring\n');

// 要监控的CSS/LESS文件
const stylesDir = path.join(__dirname, 'src', 'styles');
const filesToWatch = [
  'antd-override.less',
  'fix-overlap.less',
  'global.less'
];

// 创建文件监控
const watcher = chokidar.watch(
  filesToWatch.map(file => path.join(stylesDir, file)),
  {
    persistent: true,
    ignoreInitial: true,
    awaitWriteFinish: {
      stabilityThreshold: 500,
      pollInterval: 100
    }
  }
);

// 文件变化时的处理
watcher.on('change', (filePath) => {
  const fileName = path.basename(filePath);
  const timestamp = new Date().toLocaleTimeString();
  
  console.log(`\n🔄 [${timestamp}] ${fileName} 已修改`);
  
  // 读取文件内容
  fs.readFile(filePath, 'utf8', (err, content) => {
    if (err) {
      console.error(`❌ 读取文件失败: ${err.message}`);
      return;
    }
    
    // 分析CSS规则数量
    const ruleCount = (content.match(/{/g) || []).length;
    const lineCount = content.split('\n').length;
    
    console.log(`   📊 文件统计: ${lineCount} 行, ${ruleCount} 个CSS规则`);
    
    // 检查常见问题
    const checks = {
      hasImportant: (content.match(/!important/g) || []).length,
      hasZIndex: (content.match(/z-index/g) || []).length,
      hasMargin: (content.match(/margin[^:]*:/g) || []).length,
      hasPadding: (content.match(/padding[^:]*:/g) || []).length,
      hasMediaQuery: (content.match(/@media/g) || []).length
    };
    
    console.log(`   🔍 样式分析:`);
    console.log(`      !important: ${checks.hasImportant} 处`);
    console.log(`      z-index: ${checks.hasZIndex} 处`);
    console.log(`      margin: ${checks.hasMargin} 处`);
    console.log(`      padding: ${checks.hasPadding} 处`);
    console.log(`      媒体查询: ${checks.hasMediaQuery} 处`);
    
    // 检查特定修复
    if (fileName === 'antd-override.less') {
      const specificChecks = {
        hasProLayout: content.includes('.ant-pro-layout'),
        hasProSider: content.includes('.ant-pro-sider'),
        hasProContent: content.includes('.ant-pro-layout-content'),
        hasTabs: content.includes('.ant-tabs'),
        hasPageHeader: content.includes('.ant-page-header')
      };
      
      console.log(`   🎯 Ant Design Pro修复:`);
      Object.entries(specificChecks).forEach(([key, value]) => {
        console.log(`      ${key}: ${value ? '✅' : '❌'}`);
      });
    }
    
    // 提示用户刷新浏览器
    console.log(`\n   🚀 CSS已更新，请在浏览器中:`);
    console.log(`      1. 按 Ctrl+Shift+R 强制刷新`);
    console.log(`      2. 或按 F5 刷新页面`);
    console.log(`      3. 检查UI重叠问题是否修复\n`);
    
    // 生成CSS应用报告
    generateReport(fileName, content);
  });
});

// 生成修复报告
function generateReport(fileName, content) {
  const reportDir = path.join(__dirname, 'css-reports');
  if (!fs.existsSync(reportDir)) {
    fs.mkdirSync(reportDir, { recursive: true });
  }
  
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const reportFile = path.join(reportDir, `${fileName}-${timestamp}.txt`);
  
  const report = `
CSS修复报告
============
文件: ${fileName}
时间: ${new Date().toLocaleString()}
大小: ${content.length} 字符

关键修复点:
${extractKeyFixes(content)}

建议操作:
1. 检查侧边栏与页签间距
2. 验证z-index层级
3. 测试响应式布局
4. 验证暗色模式

`;
  
  fs.writeFileSync(reportFile, report);
  console.log(`   📋 修复报告已保存: ${reportFile}`);
}

// 提取关键修复点
function extractKeyFixes(content) {
  const fixes = [];
  const lines = content.split('\n');
  
  lines.forEach((line, index) => {
    const trimmed = line.trim();
    
    // 查找关键CSS规则
    if (
      trimmed.includes('margin-left') ||
      trimmed.includes('z-index') ||
      trimmed.includes('.ant-pro-') ||
      trimmed.includes('.ant-tabs') ||
      trimmed.includes('!important')
    ) {
      fixes.push(`第 ${index + 1} 行: ${trimmed.substring(0, 80)}...`);
    }
  });
  
  return fixes.slice(0, 10).join('\n'); // 只返回前10个关键点
}

// 错误处理
watcher.on('error', (error) => {
  console.error(`❌ 监控错误: ${error.message}`);
});

// 优雅关闭
process.on('SIGINT', () => {
  console.log('\n👋 停止CSS热重载监控');
  watcher.close();
  process.exit(0);
});

console.log('✅ 开始监控CSS文件变化...');
console.log('修改任何CSS/LESS文件将自动检测并提示刷新');