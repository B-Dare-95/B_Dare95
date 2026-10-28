# DWG to RVT

> ⚡ **TL;DR**
> Turns a **linked or imported DWG plan** into real Revit **walls, railings, doors, windows, columns and grids**. You decide which layer becomes what, and which type to use.
>
> 1. Link or import the DWG into a plan view, then click **DWG to RVT**.
> 2. Pick the drawing in **Source DWG**.
> 3. For each layer, set the **Category**, then pick one type (**Single**) or add size rules (**Multiple**).
> 4. Click **Create Elements**. The new elements are selected for you.
>
> ⚠️ Doors and windows need a wall on the DWG's level under their symbol. In **Single** mode, walls drawn as two lines are only found between 20 and 600 mm thick. **Replace previous result** deletes what the tool made from this DWG last time, including any edits you made to it.

🎬 *[GIF, ~15 s: open DWG to RVT → map the wall, door and column layers → Create Elements → walls, doors and columns appear on the plan, selected]*

*📍 B-Dare95 tab → CAD panel → DWG to RVT · 🧩 Revit 2024+ · 👤 Mohamed Bedair · 🗓️ 28 Oct 2026*

---

# 📖 Full guide

*Everything below is reference. You only need it if the TL;DR didn't answer your question.*

## 1. What this tool does

**DWG to RVT** reads the lines on each layer of a DWG plan and builds Revit elements from them. Each layer is mapped to one category:

| Category | What the tool builds from the layer |
|---|---|
| **Walls** | Walls along each line, or along the centerline between two parallel lines |
| **Railings** | Railings along each line (or between two parallel lines). Connected lines become one railing |
| **Doors** / **Windows** | One door or window per symbol, hosted in the wall underneath |
| **Columns** | One column per outline, rotated to match it |
| **Grids** | Grid lines, numbered and lettered for you |
| **Ignore** | Nothing. The layer is skipped (this is the default) |

> 💡 Think of it as tracing paper in reverse: you tell Revit what each layer means, and it does the tracing.

---

## 2. How to use it

1. Link or import the DWG plan into a **plan view**.
2. Go to **B-Dare95** tab → **CAD** panel → **DWG to RVT**. The **DWG to Revit** window opens.
3. At the top, pick the drawing in **Source DWG**. Each entry shows the DWG name, whether it's **Linked** or **Imported**, and the view it's in if it was placed in **current view only**. The last DWG you used is picked for you.
4. The status line at the bottom tells you how many layers were read and which level the elements will go on.
5. Use **Filter layers...** to find layers by name. Each row shows the layer name and how many curves and blocks it holds.
6. For each layer you want to use, fill in the row:
   - **CATEGORY**: what the layer becomes.
   - **DRAW FROM** *(Walls and Railings only)*: **Single line** or **Two lines** (see [Section 3](#3-single-line-or-two-lines)).
   - **MODE**: **Single** or **Multiple** (see [Section 4](#4-single-or-multiple-types)).
   - **FAMILY TYPE**: the type to use (in **Single** mode).
7. Leave **Replace previous result** on if you're re-running after the drawing changed (see [Section 6](#6-what-gets-created-and-where)).
8. Click **Create Elements**. Click **Cancel** to close without doing anything.
9. A **Build finished** window lists what was made, plus any notes. The new elements are **selected**, ready for you to check.

📸 *[Screenshot: the DWG to Revit window with a wall layer in Multiple mode and its rule list open]*

---

## 3. Single line or Two lines

For **Walls** and **Railings** you choose how the path is found:

| | **Single line** | **Two lines** |
|---|---|---|
| Path | Each drawn line (or arc) becomes the element's path | The centerline between two parallel lines becomes the path |
| Size used for rules | None, so only **Single** mode is available | The distance between the two lines |
| Default for | **Railings** | **Walls** |

With **Two lines**, the tool also tidies the walls:

- Curved walls are found from pairs of arcs that share a centre.
- Pieces in a straight line with the same thickness are joined into one wall.
- Gaps up to 3000 mm are closed when a **door or window symbol** sits in the gap. This only works if the door and window layers are mapped in the **same run**.
- Wall ends are extended to meet a crossing wall, so L corners and T junctions close up.

---

## 4. Single or Multiple types

| Mode | What happens |
|---|---|
| **Single** | Every element on the layer gets the type in **FAMILY TYPE**. |
| **Multiple** | You add **size rules**. Each element gets the type of the **first rule its size matches**. |

**Multiple** is available for **Walls**, **Railings**, **Doors**, **Windows** and **Columns**, but not for walls or railings drawn from a **Single line**. **Grids** always use one type.

**Setting up rules:**

1. Click **Multiple**. A first rule is added and the rule list opens.
2. In each rule, pick a **FAMILY TYPE**, an **EVALUATOR**, and type the **SIZE (MM)**.
3. Click **+ Add rule** for more rules. Click **✕** to remove one.
4. The **FAMILY TYPE** dropdown on the row turns into an **Add Rules** button. Click it to show or hide the rule list.

> ⚠️ Rules are checked **top to bottom**, and the first match wins. Put the narrow rules (**Equal**) above the wide ones (**Greater than**, **Less than**).

> ⚠️ Changing a layer's **CATEGORY** clears its rules.

**Evaluators:**

| Evaluator | Matches when the measured size is… |
|---|---|
| **Equal** | Within ±2 mm (walls, railings) or ±5 mm (doors, windows, columns) |
| **Greater than** | More than the value |
| **Less than** | Less than the value |
| **Greater or equal** | The value or more (same small tolerance as Equal) |
| **Less or equal** | The value or less (same small tolerance as Equal) |

**Columns** have two size boxes, width **×** length. The order doesn't matter: a 300 × 600 rule also catches a 600 × 300 outline. Switch on **ONE SIZE** for square or round columns and type one number. On a rectangular outline, one size means both sides must match.

---

## 5. How sizes are measured

| Category | Size compared with your rules | Good to know |
|---|---|---|
| **Walls**, **Railings** *(Two lines)* | Distance between the two parallel lines | In **Single** mode, only pairs 20 to 600 mm apart are used |
| **Doors**, **Windows** | Width of the symbol measured **along the wall** | Symbols smaller than 200 mm or larger than 6000 mm are ignored |
| **Columns** | Width and length of the outline | An outline with no straight lines is treated as **round** (one size). Outlines under 50 mm or over 3000 mm are ignored |
| **Grids** | Not measured | Lines shorter than 1000 mm and arcs with a radius under 3000 mm are ignored |

**How symbols are grouped** (doors, windows, columns): each **block** in the DWG is one symbol. Loose lines are grouped together when they touch or nearly touch (within 20 mm).

---

## 6. What gets created and where

**Level.** Everything goes on the **DWG's own level**: the level of the plan view it sits in (if placed in current view only), otherwise its **Base Level**. The status line names it before you build.

**Heights.**

| Element | Top |
|---|---|
| **Walls** | Up to the **next level above**. On the top level: 3000 mm high |
| **Columns** | Up to the **next level above**. On the top level: 3000 mm above the base level |

**Doors and windows** are hosted in the wall under the symbol. It must be a wall on the DWG's level: either one that's already there, or one this run just made (walls are built first). The tool tries to match each door's swing side and hinge side to the drawn swing.

**Columns** from a structural column family are placed as **structural columns**. Each column is rotated to match its outline.

**Grids** run left to right as **1, 2, 3…** for vertical lines, and top to bottom as **A, B, C…** for horizontal lines (I and O are skipped). Names already used in the project are skipped. Pieces of the same line become one grid, and a line that already has a grid is skipped. Curved grids get numbers.

**Replace previous result** *(on by default)*:

| | **On** | **Off** |
|---|---|---|
| Elements made earlier from this DWG | **Deleted** first, then rebuilt | Kept. New elements are added alongside |
| Elements you drew yourself | Not touched | Not touched |
| Good for | Rebuilding cleanly after the drawing changed | Adding a layer you skipped last time |

> ⚠️ With **Replace previous result** on, any edits you made to the tool's elements are lost, because they're deleted and rebuilt.

**Settings saved in the project.** When you click **Create Elements**, the layer mapping and rules are saved in the project, by DWG name. The **Replace previous result** setting and the last DWG used are saved too. Next time you open the tool on the same DWG, everything is filled in. **Cancel** saves nothing.

---

## 7. Undoing

The whole run is **one** step in Revit's Undo list: **DWG to Revit**. Press **Ctrl + Z** to put everything back as it was, including any previous result that was replaced.

Each category is built in its own step inside the run. If one fails (for example walls), only that category is rolled back. The others are still built, and the failure is listed in the notes.

---

## 8. Messages you may see

| Message | Why | What to do |
|---|---|---|
| 🟢 **"Build finished"** with lines like **"Walls: _"**, **"Previous result removed: _"** | It worked. Counts are listed per category. | Check the selected elements. Read any **Notes:** below the counts. |
| 🟡 **"Nothing was created."** | No element could be built. | Read the notes below it. |
| 🔴 **"No linked or imported DWG was found in this project."** | There's no DWG in the model. | Link the DWG plan into a plan view first. |
| 🟡 **"No curves found in this DWG. Is it loaded and visible?"** | The tool couldn't read any lines. | Check the DWG is loaded and visible. |
| 🟡 **"Couldn't find the DWG's level. Link it into a plan view or set its Base Level."** | The tool doesn't know where to place elements. | Do one of the two. |
| 🟡 **"Pick a DWG with layers first."** | No DWG picked, or it has no layers. | Pick a DWG in **Source DWG**. |
| 🟡 **"Map at least one layer to an element category."** | Every layer is set to **Ignore**. | Set a **CATEGORY** on at least one layer. |
| 🟡 **"Layer '_': no _ types are loaded in the project."** | There's no type of that category to use. | Load a family or type, then run again. |
| 🟡 **"Layer '_': add at least one rule."** | **Multiple** mode with no rules. | Click **+ Add rule**, or switch to **Single**. |
| 🟡 **"Layer '_', rule _: every size box needs a number in mm."** | A size box is empty, zero or not a number. | Type a positive number in mm. |
| 🔵 **"Walls: no rule matches _ mm"** *(also Railings, Columns, or "Doors: no rule matches width _ mm")* | An element's size didn't match any rule. | Add a rule for that size. |
| 🔵 **"Walls: the size rules don't allow any thickness"** | The rules can't match any wall thickness. | Check the evaluators and sizes. |
| 🔵 **"Doors: no wall found under the symbol"** *(or Windows)* | No wall on the DWG's level under that symbol. | Map the wall layer in the same run, or add the wall. |
| 🔵 **"Doors: drawing piece ignored (too small or too large)"** *(or Windows)* | The symbol is under 200 mm or over 6000 mm. | Check the layer only holds door or window symbols. |
| 🔵 **"Columns: outline ignored (too small or too large)"** | The outline is under 50 mm or over 3000 mm. | Check the layer only holds column outlines. |
| 🔵 **"Grids: line already has a grid, skipped"** | There's already a grid on that line. | Nothing to do. |
| 🔵 **"Layer '_': the chosen type no longer exists"** / **"a rule's type no longer exists, rule skipped"** | A saved type was deleted or renamed. | Pick the type again. |
| 🔴 **"Wall skipped: …"**, **"Column skipped: …"**, **"Grid skipped: …"** *(and similar)* | Revit refused that one element. | The others were still made. If it keeps happening, contact the author. |
| 🔴 **"DWG to Revit - Walls failed: …"** *(or another category)* | That whole category was rolled back. | Screenshot it and contact the author. |

A **(x_)** after a note means it happened that many times.

---

## 9. FAQ & troubleshooting

**My doors and windows weren't placed.**
They need a wall on the DWG's level under the symbol. Map the wall layer in the same run, or check the existing walls are on that level.

**My walls stop at every door opening.**
Map the door and window layers in the **same run**. The tool only closes gaps where it finds a door or window symbol.

**Two doors became one big door (or one wasn't recognised).**
Loose lines that touch are grouped as one symbol. Doors drawn as **blocks** in the DWG are always kept separate.

**A wall layer gave me nothing.**
Check **DRAW FROM**. With **Two lines**, the tool needs pairs of parallel lines. In **Single** mode they must be 20 to 600 mm apart. If your walls are drawn as one line, switch to **Single line**.

**Every wall got the same type.**
Switch the layer to **Multiple** and add one rule per thickness, for example **Equal 100** → a 100 mm wall type.

**Can I rebuild after the architect updates the DWG?**
Yes. Reload the DWG, keep **Replace previous result** on, and click **Create Elements**. Your mapping is remembered. If you delete the DWG and link it again, your mapping is still remembered by name, but the tool can't find the old result to replace. Delete the old elements yourself.

**Does it change the size of my types?**
No. It only picks from the types already in the project. Load or create the types you need first.

---

## 10. Contact the author

If your problem isn't solved by the steps above, **please don't try to fix the tool yourself**. Contact:

> 👤 **Mohamed Bedair**

**Please include:** a screenshot of the **Build finished** window **with its notes**, the **DWG name**, your **Revit version**, and the **model name**.
