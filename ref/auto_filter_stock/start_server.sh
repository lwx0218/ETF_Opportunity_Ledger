#!/bin/bash

# 自动筛选强势股 - 服务器启动脚本
# Auto Filter Stock - Server Startup Script

echo "=========================================="
echo "  自动筛选强势股 - 可视化报告系统"
echo "  Auto Filter Stock - Visualization System"
echo "=========================================="
echo ""

# 检查Python环境
if ! command -v python &> /dev/null; then
    echo "❌ 错误: 未找到Python，请先安装Python 3.11+"
    exit 1
fi

PYTHON_VERSION=$(python --version 2>&1 | awk '{print $2}')
echo "✅ Python版本: $PYTHON_VERSION"
echo ""

# 检查依赖
echo "📦 检查依赖..."
REQUIRED_PACKAGES=("fastapi" "uvicorn" "pandas" "plotly" "pywencai")
MISSING_PACKAGES=()

for package in "${REQUIRED_PACKAGES[@]}"; do
    if ! python -c "import $package" 2>/dev/null; then
        MISSING_PACKAGES+=("$package")
    fi
done

if [ ${#MISSING_PACKAGES[@]} -gt 0 ]; then
    echo "⚠️  缺少以下依赖包: ${MISSING_PACKAGES[*]}"
    echo "   请运行: pip install ${MISSING_PACKAGES[*]}"
    echo ""
    read -p "是否现在安装? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        pip install "${MISSING_PACKAGES[@]}"
    else
        echo "❌ 已取消启动"
        exit 1
    fi
fi

echo "✅ 所有依赖已安装"
echo ""

# 加载 .env 文件中的环境变量
if [ -f .env ]; then
    echo "📄 加载 .env 文件..."
    set -a  # 自动导出所有变量
    source .env
    set +a
    echo "✅ 环境变量已加载"
fi

# 设置环境变量
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"

# 获取配置
HOST="${API_HOST:-0.0.0.0}"
PORT="${API_PORT:-8000}"

echo "🚀 启动服务器..."
echo "   主机: $HOST"
echo "   端口: $PORT"
echo ""
echo "📊 访问方式:"
echo "   主页 (可视化):    http://localhost:$PORT/"
echo "   API文档:          http://localhost:$PORT/docs"
echo "   健康检查:         http://localhost:$PORT/api/system/health"
echo ""
echo "🔧 API端点:"
echo "   筛选股票:         POST http://localhost:$PORT/api/screening/run"
echo "   查看结果:         GET  http://localhost:$PORT/api/screening/results/{session_id}"
echo "   股票详情:         GET  http://localhost:$PORT/api/stocks/{symbol}/details"
echo "   K线图:            GET  http://localhost:$PORT/api/stocks/{symbol}/chart/kline"
echo "   参数管理:         GET  http://localhost:$PORT/api/parameters"
echo ""
echo "💡 提示:"
echo "   - 按 Ctrl+C 停止服务器"
echo "   - 查看日志: tail -f logs/stock_screening.log"
echo "   - 测试API: curl http://localhost:$PORT/api/system/health"
echo ""
echo "=========================================="
echo ""

# 启动服务器
python main.py

# 如果服务器异常退出
if [ $? -ne 0 ]; then
    echo ""
    echo "❌ 服务器启动失败"
    echo "   请检查日志: logs/stock_screening.log"
    exit 1
fi

