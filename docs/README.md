# TextCleaner

<p align="center">
  <a href="https://github.com/leon0410ss-boop/Spanish-text-cleaner/blob/main/docs/README.md">
    <img src="https://img.shields.io/badge/🇨🇳-中文-red?style=for-the-badge">
  </a>

  <a href="https://github.com/leon0410ss-boop/Spanish-text-cleaner/blob/main/docs/README_EN.md">
    <img src="https://img.shields.io/badge/🇺🇸-English-blue?style=for-the-badge">
  </a>

  <a href="https://github.com/leon0410ss-boop/Spanish-text-cleaner/blob/main/docs/README_ES.md">
    <img src="https://img.shields.io/badge/🇪🇸-Español-yellow?style=for-the-badge">
  </a>
</p>

西班牙语 OCR 文本清洗工具，主要用于清洗由 MinerU、OCR或PDF解析工具生成的Markdown文本。

当前版本：v1.2.0

## 功能简介

TextCleaner 面向西班牙语学术文本、报告、书籍等OCR结果，帮助用户自动完成常见的文本清洗工作，例如：
* 清理OCR识别后的多余空行、异常空格和格式噪声
* 西班牙语断词修复：

  跨行带连字符，例如situa-ción → situación
  跨行不带连字符，例如situa\nción → situación

  行内断词，例如geográfica → geográfica
* 恢复部分丢失的西班牙语重音，例如politica → política
* 删除脚注编号、注释编号
* 删除公式块和公式噪音
* 删除书籍/报告的前置封面、版权页、目录
* 删除参考文献、Bibliografía、Notas、附录、广告、订阅页等与正文无关的内容
* 支持拖放markdown文件进行清洗
* 支持批量处理 markdown文件
* PDF 辅助校对
* 拆分大型pdf文件
* 形符数统计

## 暂未开放的功能

* 自动批量调用MInerU解析pdf文件

该功能目前仍存在已知问题，当前版本建议先手动使用MinerU解析PDF，再将生成的Markdown文件放入output/mineru_raw/中进行清洗

## 适用场景

本工具适合以下使用场景：
* 西班牙语PDF文献OCR后的文本清洗
* MinerU 解析结果的二次整理
* 语料库建设前的Markdown预处理
* 学术文本、行业报告、书籍等资料的批量清洗

## 安装与使用

首次安装请把项目文件夹中唯一的zip解压至程序目录中

- macOS：首次运行 `1_首次安装_macOS.command`，之后把文件拖到 `TextCleaner.app`。
- Windows：首次运行 `1_首次安装_Windows.bat`，之后把文件拖到 `2_拖放清洗_Windows.bat`。

源码运行：

```bash
python3 -m pip install -r requirements.txt
python3 "textcleaner V1.2.py"
```

## 常用入口


- 双击 `拆分大PDF.command`：把超过 250 页的 PDF 按每卷 200 页拆分到桌面 `pdf_split/`
- 双击 `TextCleaner.app`：清洗拖入的 Markdown
- 运行 `textcleaner V1.2.py`：清洗 `output/mineru_raw/` 中的 Markdown

## 目录

- `data/`：停用短语和候选词
- `docs/`：项目文档与使用说明
- `tests/`：自动测试
- `output/`：TextCleaner 的输入、输出和日志

## 测试

```bash
python3 -m pytest
```

## 更多说明请查看：

- `docs/README.md`
- `docs/PDF拆分使用说明.txt`
- `docs/拖放程序使用说明.txt`

# 注意事项

* 本工具主要针对西班牙语OCR文本设计，其他语言文本需要自行调整规则。
* OCR 结果质量会影响最终清洗效果。
* 建议在批量处理前，先用少量文件进行测试。
* 清洗后的文本仍建议人工检查，测试发现有误删情况发生，尤其是用于学术研究或语料库建设时。
