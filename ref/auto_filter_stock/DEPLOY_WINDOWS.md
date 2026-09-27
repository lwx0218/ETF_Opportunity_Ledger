# 📦 强势股智能筛选系统 - Windows 部署指南

## 🎯 系统简介

基于量化指标的A股强势股自动筛选系统，提供Web可视化界面和专业技术分析图表。

- **数据源**: 同花顺问财(成交额/热度) + AKShare(历史价格，免费开源)
- **技术栈**: Python 3.11+ / FastAPI / Plotly.js

---

## 📋 系统要求

- **操作系统**: Windows 10/11
- **Python**: 3.11 或更高版本
- **内存**: 至少 2GB 可用内存
- **网络**: 需要互联网连接

---

## 🚀 快速部署（5分钟）

### 步骤 1: 安装 Python

1. 访问 https://www.python.org/downloads/
2. 下载 Python 3.11 或更高版本
3. **重要**: 安装时勾选 "Add Python to PATH"
4. 完成安装

验证安装：
```cmd
python --version
```

应显示 `Python 3.11.x` 或更高版本。

### 步骤 2: 解压项目

将下载的 `auto_filter_stock_windows.zip` 解压到任意目录，例如：
```
C:\Users\YourName\auto_filter_stock
```

### 步骤 3: 安装依赖

打开 **命令提示符(CMD)** 或 **PowerShell**：

```cmd
# 进入项目目录
cd C:\Users\YourName\auto_filter_stock

# 升级 pip
python -m pip install --upgrade pip

# 安装所有依赖
pip install -r requirements.txt
```

**等待安装完成**（约2-3分钟）

### 步骤 4: 配置环境变量

在项目目录创建 `.env` 文件：

**方法1 - 使用记事本**：
1. 右键 → 新建 → 文本文档
2. 重命名为 `.env`（删除.txt后缀）
3. 用记事本打开，添加内容：

```env
# 同花顺问财Cookie（必需）
PYWENCAI_COOKIE=你的cookie字符串

# 日志级别（可选）
LOG_LEVEL=INFO
```

**方法2 - 使用命令行**：
```cmd
copy .env.example .env
notepad .env
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

**或使用开发者工具**：
1. 访问 https://www.iwencai.com/unifiedwap/home/index 并登录
2. 按 `F12` 打开开发者工具
3. 切换到 "Application" 标签
4. 左侧选择 "Cookies" → "iwencai.com"
5. 在Console执行: `document.cookie`
6. 复制输出的完整Cookie字符串

### 步骤 5: 启动服务器

**方法1 - 双击启动**：
```
双击运行: start_server.bat
```

**方法2 - 命令行启动**：
```cmd
python main.py
```

看到以下信息表示启动成功：
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

⚠️ **防火墙提示**: 首次运行可能弹出防火墙警告，请点击"允许访问"。

### 步骤 6: 访问系统

打开浏览器（推荐 Chrome/Edge），访问：
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

### 1. Python 未找到

错误：`'python' 不是内部或外部命令`

**解决方案**：
```cmd
# 检查是否安装
where python

# 如果没有输出，重新安装Python并勾选"Add to PATH"
```

### 2. 端口被占用

错误：`Address already in use`

**解决方案**：
```cmd
# 查看占用端口的进程
netstat -ano | findstr :8000

# 结束进程（替换PID为实际数字）
taskkill /PID 12345 /F
```

或修改 `.env` 使用其他端口：
```env
API_PORT=8001
```

### 3. Cookie 失效

错误：`ERROR: Pywencai cookie not found!`

**解决方案**：
重新获取Cookie并更新 `.env` 文件。

### 4. 防火墙阻止

Windows Defender 可能阻止访问。

**解决方案**：
- 允许 Python 通过防火墙
- 或临时关闭防火墙测试

### 5. 依赖安装失败

**解决方案**：
```cmd
# 使用国内镜像加速
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 或使用阿里云镜像
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

### 6. 编码错误

如果出现中文乱码：

**解决方案**：
```cmd
# 设置环境变量
set PYTHONIOENCODING=utf-8

# 然后重新启动
python main.py
```

---

## 🔄 更新系统

```cmd
# 停止服务器（Ctrl+C）

# 更新依赖
pip install -r requirements.txt --upgrade

# 重启服务器
python main.py
```

---

## 🛑 停止服务器

在命令行窗口按 `Ctrl+C`

或使用任务管理器：
1. 按 `Ctrl+Shift+Esc` 打开任务管理器
2. 找到 `python.exe` 进程
3. 右键 → 结束任务

---

## 📊 数据说明

### 筛选流程

1. **阶段1**: 获取成交额Top100股票
2. **阶段2**: 获取热度Top100股票  
3. **阶段3**: 计算交集并加权排名Top30
4. **阶段4**: 使用AKShare获取历史数据，计算25日动量
5. **阶段5**: 输出最强Top10股票

### 结果文件

所有筛选结果保存在 `results\` 目录：
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

## 📁 目录结构

```
auto_filter_stock/
├── main.py                    # 主程序入口
├── start_server.bat          # Windows启动脚本
├── requirements.txt          # 依赖列表
├── .env                      # 配置文件（需创建）
├── README.md                 # 项目说明
├── static/                   # 前端页面
│   └── index.html
├── src/                      # 核心源代码
│   ├── analysis/            # 分析模块
│   ├── api/                 # API接口
│   ├── data/                # 数据获取（含AKShare）
│   └── ...
├── results/                  # 筛选结果（自动创建）
└── logs/                     # 日志文件（自动创建）
```

---

## 📞 技术支持

**遇到问题？**

1. 查看日志：`logs\stock_screening.log`（自动创建）
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

## 🎓 推荐配置

- **浏览器**: Chrome / Edge（最新版）
- **屏幕**: 1920x1080 或更高
- **网络**: 宽带连接

---

## 📝 开发信息

- **版本**: 2.0.0
- **数据源**: AKShare (2025-10-12 升级)
- **Python**: 3.11+
- **Web框架**: FastAPI + Uvicorn

祝您使用愉快！🎉

