#!/usr/bin/env python3
"""
This script is vibe-coded. It's not part of the library itself.

Generate GitHub release notes from CHANGELOG.md.

Usage:
    python scripts/github_release_notes.py 0.10.0

Converts single newlines to spaces while preserving paragraph breaks (double newlines)
for proper rendering in GitHub markdown.
"""

import re
import sys
from pathlib import Path


def extract_release_notes(version: str) -> str:
    """Extract release notes for a specific version from CHANGELOG.md."""
    changelog_path = Path(__file__).parent.parent / "CHANGELOG.md"

    with open(changelog_path) as f:
        content = f.read()

    # Find the section for this version
    # Pattern: ## X.Y.Z followed by content until the next ## or EOF
    pattern = rf"^## {re.escape(version)}\b(.+?)(?=^##|\Z)"
    match = re.search(pattern, content, re.MULTILINE | re.DOTALL)

    if not match:
        raise ValueError(f"Version {version} not found in CHANGELOG.md")

    return match.group(1).strip()


def process_for_github(text: str) -> str:
    """
    Process changelog text for GitHub markdown.

    Converts single newlines to spaces while preserving:
    - Paragraph breaks (double newlines)
    - List items (lines starting with `-` or `*`) at any level
    - Indentation for list items and their content
    """
    # Split by double newlines (paragraph breaks)
    paragraphs = text.split("\n\n")

    processed = []
    for para in paragraphs:
        lines = para.split("\n")
        result_lines = []
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.lstrip()
            indent = line[: len(line) - len(stripped)]

            # Check if this is a list item
            is_list_item = stripped.startswith(("-", "*")) and (
                len(stripped) > 1 and stripped[1] in (" ", "\t")
            )

            if is_list_item:
                # Collect continuation lines for this list item
                # (must be more indented than the list marker)
                list_indent = indent
                item_lines = [stripped]
                i += 1

                while i < len(lines):
                    next_line = lines[i]
                    next_stripped = next_line.lstrip()
                    next_indent = next_line[
                        : len(next_line) - len(next_stripped)
                    ]

                    # Check if it's a list item at a deeper level
                    is_next_list = next_stripped.startswith(("-", "*")) and (
                        len(next_stripped) > 1
                        and next_stripped[1] in (" ", "\t")
                    )

                    if (
                        next_stripped
                        and not is_next_list
                        and len(next_indent) > len(list_indent)
                    ):
                        # Continuation of current item (not a nested list)
                        item_lines.append(next_stripped)
                        i += 1
                    elif is_next_list and len(next_indent) > len(list_indent):
                        # Nested list item - break to process separately
                        break
                    elif next_stripped and len(next_indent) <= len(
                        list_indent
                    ):
                        # Back to same level or less indented - stop
                        break
                    elif not next_stripped:
                        # Empty line - stop
                        break
                    else:
                        break

                # Fold the item lines
                folded_item = " ".join(item_lines)
                result_lines.append(indent + folded_item)
            else:
                # Regular line (not a list item)
                if stripped:
                    # Collect lines at the same indentation level
                    para_indent = indent
                    para_lines = [stripped]
                    i += 1

                    while i < len(lines):
                        next_line = lines[i]
                        next_stripped = next_line.lstrip()
                        next_indent = next_line[
                            : len(next_line) - len(next_stripped)
                        ]

                        # Check if it's a list item
                        is_next_list = next_stripped.startswith(
                            ("-", "*")
                        ) and (
                            len(next_stripped) > 1
                            and next_stripped[1] in (" ", "\t")
                        )

                        if is_next_list:
                            # List item - stop here
                            break
                        elif not next_stripped:
                            # Empty line - stop here
                            break
                        elif next_indent == para_indent:
                            # Same indentation - part of same paragraph
                            para_lines.append(next_stripped)
                            i += 1
                        else:
                            # Different indentation - stop
                            break

                    result_lines.append(indent + " ".join(para_lines))
                else:
                    # Empty line - skip
                    i += 1

        processed.append("\n".join(result_lines))

    # Join paragraphs back with double newlines
    return "\n\n".join(processed)


def main():
    if len(sys.argv) != 2:
        print(
            "Usage: python scripts/github_release_notes.py <version>",
            file=sys.stderr,
        )
        sys.exit(1)

    version = sys.argv[1]

    try:
        notes = extract_release_notes(version)
        formatted = process_for_github(notes)
        print(formatted)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
