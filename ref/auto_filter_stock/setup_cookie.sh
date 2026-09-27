#!/bin/bash

echo "======================================"
echo "同花顺问财 Cookie 配置工具"
echo "======================================"
echo ""
echo "请按照以下步骤获取Cookie："
echo ""
echo "1. 打开浏览器访问: https://www.iwencai.com/"
echo "2. 登录您的同花顺账号"
echo "3. 按 F12 打开开发者工具"
echo "4. 切换到 Network (网络) 标签"
echo "5. 在问财搜索框输入任意内容并搜索"
echo "6. 在Network中找到请求，查看 Headers"
echo "7. 复制完整的 Cookie 值"
echo ""
echo "详细图文教程请查看: COOKIE_SETUP.md"
echo ""
echo "======================================"
echo ""
read -p "请粘贴您复制的Cookie (按回车结束): " cookie

if [ -z "$cookie" ]; then
    echo ""
    echo "❌ Cookie不能为空！"
    exit 1
fi

# 创建或更新 .env 文件
if [ -f .env ]; then
    # 如果存在，更新Cookie行
    if grep -q "PYWENCAI_COOKIE=" .env; then
        # Mac和Linux的sed语法不同，做兼容处理
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s|^PYWENCAI_COOKIE=.*|PYWENCAI_COOKIE=$cookie|" .env
        else
            sed -i "s|^PYWENCAI_COOKIE=.*|PYWENCAI_COOKIE=$cookie|" .env
        fi
        echo ""
        echo "✅ .env 文件已更新"
    else
        echo "" >> .env
        echo "PYWENCAI_COOKIE=$cookie" >> .env
        echo ""
        echo "✅ Cookie已添加到 .env 文件"
    fi
else
    # 如果不存在，创建新文件
    cp .env.example .env
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|^PYWENCAI_COOKIE=.*|PYWENCAI_COOKIE=$cookie|" .env
    else
        sed -i "s|^PYWENCAI_COOKIE=.*|PYWENCAI_COOKIE=$cookie|" .env
    fi
    echo ""
    echo "✅ .env 文件已创建并配置Cookie"
fi

echo ""
echo "======================================"
echo "配置完成！"
echo "======================================"
echo ""
echo "下一步："
echo "1. 重启服务器以使配置生效"
echo "2. 运行: ./start_server.sh"
echo "   或者: python -m uvicorn src.api.app:app --reload"
echo ""
