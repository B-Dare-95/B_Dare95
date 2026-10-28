# CAD to Lines

> ⚡ **TL;DR**
> Turns the lines of a **linked or imported CAD** into **Revit detail lines** in the active view. Two buttons:
> **All Lines** draws every layer in **one** line style. **By Layers** lets you give **each group of layers its own** line style.
>
> **All Lines**
> 1. Open the view, select the CAD (or click the button and pick it).
> 2. Pick a line style, press **Convert** (or double-click the style).
>
> **By Layers**
> 1. Open the view, select the CAD (or click the button and pick it).
> 2. Pick layers on the left, a line style in the middle, press **Bind**. Repeat for each group.
> 3. Press **Convert**. Only bound layers are drawn.
>
> ⚠️ Works only in plan, section, elevation, detail, drafting and legend views. Points, solids and fills are ignored, very short curves are skipped, and tilted or unsupported curves become straight segments.

🎬 *[GIF, ~15 s: select a CAD in a floor plan → By Layers → bind walls layers to one style and door layers to another → Convert → the new detail lines are selected]*

*📍 B-Dare95 tab → CAD panel → CAD to Lines ▾ → All Lines / By Layers · 🧩 Revit 2024+ · 👤 Mohamed Bedair · 🗓️ 28 Oct 2026*

---

# 📖 Full guide

*Everything below is reference. You only need it if the TL;DR didn't answer your question.*

## 1. What this tool does

A CAD file sitting in Revit is one element. You can't edit, restyle or delete its lines one by one.

**CAD to Lines** reads every line, arc and polyline inside the CAD (including inside blocks) and draws a matching **detail line** in the view you have open. The new lines are **selected** when it finishes, so you can check them straight away.

The CAD itself is left untouched. It works the same for **linked** and **imported** CAD.

---

## 2. Which button to use

| | **All Lines** | **By Layers** |
|---|---|---|
| Line styles | **One** style for everything | A **different** style per group of layers |
| Layers converted | **All** of them | Only the layers you **bind** |
| Window | One list: **LINE STYLE** | Three columns: **CAD LAYERS**, **LINE STYLE**, **BINDINGS** |
| Good for | Quick tracing, background linework | Clean drawings where walls, doors, furniture etc. need their own line weights, or when you only want some layers |

> 💡 Want only a few layers, all in the same style? Use **By Layers** and bind just those layers to one style.

---

## 3. How to use All Lines

1. Open the view you want the lines in (plan, section, elevation, detail, drafting or legend view).
2. *(Optional)* Select the CAD.
3. Click **CAD to Lines ▾ → All Lines**.
4. If you didn't select exactly one CAD, the yellow bar at the top says **"Pick the CAD to convert"**. Click the CAD. Only CAD can be picked. Press **Esc** to stop.
5. The **CAD to Detail Lines** window opens. The line under the title shows the CAD name and the view name.
6. Pick a style in the **LINE STYLE** list. Type in **Search line styles** to filter the list.
7. The bottom bar shows **All layers · _ lines → (your style)**. Press **Convert**, or just double-click the style.
8. If the CAD has more than 5,000 lines, you're asked to confirm first.
9. A message tells you how many detail lines were created. They're selected for you.

To stop without changing anything, press **Cancel**, the **✕** in the corner, or **Esc**. You can drag the window by its title.

---

## 4. How to use By Layers

Steps 1 to 4 are the same as All Lines: open the view, then select or pick the CAD. The **CAD to Detail Lines** window opens with three columns.

📸 *[Screenshot: the By Layers window with CAD LAYERS on the left, LINE STYLE in the middle and two binding cards on the right]*

### 4.1 The CAD LAYERS column

- Every layer in the CAD is listed, with its **number of lines** on the right. Geometry without a layer shows as **(no layer)**.
- **Click** a layer to select it, **click again** to unselect it. You can select as many as you like, no Ctrl needed.
- **Search layers** filters the list.
- **Select all** / **Clear** select or unselect the layers **currently shown** (so you can search first, then **Select all**).
- Once a layer is bound, its line style shows next to it in yellow.
- **Hide bound** hides layers that are already bound, so you only see what's left to do.

### 4.2 Binding layers to a line style

1. Select one or more layers on the left.
2. Pick a line style in the middle (**Search line styles** filters it).
3. Press **Bind _ layer(s)**, or double-click the style.

The layers are unselected, ready for the next group. Repeat for each group of layers.

> ℹ️ Binding a layer that's already bound **moves** it to the new style. A layer can only have one style.

### 4.3 The BINDINGS column

Each line style you've used gets a card showing:

- the **style name** and how many **lines** it will draw,
- **Remove**, to unbind every layer from that style,
- the bound layers, each with a **✕** to unbind just that layer.

**Clear all** removes every binding. Before anything is bound, the column says **"Pick one or more layers, pick a line style, then press Bind. Repeat for the next group."**

### 4.4 Converting

The bottom bar shows **Nothing bound yet** until you bind something, then **_ line style(s) · _ layer(s) · _ lines ready**.

Press **Convert**. If the bound layers have more than 5,000 lines, you're asked to confirm. Layers you didn't bind are **not** drawn. A message lists how many lines were drawn in each style, and the new lines are selected.

---

## 5. What gets created

| CAD content | What you get |
|---|---|
| Lines | **Detail lines** |
| Arcs and other curves lying flat in the view | Detail curves of the **same shape** |
| Polylines | A chain of **straight detail lines** |
| Curves that are **tilted** to the view | Flattened into **straight segments** (straight lines stay single lines) |
| Curves Revit refuses to draw as they are | Redrawn as **straight segments** |
| Blocks, including blocks inside blocks | Opened up. Their lines are drawn in the right place, size and rotation |
| Points, solids, fills and other non-line objects | **Ignored** (counted in the result message) |
| Curves shorter than Revit's minimum line length | **Skipped** (counted in the result message) |

**Where the lines go**

- Detail lines are drawn in the **active view only**.
- Allowed views: **floor plans, ceiling plans, structural plans, area plans, sections, elevations, detail views, drafting views and legends**. Not 3D views, sheets or schedules.
- Lines are placed where the CAD's lines actually sit in the model, then flattened onto the view's plane: the view's work plane if it has one, otherwise the plan's level, otherwise the view itself.
- Lines inside blocks are moved into place using each block's position. If Revit can't move a curve out of a block as it is, the tool falls back to a chain of straight segments.

**Line styles you can pick**

Every style under **Lines** in your project, except ones reserved for other tools: Room Separation, Space Separation, Area Boundary, Sketch, Insulation Batting and Axis of Rotation lines. If Revit still refuses a style for detail lines, nothing is drawn (see [Section 7](#7-messages-you-may-see)).

---

## 6. Undoing

The whole run is **one** step in Revit's Undo list: **CAD to Detail Lines**. Press **Ctrl + Z** to remove every line it created.

It's all or nothing. If a line style is refused, or Revit hits an unexpected error during the run, everything is rolled back and nothing is drawn.

---

## 7. Messages you may see

| Message | Why | What to do |
|---|---|---|
| 🟢 **"Created _ detail lines in '(view)', drawn as '(style)'."** | **All Lines** worked. | Check the selected lines. |
| 🟢 **"Created _ detail lines in '(view)'."** followed by **"(style): _ lines from _ layer(s)"** | **By Layers** worked. One row per line style. | Check the selected lines. |
| 🔵 **"_ curves were redrawn as straight segments."** | Some curves were tilted to the view, or Revit wouldn't draw them as they were. | Usually fine. Check curved areas if accuracy matters. |
| 🔵 **"_ curves were too short for Revit and were skipped."** | They're below Revit's minimum line length. | Usually tiny fragments. Nothing to do. |
| 🔵 **"_ non-line objects (points, solids, fills) were ignored."** | Only lines, arcs and polylines are converted. | Nothing to do. |
| 🟡 **"This CAD has _ lines. Converting them may take a while. Continue?"** *(All Lines)* / **"The bound layers have _ lines. …"** *(By Layers)* | More than 5,000 lines to draw. | **Yes** to carry on, **No** to stop. Consider **By Layers** to convert fewer layers. |
| 🟡 **"No lines were found in '(CAD)'."** | The CAD has no lines, arcs or polylines the tool can read. | Check you picked the right CAD. |
| 🟡 **"_ curves could not be drawn."** | Revit refused these, even as straight segments. | Check the result. If many are missing, contact the author. |
| 🔴 **"Detail lines can't be drawn in this view. Open a plan, section, elevation, detail or drafting view and try again."** | The active view is a 3D view, sheet, schedule or similar. | Open a supported view and run it again. |
| 🔴 **"'(style)' can't be used for detail lines. Nothing was changed. Run the tool again and pick another line style."** *(By Layers ends: "…bind those layers to another line style.")* | Revit doesn't allow that style on detail lines. | Run it again with a different style. |

---

## 8. FAQ & troubleshooting

**Nothing happened when I clicked the button.**
You probably pressed **Esc** while picking, or closed the window. Nothing was changed. Run it again.

**I selected two CADs but it asked me to pick one.**
The tool converts one CAD per run. If more or fewer than one CAD is selected, it asks you to pick.

**Can I pick a Revit link?**
No. Only linked or imported CAD can be picked.

**Some layers didn't come through (By Layers).**
Only **bound** layers are drawn. Check the **BINDINGS** column before pressing **Convert**. Turn on **Hide bound** to see what's still unbound.

**My arcs came out as many short straight lines.**
That happens when the arc is tilted to the view, sits inside a block Revit can't move it out of cleanly, or Revit refused the curve type. Polylines always come out as straight segments.

**The line count in the window doesn't match the number of lines created.**
The window counts CAD objects. One polyline counts as one, but it becomes several detail lines. Skipped and ignored items also make the numbers differ.

**A layer called "(no layer)" appears.**
That's CAD geometry Revit couldn't link to a layer. Bind it like any other layer, or leave it unbound.

**Can I delete the CAD afterwards?**
Yes. The detail lines are separate Revit elements and don't depend on the CAD.

---

## 9. Contact the author

If your problem isn't solved by the steps above, **please don't try to fix the tool yourself**. Contact:

> 👤 **Mohamed Bedair**

**Please include:** a screenshot of the message you got, which button you used (**All Lines** or **By Layers**), the **CAD file name**, the **view name**, your **Revit version**, and the **model name**.
