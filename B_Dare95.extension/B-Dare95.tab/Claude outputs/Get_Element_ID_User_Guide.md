# Get Element ID

> 📍 **Where to find it:** Revit ribbon → **B-Dare95** tab → **QoL** panel → **Get Element ID** (dropdown)
> 🧩 **Works with:** Revit 2024 and newer
> 👤 **Tool author:** Mohamed Bedair — [email] · [Teams / chat]
> 🏷️ **Versions:** Active Element 1.0 · Linked Element 1.2 · What's This ID? 2.0.0 (5 Oct 2026)
> 🗓️ **Last updated:** 12 Oct 2026

---

## 1. What this tool does

Every element in Revit has a unique number called its **Element ID**. You need it when someone sends you a warning report, a clash report, or asks "can you check element 123456?".

The **Get Element ID** dropdown has **three tools**:

| Tool | Direction | What it does |
|---|---|---|
| **Active Element** | Element → ID | Pick elements in **your model**. You get their names and IDs. |
| **Linked Element** | Element → ID | Pick elements **inside linked models**. You get their names and IDs, grouped per link. |
| **What's This ID?** | ID → Element | Type an ID. The tool finds it in your model **and** in every loaded link, selects it, zooms to it and shows its details. |

> 💡 The first two are like reading a label off a box. The third is like typing a label into a search box and having the warehouse bring you the box.

📸 *[Screenshot: the Get Element ID dropdown open]*

---

## 2. What this tool does NOT do

| ❌ It does NOT… | What this means for you |
|---|---|
| Change your model | All three tools only read and select. Nothing to undo. |
| Pick linked elements with Active Element | Use **Linked Element** for those. |
| Search unloaded links | **What's This ID?** skips links that aren't loaded. Reload them first. |
| Find element types by ID in a useful way | What's This ID? can find them, but types can't be selected in a view. |
| Keep the output | The lists appear in a pyRevit output window. Copy what you need before closing it. |

---

## 3. Before you start

- [ ] A model is **open** and a view where you can see the elements is **active**.
- [ ] *(Linked Element / What's This ID?)* The links you need are **loaded**.
- [ ] *(What's This ID?)* You have the ID number ready (whole number, no letters).

---

## 4. How to use — Active Element

1. Open the **Get Element ID** dropdown and click **Active Element**.
2. Revit's status bar says **"Select Element"**. Click the elements you want. You can pick several.
3. Click **Finish** on the Options Bar (top left, under the ribbon).
4. A pyRevit output window opens with one line per element:
   `Element Name : <name>>>ID: <number>`
5. Copy the IDs you need. ✅

---

## 5. How to use — Linked Element

1. Open the **Get Element ID** dropdown and click **Linked Element**.
2. Revit's status bar says **"Select Linked Element"**. Hover over a linked model and click the elements you want. You don't need to press **Tab**.
3. You can pick elements from **several links** in one go.
4. Click **Finish** on the Options Bar.
5. The output window lists the results **per link**:

```
Link : <linked model name>:
-Element Name : <name> >> ID: <number>
-Element Name : <name> >> ID: <number>
____________________________________________________________
<number>,<number>
```

6. The last line of each link is a **comma-separated list** of all its IDs, ready to paste (e.g. into Revit's **Select by ID**, in that linked model). ✅

> ⚠️ The IDs belong to the **linked model**, not your model. Typing them into **Select by ID** in your own model will select the wrong thing (or nothing).

---

## 6. How to use — What's This ID?

1. Open the **Get Element ID** dropdown and click **What's This ID?**.
2. A small window asks: **"Enter Element ID to inspect (host or linked):"**. Type the number (digits only, e.g. `412893`) and confirm.
   - Clicking **Cancel** or closing the box stops the tool quietly. Nothing happens.
3. The tool searches **your model** and **every loaded link**.
4. **Found in one place:** the element is selected, the view zooms to it, and the report opens. ✅
5. **Found in several places:** a picker window opens first (see below). Choose the one you meant, and the element is selected and the report opens. ✅

### Why can one ID be in several places?

IDs are only unique **inside one model**. Your model and a link (or two links) can each have an element with the same number. Two copies of the **same link** placed in your model also count as two places, because they sit in different positions.

### Picker window controls

The window title is **What's This ID?**. The header says **"ID _ exists in _ places"**, with the reminder **"IDs are only unique per document - pick the one you meant."** underneath.

| Control | What it does |
|---|---|
| **Filter box** ("Filter by link, category, family or type...") | Hides rows that don't match what you type. |
| **Rows** | Each row has two lines. Top: where the element lives — **Host model — \<your model\>** or **Link — \<link name\>**. Bottom: **category · family : type**. Hover a row to see the full text if it's cut off. |
| **Highlighted row** (yellow) | The one that will be inspected. The **first row** is highlighted when the window opens. Click another row to change it. |
| **Double-click a row** | Chooses it straight away. |
| **Enter** | Same as **Inspect & Select**. |
| **Inspect & Select** | Selects the highlighted element and shows the report. |
| **Cancel** / **Esc** | Closes without doing anything. |

> ⚠️ The filter box only **hides** rows. It doesn't move the highlight. If the highlighted row gets hidden by your filter, **Inspect & Select** (or **Enter**) still picks that hidden row. After filtering, **click** the row you want (or double-click it) before confirming.

📸 *[Screenshot: the picker with a host hit and two link hits]*

### Reading the report

The report opens in a Revit message box titled **What's This ID?**. The element is already selected when you see it. Close the box to carry on working. The selection stays.

| Line | Meaning |
|---|---|
| **ID** | The number you typed |
| **Source** | **Host model**, or **Link — \<linked model name\>** |
| **Link Inst.** | *(Linked only)* The link copy in your model, and that copy's own ID in **your** model |
| **Category / Family / Type** | What the element is |
| **Level** | Its level, as named in the model it lives in |
| **Phase** | Phase Created, as named in the model it lives in |
| **Workset** | Its workset in the model it lives in, or **Not workshared** |
| **Mark / Comments** | The element's Mark and Comments values |
| **Bounding Box** | Min and max corners of the element's box, in **feet** (Revit's internal unit), to 2 decimals. For linked elements it's in **your model's** coordinates, marked **[host coords]**. |

A dash (**—**) means the value is empty or doesn't apply.

The last line tells you what happened:

| Footer | Meaning |
|---|---|
| ✔ **Element selected and view zoomed.** | All done. |
| ✔ **Element selected (view not zoomed).** | Selected, but the view couldn't zoom to it (e.g. the element has no box, or the view can't zoom). |
| ✘ **Element could not be selected (view-only, non-graphical or an element type).** | The element exists, but it can't be selected in a view (e.g. a type, a view, a sheet). The report is still valid. |
| *The link instance is not visible in the active view.* | Added under ✔ for a linked element whose link is hidden in this view (or when you're on a sheet or schedule). It's selected, but there's no zoom. |

### Host vs linked: what's different

| | Element in **your model** | Element in a **link** |
|---|---|---|
| Selection | Normal selection | Linked selection, the same way as **Pre-Filter Selection (Links)** |
| Zoom | Revit shows the element. It may **switch to another view** if the element isn't visible in this one. | Zooms in the **current view only**, and only if the link is visible there |
| Bounding box | Your model's coordinates | Converted to your model's coordinates **[host coords]** |

---

## 7. Undoing

None of the three tools change the model. There's nothing in the Undo list.

To clear a selection made by **What's This ID?**, press **Esc** in the view.

---

## 8. Messages you may see

### 🟡 "No ID entered."
**Why:** You confirmed the ID box while it was empty.
**What to do:** Run it again and type a number.

### 🟡 "Invalid ID — please enter a whole number."
**Why:** You typed letters, spaces in the middle, decimals, or thousands separators (e.g. `412,893`). Spaces before or after the number are fine.
**What to do:** Type digits only, e.g. `412893`. The tool checks **one** ID at a time, so you can't paste a comma-separated list.

### 🟡 "Invalid ID — please enter a positive whole number."
**Why:** You typed 0 or a negative number.
**What to do:** Check the ID and try again.

### 🟡 "No element with ID _ in the host model or any loaded link."
**Why:** Nothing has that ID. It may have been deleted, or it lives in a link that isn't loaded.
**What to do:** If the message adds **"_ unloaded link(s) could not be searched"**, reload those links in **Manage Links** and try again.

### 🔵 "Selecting linked elements needs Revit 2023 or newer."
**Why:** Shown under the report if Revit can't select linked elements.
**What to do:** Shouldn't appear in Revit 2024+. If it does, contact the author.

### 🔵 Output window (Active Element / Linked Element)
Opens with your list. If you cancel the pick with **Esc**, no window opens and nothing happens.

---

## 9. FAQ

**Can I pick linked elements with Active Element?**
No. Use **Linked Element**.

**What's the comma-separated line for?**
It's every ID from that link in one line, so you can paste it into another tool or a report without editing.

**I typed an ID from a clash report and got three results. Which one is it?**
Check which model the clash report came from. Pick the row with that link name (or **Host model** if it's yours).

**Why are the bounding box numbers so small?**
They're in **feet**, Revit's internal unit, not your project units.

**Does What's This ID? open another view?**
For an element in **your model**, the tool asks Revit to show it. If it isn't visible in the current view, Revit may switch to another view that shows it. For a **linked** element, it only zooms in the current view, and only if the link is visible there.

**Can I use What's This ID? for an element type?**
It will find it and show the report, but types can't be selected, so the footer shows ✘.

**Can I paste the comma-separated line from Linked Element into What's This ID??**
No. It takes **one** ID at a time. Paste the IDs one by one.

**I filtered the picker and the wrong element was inspected.**
Filtering hides rows but doesn't move the yellow highlight. Click (or double-click) the row you want after filtering.

**The same link name appears twice in the picker.**
That link is placed in your model **twice** (two link instances). The **Link Inst.** line in the report shows which copy you picked, with its own ID.

---

## 10. Troubleshooting

| Symptom | Likely cause | What you can check | Contact author? |
|---|---|---|---|
| Nothing happened after picking | You pressed **Esc** or didn't click **Finish** | Pick again and click **Finish** | ❌ |
| Linked Element won't let me pick | You're hovering your own model, not a link | Hover the linked model's elements | ❌ |
| ID not found | Element deleted, or in an unloaded link | Reload links. Check the ID. | ❌ |
| Found but not zoomed (linked element) | The link is hidden in this view, or you're on a sheet/schedule | Open a view where the link is visible, then run again | ❌ |
| "Invalid ID" for a number that looks right | Commas, dots or a pasted list | Type digits only, one ID | ❌ |
| Picker inspected a different row than I wanted | The highlighted row was hidden by the filter | Click the row you want before **Inspect & Select** | ❌ |
| My view switched after What's This ID? | Host element not visible in this view, so Revit opened one that shows it | Expected. Go back with the view tabs | ❌ |
| Wrong element selected with **Select by ID** | You used a **linked** ID in your own model | Use **What's This ID?** instead | ❌ |
| Red pyRevit error window with **Active Element** in Revit 2026 or newer | Tool incompatibility | Use **What's This ID?** or Revit's own tools meanwhile | ✅ |
| Any other red pyRevit error window | Unexpected problem | Screenshot it | ✅ |

---

## 11. Contact the author

If your problem isn't solved by the steps above, **please don't try to fix the tool yourself**. Contact:

> 👤 **Mohamed Bedair**
> ✉️ [email] · 💬 [Teams / chat]

**Please include:**

1. **Which tool** you used (Active Element, Linked Element or What's This ID?)
2. The **ID** you typed, or what you picked
3. A **screenshot** of the result or error
4. Your **Revit version** (e.g. 2025)
5. The **model name**, and the **link name** if it's about a linked element
