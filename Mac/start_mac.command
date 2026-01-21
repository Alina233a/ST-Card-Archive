#!/bin/bash

# 进入当前脚本所在的目录 (Mac 必须这行，否则找不到文件)
cd "$(dirname "$0")"

echo "========================================"
echo "      ST-Card-Archive 启动助手"
echo "========================================"

# 检查 Python 环境并安装依赖
echo "正在检查环境..."

if command -v python3 &> /dev/null; then
    # 如果有 python3 (Mac默认都有)
    echo "正在安装/更新依赖库..."
    pip3 install -r requirements.txt
    
    echo "正在启动程序..."
    echo "请勿关闭此黑色窗口，关闭会导致程序退出。"
    python3 app.py
else
    # 备用方案
    echo "正在安装/更新依赖库..."
    pip install -r requirements.txt
    
    echo "正在启动程序..."
    python app.py
fi