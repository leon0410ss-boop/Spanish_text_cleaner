#!/usr/bin/env python3
import argparse
import json
import subprocess
import tempfile
import unicodedata
from pathlib import Path


DEFAULT_INPUT = Path.home() / "Desktop" / "打包"
JOINERS = {"'", "’", "ʼ", "-", "‐", "‑", "‒", "–", "—"}


def is_word_char(char):
    category = unicodedata.category(char)
    return category[0] in {"L", "N"} or category[0] == "M"


def word_like_count(text):
    text = unicodedata.normalize("NFC", text)
    count = 0
    in_word = False

    for index, char in enumerate(text):
        if is_word_char(char):
            if not in_word:
                count += 1
                in_word = True
            continue

        next_char = text[index + 1] if index + 1 < len(text) else ""
        if char in JOINERS and in_word and next_char and is_word_char(next_char):
            continue

        in_word = False

    return count


def collect_markdown_files(path):
    if path.is_file():
        if path.suffix.lower() != ".md":
            raise ValueError(f"不是 Markdown 文件：{path}")
        return [path]

    if not path.is_dir():
        raise ValueError(f"路径不存在：{path}")

    return sorted(p for p in path.rglob("*.md") if p.is_file())


def default_output_path(input_path):
    if input_path.is_file():
        return input_path.with_suffix(".word_count.txt")
    return input_path.parent / f"{input_path.name}_单词数统计.txt"


def fast_word_like_counts(markdown_files):
    return [word_like_count(md_file.read_text(encoding="utf-8")) for md_file in markdown_files]


def convert_to_docx(markdown_files, temp_dir):
    docx_paths = []
    for index, md_file in enumerate(markdown_files, start=1):
        docx_path = temp_dir / f"{index:05d}.docx"
        subprocess.run(
            ["textutil", "-convert", "docx", "-output", str(docx_path), str(md_file)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        docx_paths.append(docx_path)
    return docx_paths


def word_counts_with_microsoft_word(docx_paths):
    paths_json = json.dumps([str(path) for path in docx_paths], ensure_ascii=False)
    script = f"""
const Word = Application('Microsoft Word');
const paths = {paths_json};
const counts = [];

function findDocument(path) {{
  for (let index = 0; index < Word.documents.length; index++) {{
    const doc = Word.documents[index];
    try {{
      if (doc.posixFullName() === path) {{
        return doc;
      }}
    }} catch (error) {{}}
  }}
  return Word.documents[0];
}}

for (const path of paths) {{
  Word.open(Path(path));
  delay(0.5);
  const doc = findDocument(path);
  counts.push(String(doc.computeStatistics()));
  doc.close({{saving: 'no'}});
}}

counts.join('\\n');
"""
    result = subprocess.run(
        ["osascript", "-l", "JavaScript"],
        input=script,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Microsoft Word 统计失败")

    counts = [int(line.strip()) for line in result.stdout.splitlines() if line.strip()]
    if len(counts) != len(docx_paths):
        raise RuntimeError(f"Microsoft Word 返回了 {len(counts)} 个结果，但需要 {len(docx_paths)} 个")
    return counts


def exact_word_counts(markdown_files):
    with tempfile.TemporaryDirectory() as temp:
        temp_dir = Path(temp)
        docx_paths = convert_to_docx(markdown_files, temp_dir)
        return word_counts_with_microsoft_word(docx_paths)


def write_report(markdown_files, input_path, output_path, counts):
    rows = []
    for md_file, count in zip(markdown_files, counts):
        display_name = md_file.relative_to(input_path) if input_path.is_dir() else md_file.name
        rows.append((str(display_name), count))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as report:
        report.write("文件名\t单词数\n")
        for name, count in rows:
            report.write(f"{name}\t{count}\n")

    return rows


def main():
    parser = argparse.ArgumentParser(description="统计 Markdown 文件的 Word-like 单词数")
    parser.add_argument(
        "path",
        nargs="?",
        default=str(DEFAULT_INPUT),
        help="要统计的 md 文件或文件夹，默认统计桌面/打包",
    )
    parser.add_argument("-o", "--output", help="输出 txt 路径，默认写到输入文件夹同级")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="使用纯 Python 快速估算；默认调用 Microsoft Word 做精确统计",
    )
    args = parser.parse_args()

    input_path = Path(args.path).expanduser()
    output_path = Path(args.output).expanduser() if args.output else default_output_path(input_path)
    markdown_files = collect_markdown_files(input_path)
    counts = fast_word_like_counts(markdown_files) if args.fast else exact_word_counts(markdown_files)
    rows = write_report(markdown_files, input_path, output_path, counts)

    print(f"已统计 {len(rows)} 个 Markdown 文件")
    print(f"输出：{output_path}")


if __name__ == "__main__":
    main()
