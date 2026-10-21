# Split Ceilings

> ⚡ **TL;DR**
> Turns **one Ceiling drawn with several separate outlines** into **one Ceiling per outline**. Type, level, height offset and parameters carry over.
>
> 1. Select the Ceilings (or click the button and pick them, then **Finish**).
> 2. **Click** = split and delete the original. **Shift + Click** = split and keep the original.
> 3. Done. The new Ceilings are selected for you.
>
> ⚠️ **Mark** isn't copied, slope arrows are lost (new Ceilings are flat), and anything hosted on the original, like **ceiling-hosted light fixtures**, is deleted with it (you're asked first).

🎬 *[GIF, ~10 s: select a Ceiling with 3 separate outlines → click Split Ceilings → it becomes 3 Ceilings, each selectable on its own]*

*📍 Modify panel → Ceiling ▾ → Split Ceilings · 🧩 Revit 2024+ · 👤 Mohamed Bedair · 🗓️ 21 Oct 2026*

---

# 📖 Full guide

*Everything below is reference. You only need it if the TL;DR didn't answer your question.*

## 1. What this tool does

In Revit, one Ceiling's sketch can hold **several closed outlines** that don't touch: for example the ceilings of three separate rooms drawn in one go. Revit treats them as **one element**, so you can't tag, schedule, offset or delete them separately.

**Split Ceilings** rebuilds that Ceiling as **separate Ceilings, one per outline**.

| In the original sketch… | After the split… |
|---|---|
| Separate outlines side by side | **One Ceiling each** |
| A hole (e.g. around a column or a shaft) inside an outline | **Stays a hole** in the Ceiling around it |
| An "island" drawn inside a hole | **Becomes its own Ceiling** |

> 💡 Think of it as cutting a sheet of cookies apart: each cookie becomes its own piece, and the holes stay in the cookie they were in.

📸 *[Screenshot: before (one Ceiling, three outlines highlighted together) and after (three Ceilings)]*

---

## 2. What carries over to the new Ceilings

| ✅ Copied | ❌ Not copied |
|---|---|
| Ceiling **type** | **Mark** (must stay unique, so it's left blank) |
| **Level** | **IfcGUID** (must stay unique) |
| **Height Offset From Level** | **Slope arrows**: new Ceilings are **flat** |
| Phases, comments and every other **editable instance parameter**, including your own shared and project parameters | Anything **hosted** on the original, e.g. ceiling-hosted light fixtures, diffusers (deleted with it, see [Section 4](#4-keep-or-delete-the-originals)) |
| | **Tags** on the original (deleted with it) |

If a parameter couldn't be copied, the result window lists it by name (see [Section 6](#6-messages-you-may-see)).

> ℹ️ The new Ceilings are **new elements with new IDs**. Anything that pointed at the original's ID (tags, "hide in view" by element, notes in a clash report) won't point at the new ones.

---

## 3. How to use it

1. *(Optional)* Select the Ceilings you want to split. You can select other things too; only Ceilings with more than one boundary loop are used.
2. Go to **Modify** panel → **Ceiling ▾** → **Split Ceilings**.
   - **Click** to split and **delete** the originals.
   - **Shift + Click** to split and **keep** the originals.
3. If nothing suitable was selected, the yellow bar at the top says **"Pick Ceilings to split, then click Finish:"**. Click the Ceilings (only Ceilings with more than one boundary loop can be picked), then click **Finish** on the Options Bar.
4. If anything is **hosted** on the Ceilings and you're deleting the originals, choose what to do (see [Section 4](#4-keep-or-delete-the-originals)).
5. A result window shows how many Ceilings were split. Click the arrow to see the details per Ceiling. The new Ceilings are **selected**, ready for you to check.

---

## 4. Keep or delete the originals

| | **Click** (delete originals) | **Shift + Click** (keep originals) |
|---|---|---|
| Original Ceiling | Deleted | Kept, unchanged |
| New Ceilings | Created in its place | Created **on top of** the original |
| Hosted elements and tags on the original | **Deleted** with it | Stay on the original |
| Good for | Normal use | Checking the result before committing, or keeping the original for reference |

> ⚠️ With **Shift + Click** you end up with **overlapping Ceilings** (the original plus the new ones). Delete the original once you've checked the result.

**If anything is hosted on the Ceilings** (family instances or openings) and you clicked normally, you're asked first:

| Choice | What happens |
|---|---|
| **Keep originals** | Splits, but keeps the originals (as if you'd used Shift + Click). Hosted elements are safe on the originals. |
| **Delete originals anyway** | Splits and deletes the originals **and everything hosted on them**. |
| **Cancel** | Nothing happens. |

---

## 5. Undoing

The whole run is **one** step in Revit's Undo list: **B_Dare95 | Split Ceilings**. Press **Ctrl + Z** to put everything back as it was.

If one Ceiling fails, only that Ceiling is left unchanged. The others are still split, and it's listed in the result details.

---

## 6. Messages you may see

| Message | Why | What to do |
|---|---|---|
| 🟢 **"Split _ Ceiling(s) into _ new Ceiling(s)."** | It worked. **"Originals were kept."** is added if you kept them. | Click the arrow for the per-Ceiling details. |
| 🔵 **"Ceiling _ -> _ Ceilings (not copied: …)"** *(in the details)* | Split worked, but the listed parameters couldn't be copied. | Fill them in on the new Ceilings if you need them. |
| 🟡 **"_ hosted element(s) or opening(s) sit on the selected Ceilings…"** | Deleting the originals would delete them. | See [Section 4](#4-keep-or-delete-the-originals). |
| 🟡 **"No Ceiling with more than one boundary loop was selected."** | Nothing you selected or picked has more than one loop. | Check the Ceiling's sketch has separate outlines. |
| 🟡 **"Nothing to split."** + details **"only one outline, the other loops are holes"** | The Ceiling has one outline with holes in it, so there's nothing to separate. | Nothing to do. That Ceiling is already one piece. |
| 🟡 **"_ Ceiling(s) skipped or failed - see details."** | Some Ceilings couldn't be split. The rest were. | Click the arrow to see why. |
| 🔴 **"the sketch has an open boundary loop"** *(in the details)* | That Ceiling's sketch has a gap. | Edit the sketch, close the gap, try again. |
| 🔴 **"Split failed, nothing was changed."** / **"Revit rolled the split back, nothing was changed."** | Revit refused the change. | Screenshot it and contact the author. |

---

## 7. FAQ & troubleshooting

**The tool won't let me pick my Ceiling.**
Only Ceilings whose sketch has **more than one loop** can be picked. A Ceiling with one outline has nothing to split.

**It said "only one outline, the other loops are holes".**
The extra loops are openings inside the outline. Holes always stay with their Ceiling, so there's nothing to separate.

**My new Ceilings are flat but the original was sloped.**
Slope arrows aren't carried over. Re-apply them to the new Ceilings.

**My Ceiling tags disappeared.**
Tags belong to the original Ceiling and are deleted with it. Re-tag the new Ceilings (they're selected after the split, so **Tag All** is quick).

**The Mark values are empty.**
On purpose. Mark must be unique, so it isn't copied. Fill it in on each new Ceiling.

**My light fixtures on the Ceiling are gone.**
Ceiling-hosted fixtures belong to the original Ceiling. If you chose **Delete originals anyway**, they were deleted with it. Undo with **Ctrl + Z**, then use **Shift + Click** (keep originals) instead.

**I kept the originals. Will the fixtures move to the new Ceilings?**
No. They stay hosted on the original Ceiling. To move them to a new Ceiling you have to re-host them (Revit: select the fixture → **Pick New Host**), or re-place them.

**Does it work on Ceilings in a linked model?**
No. Only Ceilings in the model you have open.

---

## 8. Contact the author

If your problem isn't solved by the steps above, **please don't try to fix the tool yourself**. Contact:

> 👤 **Mohamed Bedair**
> ✉️ [email] · 💬 [Teams / chat]

**Please include:** a screenshot of the result window **with the details open**, the Ceiling's **ID**, your **Revit version**, and the **model name**.
