# 📦 强势股智能筛选系统 - Mac 部署指南

## 🎯 系统简介

基于量化指标的A股强势股自动筛选系统，提供Web可视化界面和专业技术分析图表。

- **数据源**: 同花顺问财(成交额/热度) + AKShare(历史价格，免费开源)
- **技术栈**: Python 3.11+ / FastAPI / Plotly.js

---

## 📋 系统要求

- **操作系统**: macOS 10.14+
- **Python**: 3.11 或更高版本
- **内存**: 至少 2GB 可用内存
- **网络**: 需要互联网连接

---

## 🚀 快速部署（5分钟）

### 步骤 1: 检查 Python 版本

打开终端，运行：
```bash
python3 --version
```

确保显示 `Python 3.11.x` 或更高版本。

### 步骤 2: 安装依赖

```bash
# 进入项目目录
cd auto_filter_stock

# 安装所有依赖（推荐使用pip）
pip3 install -r requirements.txt
```

**或者使用 Poetry（推荐）**:
```bash
# 安装 Poetry（如果还没安装）
curl -sSL https://install.python-poetry.org | python3 -

# 安装项目依赖
poetry install
```

### 步骤 3: 配置环境变量

创建 `.env` 文件：
```bash
# 复制示例配置
cp .env.example .env

# 编辑配置文件
nano .env
```

在 `.env` 文件中添加：
```env
# 同花顺问财Cookie（必需）
PYWENCAI_COOKIE=你的cookie字符串

# 日志级别（可选）
LOG_LEVEL=INFO
```

**如何获取 Cookie？**

📖 **详细图文教程请查看**: `COOKIE_GUIDE.md`

**快速方法**（推荐使用Cookie-Editor插件）：
1. 安装浏览器插件 "Cookie-Editor"
2. 访问 https://www.iwencai.com/unifiedwap/home/index
3. 登录您的问财账号
4. 点击浏览器工具栏的Cookie-Editor图标🍪
5. 点击 "Export" → 选择 "Header String"
6. Cookie自动复制到剪贴板
7. 粘贴到 `.env` 文件

或运行配置脚本：
```bash
bash setup_cookie.sh
```

### 步骤 4: 启动服务器

```bash
bash start_server.sh
```

看到以下信息表示启动成功：
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

### 步骤 5: 访问系统

打开浏览器，访问：
```
http://localhost:8000
```

---

## 🌐 使用系统

### 主界面功能

1. **参数配置**（可选）
   - 成交额Top: 100（默认）
   - 热度Top: 100（默认）
   - 动量天数: 25（默认）
   - 最终输出: 10（默认）

2. **开始筛选**
   - 点击"开始筛选"按钮
   - 实时查看进度（约1-2分钟）
   - 自动展示结果

3. **查看结果**
   - 📊 K线图 + 3条均线
   - 📈 动量评分详情
   - 📥 下载CSV结果

### API 文档

访问交互式API文档：
```
http://localhost:8000/docs
```

---

## 📦 核心依赖列表

```
fastapi==0.104.0          # Web框架
uvicorn==0.24.0           # ASGI服务器
pandas==2.1.0             # 数据处理
scikit-learn==1.3.0       # 机器学习
plotly==5.17.0            # 数据可视化
pywencai==0.1.0           # 同花顺数据
akshare==1.12.0           # AKShare数据源（新）
loguru==0.7.0             # 日志系统
pydantic==2.4.0           # 数据验证
requests==2.31.0          # HTTP请求
```

---

## 🛠️ 常见问题

### 1. 端口被占用

如果8000端口被占用，修改 `.env`：
```env
API_PORT=8001
```

或者停止占用进程：
```bash
lsof -ti:8000 | xargs kill -9
```

### 2. Cookie 失效

Cookie会定期失效，出现以下错误时需重新配置：
```
ERROR: Pywencai cookie not found!
```

重新运行：
```bash
bash setup_cookie.sh
```

### 3. 网络连接问题

AKShare 需要网络连接，如遇超时：
- 检查网络连接
- 系统会自动重试3次
- 如持续失败，请稍后再试

### 4. 依赖安装失败

```bash
# 升级 pip
pip3 install --upgrade pip

# 清理缓存后重试
pip3 cache purge
pip3 install -r requirements.txt
```

---

## 🔄 更新系统

```bash
# 停止服务器（Ctrl+C）

# 更新代码
git pull

# 更新依赖
pip3 install -r requirements.txt --upgrade

# 重启服务器
bash start_server.sh
```

---

## 🛑 停止服务器

在终端中按 `Ctrl+C`，或运行：
```bash
pkill -f "uvicorn"
```

---

## 📊 数据说明

### 筛选流程

1. **阶段1**: 获取成交额Top100股票
2. **阶段2**: 获取热度Top100股票  
3. **阶段3**: 计算交集并加权排名Top30
4. **阶段4**: 使用AKShare获取历史数据，计算25日动量
5. **阶段5**: 输出最强Top10股票

### 结果文件

所有筛选结果保存在 `results/` 目录：
- `*_stage1_*.csv` - 成交额Top100
- `*_stage2_*.csv` - 热度Top100
- `*_stage3_*.csv` - 加权Top30
- `*_stage4_*.csv` - 动量计算结果
- `*_stage5_*.csv` - 最终Top10

---

## 💡 性能优化

- 使用线程池并发获取历史数据（10线程）
- 30只股票约需4-5秒
- 完整筛选流程约1-2分钟

---

## 📞 技术支持

**遇到问题？**

1. 查看日志：`logs/stock_screening.log`（自动创建）
2. 检查系统健康：`http://localhost:8000/api/v1/health/`
3. 查看本文档的"常见问题"部分

---

## ✨ 特色功能

✅ 免费数据源（AKShare）
✅ 实时进度追踪
✅ 专业K线图表
✅ 多阶段筛选
✅ Web可视化界面
✅ CSV结果导出

---

## 📝 开发信息

- **版本**: 2.0.0
- **数据源**: AKShare (2025-10-12 升级)
- **Python**: 3.11+
- **Web框架**: FastAPI + Uvicorn

祝您使用愉快！🎉

