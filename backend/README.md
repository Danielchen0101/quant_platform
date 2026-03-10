# 📊 量化交易平台后端

基于Flask + Qlib + Backtrader的专业量化交易平台后端。

## 🚀 快速开始

### 1. 安装依赖
```bash
# 基础依赖
pip install flask flask-cors pandas numpy yfinance

# 完整依赖 (推荐)
pip install -r requirements.txt
```

### 2. 启动服务

#### 简化版 (快速启动)
```bash
# 默认启动简化版
python app.py

# 或明确指定
QUANT_MODE=simple python app.py
```

#### 完整版 (需要安装所有依赖)
```bash
# 启动完整版
QUANT_MODE=full python app.py
```

### 3. 验证服务
```bash
# 健康检查
curl http://localhost:8889/api/health

# 系统状态
curl http://localhost:8889/api/system/status

# 用户登录
curl -X POST http://localhost:8889/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
```

## 📁 项目结构

```
backend/
├── app.py                    # 主入口文件
├── quant_backend.py          # 完整版后端 (数据库 + Qlib)
├── start_quant_backend.py    # 简化版后端 (快速启动)
├── requirements.txt          # Python依赖
├── .env.example             # 环境变量示例
├── README.md                # 本文档
└── logs/                    # 日志目录
```

## 🔧 配置说明

### 环境变量
复制 `.env.example` 为 `.env` 并修改：

```env
# 应用配置
FLASK_ENV=development
PORT=8889
HOST=0.0.0.0
QUANT_MODE=simple  # simple 或 full

# 数据库配置 (完整版需要)
DATABASE_URL=sqlite:///quant.db
# DATABASE_URL=postgresql://user:password@localhost/quantdb

# 安全配置
SECRET_KEY=your-secret-key-here
JWT_SECRET_KEY=your-jwt-secret-key-here

# Qlib配置 (完整版需要)
QLIB_DATA_DIR=./qlib_data
QLIB_REGION=us

# CORS配置
CORS_ORIGINS=["http://localhost:3000"]
```

### 运行模式

| 模式 | 描述 | 依赖要求 | 适用场景 |
|------|------|----------|----------|
| `simple` | 简化版，快速启动 | Flask, pandas, yfinance | 开发测试，快速验证 |
| `full` | 完整版，所有功能 | 全部requirements.txt | 生产环境，完整功能 |

## 📊 API接口

### 基础接口
- `GET /api/health` - 健康检查
- `GET /api/system/status` - 系统状态
- `POST /api/auth/login` - 用户登录
- `POST /api/auth/register` - 用户注册

### 市场数据
- `GET /api/market/stocks` - 获取股票列表
- `GET /api/market/stock/<symbol>` - 获取股票详情
- `GET /api/market/indices` - 获取指数数据

### 量化分析
- `GET /api/backtest/strategies` - 获取策略列表
- `POST /api/backtest/run` - 运行策略回测
- `GET /api/backtest/results/<id>` - 获取回测结果

### 投资组合
- `POST /api/portfolio/create` - 创建投资组合
- `GET /api/portfolio/<id>` - 获取投资组合详情
- `POST /api/portfolio/<id>/trade` - 执行交易
- `GET /api/portfolio/<id>/performance` - 获取绩效报告

### 风险管理
- `POST /api/risk/analyze` - 风险分析
- `GET /api/risk/metrics` - 风险指标
- `POST /api/risk/stress-test` - 压力测试

## 🛠️ 开发指南

### 数据库迁移 (完整版)
```bash
# 初始化迁移
flask db init

# 创建迁移脚本
flask db migrate -m "Initial migration"

# 应用迁移
flask db upgrade
```

### 测试
```bash
# 运行测试
pytest tests/

# 带覆盖率测试
pytest --cov=backend tests/
```

### 代码规范
```bash
# 代码格式化
black .

# 代码检查
flake8 backend/
```

## 🔍 故障排除

### 常见问题

1. **端口被占用**
```bash
# 查找占用进程
netstat -ano | findstr :8889

# 杀死进程
taskkill /PID <PID> /F
```

2. **依赖安装失败**
```bash
# 使用国内镜像
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

3. **Qlib初始化失败**
```bash
# 手动初始化Qlib数据
python -c "import qlib; qlib.init(provider_uri='./qlib_data')"
```

4. **数据库连接失败**
```bash
# 检查数据库服务
# 对于SQLite，确保有写入权限
# 对于PostgreSQL/MySQL，检查连接字符串
```

### 日志查看
```bash
# 查看实时日志
tail -f logs/backend.log

# 查看错误日志
grep ERROR logs/backend.log
```

## 🚀 生产部署

### 使用Gunicorn
```bash
# 安装Gunicorn
pip install gunicorn

# 启动服务
gunicorn -w 4 -b 0.0.0.0:8889 "app:main()"
```

### 使用Docker
```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8889
CMD ["python", "app.py"]
```

### 使用Supervisor (Linux)
```ini
# /etc/supervisor/conf.d/quant-backend.conf
[program:quant-backend]
command=/path/to/venv/bin/gunicorn -w 4 -b 0.0.0.0:8889 "app:main()"
directory=/path/to/backend
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
```

## 📚 学习资源

### 相关技术
- [Flask官方文档](https://flask.palletsprojects.com/)
- [Qlib文档](https://qlib.readthedocs.io/)
- [Backtrader文档](https://www.backtrader.com/docu/)
- [yfinance文档](https://pypi.org/project/yfinance/)

### 量化交易
- [量化投资基础](https://github.com/quantopian/lectures)
- [算法交易策略](https://www.quantstart.com/articles/)
- [风险管理](https://www.risk.net/risk-management)

## 🤝 贡献指南

1. Fork项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启Pull Request

## 📄 许可证

本项目采用MIT许可证。详见 [LICENSE](LICENSE) 文件。

## 📞 支持

- 问题报告: [GitHub Issues](https://github.com/your-repo/issues)
- 文档: [项目Wiki](https://github.com/your-repo/wiki)
- 讨论: [Discord频道](https://discord.gg/your-channel)

---

**Happy Quant Trading!** 🚀📈