# 🚀 快速启动指南

## 问题解决：PowerShell脚本执行

### 错误原因
Windows PowerShell默认安全策略阻止运行本地脚本。

### 解决方案（三选一）

#### 方案1: 使用 `.\` 前缀（最简单）
```powershell
cd ~/.openclaw/workspace/professional_quant_platform
.\start_platform.bat
```

#### 方案2: 使用PowerShell脚本
```powershell
cd ~/.openclaw/workspace/professional_quant_platform
powershell -ExecutionPolicy Bypass -File .\start_platform.ps1
```

#### 方案3: 手动启动（最可靠）

**终端1 - 启动后端**:
```powershell
cd ~/.openclaw\workspace\professional_quant_platform\backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

**终端2 - 启动前端**:
```powershell
cd ~/.openclaw\workspace\professional_quant_platform\frontend
npm install
npm start
```

## ✅ 验证服务运行

### 检查后端
```powershell
# 新终端中运行
curl http://localhost:8889/api/system/status
# 或使用浏览器访问
# http://localhost:8889/api/system/status
```

**预期响应**:
```json
{
  "status": "online",
  "timestamp": "2026-03-08T15:30:00",
  "version": "1.0.0",
  "services": {
    "qlib": "available",
    "backtrader": "available",
    "authentication": "enabled"
  }
}
```

### 检查前端
1. 打开浏览器
2. 访问: http://localhost:3000
3. 使用测试账号登录: **admin** / **admin123**

## 🔧 故障排除

### 问题1: "无法识别命令"
**错误**: `start_platform.bat : 无法将"start_platform.bat"项识别为 cmdlet、函数、脚本文件或可运行程序的名称`

**解决**: 使用 `.\start_platform.bat` 而不是 `start_platform.bat`

### 问题2: 端口被占用
**错误**: `Address already in use`

**解决**:
```powershell
# 查找占用端口的进程
netstat -ano | findstr :3000
netstat -ano | findstr :8889

# 修改端口配置
# 后端: 修改 backend/app.py 中的 port=8889
# 前端: 修改 frontend/.env 中的 REACT_APP_API_URL
```

### 问题3: 依赖安装失败
**解决**:
```powershell
# 清理npm缓存
npm cache clean --force

# 使用淘宝镜像
npm config set registry https://registry.npmmirror.com

# 重新安装
cd frontend
npm install
```

### 问题4: Python虚拟环境问题
**解决**:
```powershell
# 删除并重新创建虚拟环境
cd backend
rmdir /s venv
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 🌐 访问地址

### 开发环境
- **前端界面**: http://localhost:3000
- **后端API**: http://localhost:8889
- **API文档**: http://localhost:8889/ (自动生成)

### 测试账号
1. **admin** / **admin123** - 管理员权限
2. **trader** / **trader123** - 交易员权限
3. **analyst** / **analyst123** - 分析师权限

## 📱 功能验证

### 步骤1: 登录验证
1. 访问 http://localhost:3000
2. 输入用户名: `admin`
3. 输入密码: `admin123`
4. 点击登录

### 步骤2: 仪表板验证
1. 登录后自动跳转到仪表板
2. 验证以下组件显示正常:
   - 资产统计卡片
   - 投资组合分布
   - 系统状态面板
   - 实时行情表格

### 步骤3: API验证
```powershell
# 验证登录API
curl -X POST http://localhost:8889/api/auth/login ^
  -H "Content-Type: application/json" ^
  -d "{\"username\":\"admin\",\"password\":\"admin123\"}"

# 验证市场数据API
curl http://localhost:8889/api/market/stocks
```

## ⚡ 一键启动命令汇总

### 方法A: 批处理文件（需要管理员权限）
```powershell
# 以管理员身份运行PowerShell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
cd ~/.openclaw/workspace/professional_quant_platform
.\start_platform.bat
```

### 方法B: PowerShell脚本（推荐）
```powershell
cd ~/.openclaw/workspace/professional_quant_platform
powershell -ExecutionPolicy Bypass -File .\start_platform.ps1
```

### 方法C: 手动启动（最稳定）
```powershell
# 终端1 - 后端
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py

# 终端2 - 前端
cd frontend
npm install
npm start
```

## 🎯 成功标志

### 后端成功
- 终端显示: `🚀 量化平台后端API`
- 显示: `API地址: http://localhost:8889`
- 显示: `Qlib状态: ✅ 已初始化`
- 无错误信息

### 前端成功
- 终端显示: `Compiled successfully!`
- 显示: `You can now view frontend in the browser.`
- 显示: `Local: http://localhost:3000`
- 浏览器自动打开登录页面

### 平台成功
1. 浏览器访问 http://localhost:3000
2. 显示现代化登录页面
3. 使用测试账号成功登录
4. 显示专业仪表板界面
5. 所有功能模块正常

## 📞 技术支持

### 如果仍然无法启动
1. **检查环境**:
   ```powershell
   # Python版本
   python --version
   
   # Node.js版本  
   node --version
   
   # npm版本
   npm --version
   ```

2. **查看日志**:
   - 后端日志: 在启动后端的终端中查看
   - 前端日志: 在启动前端的终端中查看
   - 浏览器控制台: F12打开开发者工具

3. **文件验证**:
   ```powershell
   # 检查关键文件
   dir ~/.openclaw/workspace/professional_quant_platform\
   dir ~/.openclaw/workspace/professional_quant_platform\backend\
   dir ~/.openclaw/workspace/professional_quant_platform\frontend\
   ```

### 紧急联系方式
如果以上方法都无法解决，请提供:
1. 操作系统版本
2. Python和Node.js版本
3. 完整的错误信息
4. 执行的命令和输出

## 🎉 启动成功！

当看到以下界面时，表示平台启动成功:

1. **后端终端**:
   ```
   ========================================
   🚀 量化平台后端API
   ========================================
   Qlib状态: ✅ 已初始化
   Backtrader: ✅ 可用
   API地址: http://localhost:8889
   ```

2. **前端终端**:
   ```
   Compiled successfully!
   You can now view frontend in the browser.
   Local: http://localhost:3000
   ```

3. **浏览器**:
   - 访问 http://localhost:3000
   - 看到现代化登录页面
   - 成功登录后看到专业仪表板

**现在可以开始使用专业量化平台了！** 🚀📈