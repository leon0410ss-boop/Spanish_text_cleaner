import difflib
import re
import argparse
import logging
import subprocess
import unicodedata
from pathlib import Path
from config import MINERU_OUT, CLEAN_OUT, PDF_RAW, STOP_PHRASES_FILE

# 配置日志系统
def setup_logging():
    """配置日志，同时输出到文件和控制台"""
    log_dir = Path(__file__).parent / "output"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "run.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

# 初始化日志
logger = setup_logging()

# 使用wordfreq库
try:
    from wordfreq import zipf_frequency
    WORDFREQ_AVAILABLE = True
except ImportError:
    WORDFREQ_AVAILABLE = False
    zipf_frequency = None
    raise RuntimeError(
        "wordfreq 未安装，请激活textclean虚拟环境"
    )

def load_stop_phrases(path):
    stop_phrases = set()
    if path:
        with open(path, encoding='utf-8') as f:
            for line in f:
                phrase = line.strip().lower()
                if phrase:
                    stop_phrases.add(phrase)
    return stop_phrases

def protect_html_tables(text):
    tables = []

    def replace_table(match):
        tables.append(match.group(0))
        return f"@@HTML_TABLE_{len(tables) - 1}@@"

    protected = re.sub(
        r'<table\b.*?</table>',
        replace_table,
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return protected, tables

def restore_html_tables(text, tables):
    for index, table in enumerate(tables):
        table = re.sub(r"(?<=\d)\s+%", "%", table.strip())
        text = text.replace(f"@@HTML_TABLE_{index}@@", table)
    return text

def is_image_line(line):
    return bool(re.match(r'^\s*!\[.*\]\(.*\)\s*$', line)) or bool(re.search(r'<img\s', line, re.IGNORECASE))

def is_note_or_source_line(line):
    return bool(re.match(r'^\s*(?:fuente|source|nota|note)\s*[:.]', line, re.IGNORECASE))

def is_soft_text_line(line):
    stripped = line.strip()
    if not stripped:
        return False
    if is_markdown_heading(stripped) or is_image_line(stripped) or is_note_or_source_line(stripped):
        return False
    if should_drop_metadata_line(stripped) or is_reference_heading(stripped):
        return False
    if re.search(r'^</?\w+|@@HTML_TABLE_\d+@@', stripped, re.IGNORECASE):
        return False
    return True

def line_needs_continuation(line):
    stripped = line.strip()
    return is_soft_text_line(stripped) and not re.search(r'[.!?。！？]\s*(?:["»”)\]]+)?$', stripped)

def split_author_affiliation_lines(text):
    institution_patterns = [
        r'\bUniversidad\b',
        r'\bUniversitat\b',
        r'\bUniversity\b',
        r'\bInstitute\b',
        r'\bInstituto\b',
        r'\bCollege\b',
        r'\bSchool\b',
        r'\bCentre\b',
        r'\bCenter\b',
        r'\bFundaci[oó]n\b',
        r'\bHydrogen Europe\b',
    ]
    institution_re = re.compile('|'.join(institution_patterns), re.IGNORECASE)
    named_institution_re = re.compile(
        r'\b([A-ZÁÉÍÓÚÜÑ][\wÁÉÍÓÚÜÑáéíóúüñ-]+\s+)'
        r'(?=(?:University|Institute|College|School|Centre|Center)\b)'
    )
    split_lines = []

    for line in text.splitlines():
        stripped = line.strip()
        if (
            not stripped
            or len(stripped) > 220
            or is_markdown_heading(stripped)
            or re.search(r'[.!?;:]\s*$', stripped)
        ):
            split_lines.append(line)
            continue

        match = institution_re.search(stripped)
        if not match or match.start() == 0:
            split_lines.append(line)
            continue

        split_at = match.start()
        named_match = named_institution_re.search(stripped[:match.end()])
        if named_match and named_match.start() > 0:
            split_at = named_match.start()

        author = stripped[:split_at].strip()
        affiliation = stripped[split_at:].strip()
        if len(author.split()) < 2 or not affiliation:
            split_lines.append(line)
            continue

        # The temporary blank keeps the byline boundary intact during reflow.
        # Final normalization removes blank lines but preserves the line break.
        split_lines.extend([author, '', affiliation])

    return "\n".join(split_lines)

def reflow_soft_line_breaks(text):
    lines = text.splitlines()
    reordered = []
    index = 0

    while index < len(lines):
        line = lines[index]
        if line_needs_continuation(line):
            float_index = index + 1
            float_lines = []
            while float_index < len(lines):
                candidate = lines[float_index]
                if not candidate.strip():
                    break
                if is_image_line(candidate) or is_note_or_source_line(candidate):
                    float_lines.append(candidate)
                    float_index += 1
                    continue
                break
            if float_lines and float_index < len(lines) and is_soft_text_line(lines[float_index]):
                reordered.append(f"{line.rstrip()} {lines[float_index].lstrip()}")
                reordered.extend(float_lines)
                index = float_index + 1
                continue
        reordered.append(line)
        index += 1

    lines = reordered
    merged = []
    index = 0
    while index < len(lines):
        line = lines[index]
        while line_needs_continuation(line):
            next_index = index + 1
            if next_index >= len(lines) or not is_soft_text_line(lines[next_index]):
                break
            line = f"{line.rstrip()} {lines[next_index].lstrip()}"
            index = next_index
        merged.append(line)
        index += 1

    return "\n".join(merged)

def remove_annotation_stars(line):
    line = re.sub(r'\\?\*+', '', line)
    return re.sub(r'\s{2,}', ' ', line).strip()

def remove_formula_blocks(text):
    text = re.sub(r'\$\$.*?\$\$', '', text, flags=re.DOTALL)
    text = re.sub(r'\\\[.*?\\\]', '', text, flags=re.DOTALL)
    text = re.sub(r'\\\(.*?\\\)', '', text, flags=re.DOTALL)
    text = re.sub(r'\$[^$\n]*(?:\\|[_{}^=])[^$\n]*\$', '', text)

    def remove_short_formula(match):
        body = match.group(1).strip()
        if len(body) > 24:
            return match.group(0)
        if re.fullmatch(r'[A-Za-zÁÉÍÓÚÜÑáéíóúüñ](?:\s*[.;,])?', body):
            return ''
        if re.search(r'\b[A-Za-z]\b', body) and re.search(r"[,+\-*/=<>\u2264\u2265′']", body):
            return ''
        return match.group(0)

    text = re.sub(r'\$([^$\n]{1,120})\$', remove_short_formula, text)
    return re.sub(r'^\s*#{0,6}\s*\$[^$]*\\[^$]*\$\s*$', '', text, flags=re.MULTILINE)

def remove_formula_noise(line):
    if is_image_line(line) or re.search(r'<table\b|</table>|<tr\b|<td\b|@@HTML_TABLE_\d+@@', line, re.IGNORECASE):
        return line
    if re.search(r'(?:∑|\\(?:mathsf|sum|frac|cdot)|[_^{}])', line):
        titleless = strip_markdown_heading(line)
        letters = len(re.findall(r'[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]', titleless))
        formula_marks = len(re.findall(r'(?:∑|\\(?:mathsf|sum|frac|cdot)|[_^{}=])', titleless))
        if formula_marks >= 4 and letters < 40:
            return ''
    line = re.sub(r'∑\S*', '', line)
    line = re.sub(r'\S*\\(?:mathsf|sum|frac|cdot|left|right)\S*', '', line)
    line = re.sub(r'\S*[_^{}]\S*', '', line)
    line = re.sub(r'\S*[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]\d*[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]*=\S*', '', line)
    letters = r'A-Za-zÁÉÍÓÚÜÑáéíóúüñ'
    line = re.sub(rf'\b([{letters}]{{4,}})-\s+([{letters}]{{1,4}})\b', r'\1\2', line)
    return re.sub(r'\s{2,}', ' ', line).strip()

def strip_markdown_heading(line):
    return re.sub(r'^\s{0,3}#{1,6}\s*', '', line).strip()

def is_markdown_heading(line):
    return bool(re.match(r'^\s{0,3}#{1,6}\s+\S', line))

def markdown_heading_level(line):
    match = re.match(r'^\s{0,3}(#{1,6})\s+\S', line)
    return len(match.group(1)) if match else 0

def normalized_heading_text(line):
    title = strip_markdown_heading(line)
    title = unicodedata.normalize('NFKC', title)
    title = re.sub(r'[*.:：\s]+$', '', title).strip().lower()
    return title

def is_publication_metadata_line(line):
    title = normalized_heading_text(line)
    return bool(re.match(
        r'^(?:e-)?issn\b|^(?:e-)?nipo\b|^dl\b|^pvp\b|^ecpmineco\b|'
        r'^fecyt-\d+\b|^cat[aá]logo\s+general\s+de\s+publicaciones\s+oficiales\b',
        title,
    ))

def is_issue_front_matter(lines, scan_limit):
    front_text = "\n".join(strip_markdown_heading(line).lower() for line in lines[:scan_limit])
    has_issue_identity = bool(re.search(
        r'informaci[oó]n\s+comercial\s+espa[ñn]ola|cuadernos\s+econ[oó]micos',
        front_text,
    ))
    has_editorial_metadata = any(
        is_publication_metadata_line(line)
        or re.search(
            r'\b(consejo\s+editorial|direcci[oó]n\s+ejecutiva|jefe\s+de\s+redacci[oó]n|'
            r'edici[oó]n\s+y\s+redacci[oó]n|distribuci[oó]n)\b',
            strip_markdown_heading(line).lower(),
        )
        for line in lines[:scan_limit]
    )
    return has_issue_identity and has_editorial_metadata

def first_issue_body_heading_index(lines, scan_limit):
    for index, line in enumerate(lines[:scan_limit]):
        if not is_markdown_heading(line):
            continue
        title = normalized_heading_text(line)
        if title == 'presentación':
            return index
        if markdown_heading_level(line) == 1 and title.startswith('presentación '):
            return index
    return None

def is_reference_heading(line, line_index=0, total_lines=0):
    title = strip_markdown_heading(line)
    title = re.sub(r'[*.:：\s]+$', '', title).strip()
    lower = title.lower()

    if re.search(r'\.{2,}\s*\d+\s*$', lower):
        return False
    if re.search(r'\s+\d{1,4}\s*$', lower) and not is_markdown_heading(line):
        return False

    reference_title = re.match(
        r'^(referencias(?:\s+bibliogr[aá]ficas?)?|bibliograf[ií]a|bibliographic\s+references|references|notas(?:\s+al\s+final)?|notes)\b',
        lower,
    )
    if not reference_title:
        return False

    if is_markdown_heading(line):
        return True

    # Some MinerU book outputs lose heading markers in back matter.
    return total_lines and line_index > total_lines * 0.15 and len(title) <= 32

def is_backmatter_heading(line, line_index=0, total_lines=0):
    title = normalized_heading_text(line)
    backmatter_match = re.match(
        r'^(aviso\s+legal|glosario(?:\s+de\s+t[eé]rminos)?|'
        r'normas\s+de\s+publicaci[oó]n|instrucciones\s+para\s+autores|formato\s+y\s+ejemplos|'
        r'[ií]ndice\s+general|[ií]ndice\s+anal[ií]tico|colof[oó]n|cr[eé]ditos\s+de\s+im[aá]genes|'
        r'sobre\s+el\s+autor|sobre\s+la\s+autora|acerca\s+del\s+autor|legal|'
        r'economistas|suscr[ií]bete\s+a\s+(?:la|nuestra)\s+newsletter|'
        r'informaci[oó]n\s+comercial\s+espa[ñn]ola\.\s+revista\s+de\s+econom[ií]a|'
        r'informaci[oó]n\s+comercial\s+espa[ñn]ola\s+secretar[ií]a\s+de\s+estado\s+de\s+comercio|'
        r'consejo\s+editorial|director|direcci[oó]n\s+ejecutiva|jefe\s+de\s+redacci[oó]n|'
        r'edici[oó]n\s+y\s+redacci[oó]n|'
        r'contenidos\s+del\s+pr[oó]ximo\s+n[uú]mero|desde\s+1983|'
        r'serie\s+hist[oó]rica(?:\s+del\s+bolet[ií]n\s+econ[oó]mico\s+de\s+ice)?|'
        r'cuadernos\s+econ[oó]micos(?:\s+de\s+ice)?|'
        r'informes\s+mensuales\s+de\s+comercio\s+exterior|'
        r'encuesta\s+de\s+coyuntura\s+de\s+la\s+exportaci[oó]n|'
        r'[¡!]?nuevas\s+opciones\s+de\s+lectura\s+y\s+descarga\s+disponibles|'
        r'[¿?]?te\s+perdiste\s+alg[uú]n\s+n[uú]mero|'
        r'evaluadores\s+externos\s+que\s+han\s+participado|'
        r'\d+(?:\.\d+)*\.\s+t[ií]tulo\s+del\s+apartado|libro|cap[ií]tulo\s+de\s+libro|'
        r'publicaciones\s+peri[oó]dicas|informe\s+oficial\s+en\s+web|working\s+paper|'
        r'peri[oó]dico\s+en\s+l[ií]nea|ley/reglamento|'
        r'orden\s+de\s+la\s+lista\s+de\s+referencias\s+bibliogr[aá]ficas|'
        r'p[aá]gina\s+web|(?:•\s*)?formato\s+y\s+ejemplos\s+de\s+las\s+referencias|'
        r'[uú]ltimos\s+n[uú]meros\s+publicados|n[uú]meros\s+en\s+preparaci[oó]n|'
        r'n[uú]m\.\s+\d+)\b',
        title,
    )
    if backmatter_match:
        is_exact_title = not title[backmatter_match.end():].strip()
        is_known_promotional_prefix = bool(re.match(
            r'^(?:suscr[ií]bete\s+a\s+(?:la|nuestra)\s+newsletter|'
            r'informaci[oó]n\s+comercial\s+espa[ñn]ola\.\s+revista\s+de\s+econom[ií]a|'
            r'[¡!]?nuevas\s+opciones\s+de\s+lectura\s+y\s+descarga\s+disponibles|'
            r'[¿?]?te\s+perdiste\s+alg[uú]n\s+n[uú]mero)',
            title,
        ))
        if not is_exact_title and not is_known_promotional_prefix:
            return False
        if is_markdown_heading(line):
            return True
        is_late_exact_title = (
            total_lines
            and line_index > total_lines * 0.15
        )
        return bool(is_late_exact_title)
    if re.fullmatch(r'anexos?', title):
        return is_markdown_heading(line) or (total_lines and line_index > total_lines * 0.15)
    if re.fullmatch(r'distribuci[oó]n', title):
        return is_markdown_heading(line) or (total_lines and line_index > total_lines * 0.15)
    if re.match(
        r'^(t[ií]tulos\s+publicados|[uú]ltimos\s+monogr[aá]ficos\s+publicados|'
        r'[uú]ltimos\s+n[uú]meros\s+publicados|n[uú]mero\s+en\s+preparaci[oó]n|'
        r'suscripci[oó]n\s+anual|ejemplares\s+sueltos|'
        r'bolet[ií]n\s+econ[oó]mico\s+de\s+informaci[oó]n\s+comercial\s+espa[ñn]ola|'
        r'cial\s+espa[ñn]olissn)\b',
        title,
    ):
        return total_lines and line_index > total_lines * 0.15
    if is_publication_metadata_line(line):
        return True
    return False

def is_frontmatter_marker(line):
    lower = strip_markdown_heading(line).lower()
    has_named_marker = bool(re.search(
        r'\b(isbn|isbne|copyright|derechos\s+reservados|dep[oó]sito\s+legal|'
        r'cr[eé]ditos\s+de\s+im[aá]genes|informaci[oó]n\s+del\s+cat[aá]logo|'
        r'todos\s+los\s+derechos\s+reservados|quedan\s+rigurosamente\s+prohibidas|'
        r'prohibida\s+la\s+reproducci[oó]n|fotocomposici[oó]n|dise[ñn]o\s+de\s+la\s+cubierta)\b|©',
        lower,
    ))
    has_copyright_symbol = bool(re.match(r'^©\s*\d{2,4}\b', lower))
    if '©' in lower and not has_copyright_symbol:
        has_named_marker = bool(re.search(r'\b(copyright|derechos\s+reservados)\b', lower))
    return has_named_marker or has_copyright_symbol or bool(re.match(
        r'^(thema|impreso\s+por|este\s+libro\s+ha\s+sido\s+editado|a\s+mis\s+)',
        lower,
    ))

def is_frontmatter_section_heading(line):
    title = normalized_heading_text(line)
    return bool(re.match(
        r'^(abreviaturas|perfiles\s+biogr[aá]ficos|cr[eé]ditos\s+de\s+im[aá]genes|'
        r'autores|autoras|autor|autora|editora\s+y\s+autora|autores\s+y\s+autoras|'
        r'consejo\s+editorial|director|direcci[oó]n\s+ejecutiva|jefe\s+de\s+redacci[oó]n|'
        r'edici[oó]n\s+y\s+redacci[oó]n|distribuci[oó]n|'
        r'colecci[oó]n|t[ií]tulos\s+publicados|legal)\b',
        title,
    ))

def is_toc_heading(line):
    title = strip_markdown_heading(line)
    title = re.sub(r'[*:：\s]+$', '', title).strip().lower()
    compact_title = re.sub(r'\s+', '', title)
    return bool(re.match(r'^([ií]ndice(?:\s+general)?|contenido|sumario|tabla\s+de\s+contenido)$', title)) or compact_title == 'sumario'

def is_toc_entry_line(line):
    title = strip_markdown_heading(line).strip()
    if not title:
        return True
    lower = title.lower()
    if is_toc_heading(line) or is_frontmatter_marker(line):
        return True
    if re.search(r'\.{2,}\s*\d{1,4}\s*$', title):
        return True
    if re.search(r'\s+\d{1,4}\s*$', title) and len(title) <= 160:
        return True
    if re.match(r'^(p[aá]g\.?|bibliograf[ií]a|referencias|notas|fuentes)\b', lower):
        return True
    if is_markdown_heading(line):
        return False
    if len(title) <= 90 and not re.search(r'[.!?。！？]\s*$', title):
        return True
    return False

def is_compact_toc_line(line):
    title = strip_markdown_heading(line).strip()
    if not title or is_markdown_heading(line):
        return False
    section_numbers = re.findall(r'(?<!\w)\d+(?:\.\d+)+\.?\s+', title)
    page_numbers = re.findall(
        r'\s+\d{1,4}(?=\s+\d+(?:\.\d+)+\.?\s+|$)',
        title,
    )
    return len(section_numbers) >= 3 and len(page_numbers) >= 2

def is_toc_entry_at(lines, index):
    if is_toc_entry_line(lines[index]):
        return True
    if not is_markdown_heading(lines[index]):
        return False
    next_title = ''
    for next_index in range(index + 1, min(len(lines), index + 4)):
        next_title = strip_markdown_heading(lines[next_index]).strip()
        if next_title:
            break
    return bool(next_title and len(next_title) <= 120 and re.search(r'\s+\d{1,4}\s*$', next_title))

def has_high_toc_entry_density(lines, index):
    checked = 0
    hits = 0
    for line in lines[index:index + 18]:
        title = strip_markdown_heading(line).strip()
        if not title:
            continue
        checked += 1
        if is_toc_entry_line(line) or re.match(r'^(p[aá]g\.?|p[aá]gina)\b', title.lower()):
            hits += 1
    return checked >= 6 and hits / checked >= 0.45

def first_presentation_heading_index(lines, scan_limit):
    for index, line in enumerate(lines[:scan_limit]):
        title = strip_markdown_heading(line)
        title = re.sub(r'[*.:：\s]+$', '', title).strip().lower()
        if is_markdown_heading(line) and title == 'presentación':
            return index
    return None

def remove_front_matter(text):
    lines = text.splitlines()
    if not lines:
        return text

    scan_limit = min(len(lines), 260)
    has_book_front = any(is_frontmatter_marker(line) for line in lines[:scan_limit])
    toc_indexes = [i for i, line in enumerate(lines[:scan_limit]) if is_toc_heading(line)]
    if is_issue_front_matter(lines, scan_limit):
        body_index = first_issue_body_heading_index(lines, scan_limit)
        if body_index is not None:
            return "\n".join(lines[body_index:])
    if not has_book_front and not toc_indexes:
        return text

    presentation_index = first_presentation_heading_index(lines, scan_limit)
    if presentation_index is not None:
        return "\n".join(lines[presentation_index:])

    start_index = 0
    if toc_indexes:
        i = toc_indexes[-1] + 1
        while i < len(lines) and is_toc_entry_at(lines, i):
            i += 1
        while i < len(lines) and not strip_markdown_heading(lines[i]):
            i += 1
        start_index = i
    else:
        front_indexes = [i for i, line in enumerate(lines[:scan_limit]) if is_frontmatter_marker(line)]
        start_index = front_indexes[-1] + 1 if front_indexes else 0

    while start_index < len(lines) and (
        not strip_markdown_heading(lines[start_index])
        or is_frontmatter_marker(lines[start_index])
        or is_toc_heading(lines[start_index])
    ):
        start_index += 1

    later_front_indexes = [
        i for i in range(start_index, scan_limit)
        if is_frontmatter_marker(lines[i])
    ]
    if later_front_indexes:
        start_index = later_front_indexes[-1] + 1
        while start_index < len(lines) and (
            not strip_markdown_heading(lines[start_index])
            or is_frontmatter_marker(lines[start_index])
            or is_toc_heading(lines[start_index])
        ):
            start_index += 1

    while start_index < len(lines) and is_frontmatter_section_heading(lines[start_index]):
        start_index += 1
        while start_index < len(lines) and not is_markdown_heading(lines[start_index]):
            start_index += 1

    density_limit = min(len(lines), max(scan_limit, start_index + 360))
    while start_index < density_limit and has_high_toc_entry_density(lines, start_index):
        start_index += 1
    while start_index < len(lines) and (not strip_markdown_heading(lines[start_index]) or is_toc_entry_line(lines[start_index])):
        start_index += 1
    while start_index < len(lines) and is_frontmatter_section_heading(lines[start_index]):
        start_index += 1
        while start_index < len(lines) and not is_markdown_heading(lines[start_index]):
            start_index += 1

    return "\n".join(lines[start_index:])

def should_drop_metadata_line(line):
    title = strip_markdown_heading(line)
    lower = title.strip().lower()
    if is_publication_metadata_line(line):
        return True
    if re.match(r'^notas\s*:', lower):
        return True
    return bool(re.match(
        r'^(referencias(?:\s+bibliogr[aá]ficas?)?|bibliograf[ií]a(?:\s+\S+){0,4}|references|notas?)\s*\.{0,}\s*\d{1,4}\s*$',
        lower,
    ))

def next_nonempty_line_index(lines, start_index):
    for index in range(start_index, len(lines)):
        if strip_markdown_heading(lines[index]).strip():
            return index
    return None

def is_likely_author_heading(line):
    if not is_markdown_heading(line) or markdown_heading_level(line) > 2:
        return False
    title = strip_markdown_heading(line).strip()
    if (
        not title
        or len(title) > 90
        or re.search(r'[.!?:;]\s*$', title)
        or re.search(
            r'\b(econom[ií]a|an[aá]lisis|n[uú]mero|contenidos|coordinador|'
            r'coordinadores|suscripci[oó]n)\b',
            title,
            re.IGNORECASE,
        )
    ):
        return False
    capitalized_words = re.findall(
        r'\b[A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ.-]*\b',
        title,
    )
    return len(title.split()) >= 2 and len(capitalized_words) >= 2

def is_content_restart_heading(line, line_index, total_lines):
    numbered_heading = bool(re.match(r'^\d+(?:\.\d+)+(?:\s+|$)', normalized_heading_text(line)))
    return (
        is_markdown_heading(line)
        and not is_reference_heading(line, line_index, total_lines)
        and not is_backmatter_heading(line, line_index, total_lines)
        and (markdown_heading_level(line) == 1 or numbered_heading or is_likely_author_heading(line))
    )

def is_likely_author_byline_before_heading(lines, index):
    line = lines[index]
    title = strip_markdown_heading(line).strip()
    if (
        not title
        or is_markdown_heading(line)
        or is_image_line(line)
        or len(title) > 180
        or re.search(r'[.!?:;]\s*$', title)
        or re.match(r'^(?:pdf|html|xml|accesible\s+en)\b', title, re.IGNORECASE)
        or re.search(r'https?://|www\.', title, re.IGNORECASE)
    ):
        return False

    next_index = next_nonempty_line_index(lines, index + 1)
    if next_index is None:
        return False
    next_line = lines[next_index]
    if not is_content_restart_heading(next_line, next_index, len(lines)):
        return False

    capitalized_words = re.findall(
        r'\b[A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ.-]*\b',
        title,
    )
    return len(title.split()) >= 2 and len(capitalized_words) >= 2

def remove_reference_sections(text):
    lines = text.splitlines()
    kept = []
    skipping = False

    for index, line in enumerate(lines):
        if skipping:
            if is_likely_author_byline_before_heading(lines, index):
                skipping = False
                kept.append(line)
                continue
            if is_content_restart_heading(line, index, len(lines)):
                if is_backmatter_heading(line, index, len(lines)):
                    continue
                skipping = False
            else:
                continue

        if is_reference_heading(line, index, len(lines)) or is_backmatter_heading(line, index, len(lines)):
            skipping = True
            continue
        if len(lines) and index > len(lines) * 0.75 and is_frontmatter_marker(line):
            skipping = True
            continue

        kept.append(line)

    return "\n".join(kept)

def remove_inline_note_numbers(line):
    lowercase_letters = r'a-záéíóúüñ'
    letters = r'A-Za-zÁÉÍÓÚÜÑáéíóúüñ'
    protected_codes = {
        'AT1', 'CET1', 'CO2', 'CRR2', 'G20', 'IFRS9', 'NIIF9', 'P2R',
    }
    protected_numbered_terms = {
        'at', 'cet', 'ifrs', 'niif', 'pilar', 'stage', 'tier',
    }

    def is_protected_numbered_term(word, number):
        plain_word = word.rstrip('»”")').lower()
        combined = f"{plain_word}{number}".upper()
        return (
            combined in protected_codes
            or (
                plain_word in protected_numbered_terms
                and number in {'1', '2', '3', '9'}
            )
        )

    def remove_attached_note_number(match):
        word = match.group(1)
        number = match.group(2)
        if is_protected_numbered_term(word, number):
            return match.group(0)
        return word

    def remove_spaced_note_number(match):
        word = match.group(1)
        number = match.group(2)
        if is_protected_numbered_term(word, number):
            return match.group(0)
        return word

    line = re.sub(
        r'\bstage\s+([123])([1-9])(?=\s+[a-záéíóúüñ])',
        r'stage \1',
        line,
        flags=re.IGNORECASE,
    )
    line = re.sub(
        rf'\b([{letters}]+)(\d{{1,3}})(?=(?:[.;:](?!\d)|$))',
        remove_attached_note_number,
        line,
    )
    line = re.sub(
        rf'\b([{letters}]+)(\d{{1,2}})(?=\s+[{lowercase_letters}])',
        remove_attached_note_number,
        line,
    )
    line = re.sub(r'(?<=\))\d{1,2}(?=(?:[.;:](?!\d)|$|\s+[a-záéíóúüñ]))', '', line)

    if len(line) < 60:
        return line
    if re.match(r'^\s*(?:!\[|<table\b|</table>|<tr\b|<td\b|figura\b|gr[aá]fico\b|cuadro\b|tabla\b)', line, re.IGNORECASE):
        return line

    line = re.sub(
        rf'\b([{letters}]+[»”")]?)\s+(\d{{1,3}})(?=(?:[.;:](?!\d)|$))',
        remove_spaced_note_number,
        line,
    )
    line = re.sub(
        rf'\b([{letters}]+)(\d{{1,3}})(?=(?:[.;:](?!\d)|$))',
        remove_attached_note_number,
        line,
    )
    def remove_number_before_comma(match):
        previous = match.group(1)
        number = match.group(2)
        if previous.lower() in {'del'}:
            return match.group(0)
        if re.match(r'^[A-ZÁÉÍÓÚÜÑ]$', previous):
            return match.group(0)
        if len(number) > 2:
            return match.group(0)
        return previous

    line = re.sub(
        rf'\b([{letters}]+)\s+(\d{{1,3}})(?=,\s+(?!\d))',
        remove_number_before_comma,
        line,
    )
    line = re.sub(rf'(?<=[{lowercase_letters}])\d{{1,3}}(?=,\s+(?!\d))', '', line)

    protected_number_contexts = {
        'art', 'arts', 'artículo', 'artículos', 'capítulo', 'capítulos',
        'apartado', 'apartados',
        'chapter', 'chapters', 'figura', 'figuras', 'tabla', 'tablas', 'cuadro', 'cuadros',
        'gráfico', 'gráficos', 'siglo', 'siglos', 'año', 'años',
        'página', 'páginas', 'pp', 'núm', 'número', 'números',
    }

    def remove_between_words(match):
        previous_word = match.group(1)
        note_number = match.group(2)
        next_word = match.group(3)
        if previous_word.lower().strip('.').strip() in protected_number_contexts:
            return match.group(0)
        if not re.search(r'[»”"\)]$', previous_word):
            return match.group(0)
        if len(note_number) > 2:
            return match.group(0)
        return f"{previous_word} {next_word}"

    line = re.sub(
        rf'\b([{letters}][{letters}.]*[»”"]?)\s+(\d{{1,2}})\s+([{letters}][{letters}-]*)\b',
        remove_between_words,
        line,
    )
    return line

# 清理多余空格，连续空行，单个空行      单个空行待添加
def normalize_text_after_cleaning(text):
    normalized_lines = []

    for raw_line in text.splitlines():
        line = raw_line
        # 合并连续空格和制表符
        line = re.sub(r"[ \t]{2,}", " ", line)
        line = re.sub(r"(?<=\d)\s+%", "%", line)
        # 删除标点符号前多余空格
        line = re.sub(r"\s+([,.;:!?，。；：！？])", r"\1", line)
        # 删除两个单词之间多余的空格（待研究）
        pass
        # 删除首尾空格
        line = line.strip()
        # 删除所有空白行
        if line:
            normalized_lines.append(line)
    return "\n".join(normalized_lines)

def remove_inline_note_numbers_from_text(text):
    return "\n".join(remove_inline_note_numbers(line) for line in text.splitlines())

def simplify_match_key(text):
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[_\-\s]*(?:copia|copy|副本)\d*$', '', text, flags=re.IGNORECASE)
    return re.sub(r'[^a-z0-9]+', '', text.lower())

def find_matching_pdfs(md_path, pdf_root):
    if not pdf_root:
        return []
    pdf_root = Path(pdf_root).expanduser()
    if not pdf_root.exists():
        return []

    md_keys = {
        simplify_match_key(md_path.stem),
        simplify_match_key(md_path.parent.name),
    }
    matches = []
    for pdf_path in sorted(pdf_root.rglob("*.pdf")):
        pdf_key = simplify_match_key(pdf_path.stem)
        parent_key = simplify_match_key(pdf_path.parent.name)
        part_stem = re.sub(
            r'[_\-\s]+(?:part|parte)?\d+$',
            '',
            pdf_path.stem,
            flags=re.IGNORECASE,
        )
        if (
            pdf_key in md_keys
            or parent_key in md_keys
            or simplify_match_key(part_stem) in md_keys
        ):
            matches.append(pdf_path)
    return matches

def find_matching_pdf(md_path, pdf_root):
    matches = find_matching_pdfs(md_path, pdf_root)
    return matches[0] if matches else None

def pdfs_to_delete_after_clean(md_path, pdf_paths):
    if not pdf_paths:
        return []

    md_key = simplify_match_key(md_path.stem)
    unique_paths = []
    seen = set()
    for pdf_path in pdf_paths:
        resolved = Path(pdf_path).resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_paths.append(Path(pdf_path))

    exact_matches = [
        pdf_path
        for pdf_path in unique_paths
        if simplify_match_key(pdf_path.stem) == md_key
    ]
    return exact_matches or unique_paths

def delete_pdf_files(pdf_paths):
    deleted = []
    for pdf_path in pdf_paths:
        try:
            Path(pdf_path).unlink()
            deleted.append(Path(pdf_path))
            logger.info(f"Deleted PDF after successful clean: {pdf_path}")
        except FileNotFoundError:
            logger.info(f"PDF already absent after successful clean: {pdf_path}")
    return deleted

def extract_pdf_text(pdf_path):
    try:
        import fitz
        with fitz.open(pdf_path) as document:
            return "\n".join(page.get_text("text") for page in document)
    except Exception:
        pass

    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout
    except Exception as exc:
        raise RuntimeError(f"无法读取PDF文本: {pdf_path}") from exc

def repair_lost_thousand_numbers(cleaned_text, source_texts):
    repaired = cleaned_text
    source_numbers = {}
    for source_text in source_texts:
        if not source_text:
            continue
        for match in re.finditer(r'\b\d{1,3}(?:[.,]\d{3})+\b', source_text):
            number = match.group(0)
            suffix = re.escape(number[number.find('.'):] if '.' in number else number[number.find(','):])
            source_numbers.setdefault(suffix, set()).add(number)

    for suffix, numbers in source_numbers.items():
        if len(numbers) != 1:
            continue
        number = next(iter(numbers))
        repaired = re.sub(rf'(?<!\d)\s*{suffix}\b', f" {number}", repaired)

    return repaired

ACCENT_CACHE = {}
ACCENT_SKIP_WORDS = {
    'esta', 'este', 'estos', 'estas', 'solo', 'como', 'donde', 'cuando',
    'quien', 'quienes', 'cual', 'cuales', 'aun',
}
ACCENT_VOWELS = {
    'a': 'á',
    'e': 'é',
    'i': 'í',
    'o': 'ó',
    'u': 'ú',
}

def preserve_word_case(original, corrected):
    if original.isupper():
        return corrected.upper()
    if original[:1].isupper():
        return corrected[:1].upper() + corrected[1:]
    return corrected

def best_accented_form(word):
    lower = word.lower()
    if lower in ACCENT_CACHE:
        return ACCENT_CACHE[lower]
    if (
        len(lower) < 4
        or lower in ACCENT_SKIP_WORDS
        or not lower.isalpha()
        or any(ch in lower for ch in 'áéíóúüñ')
    ):
        ACCENT_CACHE[lower] = lower
        return lower

    candidates = set()
    for index, char in enumerate(lower):
        if char in ACCENT_VOWELS:
            candidates.add(lower[:index] + ACCENT_VOWELS[char] + lower[index + 1:])
        elif char == 'n':
            candidates.add(lower[:index] + 'ñ' + lower[index + 1:])

    best = lower
    if WORDFREQ_AVAILABLE:
        try:
            base_score = zipf_frequency(lower, 'es')
            best_score = base_score
            for candidate in candidates:
                score = zipf_frequency(candidate, 'es')
                if score >= 3.0 and score > best_score + 0.75:
                    best = candidate
                    best_score = score
        except:
            best = lower

    ACCENT_CACHE[lower] = best
    return best

def restore_spanish_accents_line(line):
    if re.match(r'^\s*(?:!\[|https?://|<)', line, re.IGNORECASE):
        return line

    letters = r'A-Za-zÁÉÍÓÚÜÑáéíóúüñ'

    def replace_word(match):
        word = match.group(0)
        corrected = best_accented_form(word)
        return preserve_word_case(word, corrected)

    return re.sub(rf'\b[{letters}]{{4,}}\b', replace_word, line)

def merge_hyphenated_lines(text):
    """
    合并跨行断词，处理两种情况：
    1. 带连字符：situa- \n ción -> situación
    2. 无连字符：situa \n ción -> situación
    适用于西班牙语
    """
    # 情况1：处理行尾带连字符的断词（如 "situa- \n ción"）
    # 注意：保留连字符后的换行，合并时删除连字符
    text = re.sub(r'(\w+)-\n\s*(\w+)', r'\1\2', text)
    
    # 情况2：处理行尾无连字符的断词（如 "situa \n ción"）
    # 需要判断合并后是否是合理单词
    lines = text.split('\n')
    merged_lines = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # 如果当前行以单词片段结尾（最后一个字符是字母或重音字母）
        if i < len(lines) - 1 and re.search(r'[a-zA-ZáéíóúüñÁÉÍÓÚÜÑ]$', line.strip()):
            next_line = lines[i + 1]
            # 如果下一行以单词片段开头
            if re.match(r'^[a-zA-ZáéíóúüñÁÉÍÓÚÜÑ]', next_line.strip()):
                # 提取当前行的末尾单词片段和下一行的开头单词片段
                current_words = line.split()
                next_words = next_line.split()
                
                if current_words and next_words:
                    last_word = current_words[-1]
                    first_word = next_words[0]
                    
                    # 尝试合并
                    candidate = last_word + first_word
                    
                    # 使用wordfreq判断是否应该合并
                    if WORDFREQ_AVAILABLE:
                        phrase_str = f"{last_word} {first_word}"
                        try:
                            if zipf_frequency(candidate, 'es') > zipf_frequency(phrase_str, 'es'):
                                # 应该合并：修改当前行和下一行
                                current_words[-1] = candidate
                                next_words.pop(0)
                                line = ' '.join(current_words + next_words)
                                lines[i + 1] = ''
                        except:
                            # 如果词频查询失败，保守起见不合并
                            pass
        
        merged_lines.append(line)
        i += 1
    
    # 重新组合文本
    result = '\n'.join(merged_lines)
        
    return result

def repair_known_repeated_fragments(text):
    return re.sub(
        r'\bLas ediciones anterio-\s+.{1,300}?\bLas ediciones anteriores\b',
        'Las ediciones anteriores',
        text,
    )

def default_review_log_dir(output_path):
    output_path = Path(output_path)
    if output_path.parent.name == "cleaned":
        return output_path.parent.parent / "review_logs"
    return output_path.parent / "review_logs"

def review_log_path_for(output_path, review_log_dir=None):
    output_path = Path(output_path)
    review_root = Path(review_log_dir).expanduser() if review_log_dir else default_review_log_dir(output_path)
    return review_root / output_path.with_suffix(".review.log").name

def deletion_log_path_for(output_path):
    return Path(output_path).with_suffix(".deletions.log")

def build_deletion_log(input_path, original_text, cleaned_text):
    original_lines = original_text.splitlines()
    cleaned_lines = cleaned_text.splitlines()
    matcher = difflib.SequenceMatcher(a=original_lines, b=cleaned_lines, autojunk=False)

    sections = []
    for tag, original_start, original_end, _, _ in matcher.get_opcodes():
        if tag not in {"delete", "replace"}:
            continue
        removed_lines = original_lines[original_start:original_end]
        if not any(line.strip() for line in removed_lines):
            continue
        label = "删除的原文" if tag == "delete" else "改写或局部删除前的原文"
        sections.append((label, original_start + 1, original_end, removed_lines))

    lines = [
        f"=== {Path(input_path).name} 删除内容记录 ===",
        "说明：本日志根据清洗前后文本差异生成，记录清洗后不再原样出现的原文内容。",
        "",
    ]
    if not sections:
        lines.append("未发现删除内容。")
        return "\n".join(lines) + "\n"

    for index, (label, start, end, removed_lines) in enumerate(sections, start=1):
        line_range = f"原文第 {start} 行" if start == end else f"原文第 {start}-{end} 行"
        lines.append(f"[{index}] {label}（{line_range}）")
        lines.extend(removed_lines)
        lines.append("")

    return "\n".join(lines)

def write_deletion_log(input_path, output_path, original_text, cleaned_text):
    log_path = deletion_log_path_for(output_path)
    log_path.write_text(build_deletion_log(input_path, original_text, cleaned_text), encoding="utf-8")
    logger.info(f"Deletion log written → {log_path}")

def clean_markdown_text(text, stop_phrases=None, keep_footnote_numbers=False):
    if stop_phrases is None:
        stop_phrases = set()
    stop_phrases = {phrase.lower() for phrase in stop_phrases}
    
    # 问题3：Unicode规范化，处理ﬁ、ﬂ等连字符号
    text = unicodedata.normalize('NFKC', text)
    text = remove_formula_blocks(text)
    text = remove_front_matter(text)
    text = split_author_affiliation_lines(text)

    text, protected_tables = protect_html_tables(text)
    text = reflow_soft_line_breaks(text)
    
    # 问题1：跨行断词合并（必须在逐行处理之前进行）
    text = merge_hyphenated_lines(text)
    text = repair_known_repeated_fragments(text)

    lines = text.splitlines()
    cleaned_lines = []
    review_hits = []
    in_table = False

    for line_no, line in enumerate(lines, start=1):
        # 跳过HTML表格 这里需要再检查一下
        if re.search(r'<table\b', line, re.IGNORECASE):
            in_table = True

        if in_table:
            cleaned_lines.append(line)
            if re.search(r'</table>', line, re.IGNORECASE):
                in_table = False
            continue

        # 检查图片并跳过 正则表达式需要再研究
        if re.match(r'!\[.*\]\(.*\)', line) or re.search(r'<img\s', line, re.IGNORECASE):
            cleaned_lines.append(line)
            continue

        if is_compact_toc_line(line):
            continue

        # 删除数字开头的这一段话，但跳过Markdown标题（以#开头）
        if re.match(r'^\s*\d{1,2}\s+', line) and not line.strip().startswith('#'):
            continue

        # 删除脚注引用[n]
        if not keep_footnote_numbers:
            line = re.sub(r'\[\d+\]', '', line)
            line = remove_inline_note_numbers(line)
            line = remove_annotation_stars(line)
            line = remove_formula_noise(line)

        if should_drop_metadata_line(line):
            continue
        # 合并断开的西班牙语单词，处理带连字符或空格的断词
        # stop_phrases 白名单：放"拿不准"的词组（如 sobre todo / sobretodo）
        # 命中白名单时：跳过自动合并，写入 review log 供人工判断
        words = line.split()
        merged = []
        i = 0

        while i < len(words):
            word = words[i]
            
            # 尝试尽可能多地合并后续单词
            merged_word = word
            j = i + 1
            
            while j < len(words):
                token_letters = r'A-Za-zÁÉÍÓÚáéíóúüÜñÑ'
                current_token_match = re.match(
                    rf'^([¡¿“"(\[]*)([{token_letters}]+)([.,;:!?，。；：！？»”")\]—–-]*)$',
                    merged_word,
                )
                next_token_match = re.match(r'^([A-Za-zÁÉÍÓÚáéíóúüÜñÑ]+)([.,;:!?，。；：！？»”")\]—–-]*)$', words[j])
                current_prefix = current_token_match.group(1) if current_token_match else ''
                current_core = current_token_match.group(2) if current_token_match else merged_word
                current_punct = current_token_match.group(3) if current_token_match else ''
                next_core = next_token_match.group(1) if next_token_match else words[j]
                next_punct = next_token_match.group(2) if next_token_match else ''

                # 检查是否可以与下一个词合并
                if merged_word.endswith('-'):
                    base_word = current_core.rstrip('-') if current_token_match else merged_word.rstrip('-')
                    candidate = base_word + next_core
                    phrase_str = f"{base_word} {next_core}"
                    
                    if phrase_str.lower() in stop_phrases:
                        review_hits.append(
                            f"行 {line_no} | 白名单短语（连字符）: '{phrase_str}' "
                            f"-> 候选合并词: '{candidate}' | 原文: {lines[line_no-1].strip()}"
                        )
                        break
                    
                    should_merge = False
                    if WORDFREQ_AVAILABLE:
                        try:
                            should_merge = zipf_frequency(candidate, 'es') > zipf_frequency(phrase_str, 'es')
                        except:
                            should_merge = False
                    
                    if should_merge:
                        merged_word = current_prefix + candidate + next_punct
                        j += 1
                        continue
                    else:
                        break
                
                elif current_token_match and not current_punct and next_token_match:
                    candidate = current_core + next_core
                    phrase_str = f"{current_core} {next_core}"
                    
                    if phrase_str.lower() in stop_phrases:
                        review_hits.append(
                            f"行 {line_no} | 白名单短语（无连字符）: '{phrase_str}' "
                            f"-> 候选合并词: '{candidate}' | 原文: {lines[line_no-1].strip()}"
                        )
                        break
                    
                    should_merge = False
                    if WORDFREQ_AVAILABLE:
                        try:
                            should_merge = zipf_frequency(candidate, 'es') > zipf_frequency(phrase_str, 'es')
                        except:
                            should_merge = False
                    
                    if should_merge:
                        merged_word = current_prefix + candidate + next_punct
                        j += 1
                        continue
                    else:
                        break
                else:
                    break
            
            merged.append(merged_word)
            i = j if j > i + 1 else i + 1
        
        cleaned_lines.append(restore_spanish_accents_line(" ".join(merged)))


    cleaned_text = "\n".join(cleaned_lines)
    cleaned_text = remove_reference_sections(cleaned_text)
    cleaned_text = normalize_text_after_cleaning(cleaned_text)
    cleaned_text = remove_inline_note_numbers_from_text(cleaned_text)
    cleaned_text = restore_html_tables(cleaned_text, protected_tables)

    return cleaned_text, review_hits

def clean_markdown_file(input_path, output_path, pdf_text=None, review_log_dir=None, **kwargs):
    text = input_path.read_text(encoding='utf-8')
    cleaned, review_hits = clean_markdown_text(text, **kwargs)
    cleaned = repair_lost_thousand_numbers(cleaned, [text, pdf_text])
    
    output_path.write_text(cleaned, encoding='utf-8')
    logger.info(f"Cleaned {input_path} → {output_path}")
    write_deletion_log(input_path, output_path, text, cleaned)
    # 人工检查日志
    log_path = review_log_path_for(output_path, review_log_dir)
    if review_hits:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as f:
            f.write(f"=== {input_path.name} ===\n")
            for item in review_hits:
                f.write(item + "\n")
            f.write("\n")
        logger.info(f"Review log written → {log_path}")
    elif log_path.exists():
        log_path.unlink()

    old_cleaned_log_path = output_path.with_suffix(".review.log")
    if old_cleaned_log_path != log_path and old_cleaned_log_path.exists():
        old_cleaned_log_path.unlink()

# 主程序
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="清洗已有 Markdown 文本")
    parser.add_argument("paths", nargs="*", help="要清洗的 Markdown 文件或文件夹（可选，不提供则扫描 output/mineru_raw/）")
    parser.add_argument("--stop-phrases", "-s", help="停用词白名单文件，每行一个短语")
    parser.add_argument("--keep-footnote-numbers", action="store_true",
                        help="是否保留脚注/注释编号（默认删除）")
    parser.add_argument("--mineru-out", default=str(MINERU_OUT),
                        help="已有 Markdown 根目录")
    parser.add_argument("--clean-out", default=str(CLEAN_OUT),
                        help="清洗后 md 输出目录")
    parser.add_argument("--review-log-out",
                        help="人工检查日志输出目录（默认使用 clean-out 同级的 review_logs）")
    parser.add_argument("--pdf-assisted", action="store_true",
                        help="启用同名PDF辅助校对（不做PDF转Markdown）")
    parser.add_argument("--pdf-root", default=str(PDF_RAW),
                        help="可选原始PDF目录，用于辅助校对")
    parser.add_argument("--keep-matched-pdfs", action="store_true",
                        help="清洗成功后保留匹配PDF（默认删除）")
    
    args = parser.parse_args()

    # 加载白名单
    stop_phrases_path = Path(args.stop_phrases).expanduser() if args.stop_phrases else STOP_PHRASES_FILE
    stop_phrases = load_stop_phrases(stop_phrases_path) if stop_phrases_path.exists() else set()
    
    md_paths = []
    
    # 如果没有提供路径参数，扫描默认 Markdown 目录
    if not args.paths:
        logger.info(f"没有指定文件，扫描默认Markdown目录: {args.mineru_out}")
        md_paths.extend(sorted(Path(args.mineru_out).expanduser().rglob("*.md")))
    else:
        # 处理提供的路径参数
        for path_str in args.paths:
            path = Path(path_str)
            if path.is_dir():
                md_paths.extend(sorted(path.rglob("*.md")))
            elif path.suffix.lower() == ".pdf":
                logger.warning(f"跳过PDF文件，当前程序只清洗已有Markdown: {path}")
            elif path.suffix.lower() == ".md":
                md_paths.append(path)
            else:
                logger.warning(f"跳过不识别的文件类型: {path}")

    # 去重
    unique_md_paths = []
    seen = set()
    for p in md_paths:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            unique_md_paths.append(p)

    if not unique_md_paths:
        logger.error("没有找到任何可清洗的Markdown文件")
        exit(1)

    # 清洗所有md
    clean_root = Path(args.clean_out).expanduser()
    clean_root.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"开始清洗 {len(unique_md_paths)} 个Markdown文件...")
    
    for md in unique_md_paths:
        try:
            try:
                relative_md = md.resolve().relative_to(Path(args.mineru_out).expanduser().resolve())
                out_stem = "__".join(relative_md.with_suffix("").parts)
            except ValueError:
                out_stem = md.stem
            out_path = clean_root / f"{out_stem}.clean.md"
            pdf_text = None
            pdf_paths = []
            if args.pdf_assisted or not args.keep_matched_pdfs:
                pdf_paths = find_matching_pdfs(md, args.pdf_root)
            if args.pdf_assisted:
                if pdf_paths:
                    try:
                        pdf_text = "\n".join(extract_pdf_text(path) for path in pdf_paths)
                        logger.info(
                            "使用PDF辅助校对: %s",
                            ", ".join(str(path) for path in pdf_paths),
                        )
                    except RuntimeError as e:
                        logger.warning(str(e))
                else:
                    logger.warning(f"未找到同名PDF，跳过PDF辅助校对: {md}")
            clean_markdown_file(
                md,
                out_path,
                pdf_text=pdf_text,
                review_log_dir=args.review_log_out,
                stop_phrases=stop_phrases,
                keep_footnote_numbers=args.keep_footnote_numbers
            )
            if not args.keep_matched_pdfs:
                delete_pdf_files(pdfs_to_delete_after_clean(md, pdf_paths))
        except Exception as e:
            logger.error(f"清洗失败 {md.name}: {e}")
    
    logger.info("所有处理完成！")
