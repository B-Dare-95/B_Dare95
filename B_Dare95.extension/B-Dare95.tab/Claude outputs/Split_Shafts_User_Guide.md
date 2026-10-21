# Split Shafts

> ⚡ **TL;DR**
> Turns **one Shaft Opening drawn with several separate outlines** into **one Shaft per outline**. Base, top, offsets, phases and parameters carry over, and the new Shafts cut the same floors.
>
> 1. Select the Shafts (or click the button and pick them, then **Finish**).
> 2. **Click** = split and delete the original. **Shift + Click** = split and keep the original.
> 3. Done. The new Shafts are selected for you.
>
> ⚠️ **Mark** isn't copied, **symbolic lines** in the shaft sketch are lost, and the new Shafts get **new IDs** (tags on the original are deleted with it).

🎬 *[GIF, ~10 s: select a Shaft with 4 separate outlines in a plan → click Split Shafts → it becomes 4 Shafts, each still cutting the slab]*

*📍 Modify panel → Shafts ▾ → Split Shafts · 🧩 Revit 2024+ · 👤 Mohamed Bedair · 🗓️ 21 Oct 2026*

---

# 📖 Full guide

*Everything below is reference. You only need it if the TL;DR didn't answer your question.*

## 1. What this tool does

In Revit, one **Shaft Opening** can hold **several closed outlines** that don't touch, for example all the MEP risers on a floor drawn as one Shaft. Revit treats them as **one element**, so you can't tag, schedule, give a different function, or change the base/top of one riser on its own.

**Split Shafts** rebuilds that Shaft as **separate Shafts, one per outline**.

| In the original sketch… | After the split… |
|---|---|
| Separate outlines side by side | **One Shaft each** |
| A loop drawn inside an outline | **Stays with** the Shaft around it |
| An "island" drawn inside that inner loop | **Becomes its own Shaft** |

The new Shafts **cut the same floors, ceilings and roofs** as the original did, automatically.

> 💡 It pairs well with the other Shaft tools: once each riser is its own Shaft, you can tag it, give it a function and match its base/top separately.

📸 *[Screenshot: before (one Shaft, four outlines highlighted together) and after (four Shafts)]*

---

## 2. What carries over to the new Shafts

| ✅ Copied | ❌ Not copied |
|---|---|
| **Base Constraint** and **Base Offset** | **Mark** (must stay unique, so it's left blank) |
| **Top Constraint** and **Top Offset** | **IfcGUID** (must stay unique) |
| **Unconnected Height** (if the top is Unconnected) | **Symbolic lines** drawn in the shaft sketch |
| **Phase Created / Demolished** | **Tags** on the original (deleted with it) |
| Comments and every other **editable instance parameter**, including your own shared and project parameters (e.g. shaft function) | |

If a parameter couldn't be copied, the result window lists it by name (see [Section 6](#6-messages-you-may-see)).

> ℹ️ The new Shafts are **new elements with new IDs**. Anything that pointed at the original's ID (tags, "hide in view" by element, notes in a clash report, a Shaft Manager export) won't point at the new ones.

---

## 3. How to use it

1. *(Optional)* Select the Shafts you want to split. You can select other things too; only Shafts with more than one boundary loop are used.
2. Go to **Modify** panel → **Shafts ▾** → **Split Shafts**.
   - **Click** to split and **delete** the originals.
   - **Shift + Click** to split and **keep** the originals.
3. If nothing suitable was selected, the yellow bar at the top says **"Pick Shafts to split, then click Finish:"**. Click the Shafts (only Shafts with more than one boundary loop can be picked), then click **Finish** on the Options Bar.
4. If anything depends on the Shafts and you're deleting the originals, choose what to do (see [Section 4](#4-keep-or-delete-the-originals)).
5. A result window shows how many Shafts were split. Click the arrow to see the details per Shaft. The new Shafts are **selected**, ready for you to check.

---

## 4. Keep or delete the originals

| | **Click** (delete originals) | **Shift + Click** (keep originals) |
|---|---|---|
| Original Shaft | Deleted | Kept, unchanged |
| New Shafts | Created in its place | Created **on top of** the original |
| Tags and dependent elements of the original | **Deleted** with it | Stay on the original |
| Good for | Normal use | Checking the result before committing |

> ⚠️ With **Shift + Click** you end up with **overlapping Shafts** (the original plus the new ones). Delete the original once you've checked the result.

**If any elements depend on the Shafts** and you clicked normally, you're asked first:

| Choice | What happens |
|---|---|
| **Keep originals** | Splits, but keeps the originals (as if you'd used Shift + Click). |
| **Delete originals anyway** | Splits and deletes the originals **and the elements that depend on them**. |
| **Cancel** | Nothing happens. |

---

## 5. Undoing

The whole run is **one** step in Revit's Undo list: **B_Dare95 | Split Shafts**. Press **Ctrl + Z** to put everything back as it was.

If one Shaft fails, only that Shaft is left unchanged. The others are still split, and it's listed in the result details.

---

## 6. Messages you may see

| Message | Why | What to do |
|---|---|---|
| 🟢 **"Split _ Shaft(s) into _ new Shaft(s)."** | It worked. **"Originals were kept."** is added if you kept them. | Click the arrow for the per-Shaft details. |
| 🔵 **"Shaft _ -> _ Shafts (not copied: …)"** *(in the details)* | Split worked, but the listed parameters couldn't be copied. | Fill them in on the new Shafts if you need them. |
| 🟡 **"_ hosted element(s) depend on the selected Shafts…"** | Deleting the originals would delete them. | See [Section 4](#4-keep-or-delete-the-originals). |
| 🟡 **"No Shaft with more than one boundary loop was selected."** | Nothing you selected or picked has more than one loop. | Check the Shaft's sketch has separate outlines. |
| 🟡 **"Nothing to split."** + details **"only one outline, the other loops sit inside it"** | The Shaft has one outline with loops inside it, so there's nothing to separate. | Nothing to do. That Shaft is already one piece. |
| 🟡 **"_ Shaft(s) skipped or failed - see details."** | Some Shafts couldn't be split. The rest were. | Click the arrow to see why. |
| 🔴 **"the sketch has an open boundary loop"** *(in the details)* | That Shaft's sketch has a gap. | Edit the sketch, close the gap, try again. |
| 🔴 **"base constraint not found"** *(in the details)* | Revit couldn't read that Shaft's base level. | Check the Shaft's **Base Constraint** in Properties, then try again. |
| 🔴 **"Split failed, nothing was changed."** / **"Revit rolled the split back, nothing was changed."** | Revit refused the change. | Screenshot it and contact the author. |

---

## 7. FAQ & troubleshooting

**The tool won't let me pick my Shaft.**
Only Shafts whose sketch has **more than one loop** can be picked. A Shaft with one outline has nothing to split.

**It said "only one outline, the other loops sit inside it".**
The extra loops are inside the main outline, so they stay with it. There's nothing to separate.

**Do the new Shafts still cut the slabs?**
Yes. A Shaft cuts whatever it passes through between its base and top, and the new Shafts get the same base, top and offsets as the original.

**My original had an Unconnected top. Is that kept?**
Yes. The new Shafts end up with an Unconnected top and the same **Unconnected Height**.

**My Shaft tags disappeared.**
Tags belong to the original Shaft and are deleted with it. Re-tag the new Shafts (they're selected after the split), for example with the **Shaft Tag** tool.

**The Mark values are empty.**
On purpose. Mark must be unique, so it isn't copied. Fill it in on each new Shaft.

**The cross/diagonal lines I drew in the shaft sketch are gone.**
Symbolic lines in the shaft sketch aren't carried over. Edit each new Shaft's sketch to add them back.

**Does it work on Shafts in a linked model?**
No. Only Shafts in the model you have open.

---

## 8. Contact the author

If your problem isn't solved by the steps above, **please don't try to fix the tool yourself**. Contact:

> 👤 **Mohamed Bedair**
> ✉️ [email] · 💬 [Teams / chat]

**Please include:** a screenshot of the result window **with the details open**, the Shaft's **ID**, your **Revit version**, and the **model name**.
