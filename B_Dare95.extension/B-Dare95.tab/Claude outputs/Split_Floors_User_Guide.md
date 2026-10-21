# Split Floors

> ⚡ **TL;DR**
> Turns **one Floor drawn with several separate outlines** into **one Floor per outline**. Type, level and parameters carry over.
>
> 1. Select the Floors (or click the button and pick them, then **Finish**).
> 2. **Click** = split and delete the original. **Shift + Click** = split and keep the original.
> 3. Done. The new Floors are selected for you.
>
> ⚠️ **Mark** isn't copied, slab shape edits and slope arrows are lost (new Floors are flat), and anything hosted on the original is deleted with it (you're asked first).

🎬 *[GIF, ~10 s: select a Floor with 3 separate outlines → click Split Floors → it becomes 3 Floors, each selectable on its own]*

*📍 Modify panel → Floors ▾ → Split Floors · 🧩 Revit 2024+ · 👤 Mohamed Bedair · 🗓️ 21 Oct 2026*

---

# 📖 Full guide

*Everything below is reference. You only need it if the TL;DR didn't answer your question.*

## 1. What this tool does

In Revit, one Floor's sketch can hold **several closed outlines** that don't touch: for example two balconies, or four separate slab pieces drawn in one go. Revit treats them as **one element**, so you can't tag, schedule, offset or delete them separately.

**Split Floors** rebuilds that Floor as **separate Floors, one per outline**.

| In the original sketch… | After the split… |
|---|---|
| Separate outlines side by side | **One Floor each** |
| A hole (e.g. a shaft opening) inside an outline | **Stays a hole** in the Floor around it |
| An "island" drawn inside a hole | **Becomes its own Floor** |

> 💡 Think of it as cutting a sheet of cookies apart: each cookie becomes its own piece, and the holes stay in the cookie they were in.

📸 *[Screenshot: before (one Floor, three outlines highlighted together) and after (three Floors)]*

---

## 2. What carries over to the new Floors

| ✅ Copied | ❌ Not copied |
|---|---|
| Floor **type** | **Mark** (must stay unique, so it's left blank) |
| **Level** | **IfcGUID** (must stay unique) |
| **Structural** on/off | **Slab shape edits** (sub-elements, points): new Floors are **flat** |
| **Height Offset From Level** | **Slope arrows**: new Floors are **flat** |
| Phases, comments and every other **editable instance parameter**, including your own shared and project parameters | Anything **hosted** on the original (it's deleted with it, see [Section 4](#4-keep-or-delete-the-originals)) |
| | **Tags** on the original (deleted with it) |

If a parameter couldn't be copied, the result window lists it by name (see [Section 6](#6-messages-you-may-see)).

> ℹ️ The new Floors are **new elements with new IDs**. Anything that pointed at the original's ID (tags, "hide in view" by element, notes in a clash report) won't point at the new ones.

---

## 3. How to use it

1. *(Optional)* Select the Floors you want to split. You can select other things too; only Floors with more than one boundary loop are used.
2. Go to **Modify** panel → **Floors ▾** → **Split Floors**.
   - **Click** to split and **delete** the originals.
   - **Shift + Click** to split and **keep** the originals.
3. If nothing suitable was selected, the yellow bar at the top says **"Pick Floors to split, then click Finish:"**. Click the Floors (only Floors with more than one boundary loop can be picked), then click **Finish** on the Options Bar.
4. If some Floors have **slab shape edits**, you're warned that the new Floors will be flat. Click **Yes** to carry on.
5. If anything is **hosted** on the Floors and you're deleting the originals, choose what to do (see [Section 4](#4-keep-or-delete-the-originals)).
6. A result window shows how many Floors were split. Click the arrow to see the details per Floor. The new Floors are **selected**, ready for you to check.

---

## 4. Keep or delete the originals

| | **Click** (delete originals) | **Shift + Click** (keep originals) |
|---|---|---|
| Original Floor | Deleted | Kept, unchanged |
| New Floors | Created in its place | Created **on top of** the original |
| Hosted elements and tags on the original | **Deleted** with it | Stay on the original |
| Good for | Normal use | Checking the result before committing, or keeping the original for reference |

> ⚠️ With **Shift + Click** you end up with **overlapping Floors** (the original plus the new ones). Delete the original once you've checked the result.

**If anything is hosted on the Floors** (family instances or openings) and you clicked normally, you're asked first:

| Choice | What happens |
|---|---|
| **Keep originals** | Splits, but keeps the originals (as if you'd used Shift + Click). Hosted elements are safe on the originals. |
| **Delete originals anyway** | Splits and deletes the originals **and everything hosted on them**. |
| **Cancel** | Nothing happens. |

---

## 5. Undoing

The whole run is **one** step in Revit's Undo list: **B_Dare95 | Split Floors**. Press **Ctrl + Z** to put everything back as it was.

If one Floor fails, only that Floor is left unchanged. The others are still split, and it's listed in the result details.

---

## 6. Messages you may see

| Message | Why | What to do |
|---|---|---|
| 🟢 **"Split _ Floor(s) into _ new Floor(s)."** | It worked. **"Originals were kept."** is added if you kept them. | Click the arrow for the per-Floor details. |
| 🔵 **"Floor _ -> _ Floors (not copied: …)"** *(in the details)* | Split worked, but the listed parameters couldn't be copied. | Fill them in on the new Floors if you need them. |
| 🟡 **"_ Floor(s) have slab shape edits. The new Floors will be flat. Continue?"** | The originals have shape edits, which can't be carried over. | **Yes** to carry on, **No** to stop. |
| 🟡 **"_ hosted element(s) or opening(s) sit on the selected Floors…"** | Deleting the originals would delete them. | See [Section 4](#4-keep-or-delete-the-originals). |
| 🟡 **"No Floor with more than one boundary loop was selected."** | Nothing you selected or picked has more than one loop. | Check the Floor's sketch has separate outlines. |
| 🟡 **"Nothing to split."** + details **"only one outline, the other loops are holes"** | The Floor has one outline with holes in it, so there's nothing to separate. | Nothing to do. That Floor is already one piece. |
| 🟡 **"_ Floor(s) skipped or failed - see details."** | Some Floors couldn't be split. The rest were. | Click the arrow to see why. |
| 🔴 **"the sketch has an open boundary loop"** *(in the details)* | That Floor's sketch has a gap. | Edit the sketch, close the gap, try again. |
| 🔴 **"Split failed, nothing was changed."** / **"Revit rolled the split back, nothing was changed."** | Revit refused the change. | Screenshot it and contact the author. |

---

## 7. FAQ & troubleshooting

**The tool won't let me pick my Floor.**
Only Floors whose sketch has **more than one loop** can be picked. A Floor with one outline has nothing to split.

**It said "only one outline, the other loops are holes".**
The extra loops are openings inside the outline. Holes always stay with their Floor, so there's nothing to separate.

**My new Floors are flat but the original was sloped.**
Slope arrows and slab shape edits aren't carried over. Re-apply them to the new Floors.

**My Floor tags disappeared.**
Tags belong to the original Floor and are deleted with it. Re-tag the new Floors (they're selected after the split, so **Tag All** is quick).

**The Mark values are empty.**
On purpose. Mark must be unique, so it isn't copied. Fill it in on each new Floor.

**My light fixtures / openings on the Floor are gone.**
They were hosted on the original. If you chose **Delete originals anyway**, they were deleted with it. Undo with **Ctrl + Z**, then use **Shift + Click** (keep originals) instead.

**Does it work on Floors in a linked model?**
No. Only Floors in the model you have open.

---

## 8. Contact the author

If your problem isn't solved by the steps above, **please don't try to fix the tool yourself**. Contact:

> 👤 **Mohamed Bedair**
> ✉️ [email] · 💬 [Teams / chat]

**Please include:** a screenshot of the result window **with the details open**, the Floor's **ID**, your **Revit version**, and the **model name**.
