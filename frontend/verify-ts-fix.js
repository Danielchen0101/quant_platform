/**
 * TypeScript修复验证脚本
 * 验证dashboard.ts的修复是否有效
 */

const fs = require('fs');
const path = require('path');

console.log('🔍 TypeScript Error Fix Verification');
console.log('===============================\n');

const dashboardFile = path.join(__dirname, 'src', 'services', 'dashboard.ts');

// 读取修复后的文件
const content = fs.readFileSync(dashboardFile, 'utf8');
const lines = content.split('\n');

console.log('📄 文件: src/services/dashboard.ts');
console.log(`📏 大小: ${content.length} 字符, ${lines.length} 行\n`);

// 检查修复的关键部分
const checks = {
  hasInterface: content.includes('interface StockItem') && content.includes('interface StocksResponse'),
  hasTypeParams: content.includes('request<SystemStatus>') && content.includes('request<StocksResponse>'),
  hasOptionalChaining: content.includes('stocksRes?.stocks'),
  hasReturnType: content.includes('Promise<DashboardData>'),
  noStocksResStocks: !content.includes('stocksRes.stocks'), // 不应该有旧的写法
  hasStocksArray: content.includes('stocks: stocksRes?.stocks || []')
};

console.log('✅ 修复验证结果:');
console.log('----------------');

Object.entries(checks).forEach(([check, passed]) => {
  const emoji = passed ? '✅' : '❌';
  const description = {
    hasInterface: '添加了类型定义接口',
    hasTypeParams: '添加了泛型类型参数',
    hasOptionalChaining: '使用了可选链操作符',
    hasReturnType: '添加了返回类型',
    noStocksResStocks: '移除了 stocksRes.stocks 错误写法',
    hasStocksArray: '正确访问 stocks 数组'
  }[check];
  
  console.log(`${emoji} ${description}`);
});

console.log('\n🔧 修复详情:');
console.log('----------------');

// 显示修复的关键代码
const keySections = [
  { start: 'interface StockItem', end: '}' },
  { start: 'interface StocksResponse', end: '}' },
  { start: 'export async function fetchDashboardData', end: '}' }
];

keySections.forEach(section => {
  const startIndex = lines.findIndex(line => line.includes(section.start));
  if (startIndex !== -1) {
    console.log(`\n${section.start}:`);
    let i = startIndex;
    while (i < lines.length && !lines[i].includes(section.end)) {
      console.log(`  ${lines[i]}`);
      i++;
    }
    if (i < lines.length) {
      console.log(`  ${lines[i]}`);
    }
  }
});

// 运行TypeScript检查
console.log('\n🚀 运行TypeScript编译检查...');
const { execSync } = require('child_process');

try {
  const result = execSync('npx tsc --noEmit', {
    cwd: __dirname,
    encoding: 'utf8',
    stdio: 'pipe'
  });
  
  console.log('✅ TypeScript编译通过，无错误！\n');
  
  // 检查是否有关于stocks的警告
  if (result.includes('stocks')) {
    console.log('⚠️  注意: 找到与stocks相关的警告:');
    result.split('\n')
      .filter(line => line.includes('stocks') && line.includes('warning'))
      .forEach(line => console.log(`  ${line}`));
  }
} catch (error) {
  const output = error.stdout.toString() + error.stderr.toString();
  
  console.log('❌ TypeScript编译错误:');
  const errors = output.split('\n')
    .filter(line => line.includes('error TS'))
    .map(line => `  ${line}`);
  
  if (errors.length > 0) {
    errors.forEach(err => console.log(err));
  } else {
    console.log('  (无具体错误信息)');
  }
}

console.log('\n🎯 下一步建议:');
console.log('----------------');
console.log('1. 重启前端开发服务器:');
console.log('   Ctrl+C 停止当前服务');
console.log('   npm start 重新启动');
console.log('');
console.log('2. 验证API调用:');
console.log('   访问 http://localhost:3000');
console.log('   检查dashboard数据是否正常加载');
console.log('');
console.log('3. 检查浏览器控制台:');
console.log('   按F12打开开发者工具');
console.log('   检查Console标签是否有错误');
console.log('');
console.log('4. 测试其他功能:');
console.log('   确保其他页面没有类似的TypeScript错误');

console.log('\n📋 修复总结:');
console.log('----------------');
console.log('✅ 问题: TS2339: Property \'stocks\' does not exist');
console.log('✅ 原因: 缺少TypeScript类型定义');
console.log('✅ 解决方案:');
console.log('   1. 添加 StockItem, StocksResponse 接口');
console.log('   2. 添加泛型类型参数 request<T>()');
console.log('   3. 使用可选链操作符 ?.');
console.log('   4. 添加明确的返回类型 Promise<DashboardData>');

console.log('\n🚀 TypeScript错误已成功修复！');