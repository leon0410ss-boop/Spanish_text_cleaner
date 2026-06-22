# config.py
from pathlib import Path

# ── 目录结构 ──────────────────────────────────────────────
#
# textcleaner/
# ├── config.py
# ├── textcleaner.py
# ├── data/
# │   └── stop_phrases.txt
# ├── output/
# │   ├── mineru_raw/   ← 放入待清洗的 Markdown（可按文档分子文件夹）
# │   │   ├── doc_a/
# │   │   │   ├── doc_a.md
# │   │   │   ├── images/
# │   │   │   └── ...
# │   │   └── doc_b/
# │   │       └── ...
# │   ├── cleaned/      ← 清洗后的 md 和删除内容 log
# │   │   ├── doc_a.clean.md
# │   │   ├── doc_a.clean.deletions.log
# │   │   └── doc_b.clean.md
# │   └── review_logs/  ← 需要人工检查的清洗 review log

BASE_DIR = Path(__file__).parent         # config.py所在目录

STOP_PHRASES_FILE = BASE_DIR / "data" / "stop_phrases.txt"

MINERU_OUT = BASE_DIR / "output" / "mineru_raw"    # 待清洗 Markdown
CLEAN_OUT = BASE_DIR / "output" / "cleaned"        # 清洗后输出
REVIEW_LOG_OUT = BASE_DIR / "output" / "review_logs"  # 人工检查日志
PDF_RAW = BASE_DIR / "output" / "pdf_raw"          # 可选：原始 PDF，用于辅助校对
