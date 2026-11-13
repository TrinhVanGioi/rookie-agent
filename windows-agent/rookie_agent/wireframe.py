"""A drawing of a Java screen for the flow visualizer, made from the accessible tree.

The visualizer shows what the agent is doing without touching the screen the GDV
works on. Only the structure is drawn: where the fields, buttons, tabs and tables
are, and the captions the application gives them. Never any value: not the text in
a field, not a table cell, not the text of a label (which in a real application
can hold a customer's name or an amount).
"""

from __future__ import annotations

from typing import Any

from rookie_agent.jab.session import Node

# Accessible role -> how the visualizer draws it.
KINDS = {
    "text": "field",
    "password text": "secret",
    "push button": "button",
    "menu item": "button",
    "menu": "button",
    "hyperlink": "button",
    "page tab": "tab",
    "table": "table",
    "combo box": "select",
    "check box": "toggle",
    "radio button": "toggle",
    "label": "label",
}
# Their text is data, not a caption.
NAMELESS_KINDS = frozenset({"label"})
MAX_ITEMS = 400


def wireframe(root: Node) -> dict[str, Any]:
    """Boxes in coordinates relative to the window's top-left corner."""
    items: list[dict[str, Any]] = []

    def visit(node: Node) -> None:
        if len(items) >= MAX_ITEMS:
            return
        kind = KINDS.get(node.role)
        states = node.states.split(",")
        if kind and "showing" in states and node.width > 0 and node.height > 0:
            items.append(
                {
                    "role": node.role,
                    "kind": kind,
                    "name": None if kind in NAMELESS_KINDS else (node.name or None),
                    "x": node.x - root.x,
                    "y": node.y - root.y,
                    "w": node.width,
                    "h": node.height,
                }
            )
        for child in node.children:
            visit(child)

    visit(root)
    return {"title": root.name, "width": root.width, "height": root.height, "items": items}
