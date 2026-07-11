#!/usr/bin/env python3
r"""
split_rfc.py - Clean and split an RFC/specification document into 2-level sections.

Used by the rfc-audit skill's Phase A (step A.1). Deterministic regex processing,
no LLM. Extracted from the original diff.py clean_text/handle_doc functions.

Splitting strategy (first match wins):
  1. Numbered sections: ^(\d+(\.\d+)*)\s+(title)  -> atomic unit = 2-level (e.g. 2.1)
     Deeper sections (2.1.1) roll up into their 2-level parent (2.1).
  2. Fallback: Markdown ## (h2) headings as atomic units.
  3. Last resort: whole document as a single section.

Usage:
    python split_rfc.py <input_file> <output_dir> [--rfc-id RFC_2460]

Outputs:
    <output_dir>/sections/<RFC_ID>_<section>.md  - section full text
    <output_dir>/rfc_sections.json               - index (title + content_path;
                                                   summary left empty for the LLM to fill)
"""
import re
import json
import os
import argparse
import sys


def clean_text(text):
    """Remove RFC headers, footers, page numbers, and collapse blank lines."""
    header_pattern = re.compile(r"RFC (\d+)\s+(.*?)\s+([A-Za-z]+ \d{4})")
    footer_pattern = re.compile(r"^.*\s+\[Page \d+\]$", re.MULTILINE)
    text = header_pattern.sub("", text)
    text = footer_pattern.sub("", text)
    text = re.sub(r"\n\s*\n", "\n", text)
    return text.strip()


def split_numbered_sections(text):
    """Split by numbered section headers. Returns list of (number, title, content) or None."""
    pattern = re.compile(r"^(\d+(?:\.\d+)*)(\.?)\s+(.*)$", re.MULTILINE)
    headers = list(pattern.finditer(text))
    if not headers:
        return None

    sections = []
    for i, match in enumerate(headers):
        number = match.group(1)
        title = match.group(3).strip()
        start = match.end()
        end = headers[i + 1].start() if (i + 1) < len(headers) else len(text)
        content = text[start:end].strip()
        sections.append((number, title, content))
    return sections


def split_markdown_sections(text):
    """Fallback: split by Markdown ## (h2) headers. Returns list of (None, title, content)."""
    pattern = re.compile(r"^##\s+(.*)$", re.MULTILINE)
    headers = list(pattern.finditer(text))
    if not headers:
        return [(None, "Full Document", text)]

    sections = []
    for i, match in enumerate(headers):
        title = match.group(1).strip()
        start = match.end()
        end = headers[i + 1].start() if (i + 1) < len(headers) else len(text)
        content = text[start:end].strip()
        sections.append((None, title, content))
    return sections


def roll_up_to_2level(sections):
    """Roll up sections deeper than 2-level into their 2-level parent.

    2.1.1 -> merges into 2.1.  Top-level (2) and 2-level (2.1) stay as-is.
    """
    grouped = {}
    order = []

    # First pass: collect 2-level parents and top-level sections
    for number, title, content in sections:
        if number is None:
            key = title
            if key not in grouped:
                grouped[key] = {"number": None, "title": title, "content": ""}
                order.append(key)
            grouped[key]["content"] += "\n" + content
            continue

        parts = number.split(".")
        if len(parts) <= 2:
            key = number
            if key not in grouped:
                grouped[key] = {"number": number, "title": title, "content": ""}
                order.append(key)
            grouped[key]["content"] += "\n" + content
        else:
            parent = ".".join(parts[:2])
            if parent not in grouped:
                parent_title = title
                for n, t, _ in sections:
                    if n == parent:
                        parent_title = t
                        break
                grouped[parent] = {"number": parent, "title": parent_title, "content": ""}
                order.append(parent)
            grouped[parent]["content"] += f"\n{number} {title}\n" + content

    return [grouped[k] for k in order]


def main():
    parser = argparse.ArgumentParser(
        description="Clean and split an RFC document into 2-level sections."
    )
    parser.add_argument("input_file", help="Path to the RFC document")
    parser.add_argument("output_dir", help="Output directory for sections and index")
    parser.add_argument(
        "--rfc-id", default="RFC", help="RFC identifier for filenames (e.g. RFC_2460)"
    )
    args = parser.parse_args()

    with open(args.input_file, "r", encoding="utf-8") as f:
        raw = f.read()

    cleaned = clean_text(raw)

    sections = split_numbered_sections(cleaned)
    if sections is None:
        sections = split_markdown_sections(cleaned)

    rolled = roll_up_to_2level(sections)

    sections_dir = os.path.join(args.output_dir, "sections")
    os.makedirs(sections_dir, exist_ok=True)

    index = {}
    for sec in rolled:
        number = sec["number"]
        title = sec["title"]
        content = sec["content"].strip()

        if number:
            safe_section = re.sub(r"\.", "_", number)
            filename = f"{args.rfc_id}_{safe_section}.md"
            section_key = number
            header = f"{number} {title}\n\n"
        else:
            safe_title = re.sub(r"[^a-zA-Z0-9_-]", "_", title)[:50]
            filename = f"{args.rfc_id}_{safe_title}.md"
            section_key = title
            header = f"## {title}\n\n"

        filepath = os.path.join(sections_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(header + content)

        content_path = os.path.relpath(filepath, args.output_dir)
        index[section_key] = {
            "title": title,
            "summary": "",
            "content_path": content_path,
        }

    index_path = os.path.join(args.output_dir, "rfc_sections.json")
    output = {args.rfc_id: index} if args.rfc_id != "RFC" else index
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Split into {len(index)} sections.")
    print(f"Section files: {sections_dir}/")
    print(f"Index: {index_path}")
    print(f"Next step: LLM generates summaries for each section (Phase A.2).")


if __name__ == "__main__":
    main()
