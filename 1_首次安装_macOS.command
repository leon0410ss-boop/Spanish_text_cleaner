#!/bin/zsh

cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
    echo "未检测到 Python 3。请先安装 Python 3，再重新运行本文件。"
    read -r "?按回车键关闭窗口。"
    exit 1
fi

echo "正在创建运行环境，请稍候……"
python3 -m venv .venv || exit 1
".venv/bin/python" -m pip install --upgrade pip || exit 1
".venv/bin/python" -m pip install -r requirements.txt || exit 1

echo
echo "安装完成。今后请把文件拖到 TextCleaner.app 图标上。"
read -r "?按回车键关闭窗口。"
