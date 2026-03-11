# Python Environment Setup Guide

## Current Issue
Python is not installed on the system, causing the backend to fail to run.

## Solution

### 1. Install Python
1. Visit https://www.python.org/downloads/
2. Download the latest Python installer
3. Run the installer, **make sure to check "Add Python to PATH"**
4. Restart terminal after installation completes

### 2. Verify Installation
Open a new terminal window and run:
```cmd
python --version
```
Should display Python version (e.g., Python 3.11.4)

### 3. Install Backend Dependencies
```cmd
cd backend
python -m pip install -r requirements.txt
```

### 4. Start Backend
```cmd
cd backend
python start_quant_backend.py
```

## Alternative Solutions
If you don't want to install full Python, consider:
1. Using Docker containers to run backend
2. Using online Python environments
3. Migrating backend to Node.js (if frontend is already React)

## Project Dependencies
Python packages required by backend:
- Flask
- Flask-CORS
- python-dotenv
- yfinance
- pandas
- numpy

---

## 中文翻译备注

### 问题描述
系统未安装Python，导致后端无法运行。

### 解决方案步骤
1. **安装Python**：从官网下载并安装，务必勾选"Add Python to PATH"
2. **验证安装**：运行 `python --version` 确认安装成功
3. **安装依赖**：进入backend目录，运行 `pip install -r requirements.txt`
4. **启动后端**：运行 `python start_quant_backend.py`

### 备选方案
1. 使用Docker容器运行后端
2. 使用在线Python环境
3. 将后端迁移到Node.js

### 项目依赖
后端需要的Python包：
- Flask：Web框架
- Flask-CORS：跨域支持
- python-dotenv：环境变量管理
- yfinance：股票数据获取
- pandas：数据处理
- numpy：数值计算