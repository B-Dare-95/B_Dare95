# Split at Beams

> ⚡ **TL;DR**
> Fits walls to the structure: the **base sits on the structural slab below**, the **top stops under the slab above**, and the wall is **cut where beams pass through**. Beams and slabs can come from your model and from loaded links.
>
> 1. Select the walls → **Modify | Walls** tab → **B95-Walls** panel → **Split at Beams**.
> 2. Choose what to fit to (slabs, beams) and where to read them from (your model, links), then click **Run**.
> 3. Check the summary and click **Yes**. Then draw a box around more walls, or press **Esc** to stop.
>
> ⚠️ Only straight Basic walls that aren't pinned, grouped, attached or profile-edited. Doors and windows that fit no piece are removed (you're asked first). Only the offsets change, never the base and top levels.

🎬 *[GIF, ~10 s: select a wall that runs through a beam → Modify | Walls → B95-Walls → Split at Beams → Run → Yes → the wall now sits on the slab, stops under the slab above and is cut around the beam]*

*📍 Select a wall → Modify | Walls tab → B95-Walls panel → Split at Beams · 🧩 Revit 2024+ · 👤 Mohamed Bedair · 🗓️ 28 Oct 2026*

---

# 📖 Full guide

*Everything below is reference. You only need it if the TL;DR didn't answer your question.*

## 1. What this tool does

Walls are often modelled from level to level, so they run **into the slabs** and **through the beams**. **Split at Beams** trims each wall to the structure around it:

| Where the structure is… | What happens to the wall |
|---|---|
| A **structural slab below** the wall | The wall's **base moves to the top of the slab** |
| A **structural slab above** the wall | The wall's **top moves to the underside of the slab** |
| A **beam right under the slab** above | The wall's top is **lowered under the beam** along the beam's length |
| A **beam in the middle** of the wall | The wall is **cut around the beam**: pieces beside, below and above it |
| A **slab partway up** the wall (a wall drawn over several storeys) | The wall is **cut at that slab** |

Beams and slabs can be in **your model**, in **any loaded link**, or both. Links are only read, never changed.

> 💡 Think of it as fitting a sheet of plasterboard between floor and ceiling and cutting notches where the beams come through.

📸 *[Screenshot: wall elevation before (running through slabs and a beam) and after (sitting on the slab, stopping under it, cut around the beam)]*

---

## 2. What changes and what doesn't

| ✅ Changes | ❌ Stays the same |
|---|---|
| **Base Offset** | **Base Constraint** (the base level) |
| **Top Offset**, or **Unconnected Height** if the wall has no top level | **Top Constraint** (the top level) |
| The wall's **length**, where it's cut into pieces | Wall **type** and parameters (each piece is a copy of the original) |
| | **Linked models** (only read) |

**When a wall is cut into pieces:**

- The **original wall becomes the largest piece**. It keeps its **ID**, its **tags** and its place in **schedules**.
- The other pieces are **copies** of the original, so they have **new IDs**.
- Every piece is a **rectangle** in elevation.
- At the new ends next to beams, walls are **allowed to join**. The wall's original outer ends keep the **join setting they had**.

---

## 3. How to use it

1. **Select the wall(s)** you want to fit. As soon as at least one wall is selected, the **B95-Walls** panel appears in the **Modify | Walls** tab.
2. Click **B95-Walls** → **Split at Beams**. The options window opens (title: **Split Walls at Beams & Slabs**).
3. Set the options (see [Section 4](#4-the-options-window)) and click **Run**. Your choices are **remembered** for next time.
4. If you chose **Pick walls (rectangle)**, your selected walls are checked first.
   - If you chose **All walls in active view**, **every wall in the view** is checked instead, not just your selection.
5. With more than 15 walls, a **Checking walls** progress bar appears. You can cancel it; nothing changes.
6. A **summary** shows how many walls will be adjusted and how many pieces they'll become. Click **Yes** to apply, **No** to cancel.
   - If some doors, windows or openings would be lost, you get three choices instead (see [Section 6](#6-doors-windows-and-openings)).
7. An **Adjusting walls** progress bar runs, then **Round complete.** shows the result.
8. With **Pick walls**, you're asked **"Select more walls?"**. Click **Yes**, then draw a box around more walls (the status bar says **"Draw a rectangle around the walls to cut (only walls are picked)"**). Click **No**, or press **Esc** while drawing, to finish.

> 💡 **All walls in active view** runs one round only. There's no "Select more walls?" at the end.

---

## 4. The options window

| Section | Option | What it does |
|---|---|---|
| **FIT WALLS TO** | **Structural slabs (base & top)** | Moves the base onto the slab below and the top under the slab above. Also cuts walls at slabs they pass through. |
| | **Beams (lower top / cut)** | Lowers the top under beams and cuts walls where beams pass through. |
| **READ BEAMS AND SLABS FROM** | **Active model** | Uses beams and slabs in the model you have open. |
| | **Loaded links** | Uses beams and slabs in every loaded Revit link. Unloaded links are skipped. |
| **WALLS TO PROCESS** | **Pick walls (rectangle)** | Your selected walls first, then you can keep drawing boxes until you stop. |
| | **All walls in active view** | Every wall visible in the current view, in one go. |

Each option is a toggle (yellow = on). You need at least **one of Slabs / Beams** and at least **one of Active model / Loaded links**, or the window shows a red note and won't run.

---

## 5. How the walls are fitted

### What counts as a slab or a beam

- **Slabs:** Floors with **Structural** ticked. Non-structural Floors (finishes, screeds) are ignored.
- **Beams:** elements in the **Structural Framing** category. **Braces** are ignored.
- A beam or slab only counts if it goes at least **10 mm into the wall's thickness**. The tool uses the wall's **real faces**, wherever its location line is.

### Base and top

- **Slab below:** a structural slab whose top is within **1000 mm** of the wall's current base. The base moves to the **top of that slab**. If the slab steps down inside the wall's footprint (a drop or sunken area), the **lowest top** is used.
- **Slab above:** a structural slab whose top is within **1000 mm** of the wall's current top. The top moves to the **underside of that slab**. If the underside steps, the **highest underside** is used.
- **No slab within 1000 mm:** that end of the wall is **left where it is**, and the result says how many walls this happened to.

### Cuts

| Situation | Result |
|---|---|
| Beam whose top is within **50 mm** of the slab underside | The wall's top is lowered to the **bottom of the beam** along the beam's length |
| Beam whose bottom is within **50 mm** of the slab top | The wall starts at the **top of the beam** along the beam's length |
| Beam in the middle of the wall | Pieces **beside** the beam, and **below and above** it |
| Sloped or irregular beam | Cut out as the **rectangle that encloses it** inside the wall |
| Two cut lines less than **50 mm** apart, or less than 50 mm from the wall's end | Merged, so no thin sliver pieces are made |
| Wall fully inside beams | **Skipped**, left untouched |
| Wall already fits (within about 2 mm) | Counted as **Already fitted**, not changed |

> ℹ️ If the wall **cuts** a beam or slab in your model (through **Join Geometry**), the tool briefly unjoins them to measure the beam or slab's full shape, then puts everything back. Nothing from that check is saved.

---

## 6. Doors, windows and openings

- Each door, window, opening or wall-hosted family **stays on the piece it fits in**, with its type and values unchanged.
- If the wall is only made taller or shorter (not cut along its length), **everything stays** on it.
- If an element **fits no piece** (for example it sits where a beam cuts the wall), it can't be kept. **Before anything changes**, the summary lists those elements and their walls by ID, and you choose:

| Choice | What happens |
|---|---|
| **Adjust all _ walls (remove the _ hosted element(s))** | Every wall is adjusted. The listed elements are **deleted**. |
| **Skip the _ wall(s) above, adjust the other _** | The walls holding those elements are **left unchanged**. All other walls are adjusted. |
| **Cancel** | Nothing changes. |

If you removed elements, **Round complete.** lists their IDs under **"Hosted elements removed (fit no piece) - re-place manually:"**.

---

## 7. Walls that are skipped

Skipped walls are left unchanged and listed under **Skipped:** with the reason.

| Reason shown | What to do |
|---|---|
| **part of a stacked wall** / **not a Basic wall (stacked/curtain)** | Not supported. Only Basic walls. |
| **not a straight wall** | Curved walls aren't supported. |
| **inside a group** | Ungroup, or edit the group, then run again. |
| **pinned** | Unpin the wall. |
| **top or base attached (detach first)** | Use **Detach Top/Base**, then run again. |
| **has an edited profile** | Reset the profile, or adjust that wall by hand. |
| **wall lies entirely inside beams (left untouched)** | Nothing would be left of the wall. Check it's meant to be there. |
| **wall too short** / **zero height** | The wall is too small to work with. |
| **no location curve** / **could not read wall type** / **could not read base constraint** | Revit couldn't read the wall. Contact the author if unexpected. |
| **analysis error: …** | Unexpected problem. Screenshot it and contact the author. |

---

## 8. Undoing

Each **round** (one set of walls + **Yes**) is a single step in Revit's Undo list: **Split Walls at Beams & Slabs**. Press **Ctrl + Z** once to undo the whole round. If you ran several rounds, undo once per round.

- Each wall is handled on its own. If one fails, only that wall is left unchanged; the others are still adjusted.
- If you **cancel the Adjusting walls** progress bar, the walls already done **stay adjusted** and the rest are left unchanged. **Ctrl + Z** undoes the walls that were done.
- Revit's own warnings during the run are **dismissed automatically**, and errors get Revit's **default fix** (for example **Unjoin Elements**). They're listed at the end under **"Revit messages answered automatically:"**. An error with no fix leaves that wall unchanged.

---

## 9. Messages you may see

All messages appear in a window titled **Split Walls at Beams & Slabs**.

| Message | Why | What to do |
|---|---|---|
| 🟢 **"Round complete."** + **"Walls adjusted: _ / _"** + **"Resulting walls: _"** | It worked. Extra lines may follow (see below). | Read any extra lines. **Yes** to pick more walls, **No** to finish. |
| 🔵 **"Walls checked: _"** … **"Proceed?"** | Summary before any change, incl. **"Walls to adjust: _ -> _ wall(s) after cutting at beams"**, **"Slabs used / Beams involved"** and **"Already fitted"**. | **Yes** to apply, **No** to cancel. |
| 🟡 **"_ hosted element(s) fit no piece and would be REMOVED:"** | Some doors, windows or openings won't fit any piece. | See [Section 6](#6-doors-windows-and-openings). |
| 🟡 **"None of the _ wall(s) need adjusting."** | The walls already fit, or were all skipped. | Check the **Already fitted** and **Skipped** lines. |
| 🟡 **"No structural slab within 1000 mm - that end was kept:"** + **"below _ wall(s), above _ wall(s)"** | No structural slab near the base or top of some walls. | Check the slab is a Floor with **Structural** ticked and the link is loaded. |
| 🟡 **"Skipped: _"** + reasons | Some walls can't be processed. | See [Section 7](#7-walls-that-are-skipped). |
| 🟡 **"Left unchanged to keep their hosted elements (_ wall(s)):"** | You chose to skip walls that would lose elements. | Nothing to do, or adjust them by hand. |
| 🟡 **"Hosted elements removed (fit no piece) - re-place manually:"** | You chose to remove them. | Re-place them, or **Ctrl + Z**. |
| 🟡 **"Every wall to adjust would lose a hosted element - nothing was changed."** | You chose to skip those walls, and that was all of them. | Run again and choose **Adjust all**, or move the elements first. |
| 🟡 **"Stopped by you - the last _ wall(s) were left unchanged."** | You cancelled the Adjusting walls progress bar. | Run again on the remaining walls if needed. |
| 🟡 **"Cancelled - nothing was changed."** / **"Check cancelled - nothing was changed."** | You said **No**, chose **Cancel**, or cancelled the check. | Nothing to do. |
| 🟡 **"No walls were picked. Select more walls?"** | Your box didn't catch any walls. | **Yes** and draw a bigger box. |
| 🟡 **"No walls in the active view."** | **All walls in active view** found none. | Open a view with walls, or use **Pick walls**. |
| 🟡 **"Choose at least one of Beams / Slabs."** / **"Choose at least one of Active model / Loaded links."** *(red, in the options window)* | A whole group of options is off. | Turn at least one on. |
| 🟡 **"Unloaded links skipped: …"** | Those links weren't loaded, so their beams and slabs weren't used. | Load them and run again if they matter. |
| 🔵 **"Revit messages answered automatically:"** | Revit warnings or errors were handled for you. | Read them if the result looks odd. |
| 🔵 **"Wall _: joined elements could not be unjoined for measuring; their cut geometry was used."** | The tool couldn't measure the full beam or slab shape for that wall. | Check that wall's result. |
| 🔴 **"Slabs that could not be intersected (ignored):"** | Revit couldn't work out where those slabs meet the wall. | Check those walls by hand. |
| 🔴 **"Walls left unchanged due to errors:"** + **"Wall _: …"** | Revit refused the change for those walls (e.g. **"Revit rejected the result (…)"**). | Note the IDs and the message. Contact the author if unclear. |
| 🔴 **"No source to read beams/slabs from (active model is off and no link is loaded)."** | Only **Loaded links** was on, and no link is loaded. | Load a link, or turn **Active model** on. |

---

## 10. FAQ & troubleshooting

**I only selected two walls, but it changed walls all over the view.**
The options window remembers your last choice. If **All walls in active view** was on, every wall in the view is processed. Switch to **Pick walls (rectangle)**.

**The base didn't move onto the slab.**
The slab must be a **Floor** with **Structural** ticked, and its top must be within **1000 mm** of the wall's base. Foundation slabs (Structural Foundation category) aren't read. If it's in a link, the link must be loaded and **Loaded links** turned on.

**The wall still overlaps part of the slab.**
Where a slab steps, the base goes to its **lowest top** and the top goes to its **highest underside**. Around a thicker or raised part of the slab, the wall can still overlap it.

**A beam didn't cut the wall.**
It must be in **Structural Framing** (braces are ignored) and go at least **10 mm** into the wall's thickness. Check **Beams** and the right source are turned on.

**My door or window disappeared.**
It fit no piece and you chose **Adjust all**. Its ID is in the **Round complete.** report. Undo with **Ctrl + Z** and choose **Skip the _ wall(s) above** instead, or re-place it by hand.

**My tags are gone from some pieces.**
Tags stay on the original wall, which becomes the **largest piece**. The other pieces are new walls, so tag them yourself.

**Why are my wall's levels unchanged?**
On purpose. Only **Base Offset** and **Top Offset** (or **Unconnected Height**) change.

**Does it also cut walls at columns?**
No. It only reads beams and structural slabs. For columns, use **Split at Columns**.

**Does it change walls in a linked model?**
No. Only walls in the model you have open. Links are only read for beams and slabs.

---

## 11. Contact the author

If your problem isn't solved by the steps above, **please don't try to fix the tool yourself**. Contact:

> 👤 **Mohamed Bedair**

**Please include:** a screenshot of the **Round complete.** window (or the error), an **elevation or section** showing the wall and the beams/slabs, the **wall IDs**, your **Revit version**, and the **model name**.
