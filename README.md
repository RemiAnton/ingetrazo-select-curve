# Select Curve for IngeTrazo (macOS)

An interactive curve selection tool for **[IngeTrazo](https://ingetrazo.com)** that faithfully replicates the full behavior and functionality of Thomas Thomassen's (**ThomThom**) acclaimed *Select Curve* plugin from Trimble SketchUp.

---

## Overview

In 3D CAD, polygon, and surface modeling, curves, arcs, and freehand outlines are often broken down or "exploded" into individual connected line segments. Bounded by softened or hidden geometry on curved/extruded surfaces (such as cylinder caps, loft profiles, fillets, and CNC contours), selecting these curves piece-by-piece with standard tools is tedious and error-prone.

**Select Curve** allows you to hover over and click any single visible edge segment to automatically detect and select the entire continuous chain of connected visible edges forming a logical curve, without requiring the geometry to be formally grouped, welded, or pre-configured as a curve entity.

---

## Features

### 1. Bidirectional Topological Edge Traversal
- **Bidirectional Exploration:** Traverses outward in both directions from the picked edge through its start (`v0`) and end (`v1`) vertices.
- **Smart Visibility Filtering:** Automatically ignores hidden, softened, or smoothed edges. For example, along the top rim of a cylinder where side vertical edges are softened, the rim is seamlessly traversed as a continuous circular curve.
- **Continuation Condition:** When a vertex connects to exactly one other visible edge (2 visible edges total meeting at the vertex), traversal continues.
- **Stopping Conditions:**
  - **Dead End:** Reaches an open endpoint (0 other visible edges).
  - **Branch / Fork:** Meets an intersection, T-junction, or crossroad (2 or more other visible edges).
  - **Closed Loop:** Terminates cleanly upon reaching an edge already visited in the chain (e.g. circles, closed polygons).

### 2. Live Interactive Viewport Pre-Highlighting (Hover Preview)
- **Real-Time Detection:** As your cursor hovers across the viewport, the tool identifies the edge beneath the pointer.
- **Glowing Visual Feedback:** Dynamically highlights the detected curve chain with a dual-pass glowing cyan/electric blue overlay and terminal node endpoints before clicking.
- **Instant Clear:** Moving the cursor onto a face or into empty viewport background instantly clears the preview overlay.

### 3. macOS Native Modifier Key Integration
- **Default Click (No Modifiers):** Replaces selection with the detected curve chain.
- **Toggle (`Shift ⇧`):** Toggles the detected curve chain (adds if unselected; removes if already selected).
- **Add (`Option ⌥` / `Alt` or `Command ⌘`):** Appends the curve chain to the existing selection without clearing prior selections.
- **Subtract (`Shift + Option ⇧⌥` or `Shift + Command ⇧⌘`):** Deselects and removes the curve chain from the current selection.
- **Empty Space Click:** Clears current selection (when clicked with no modifier keys).

### 4. Native macOS UI & Workflow Integration
- **Retina/HiDPI Icon:** Dedicated toolbar button in the main CAD toolbar right beside the standard Select tool, with scalable vector-quality artwork.
- **Menu Registration:** Accessible via both **Tools ▸ Select Curve** and **Extensions ▸ Select Curve**.
- **Keyboard Shortcut:** Pre-bound to `Shift + Space` (and `Ctrl + Space`), providing an instant toggle alongside the standard `Space` Select tool.
- **Contextual Status Bar:** Displays macOS modifier guidelines (`⇧ = Toggle, ⌥/⌘ = Add, ⇧+⌥/⌘ = Subtract. Esc = Exit`) and real-time selection feedback (`Selected 24 connected edges`).
- **Clean Deactivation & Cancellation:** Restores default cursors and clears temporary highlights on tool switch or `Esc`.

---

## Installation

### Manual Installation
Copy `select_curve.py` into your IngeTrazo plugins directory:

- **macOS / Linux:** `~/.local/share/ingetrazo/plugins/select_curve.py`
- **Windows:** `%APPDATA%\ingetrazo\plugins\select_curve.py`

Restart IngeTrazo (or hot-reload via the Extensions menu). The **Select Curve** icon will appear on your main toolbar and under **Tools** / **Extensions**.

---

## License

MIT License. Copyright (c) 2026 Remi Anton and IngeTrazo contributors.
