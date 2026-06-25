import argparse
import math
import re
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter


DEFAULT_INPUT = Path.home() / "Desktop" / "pdf"
DEFAULT_OUTPUT = Path.home() / "Desktop" / "pdf_split"
DEFAULT_SPLIT_THRESHOLD = 250
DEFAULT_PAGES_PER_PART = 200
OLD_PART_PATTERN = re.compile(
    r"^(?P<stem>.+)_part(?P<number>\d{3})_pages\d{4}-\d{4}\.pdf$",
    re.IGNORECASE,
)


def part_path(output_dir, source, part_number):
    return output_dir / source.stem / f"{source.stem}_{part_number}.pdf"


def organize_existing_parts(output_dir):
    moved = []
    if not output_dir.exists():
        return moved

    for old_path in sorted(output_dir.glob("*.pdf")):
        match = OLD_PART_PATTERN.match(old_path.name)
        if not match:
            continue
        stem = match.group("stem")
        part_number = int(match.group("number"))
        target_dir = output_dir / stem
        target_path = target_dir / f"{stem}_{part_number}.pdf"
        target_dir.mkdir(parents=True, exist_ok=True)

        if target_path.exists():
            if target_path.stat().st_size == old_path.stat().st_size:
                old_path.unlink()
                moved.append(target_path)
                continue
            raise FileExistsError(f"目标文件已存在且内容大小不同：{target_path}")

        old_path.replace(target_path)
        moved.append(target_path)

    return moved


def output_is_complete(path, expected_pages):
    if not path.exists():
        return False
    try:
        return len(PdfReader(str(path)).pages) == expected_pages
    except Exception:
        return False


def split_pdf(source, output_dir, pages_per_part, split_threshold=DEFAULT_SPLIT_THRESHOLD):
    reader = PdfReader(str(source))
    total_pages = len(reader.pages)
    if total_pages <= split_threshold:
        return total_pages, []

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    part_count = math.ceil(total_pages / pages_per_part)

    for part_index in range(part_count):
        start_page = part_index * pages_per_part
        end_page = min(start_page + pages_per_part, total_pages)
        output_path = part_path(output_dir, source, part_index + 1)
        expected_pages = end_page - start_page

        if output_is_complete(output_path, expected_pages):
            print(
                f"  [{part_index + 1}/{part_count}] 已存在："
                f"{output_path.name}（{expected_pages} 页）"
            )
            outputs.append(output_path)
            continue

        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = output_path.with_suffix(".pdf.tmp")
        writer = PdfWriter()
        for page_index in range(start_page, end_page):
            writer.add_page(reader.pages[page_index])
        with temporary_path.open("wb") as output_file:
            writer.write(output_file)
        temporary_path.replace(output_path)
        outputs.append(output_path)
        print(
            f"  [{part_index + 1}/{part_count}] 完成："
            f"{output_path.name}（{expected_pages} 页）"
        )

    return total_pages, outputs


def parse_args():
    parser = argparse.ArgumentParser(
        description="扫描 PDF 页数，并将超过指定页数的文件无损拆分。"
    )
    parser.add_argument("input_dir", nargs="?", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("output_dir", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_SPLIT_THRESHOLD,
        help="超过此页数才拆分（默认 250）",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=DEFAULT_PAGES_PER_PART,
        help="每个分卷的最大页数（默认 200）",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    input_dir = args.input_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()

    if not input_dir.is_dir():
        print(f"输入目录不存在：{input_dir}")
        return 2
    if args.pages < 1:
        print("--pages 必须大于 0")
        return 2
    if args.threshold < 1:
        print("--threshold 必须大于 0")
        return 2

    pdfs = sorted(input_dir.glob("*.pdf"), key=lambda path: path.name.casefold())
    if not pdfs:
        print(f"没有找到 PDF：{input_dir}")
        return 1

    moved = organize_existing_parts(output_dir)
    if moved:
        print(f"已整理 {len(moved)} 个旧分卷到各自文件夹。\n")

    print(
        f"扫描 {len(pdfs)} 份 PDF；超过 {args.threshold} 页时拆分，"
        f"每卷最多 {args.pages} 页"
    )
    print(f"输出目录：{output_dir}\n")
    split_count = 0
    part_count = 0
    failures = []

    for index, pdf_path in enumerate(pdfs, start=1):
        print(f"[{index}/{len(pdfs)}] 检测：{pdf_path.name}")
        try:
            total_pages, outputs = split_pdf(
                pdf_path,
                output_dir,
                args.pages,
                args.threshold,
            )
            if outputs:
                print(f"  共 {total_pages} 页，已拆为 {len(outputs)} 个分卷")
            else:
                print(f"  共 {total_pages} 页，无需拆分")
            if outputs:
                split_count += 1
                part_count += len(outputs)
        except Exception as exc:
            failures.append(pdf_path)
            print(f"  失败：{exc}")

    print(
        f"\n完成：拆分 {split_count} 份大 PDF，生成或确认 {part_count} 个分卷；"
        f"失败 {len(failures)} 份。"
    )
    print("原始 PDF 未修改。")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
