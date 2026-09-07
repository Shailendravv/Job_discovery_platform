"""
Convert Camofox accessibility-tree snapshots to clean HTML.

The tree format is a YAML-like indented structure where each line is:
    <indent>- <node_type><: <value>> [<attr>]

Example input:
    - main:
      - heading "AI Transformation Owner" [level=1]
      - paragraph:
        - text: "Some text"
        - link "click here" [e1]:
          - /url: https://example.com
      - list:
        - listitem:
          - strong: Important
          - text: detail

Output:
    <h1>AI Transformation Owner</h1>
    <p>Some text <a href="https://example.com">click here</a></p>
    <ul><li><strong>Important</strong> detail</li></ul>
"""

from __future__ import annotations

import re
from typing import Optional


_HTML_ESCAPE = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})


def _e(text: str) -> str:
    """Escape HTML entities in text content."""
    return text.translate(_HTML_ESCAPE)


_SKIP_NODES = {
    "img", "button", "combobox", "separator", "log", "iframe",
    "banner", "navigation", "contentinfo",
}

_INLINE_NODES = {"text", "strong", "emphasis", "link"}

_PROPERTY_NODES = {"/url"}


def _parse_indent(line: str) -> int:
    stripped = line.lstrip(" ")
    return len(line) - len(stripped)


def _strip_line_prefix(line: str) -> str:
    s = line.lstrip(" ")
    if s.startswith("- "):
        s = s[2:]
    return s


def _parse_value(line: str) -> tuple[str, str, dict[str, str]]:
    text = line.strip()

    attrs: dict[str, str] = {}
    attr_pattern = re.findall(r'\[([^\]]+)\]', text)
    for a in attr_pattern:
        if "=" in a:
            k, v = a.split("=", 1)
            attrs[k.strip()] = v.strip()
        else:
            attrs[a.strip()] = "true"
    text = re.sub(r'\s*\[([^\]]+)\]', '', text)

    colon_pos = text.find(":")
    if colon_pos == -1:
        node_type = text.strip()
        value = ""
    else:
        node_type = text[:colon_pos].strip()
        value = text[colon_pos + 1:].strip()

    value = value.strip('"').strip("'")

    quoted_match = re.match(r'''^(\S+)\s+(["'])([^"']*)\2\s*(.*)$''', node_type)
    if quoted_match:
        node_type = quoted_match.group(1)
        embedded = quoted_match.group(3)
        after = quoted_match.group(4).strip()
        if value:
            value = f"{embedded} {value}"
        elif after:
            value = f"{embedded} {after}"
        else:
            value = embedded

    return node_type, value, attrs


def _is_tree_format(text: str) -> bool:
    lines = [l for l in text.split("\n") if l.strip()]
    if not lines:
        return False
    first = lines[0].lstrip(" ")
    return first.startswith("- ")


def _build_tree(text: str) -> list[tuple[int, str, str, dict[str, str]]]:
    nodes: list[tuple[int, str, str, dict[str, str]]] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        indent = _parse_indent(line)
        content = _strip_line_prefix(stripped)
        node_type, value, attrs = _parse_value(content)
        nodes.append((indent, node_type, value, attrs))
    return nodes


def _render_block(
    nodes: list[tuple[int, str, str, dict[str, str]]],
    start: int,
    parent_indent: int,
) -> tuple[str, int]:
    parts: list[str] = []
    i = start

    while i < len(nodes):
        indent, node_type, value, attrs = nodes[i]

        if indent <= parent_indent:
            break

        if node_type in _SKIP_NODES:
            skip_indent = indent
            i += 1
            while i < len(nodes) and nodes[i][0] > skip_indent:
                i += 1
            continue

        if node_type in _PROPERTY_NODES:
            i += 1
            continue

        if node_type == "link":
            url = ""
            child_text = ""
            j = i + 1
            while j < len(nodes) and nodes[j][0] > indent:
                if nodes[j][1] == "/url":
                    url = nodes[j][2]
                elif nodes[j][1] not in _SKIP_NODES:
                    child_text += _e(nodes[j][2]) + " "
                j += 1
            label = _e(value) or child_text.strip()
            if url:
                parts.append(f'<a href="{_e(url)}">{label}</a>')
            else:
                parts.append(label)
            i = j
            continue

        if node_type == "heading":
            level_str = attrs.get("level", "1")
            try:
                level = int(level_str)
            except ValueError:
                level = 1
            tag = f"h{level}"
            parts.append(f"<{tag}>{_e(value)}</{tag}>")
            i += 1
            continue

        if node_type == "list":
            items: list[str] = []
            j = i + 1
            while j < len(nodes) and nodes[j][0] > indent:
                if nodes[j][1] == "listitem":
                    li_value = _e(nodes[j][2])
                    li_children, j = _render_block(nodes, j + 1, nodes[j][0])
                    li_content = li_value
                    if li_children:
                        li_content = li_value + " " + li_children if li_value else li_children
                    items.append(f"<li>{li_content}</li>")
                else:
                    j += 1
            if items:
                parts.append("<ul>" + "".join(items) + "</ul>")
            i = j
            continue

        if node_type == "listitem":
            child_html, i = _render_block(nodes, i + 1, indent)
            content = _e(value)
            if child_html:
                content = _e(value) + " " + child_html if value else child_html
            parts.append(f"<li>{content}</li>")
            continue

        if node_type == "strong":
            child_html, next_i = _render_block(nodes, i + 1, indent)
            if child_html:
                parts.append(f"<strong>{child_html}</strong>")
            else:
                parts.append(f"<strong>{_e(value)}</strong>")
            i = next_i
            continue

        if node_type == "emphasis":
            child_html, next_i = _render_block(nodes, i + 1, indent)
            if child_html:
                parts.append(f"<em>{child_html}</em>")
            else:
                parts.append(f"<em>{_e(value)}</em>")
            i = next_i
            continue

        if node_type == "paragraph":
            has_children = (i + 1 < len(nodes) and nodes[i + 1][0] > indent) or not value
            if has_children and not value:
                child_html, next_i = _render_block(nodes, i + 1, indent)
                stripped = child_html.strip()
                if stripped:
                    parts.append(f"<p>{stripped}</p>")
                i = next_i
            else:
                parts.append(f"<p>{_e(value)}</p>")
                i += 1
            continue

        if node_type == "text":
            parts.append(_e(value))
            i += 1
            continue

        if value:
            parts.append(_e(value))
        i += 1

    return "".join(parts), i


def tree_to_html(text: str) -> str:
    if not text or not _is_tree_format(text):
        return text

    nodes = _build_tree(text)
    html, _ = _render_block(nodes, 0, -1)
    result = html.strip()

    result = re.sub(r"\n\s*\n", "\n", result)

    return result or text
