# Pre-Filter Selection — User Guide

> 📍 **Where to find it:** Revit ribbon → **B-Dare95** tab → **QoL** panel → **Pre-Filter Selection** (split button)
> 🧩 **Works with:** Revit 2024 and newer
> 👤 **Tool author:** Mohamed Bedair — [contact email / Teams]
> 🏷️ **Versions:** Pre-Filter Selection 1.2.0 · Pre-Filter by Parameter 1.5.0
> 🗓️ **Last updated:** [Date]

---

## 1. What this tool does

**Pre-Filter Selection** lets you drag a selection box in a view and get **only the elements you actually want**, instead of everything the box touches.

You tell the tool what you're after **before** you draw the box. That's why it's called a *pre*-filter.

The button has **two tools** inside it:

| Tool | How to open it | What it does |
|---|---|---|
| **Pre-Filter Selection** | Click the **main (top) part** of the button | Pick **one or more categories** (e.g. Walls + Doors). The box only selects those. |
| ↳ **Exclude mode** | **Shift + click** the main part of the button | Pick categories you **don't** want. The box selects **everything except** those. |
| **Pre-Filter by Parameter** | Click the **small arrow** under the button, then choose it | Pick **one category**, then narrow it down by parameter values (e.g. only Doors where *Fire Rating = 60 min*). |

> 💡 Think of it as telling Revit "only catch fish of this kind" before you throw the net.

📸 *[Screenshot: the split button, with the dropdown arrow open]*

---

## 2. What this tool does NOT do

| ❌ It does NOT… | What this means for you |
|---|---|
| Change your model | It only **selects** elements. Nothing is moved, edited or deleted. |
| Add to your current selection | Each run **replaces** whatever you had selected before. |
| Select elements inside linked models | Only elements in the model you're working in can be picked. |
| Select annotation | The lists only show **model categories** (walls, pipes, doors…). Tags, dimensions, text notes and similar aren't listed. |
| Select things outside the box | Only elements inside the box you draw in the current view are selected, not the whole model. |
| Save your choices | Each run starts fresh. The window doesn't remember what you ticked last time. |
| Support "contains", "greater than", etc. | *Pre-Filter by Parameter* matches **exact values only** (see [Section 7](#7-understanding-and--or--not)). |

---

## 3. Before you start

- [ ] A model is **open**, and a view you can select in (plan, section, 3D…) is **active**.
- [ ] The elements you want are **visible** in that view. The box can only catch what you can see.
- [ ] You've finished or cancelled any edit mode (e.g. sketch mode).

---

## 4. How to use — Pre-Filter Selection (categories)

1. Click the **main part** of the **Pre-Filter Selection** button.
2. The **Choose Categories** window opens.
3. *(Optional)* Type in the **search box** at the top to shorten the list, e.g. type `pipe`.
4. **Tick** the categories you want. The counter on the right shows how many are ticked.
5. Click **Make A Selection**. The button stays greyed out until at least one category is ticked.
6. The window closes. **Drag a box** in the view.
7. Only elements from your ticked categories end up selected. ✅

📸 *[Screenshot: the Choose Categories window]*

### Window controls

| Control | What it does |
|---|---|
| **Search box** (top) | Filters the list as you type. It matches any part of the name, and upper/lower case doesn't matter. |
| **Select All** | Ticks every category **currently shown**. Combine it with search: type `pipe`, then **Select All** to tick every pipe-related category. |
| **Clear** | Unticks **everything**, including categories hidden by your search. |
| **"_ selected" counter** | Shows how many categories are ticked. |
| **Make A Selection** | Closes the window and starts the box selection. |

---

## 5. Exclude mode (Shift + click)

Use this when it's easier to say what you **don't** want.

1. Hold **Shift** and click the **main part** of the button.
2. The same **Choose Categories** window opens.
3. Tick the categories you want to **leave out** (e.g. Furniture, Generic Models).
4. Click **Make A Selection** and **drag a box**.
5. Everything in the box is selected **except** the ticked categories. ✅

> ⚠️ **Heads-up:** While you drag in Exclude mode, Revit highlights **everything** in the box, including the categories you excluded. That's normal. They're removed as soon as you release the mouse.

---

## 6. How to use — Pre-Filter by Parameter

1. Click the **small arrow** under the Pre-Filter Selection button and choose **Pre-Filter by Parameter**.
2. The **Choose Category** window opens.
3. Pick **one** category from the list (use the search box to find it quickly).
4. *(Optional)* Under **PARAMETER FILTERS**:
   - Choose a **Parameter** from the left dropdown.
   - Choose a **Value** from the right dropdown. It only lists values that actually exist in your model.
5. *(Optional)* Click **+ Add Filter** to add another rule. Choose **AND / OR / NOT** on the small buttons between the rows (see [Section 7](#7-understanding-and--or--not)).
6. Click **Make A Selection** and **drag a box**.
7. Only elements of that category that match your rules are selected. ✅

> 💡 You can skip the parameter rows completely. The tool then works like the category tool, but for a single category.

📸 *[Screenshot: the Choose Category window with two filter rows]*

### Window controls

| Control | What it does |
|---|---|
| **Category list** | Choose **one** category (round buttons). |
| **Parameter** dropdown | Every parameter found on elements of that category, both instance and type parameters. |
| **Value** dropdown | Every value that parameter has in the model. It's greyed out until a parameter is chosen. |
| **+ Add Filter** | Adds another rule row. It's greyed out until a category is chosen. |
| **AND / OR / NOT** (between rows) | Sets how the new row combines with the rows above it. The default is **AND**. |
| **NOT** (on the first row only) | Flips the first rule: "everything that does **not** have this value". |
| **×** | Removes that row. |
| **Make A Selection** | Starts the box selection. It stays greyed out until a category is chosen, and while any row has a parameter chosen but no value. |

---

## 7. Understanding AND / OR / NOT

Rules are read **top to bottom**, one at a time. Each new row combines with **the result of all the rows above it**.

| Operator | Meaning | Example |
|---|---|---|
| **AND** | Must match the rows above **and** this row | Level = *L01* **AND** Fire Rating = *60 min* → only 60-min doors on L01 |
| **OR** | Matches the rows above **or** this row | Level = *L01* **OR** Level = *L02* → doors on either level |
| **NOT** | Must match the rows above, but **not** this row | Level = *L01* **NOT** Type = *D1* → doors on L01, except type D1 |
| **NOT** on the first row | Everything that does **not** have this value | **NOT** Level = *L01* → doors on every level except L01 |

> ⚠️ **Order matters.** There are no brackets. Rules are read strictly top to bottom:
> `Level = L01` **OR** `Level = L02` **AND** `Fire Rating = 60 min`
> means **(L01 or L02)** *and then* **60 min**. Put your **OR** rows first and your narrowing **AND** rows after them.

### About values

- The value must match **exactly** what's in the dropdown. That's why you pick it instead of typing it.
- Values are shown the way Revit displays them, including units (e.g. `900 mm`).
- A rule is checked against **both** the element and its type. If either one has that value, it counts as a match.
- Empty values aren't listed, so you can't filter for "parameter is blank".

---

## 8. Cancelling and undoing

| You want to… | Do this |
|---|---|
| Close the window without selecting | Click the window's **X**. Nothing happens. |
| Stop while drawing the box | Press **Esc**. The tool ends quietly. |
| Clear the selection afterwards | Press **Esc** in the view, or click an empty spot. |
| Undo | Not needed. The tool never changes the model, so there's nothing in the Undo list. |

---

## 9. What you'll see on screen

These tools don't show success or warning messages. Here's what to expect:

| Moment | What you see |
|---|---|
| After clicking the button | The **Choose Categories** or **Choose Category** window |
| After **Make A Selection** | The window closes, and Revit's status bar (bottom left) says **"Select Elements"** |
| While dragging | Only the elements that will be selected are highlighted *(except in Exclude mode, see [Section 5](#5-exclude-mode-shift--click))* |
| After releasing the mouse | The elements are selected. The count appears in the bottom-right selection counter. |
| 🔴 A pyRevit error window | Something unexpected happened. Screenshot it and contact the author (see [Section 12](#12-contact-the-author)). |

---

## 10. FAQ

**Does this change anything in my model?**
No. It only selects. That's also why there's nothing to undo.

**Can I add more elements to what I've already selected?**
Not with the tool, because each run replaces the selection. Afterwards you can add elements the normal Revit way (**Ctrl + click**).

**Why is a category in the list when there's nothing of it in my model?**
The list shows every model category the model knows about, whether or not it's used.

**I can't find Tags / Dimensions / Text in the list.**
Those are annotation categories. The tool only lists model categories.

**Can I select elements from a linked model?**
No. Only elements in the model you're working in.

**Why does the Parameter dropdown take a moment to fill?**
The tool scans every element of that category in the whole model to build the list. Big categories (e.g. Pipes, Ducts) can take a few seconds.

**The value I want isn't in the Value dropdown.**
Only values that exist in the model are listed, and blank values are skipped. Check the element's properties to confirm what the value actually is.

**Can I filter "Length greater than 3 m" or "Mark contains A-"?**
No. Values must match exactly. Pick each value you need and combine the rows with **OR**.

**Can I choose several categories in Pre-Filter by Parameter?**
No, one category at a time. Parameters differ between categories, so the tool keeps it to one.

**Does Shift + click work on Pre-Filter by Parameter?**
No. Exclude mode belongs to the category tool only. For the parameter tool, use **NOT** instead.

**My results changed after someone converted the project units.**
Values are compared the way they're displayed (e.g. `900 mm` vs `2' 11 7/16"`). Pick the values again from the dropdown after a unit change.

---

## 11. Troubleshooting

| Symptom | Likely cause | What you can check | Contact author? |
|---|---|---|---|
| Can't find the button | B-Dare95 tab missing or not loaded | Restart Revit. Check that the **B-Dare95** tab is on the ribbon. | ✅ If it's still missing |
| **Make A Selection** is greyed out | No category chosen, or a row has a parameter but no value | Tick or choose a category. Pick a value, or remove the row with **×**. | ❌ |
| **+ Add Filter** is greyed out | No category chosen yet | Choose a category first | ❌ |
| Nothing got selected | No matching elements in the box, or they're hidden in the view | Draw a bigger box. Check visibility/graphics. Loosen your rules. | ❌ |
| Fewer elements than expected | Rules too strict, or rule order (see [Section 7](#7-understanding-and--or--not)) | Try one rule at a time. Move **OR** rows above **AND** rows. | ❌ |
| Excluded elements highlighted while dragging | Normal in Exclude mode | Release the mouse. They're removed. | ❌ |
| Linked elements not selected | Linked models aren't supported | Open the linked model directly | ❌ |
| Parameter or Value dropdown is empty | Category has no elements, or parameter has no values | Check that the model has elements of that category | ❌ |
| Window takes long to fill | Very large category | Wait a few seconds | ✅ If Revit freezes |
| Red pyRevit error window | Unexpected problem | Screenshot it | ✅ |
| Anything else unexpected | — | Press **Esc**, then try again | ✅ If it repeats |

---

## 12. Contact the author

If your problem isn't solved by the steps above, **please don't try to fix the tool yourself**. Contact:

> 👤 **Mohamed Bedair**
> ✉️ [email] · 💬 [Teams / chat]

**Please include:**

1. **Which tool** you used (Pre-Filter Selection, Exclude mode, or Pre-Filter by Parameter)
2. A **screenshot** of the window with your choices, and of any error
3. Your **Revit version** (e.g. 2025)
4. The **model name** and the **view** you were in
5. **What you expected** to be selected, and what actually was
