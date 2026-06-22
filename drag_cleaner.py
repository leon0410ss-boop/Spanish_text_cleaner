import importlib.util
import re
import sys
from pathlib import Path

from config import CLEAN_OUT, REVIEW_LOG_OUT, PDF_RAW, STOP_PHRASES_FILE


PROJECT_ROOT = Path(__file__).resolve().parent
CLEANER_PATH = PROJECT_ROOT / "textcleaner V1.2.py"


def load_cleaner():
    spec = importlib.util.spec_from_file_location("textcleaner_v1_2", CLEANER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect_files(paths):
    markdown_files = []
    pdf_files = []

    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if path.is_dir():
            markdown_files.extend(sorted(path.rglob("*.md")))
            pdf_files.extend(sorted(path.rglob("*.pdf")))
        elif path.suffix.lower() == ".md":
            markdown_files.append(path)
        elif path.suffix.lower() == ".pdf":
            pdf_files.append(path)

    return unique_paths(markdown_files), unique_paths(pdf_files)


def unique_paths(paths):
    unique = []
    seen = set()
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def match_pdfs(cleaner, md_path, pdf_files):
    md_keys = {
        cleaner.simplify_match_key(md_path.stem),
        cleaner.simplify_match_key(md_path.parent.name),
    }
    matches = []
    for pdf_path in pdf_files:
        part_stem = re.sub(
            r'[_\-\s]+(?:part|parte)?\d+$',
            '',
            pdf_path.stem,
            flags=re.IGNORECASE,
        )
        if (
            cleaner.simplify_match_key(pdf_path.stem) in md_keys
            or cleaner.simplify_match_key(pdf_path.parent.name) in md_keys
            or cleaner.simplify_match_key(part_stem) in md_keys
        ):
            matches.append(pdf_path)
    return matches or cleaner.find_matching_pdfs(md_path, PDF_RAW)


def output_path_for(md_path, duplicate_stems):
    stem = md_path.stem
    if stem in duplicate_stems:
        stem = f"{md_path.parent.name}__{stem}"
    return CLEAN_OUT / f"{stem}.clean.md"


def main(paths):
    cleaner = load_cleaner()
    markdown_files, dropped_pdfs = collect_files(paths)
    if not markdown_files:
        print("没有找到 Markdown 文件。请拖入 md 文件，或包含 md 的文件夹。")
        return 1

    CLEAN_OUT.mkdir(parents=True, exist_ok=True)
    REVIEW_LOG_OUT.mkdir(parents=True, exist_ok=True)
    stop_phrases = (
        cleaner.load_stop_phrases(STOP_PHRASES_FILE)
        if STOP_PHRASES_FILE.exists()
        else set()
    )

    stem_counts = {}
    for md_path in markdown_files:
        stem_counts[md_path.stem] = stem_counts.get(md_path.stem, 0) + 1
    duplicate_stems = {stem for stem, count in stem_counts.items() if count > 1}

    completed = []
    deleted_pdfs = []
    warnings = []
    failures = []

    for md_path in markdown_files:
        try:
            pdf_paths = match_pdfs(cleaner, md_path, dropped_pdfs)
            pdf_text = None
            if pdf_paths:
                try:
                    pdf_text = "\n".join(
                        cleaner.extract_pdf_text(path) for path in pdf_paths
                    )
                except RuntimeError as exc:
                    warnings.append(f"{md_path.name}: PDF读取失败，已仅使用md清洗")
                    cleaner.logger.warning(str(exc))
            else:
                warnings.append(f"{md_path.name}: 未找到同名PDF，已仅使用md清洗")

            output_path = output_path_for(md_path, duplicate_stems)
            cleaner.clean_markdown_file(
                md_path,
                output_path,
                pdf_text=pdf_text,
                review_log_dir=REVIEW_LOG_OUT,
                stop_phrases=stop_phrases,
                keep_footnote_numbers=False,
            )
            deleted_pdfs.extend(
                cleaner.delete_pdf_files(
                    cleaner.pdfs_to_delete_after_clean(md_path, pdf_paths)
                )
            )
            completed.append(output_path.name)
        except Exception as exc:
            failures.append(f"{md_path.name}: {exc}")

    print(f"处理完成：{len(completed)} 个文件")
    print(f"输出位置：{CLEAN_OUT}")
    if deleted_pdfs:
        print(f"已删除对应PDF：{len(deleted_pdfs)} 个")
    if warnings:
        print(f"提示：{len(warnings)} 个文件未使用PDF辅助")
    if failures:
        print(f"失败：{len(failures)} 个文件")
        for failure in failures[:5]:
            print(failure)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
