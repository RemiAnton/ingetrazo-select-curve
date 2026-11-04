# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Remi Clinton and IngeTrazo contributors.
"""Select Curve interactive selection tool for IngeTrazo on macOS.

Selects a whole chain of connected edges with one click:
- Bidirectional edge traversal finding connected visible/hard edge paths.
- Ignores hidden, softened, and smoothed edges (e.g. cylinder rims stay continuous).
- Stops traversal at dead-ends (0 edges), forks/branches (2+ edges), or closed loops.
- Interactive live viewport pre-highlighting matching IngeTrazo's default line hover representation:
    * Crisp solid highlight in IngeTrazo's native hover blue (rgb(77, 140, 242), width 3.0px).
    * No preview highlight for already-selected curves.
- macOS modifier keys:
    * Default Click: Clears selection and selects the detected curve chain.
    * Shift: Toggles chain (adds if unselected, removes if already selected).
    * Option / Alt or Command (⌘): Appends chain to current selection.
    * Shift + Option or Shift + Command (⌘): Subtracts chain from current selection.
    * Empty Click: Clears current selection.
- Native macOS UI integration:
    * Dedicated toolbar button in the main CAD toolbar with high-DPI Retina icon.
    * Tools & Extensions menu entries.
    * Robust keyboard shortcut (Shift+Space / Ctrl+Space) with event filter dispatch.
    * Status bar contextual prompts with macOS symbols (⇧, ⌥, ⌘) and selection count feedback.
    * Clean deactivation and Esc cancellation returning to standard Select tool.
"""
from __future__ import annotations

import logging
from typing import Optional, Set, List

from PySide6.QtCore import QEvent, QLineF, QObject, QPointF, Qt
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QCursor,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QVector3D,
)
from PySide6.QtWidgets import QApplication, QMainWindow, QToolBar, QMenu

from core.i18n import current_language
from tools.base import Tool, ToolContext

log = logging.getLogger("ingetrazo.plugins.select_curve")

KEY = "select_curve"
SHORTCUT = "Shift+Space"
SHORTCUT_ALT = "Ctrl+Space"

# Native IngeTrazo hover edge color: (0.3, 0.55, 0.95)
HOVER_LINE_COLOR = QColor.fromRgbF(0.3, 0.55, 0.95, 1.0)
HOVER_LINE_WIDTH = 3.0

# Status bar messages & localization
_PROMPTS = {
    "en": "Click an edge to select connected visible curve. ⇧ = Toggle, ⌥/⌘ = Add, ⇧+⌥/⌘ = Subtract. Esc = Exit.",
    "es": "Clic en arista para seleccionar curva visible conectada. ⇧ = Alternar, ⌥/⌘ = Añadir, ⇧+⌥/⌘ = Restar. Esc = Salir.",
    "pt-BR": "Clique numa aresta para selecionar curva visível conectada. ⇧ = Alternar, ⌥/⌘ = Adicionar, ⇧+⌥/⌘ = Subtrair. Esc = Sair.",
}

_TOOL_TIPS = {
    "en": "Select connected chain of visible edges (curve) [Shift+Space]",
    "es": "Seleccionar cadena conectada de aristas visibles (curva) [Shift+Espacio]",
    "pt-BR": "Selecionar cadeia conectada de arestas visíveis (curva) [Shift+Espaço]",
}


def _get_prompt() -> str:
    lang = current_language()
    return _PROMPTS.get(lang, _PROMPTS["en"])


def _get_tooltip() -> str:
    lang = current_language()
    return _TOOL_TIPS.get(lang, _TOOL_TIPS["en"])


# ---------------------------------------------------------------------------
# Edge Traversal & Visibility Utilities
# ---------------------------------------------------------------------------

def is_layer_visible(scene, layer_name: str | None) -> bool:
    """Check if the given layer name is visible in the scene."""
    if not layer_name:
        return True
    for ly in getattr(scene, "layers", []):
        if getattr(ly, "name", None) == layer_name:
            return getattr(ly, "visible", True)
    return True


def is_edge_visible(edge, scene=None) -> bool:
    """Determine whether an edge is visible and unsoftened.

    Hidden, softened, or smoothed edges are treated as non-structural/invisible
    and ignored during curve chain traversal.
    """
    if getattr(edge, "hidden", False):
        return False
    if getattr(edge, "soft", False):
        return False
    if getattr(edge, "smooth", False):
        return False
    if scene is not None and getattr(edge, "layer", None):
        if not is_layer_visible(scene, edge.layer):
            return False
    return True


def _matrix_of(scene, group):
    """Retrieve world transformation matrix placing group (or None)."""
    if group is None:
        return None
    try:
        from core.group import iter_placements
        for top in getattr(scene, "groups", []):
            for g, m in iter_placements(top):
                if g is group:
                    return m
    except Exception:
        pass
    return getattr(group, "xform", None)


def find_connected_curve(start_edge, scene) -> List:
    """Bidirectional edge path traversal starting from start_edge.

    1. Filters connected edges at each vertex to only visible, unsoftened edges.
    2. Continues if exactly 1 other visible edge meets at the vertex.
    3. Stops at dead-ends (0 edges), forks/intersections (2+ edges), or closed loops.
    Returns the ordered list of Edge entities forming the curve.
    """
    if start_edge is None or not is_edge_visible(start_edge, scene):
        return []

    visited_ids: Set[int] = {id(start_edge)}
    forward_chain: List = []
    backward_chain: List = []

    def get_connected_visible(vertex, current_edge) -> List:
        conns = []
        for ed in getattr(vertex, "edges", []):
            if ed is not current_edge and is_edge_visible(ed, scene):
                conns.append(ed)
        return conns

    # --- Forward direction (traversing through start_edge.v1) ---
    cur_edge = start_edge
    cur_vert = getattr(start_edge, "v1", None)
    while cur_vert is not None:
        conns = get_connected_visible(cur_vert, cur_edge)
        if len(conns) != 1:
            break
        next_edge = conns[0]
        if id(next_edge) in visited_ids:
            break
        visited_ids.add(id(next_edge))
        forward_chain.append(next_edge)
        cur_vert = next_edge.v1 if next_edge.v0 is cur_vert else next_edge.v0
        cur_edge = next_edge

    # --- Backward direction (traversing through start_edge.v0) ---
    cur_edge = start_edge
    cur_vert = getattr(start_edge, "v0", None)
    while cur_vert is not None:
        conns = get_connected_visible(cur_vert, cur_edge)
        if len(conns) != 1:
            break
        next_edge = conns[0]
        if id(next_edge) in visited_ids:
            break
        visited_ids.add(id(next_edge))
        backward_chain.append(next_edge)
        cur_vert = next_edge.v1 if next_edge.v0 is cur_vert else next_edge.v0
        cur_edge = next_edge

    backward_chain.reverse()
    return backward_chain + [start_edge] + forward_chain


# ---------------------------------------------------------------------------
# High-DPI Retina Icon & Custom Cursor Generators
# ---------------------------------------------------------------------------

def create_curve_icon() -> QIcon:
    """Generate high-DPI Retina/HiDPI icon for Select Curve toolbar & menus."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        s = float(size)

        # 1. Connected curve path
        path = QPainterPath()
        path.moveTo(s * 0.15, s * 0.75)
        path.cubicTo(s * 0.25, s * 0.20, s * 0.55, s * 0.15, s * 0.85, s * 0.40)

        # Subtle dark outline for high contrast
        p.setPen(
            QPen(
                QColor(20, 30, 45, 220),
                max(1.5, 3.2 * (s / 24.0)),
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        p.drawPath(path)

        # Native IngeTrazo hover blue stroke
        p.setPen(
            QPen(
                HOVER_LINE_COLOR,
                max(1.0, 2.0 * (s / 24.0)),
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        p.drawPath(path)

        # Curve nodes (vertices)
        node_radius = max(1.2, 2.2 * (s / 24.0))
        for pt in [
            QPointF(s * 0.15, s * 0.75),
            QPointF(s * 0.46, s * 0.22),
            QPointF(s * 0.85, s * 0.40),
        ]:
            p.setPen(QPen(QColor(15, 25, 35), max(0.8, 1.2 * (s / 24.0))))
            p.setBrush(QBrush(QColor(255, 255, 255)))
            p.drawEllipse(pt, node_radius, node_radius)

        # Selection pointer arrow targeting one of the curve segments
        cursor_poly = QPolygonF(
            [
                QPointF(s * 0.48, s * 0.42),
                QPointF(s * 0.82, s * 0.52),
                QPointF(s * 0.68, s * 0.64),
                QPointF(s * 0.82, s * 0.88),
                QPointF(s * 0.72, s * 0.94),
                QPointF(s * 0.58, s * 0.70),
                QPointF(s * 0.48, s * 0.80),
            ]
        )
        p.setPen(
            QPen(
                QColor(15, 25, 35),
                max(1.0, 1.4 * (s / 24.0)),
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        p.setBrush(QBrush(QColor(255, 255, 255)))
        p.drawPolygon(cursor_poly)

        p.end()
        icon.addPixmap(pixmap)
    return icon


def create_curve_cursor(mode: str = "") -> QCursor:
    """Generate custom macOS CAD cursor with curve badge and modifier symbols (+, -, ±)."""
    size = 32
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # Main arrow pointer
    arrow = QPolygonF(
        [
            QPointF(1, 1),
            QPointF(1, 18),
            QPointF(5, 14),
            QPointF(9, 23),
            QPointF(12, 22),
            QPointF(8, 13),
            QPointF(14, 13),
        ]
    )
    p.setPen(
        QPen(
            QColor(20, 20, 20),
            1.2,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    p.setBrush(QBrush(QColor(255, 255, 255)))
    p.drawPolygon(arrow)

    # Curve badge at bottom right
    badge_path = QPainterPath()
    badge_path.moveTo(14, 26)
    badge_path.cubicTo(17, 18, 23, 17, 28, 22)
    p.setPen(
        QPen(
            HOVER_LINE_COLOR,
            2.0,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(badge_path)

    # Node dots on badge
    p.setPen(QPen(QColor(20, 20, 20), 0.8))
    p.setBrush(QBrush(QColor(255, 255, 255)))
    p.drawEllipse(QPointF(14, 26), 1.5, 1.5)
    p.drawEllipse(QPointF(28, 22), 1.5, 1.5)

    # Modifier indicator badge
    if mode:
        font = QFont("Arial", 9, QFont.Weight.Bold)
        p.setFont(font)
        if mode == "+":
            p.setPen(QPen(QColor(0, 150, 60)))
            p.drawText(18, 12, "+")
        elif mode == "-":
            p.setPen(QPen(QColor(220, 30, 30)))
            p.drawText(19, 11, "-")
        elif mode == "+-":
            p.setPen(QPen(QColor(0, 120, 220)))
            p.drawText(16, 12, "±")

    p.end()
    return QCursor(pix, 1, 1)


# ---------------------------------------------------------------------------
# Interactive SelectCurveTool Class
# ---------------------------------------------------------------------------

class SelectCurveTool(Tool):
    """Interactive Select Curve Tool for IngeTrazo."""

    name = "Select Curve"
    shortcut = SHORTCUT
    shortcut_alt = SHORTCUT_ALT
    description = "Select connected chain of visible edges (curve)"
    uses_snap = False
    box_select = False

    def __init__(self, app=None) -> None:
        super().__init__()
        self.app = app
        self.hover_edge = None
        self.preview_edges: List = []
        self._action: Optional[QAction] = None
        self._cursors = {
            "": create_curve_cursor(""),
            "+": create_curve_cursor("+"),
            "-": create_curve_cursor("-"),
            "+-": create_curve_cursor("+-"),
        }

    def set_action(self, action: QAction) -> None:
        self._action = action

    def on_activate(self, viewport) -> None:
        self.hover_edge = None
        self.preview_edges = []
        if self._action is not None:
            self._action.setChecked(True)

        viewport.setCursor(self._cursors[""])
        prompt = _get_prompt()
        win = viewport.window()
        if win and win.statusBar():
            win.statusBar().showMessage(prompt)
        viewport.flash_status(prompt, 3500)
        viewport.update()

    def on_deactivate(self, viewport) -> None:
        self.clear_hover(viewport)
        if self._action is not None:
            self._action.setChecked(False)

        try:
            viewport.unsetCursor()
        except Exception:
            viewport.setCursor(Qt.CursorShape.ArrowCursor)

        win = viewport.window()
        if win and win.statusBar():
            win.statusBar().clearMessage()
        viewport.update()

    def clear_hover(self, viewport) -> None:
        """Clear active hover preview highlight and refresh view."""
        needs_update = bool(self.hover_edge is not None or self.preview_edges)
        self.hover_edge = None
        self.preview_edges = []
        if needs_update and viewport is not None:
            viewport.update()

    def _get_mode_from_modifiers(self, modifiers) -> tuple[str, str]:
        """Convert Qt modifier keys into selection mode and cursor badge symbol."""
        if modifiers is None:
            modifiers = QApplication.keyboardModifiers()

        is_shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        is_alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        is_meta = bool(modifiers & Qt.KeyboardModifier.MetaModifier)
        is_ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)

        is_add_mod = is_alt or is_meta or is_ctrl
        is_subtract_mod = is_shift and is_add_mod

        if is_subtract_mod:
            return "remove", "-"
        elif is_add_mod:
            return "add", "+"
        elif is_shift:
            return "toggle", "+-"
        return "replace", ""

    def on_hover(self, ctx: ToolContext) -> None:
        if ctx is None or ctx.viewport is None:
            return

        viewport = ctx.viewport
        scene = viewport.scene
        mesh = getattr(scene, "mesh", None)
        if mesh is None:
            return

        # Update cursor based on held modifiers
        _, badge = self._get_mode_from_modifiers(ctx.modifiers)
        cursor = self._cursors.get(badge, self._cursors[""])
        viewport.setCursor(cursor)

        sx = ctx.screen.x()
        sy = ctx.screen.y()

        # Dynamic edge picking
        edge = None
        if hasattr(viewport, "pick_visible_edge"):
            edge = viewport.pick_visible_edge(sx, sy)
        if edge is None and hasattr(viewport, "pick_edge"):
            cand = viewport.pick_edge(sx, sy)
            if cand is not None and is_edge_visible(cand, scene):
                edge = cand

        # Verify edge belongs to active mesh context
        if edge is not None:
            mesh_edges = getattr(mesh, "edges", ())
            if edge in mesh_edges or (hasattr(mesh_edges, "__contains__") and edge in mesh_edges):
                current_sel = getattr(scene, "selection", set())

                # Requirement 2: Do NOT show preview for already selected curves/edges
                if edge in current_sel:
                    if self.hover_edge is not None or self.preview_edges:
                        self.hover_edge = None
                        self.preview_edges = []
                        viewport.update()
                    return

                if edge is not self.hover_edge:
                    chain = find_connected_curve(edge, scene)

                    # If all edges in the chain are already selected, suppress preview
                    if chain and all(ed in current_sel for ed in chain):
                        if self.hover_edge is not None or self.preview_edges:
                            self.hover_edge = None
                            self.preview_edges = []
                            viewport.update()
                        return

                    self.hover_edge = edge
                    self.preview_edges = chain
                    viewport.update()
                return

        # Empty hover (cursor moved off edge to face or background)
        if self.hover_edge is not None or self.preview_edges:
            self.hover_edge = None
            self.preview_edges = []
            viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        if ctx is None or ctx.viewport is None:
            return

        viewport = ctx.viewport
        scene = viewport.scene
        mesh = getattr(scene, "mesh", None)
        if mesh is None:
            return

        mode, _ = self._get_mode_from_modifiers(ctx.modifiers)
        sx = ctx.screen.x()
        sy = ctx.screen.y()

        edge = None
        if hasattr(viewport, "pick_visible_edge"):
            edge = viewport.pick_visible_edge(sx, sy)
        if edge is None and hasattr(viewport, "pick_edge"):
            cand = viewport.pick_edge(sx, sy)
            if cand is not None and is_edge_visible(cand, scene):
                edge = cand

        # Check if a valid edge in the active mesh was clicked
        if edge is not None:
            mesh_edges = getattr(mesh, "edges", ())
            if edge in mesh_edges or (hasattr(mesh_edges, "__contains__") and edge in mesh_edges):
                chain = (
                    self.preview_edges
                    if (self.hover_edge is edge and self.preview_edges)
                    else find_connected_curve(edge, scene)
                )
                if chain:
                    current_sel = getattr(scene, "selection", set())
                    if mode == "toggle":
                        all_selected = all(ed in current_sel for ed in chain)
                        scene.select(chain, mode="remove" if all_selected else "add")
                    else:
                        scene.select(chain, mode=mode)

                    # Suppress hover preview after selection (since now selected)
                    self.hover_edge = None
                    self.preview_edges = []

                    viewport.update()

                    # Selection Count Feedback
                    count = len(chain)
                    msg = f"Selected {count} connected {'edge' if count == 1 else 'edges'}"
                    viewport.flash_status(msg, 3000)
                    win = viewport.window()
                    if win and win.statusBar():
                        win.statusBar().showMessage(msg, 3000)
                    return

        # Empty Space / Face Click
        if mode == "replace":
            scene.clear_selection()
            self.hover_edge = None
            self.preview_edges = []
            viewport.update()
            viewport.flash_status("Selection cleared", 1500)
            win = viewport.window()
            if win and win.statusBar():
                win.statusBar().showMessage(_get_prompt())

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key == Qt.Key.Key_Escape:
            self.clear_hover(viewport)
            try:
                from tools.select import SelectTool
                viewport.set_active_tool(SelectTool())
            except Exception:
                pass
            return True

        # Update cursor on modifier key change
        _, badge = self._get_mode_from_modifiers(modifiers)
        cursor = self._cursors.get(badge, self._cursors[""])
        viewport.setCursor(cursor)
        return False

    def on_cancel(self, viewport) -> None:
        self.clear_hover(viewport)
        try:
            from tools.select import SelectTool
            viewport.set_active_tool(SelectTool())
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Viewport Overlay Highlighting (Matching IngeTrazo's default line preview)
# ---------------------------------------------------------------------------

def draw_select_curve_overlay(viewport, painter: QPainter) -> None:
    """Renders line preview matching IngeTrazo's default line selection preview.

    Draws crisp solid lines in IngeTrazo's native hover blue (0.3, 0.55, 0.95), width 3.0px,
    without terminal circles or blurry outer halos.
    """
    active_tool = getattr(viewport, "active_tool", None)
    if not isinstance(active_tool, SelectCurveTool) or not active_tool.preview_edges:
        return

    edges = active_tool.preview_edges
    scene = viewport.scene
    matrix = _matrix_of(scene, getattr(scene, "edit_group", None))

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    dpr = float(viewport.devicePixelRatioF() if hasattr(viewport, "devicePixelRatioF") else 1.0)

    # Native IngeTrazo line preview pen (exact match to default OpenGL line hover)
    pen = QPen(
        HOVER_LINE_COLOR,
        HOVER_LINE_WIDTH * dpr,
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )

    lines: List[QLineF] = []

    for ed in edges:
        p0 = ed.v0.position
        p1 = ed.v1.position
        if matrix is not None:
            p0 = matrix.map(p0)
            p1 = matrix.map(p1)

        s0 = viewport._world_to_pixel(p0)
        s1 = viewport._world_to_pixel(p1)
        if s0 is None or s1 is None:
            continue

        clipped = viewport._clip_pixel_line(s0, s1, margin=0.0)
        if clipped is not None:
            lines.append(QLineF(clipped[0][0], clipped[0][1], clipped[1][0], clipped[1][1]))

    if lines:
        painter.setPen(pen)
        painter.drawLines(lines)

    painter.restore()


# ---------------------------------------------------------------------------
# Shortcut Event Filter for Shift+Space / Ctrl+Space
# ---------------------------------------------------------------------------

class SelectCurveShortcutFilter(QObject):
    """Event filter attached to MainWindow & Viewport to guarantee Shift+Space / Ctrl+Space activation."""

    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self._callback = callback

    def eventFilter(self, watched, event):
        etype = event.type()
        if etype in (QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride):
            if event.key() == Qt.Key.Key_Space:
                mods = event.modifiers()
                is_shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
                is_ctrl = bool(mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier))
                if is_shift or is_ctrl:
                    self._callback()
                    event.accept()
                    return True
        return False


# ---------------------------------------------------------------------------
# Extension Setup & Lifecycle Hook (setup(app))
# ---------------------------------------------------------------------------

_shared_tool_instance: Optional[SelectCurveTool] = None
_shortcut_filter: Optional[SelectCurveShortcutFilter] = None


def setup(app) -> None:
    """Extension initialization: registers unified tool action, toolbar button, and overlay."""
    global _shared_tool_instance, _shortcut_filter

    win: QMainWindow = app.window
    viewport = app.viewport
    icon = create_curve_icon()
    tooltip = _get_tooltip()

    tool = SelectCurveTool(app)
    _shared_tool_instance = tool

    def activate_select_curve():
        current = getattr(app.viewport, "active_tool", None)
        if isinstance(current, SelectCurveTool):
            return
        app.viewport.set_active_tool(tool)

    # Clean up any preexisting duplicate actions from previous hot-reloads
    for a in list(win.findChildren(QAction)):
        if a.text() == "Select Curve" and a.objectName() != "action_select_curve":
            a.setShortcut("")
            for mb_action in win.menuBar().actions():
                menu = mb_action.menu()
                if menu is not None and a in menu.actions():
                    menu.removeAction(a)
            a.deleteLater()

    # 1. Single unified QAction (no duplicate actions with Shift+Space)
    action = win.findChild(QAction, "action_select_curve")
    if action is None:
        action = QAction(icon, "Select Curve", win)
        action.setObjectName("action_select_curve")
        action.setCheckable(True)
        action.setShortcuts([QKeySequence(SHORTCUT), QKeySequence(SHORTCUT_ALT)])
        action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        action.setToolTip(tooltip)
        action.setStatusTip(_get_prompt())
        action.triggered.connect(activate_select_curve)
    else:
        action.setIcon(icon)
        action.setShortcuts([QKeySequence(SHORTCUT), QKeySequence(SHORTCUT_ALT)])
        action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        action.setToolTip(tooltip)

    tool.set_action(action)

    # 2. Add to Extensions menu
    mb = win.menuBar()
    ext_menu = None
    for a in mb.actions():
        if a.text() in ("Extensions", "Extensiones", "Extensões"):
            ext_menu = a.menu()
            break
    if ext_menu is not None and action not in ext_menu.actions():
        # Insert before extension manager entries if present, else append
        anchor = None
        for ma in ext_menu.actions():
            if any(k in ma.text() for k in ("Manage extensions", "Open extensions", "Develop an extension")):
                anchor = ma
                break
        if anchor is not None:
            ext_menu.insertAction(anchor, action)
        else:
            ext_menu.addAction(action)

    # 3. Add to Tools menu right next to standard Select action
    tools_menu = None
    for a in mb.actions():
        if a.text() in ("Tools", "Herramientas", "Ferramentas"):
            tools_menu = a.menu()
            break

    if tools_menu is not None and action not in tools_menu.actions():
        select_action = None
        for ma in tools_menu.actions():
            if ma.text() in ("Select", "Seleccionar", "Selecionar"):
                select_action = ma
                break
        if select_action is not None:
            idx = tools_menu.actions().index(select_action)
            if idx + 1 < len(tools_menu.actions()):
                tools_menu.insertAction(tools_menu.actions()[idx + 1], action)
            else:
                tools_menu.addAction(action)
        else:
            tools_menu.addAction(action)

    # 4. Add dedicated button to the main CAD toolbar
    main_tb = win.findChild(QToolBar, "main")
    if main_tb is not None and action not in main_tb.actions():
        select_tb_action = None
        for ta in main_tb.actions():
            if ta.text() in ("Select", "Seleccionar", "Selecionar"):
                select_tb_action = ta
                break
        if select_tb_action is not None:
            idx = main_tb.actions().index(select_tb_action)
            if idx + 1 < len(main_tb.actions()):
                main_tb.insertAction(main_tb.actions()[idx + 1], action)
            else:
                main_tb.addAction(action)
        else:
            main_tb.addAction(action)

        grp = select_tb_action.actionGroup() if select_tb_action is not None else None
        if grp is not None:
            grp.addAction(action)

    # 5. Guaranteed keyboard event filter for Shift+Space / Ctrl+Space
    if _shortcut_filter is not None:
        try:
            win.removeEventFilter(_shortcut_filter)
            viewport.removeEventFilter(_shortcut_filter)
        except Exception:
            pass

    _shortcut_filter = SelectCurveShortcutFilter(activate_select_curve, win)
    win.installEventFilter(_shortcut_filter)
    viewport.installEventFilter(_shortcut_filter)

    # 6. Register Viewport QPainter Overlay
    app.add_overlay(draw_select_curve_overlay)

    # 7. Multi-tab safety & Document Change Hook
    def on_doc_changed():
        if _shared_tool_instance is not None:
            _shared_tool_instance.clear_hover(app.viewport)
        if _shortcut_filter is not None and app.viewport is not None:
            try:
                app.viewport.installEventFilter(_shortcut_filter)
            except Exception:
                pass

    app.on_document_changed(on_doc_changed)
