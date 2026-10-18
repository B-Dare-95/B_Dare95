# Ghost by Category

> ⚡ **TL;DR**
> Makes the **categories you pick see-through** in the active view. Your colours and patterns stay as they are.
>
> 1. **Visuals** panel → **Ghost Mode ▾** → **Ghost by Category**
> 2. Tick the categories to ghost. (Want the opposite? Tick **Negate mode**, or **Shift + Click** the button.)
> 3. Click **Apply**. The window stays open and follows you to the next view.
>
> ⚠️ Doesn't work on views with a **view template**. Ghosting is **saved in the view**: undo it with **Restore View** or **Ctrl + Z**.

🎬 *[GIF, ~15 s: tick Pipes + Ducts → Negate → Apply → everything else goes see-through → Restore View]*

*📍 Visuals panel · 🧩 Revit 2024+ · 👤 Mohamed Bedair · 🗓️ 12 Oct 2026*

---

# 📖 Full guide

*Everything below is reference. You only need it if the TL;DR didn't answer your question.*

## 1. What this tool does

**Ghost by Category** makes the **categories you choose** see-through in the **active view**, and leaves everything else solid.

It opens a window that **stays open while you work**. When you switch to another view, the list updates to show that view.

| Mode | What gets ghosted |
|---|---|
| **Normal** | Only the categories you **tick**. |
| **Negate** | Everything **except** the categories you tick. |

> 💡 Example: you want to see the pipes and ducts inside the ceiling. Tick **Pipes** and **Ducts**, turn on **Negate mode**, and click **Apply**. Walls, floors, ceilings and everything else go see-through, and the pipes and ducts stay solid.

It only changes **transparency**. Any colours, patterns, halftone or line weights you've already set on a category stay as they are.

📸 *[Screenshot: the Ghost by Category window next to a 3D view with Pipes and Ducts kept solid]*

---

## 2. Ghost by Category vs Ghost Model

The **Ghost Mode** split button has two tools:

| | **Ghost Model** | **Ghost by Category** |
|---|---|---|
| What it ghosts | **Every** category | Only the categories you choose (or all except them) |
| How you use it | One click ON, one click OFF | A window with a list, then **Apply** |
| Transparency | Fixed at 95% | Your choice, 10% to 100% |
| Your other V/G overrides | **Replaced** when you turn it ON, **cleared** when you turn it OFF | **Kept**, always |
| Visual style | Switched to Shaded (ON) / Shaded with Edges (OFF) | Unchanged, unless you tick the Shaded with Edges option |
| Hides model lines | Yes | No |

> 💡 If you've set up colours or patterns in a view and don't want to lose them, use **Ghost by Category**.

---

## 3. What this tool does NOT do

| ❌ It does NOT… | What this means for you |
|---|---|
| Change elements | Only the **view's graphics** change. |
| Work on views with a view template | The window shows a red message and **Apply** is greyed out. |
| Touch annotation categories | Only **model** categories are listed (walls, doors, pipes…), not tags, dimensions or text. |
| Touch view filters or per-element overrides | Transparency set by **filters** or **Override Graphics in View → By Element** stays as it is, and isn't shown in the list. |
| Change other views | Only the active view. |
| Undo itself when you close the window | Ghosting is saved in the view. Use **Restore View** or **Ctrl + Z** to take it off. |

---

## 4. Before you start

- [ ] The view you want to ghost is **active** (3D views work best).
- [ ] The view has **no view template** (View Properties → View Template = *\<None\>*).
- [ ] *(Shared models)* Remember that ghosting is saved **in the view**. Anyone who opens that view sees it too. If that's a problem, work on a **duplicate** of the view.

---

## 5. How to use it

1. Open the view.
2. On the **Visuals** panel, click the arrow on **Ghost Mode** and choose **Ghost by Category**.
3. The window opens. Under the title it shows **View: \<view name\>**.
4. Tick the categories you want to ghost. Use the **search box** to find them faster.
5. *(Optional)* Turn on **Negate mode** if you want to keep the ticked categories solid and ghost everything else.
6. *(Optional)* Change the **Transparency** slider (default **95%**).
7. Check the line above the buttons. It tells you what will happen, e.g. **"3 selected → 3 categories will be ghosted"**.
8. Click **Apply**. ✅
9. Leave the window open and switch views if you want to ghost another view. Click **Close** (or press **Esc**) when you're done.

> 💡 **Shortcut:** **Shift + Click** the button to open the window with **Negate mode** already on.

> 💡 Clicking the button again while the window is open brings the window to the front instead of opening a second one. **Shift + Click** while it's open also turns **Negate mode** on.

---

## 6. The window, part by part

### Header

| Item | What it shows |
|---|---|
| **View: \<name\>** | The view the list belongs to. It updates when you switch views. |
| **Negate mode** | Off = ghost the ticked categories. On = ghost everything **except** the ticked categories. |

### Category list

| Column / item | What it means |
|---|---|
| **List title** | Says **"Categories to ghost"** (normal) or **"Categories to keep SOLID"** (negate), so you always know what your ticks mean. |
| **Category name** | Tick it to include it. |
| **In view** | How many elements of that category are in this view. A dash (**–**) means none. |
| **Now** | The category's **current** transparency in this view, in yellow. Blank means 0% (solid). |
| **Search categories…** | Shows only categories whose name contains what you type. |
| **Show all model categories** | Off (default): only categories that have elements in the view. On: every model category, including empty ones. |

When you first open the window, categories that are **already ghosted** in the view come pre-ticked. When you switch views, your ticks stay the same (by category name).

### List buttons

| Button | What it does |
|---|---|
| **Select all** | Ticks every category **currently shown** in the list. |
| **Clear** | Unticks every category **currently shown**. |
| **Flip** | Swaps ticked and unticked for the categories **currently shown**. |
| **Refresh** | Recounts the elements in the view and updates the **In view** and **Now** columns. |

> ⚠️ Categories hidden by the search box (or by **Show all** being off) **keep their ticks**, and those ticks still count when you click **Apply**. Clear the search box before you **Apply** to see everything that's ticked.

### Settings

| Setting | Default | What it does |
|---|---|---|
| **Transparency** slider | **95%** | How see-through ghosted categories become. 10% to 100% in steps of 5. 100% makes surfaces almost invisible. |
| **Clear transparency on categories that are not ghosted** | **On** | On: every category you didn't ghost is set back to solid, so only your current choice is ghosted. Off: categories that were already ghosted stay ghosted, and your new choice is **added** to them. |
| **Switch Wireframe / Hidden Line view to Shaded with Edges** | **On** | Only appears when the view is in **Wireframe** or **Hidden Line**, where transparency doesn't show. When ticked, **Apply** switches the view to **Shaded with Edges**. |

### Bottom of the window

| Item | What it does |
|---|---|
| **Status line** (grey) | Tells you how many categories will be ghosted. Shows red if this view can't be ghosted. |
| **Result line** | Shows what happened after **Apply** or **Restore View** (green = done, yellow = done but some skipped, red = problem). |
| **Restore View** | Sets **every** model category in this view back to **0% transparency**. Colours, patterns and other overrides are kept. It does **not** change the visual style back. |
| **Close** / **Esc** | Closes the window. The view keeps its ghosting. |
| **Apply** | Applies your choice to the active view. |

📸 *[Screenshot: the full window with each area labelled]*

---

## 7. Undoing

Each **Apply** or **Restore View** is **one** step in Revit's Undo list:

| Action | Name in the Undo list |
|---|---|
| Apply (normal) | **Ghost by Category** |
| Apply (negate) | **Ghost by Category - Negate** |
| Restore View | **Ghost by Category - Restore** |

Press **Ctrl + Z** in Revit to reverse it. Click **Refresh** in the window afterwards so the **Now** column is up to date.

If **Apply** also switched the visual style to Shaded with Edges, the same Undo step switches it back.

---

## 8. Messages you may see

### 🔴 "This view has a View Template. Turn it off to ghost categories." *(red, in the window)*
**Why:** The active view uses a view template. The list is empty and **Apply** / **Restore View** are greyed out.
**What to do:** Set the view's **View Template** to *\<None\>*, or use a duplicate without a template. The window updates when you switch back to the view, or click **Refresh**.

### 🔴 "This view type does not support graphic overrides." *(red, in the window)*
**Why:** Some views (sheets, schedules, legends, etc.) can't have category overrides.
**What to do:** Switch to a plan, section, elevation or 3D view.

### 🔴 "No document is open." / "No active view." *(red, in the window)*
**Why:** All models are closed, or Revit has no active view.
**What to do:** Open a model and a view. The window picks it up automatically.

### 🔴 "The active view changed - list reloaded. Review it and Apply again."
**Why:** You switched views between loading the list and clicking **Apply**. Nothing was changed, to make sure your ticks don't land on the wrong view.
**What to do:** Check the list for the new view and click **Apply** again.

### 🟢 "Done - _ categories ghosted at _%, _ updated."
**Why:** Apply worked. "Ghosted" is how many categories are now see-through. "Updated" is how many categories actually changed (categories already at the right value aren't counted).

### 🟢 "View restored - _ categories updated."
**Why:** Restore View worked.

### 🟡 "… _ skipped." plus a **"Skipped categories:"** box
**Why:** Revit refused to change some categories. The others were done.
**What to do:** Usually nothing. If it happens every time for a category you need, screenshot the box and contact the author.

### 🔴 "Failed: …" / "Error: …" / "UI error in …"
**Why:** Something unexpected went wrong. For "Failed", nothing was changed.
**What to do:** Try again. If it repeats, screenshot the window and contact the author.

---

## 9. FAQ

**Which views does it work in?**
Plans, sections, elevations and 3D views without a view template. It's most useful in **3D views**.

**Will it remove the colours I set in Visibility/Graphics?**
No. It only changes surface transparency. **Restore View** only sets transparency back to 0.

**I ticked a category but nothing went see-through.**
Check that the view isn't in **Wireframe** or **Hidden Line** (transparency doesn't show there), or tick the **Switch … to Shaded with Edges** option. Also check that the elements aren't controlled by a **view filter** with its own transparency.

**Why can't I see a category in the list?**
By default only categories with elements in the view are listed. Tick **Show all model categories**. Annotation categories (tags, dimensions, text) are never listed.

**Do linked models get ghosted too?**
Linked models that display **By host view** (Revit's default) follow the same category settings, so they're ghosted too. The **In view** count only counts **your** model's elements, so a category that only exists in a link shows **–** and is hidden until you tick **Show all model categories**.

**In negate mode, are empty categories ghosted too?**
Yes. Every model category you didn't tick is ghosted, even ones with no elements in the view. That way anything added later is ghosted too.

**What's the difference between Clear and Restore View?**
**Clear** only unticks boxes in the list. Nothing happens in the view. **Restore View** changes the view: it sets every category back to solid.

**I closed the window. Is the view still ghosted?**
Yes, ghosting is saved in the view. Reopen the window and click **Restore View**, or use **Ctrl + Z**.

**Does it affect my colleagues?**
Only through the view itself. If they open the same view in a shared model, they see it ghosted.

---

## 10. Troubleshooting

| Symptom | Likely cause | What you can check | Contact author? |
|---|---|---|---|
| **Apply** is greyed out | View has a template, or doesn't support overrides | Read the red status line | ❌ |
| Ticked categories don't look see-through | View in Wireframe / Hidden Line, or a view filter overrides it | Switch to Shaded, check **Filters** in V/G | ❌ |
| More categories ghosted than expected | Ticks hidden by the search box still counted | Clear the search box, check ticks, Apply again | ❌ |
| More categories ghosted than expected (negate) | Negate ghosts **all** unticked categories, including hidden ones | Expected. Untick **Negate mode** for the opposite | ❌ |
| Old ghosting stayed after Apply | **Clear transparency on categories that are not ghosted** was off | Tick it and Apply again, or use **Restore View** | ❌ |
| **Now** column looks out of date | View changed by Undo or by hand | Click **Refresh** | ❌ |
| Window disappeared | It was minimised (it minimises together with Revit) | Click the button again to bring it back | ❌ |
| Visual style changed | The Shaded with Edges option was on | Set it back in the View Control Bar, or **Ctrl + Z** | ❌ |
| "_ skipped" every time for the same category | Revit refuses that category in this view | Screenshot the "Skipped categories" box | ✅ If you need it |
| "Failed" / "Error" message, or red pyRevit error window | Unexpected problem | Screenshot it | ✅ |

---

## 11. Contact the author

If your problem isn't solved by the steps above, **please don't try to fix the tool yourself**. Contact:

> 👤 **Mohamed Bedair**
> ✉️ [email] · 💬 [Teams / chat]

**Please include:**

1. Whether **Negate mode** was on, and which categories were ticked
2. A **screenshot** of the window (including the status and result lines) and of the view
3. Your **Revit version** (e.g. 2025)
4. The **model name** and the **view** (and its type, e.g. 3D, plan)
5. **What you expected**, and what actually happened
