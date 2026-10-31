"""
Print the text of .pptx/.docx/.xlsx files as Markdown, including tables and speaker notes.

Usage:
    python3 pptx_to_md.py deck.pptx [more files...]
"""

import sys

from office_oxide import to_markdown


def main() -> int:
    paths = sys.argv[1:]
    if not paths:
        print(__doc__, file=sys.stderr)
        return 2
    status = 0
    for path in paths:
        try:
            text = to_markdown(path)
        except Exception as exc:
            print(f'{path}: {exc}', file=sys.stderr)
            status = 1
            continue
        if len(paths) > 1:
            print(f'# {path}\n')
        print(text)
    return status


if __name__ == '__main__':
    sys.exit(main())
