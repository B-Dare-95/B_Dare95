# Clash Manager

> 📍 **Where to find it:** Revit ribbon → **B-Dare95** tab → **Clashes** panel → **Clash Manager**
> 🧩 **Works with:** Revit 2024 and newer · Navisworks **HTML** clash reports
> 👤 **Tool author:** Mohamed Bedair — [contact email / Teams]
> 🗓️ **Last updated:** 13 Oct 2026

---

## 1. What this tool does

**Clash Manager** reads a **Navisworks clash report (HTML)** and lets you walk through the clashes **inside Revit**.

For each clash you can:

| Action | Button | What happens |
|---|---|---|
| **See the details** | *(click a clash in the list)* | The two clashing elements are looked up in your model and its loaded links. The report's clash image is shown if available. |
| **Go to the two elements** | **Focus** | Both elements are **selected and highlighted** (even inside links), the view **zooms** to them, and in a 3D view a **section box** is fitted around them. |
| **Go to them and hide everything else** | **Isolate** | Same as **Focus**, plus both elements are **temporarily isolated**. |
| **Frame the clash point** | **Create Clash Box** | The active **3D view** gets a **section box** (a cube) around the clash point, and the view zooms to it. |
| **Track your progress** | **Solved** tick box | Tick a clash when it's fixed. The tick is saved and is still there next time you (or a colleague) open the same report. |

The window is called **Clash Navigator**. It floats over Revit and stays open while you work.

> 💡 Think of it as the Navisworks clash list, brought into Revit, so you can jump to each clash, fix it on the spot, and tick it off.

📸 *[Screenshot: the Clash Navigator window with a report loaded, a clash selected and a few clashes ticked as solved]*

---

## 2. What this tool does NOT do

| ❌ It does NOT… | What this means for you |
|---|---|
| Run clash tests | You need a report already exported from Navisworks. |
| Read XML, Excel or PDF reports | Only **HTML** reports. |
| Change the clash status in Navisworks | The **Solved** tick is saved for this tool only. Nothing is written back to Navisworks or into the report itself. |
| Show status, distance, grid location or date | The list shows test name, clash name and the two element IDs only. |
| Move or fix elements | It only selects, zooms, isolates and sets section boxes. You fix the model yourself. |
| Isolate a single element inside a link | With **Isolate**, an element in a linked model isolates the **whole link**. (**Focus** still selects just that element.) |
| Remember the last report | Each time the window opens, you load the report again. Your **Solved** ticks come back with it. |

---

## 3. Before you start

- [ ] The model (and the **links** the clashes come from) is **open and loaded** in Revit.
- [ ] You have a Navisworks clash report exported as **HTML**.
- [ ] The report includes the **Element ID** of each item. Without it, the tool can't find the elements.
- [ ] The report's clash-point coordinates are in **meters** (the tool reads them as meters).
- [ ] If the report has images, keep the **image folder next to the HTML file**, as Navisworks exported it.
- [ ] *(Team use)* Keep the report in a **shared folder** if you want colleagues to see the same **Solved** ticks.
- [ ] For the section box parts of **Focus** / **Isolate**, and for **Create Clash Box**: a **3D view** is active and **not locked**.

---

## 4. How to use it

1. Click **Clash Manager**. The **Clash Navigator** window opens.
2. Click **Load HTML Report...** and choose the report file.
3. Wait while it reads. The status line at the bottom shows **"Parsing … -- _ clashes so far..."**. Big reports can take a while, but the window keeps updating.
4. When done, the status line shows **"Loaded _ clashes from _ test(s); _ have clash points; _ already marked solved."** The list fills up. Clashes ticked earlier come back ticked and greyed out.
5. *(Optional)* Type in the box above the list to filter clashes.
6. Click a clash. On the right you see:
   - the clash **image** (if the report has one),
   - **Item 1** and **Item 2**: the element ID, category and name of each element, and which link it's in,
   - the **Clash point** coordinates.
7. Click **Focus** to select both elements, zoom to them and (in a 3D view) box them in.
   Or click **Isolate** to do the same and hide everything else.
8. Or switch to a **3D view**, set the **Clash Box Size (m)**, and click **Create Clash Box** to box in the clash point.
9. Fix the clash in Revit. The window stays open.
10. Tick the **Solved** box on that clash's row. It turns grey. Pick the next clash.

> 💡 Each list line reads: **[Test name] Clash name (Item 1 ID vs Item 2 ID)**. Hover over a line to see it in full if it's cut off.

### Window controls

| Control | What it does |
|---|---|
| **Load HTML Report...** | Opens a file picker for the Navisworks HTML report. The file name then appears next to the button. |
| **Filter box** (above the list) | Shows only clashes whose line contains what you type (test name, clash name or element ID). Upper/lower case doesn't matter. The status line shows **"_ of _ clashes shown."** Filtering never changes your ticks. |
| **Solved** column | One tick box per clash. Tick = solved (the line turns grey). Untick to bring it back. Saved straight away. |
| **Clash** column | All individual clashes from all tests in the report. |
| **Image** (top right) | The clash image from the report, if found. |
| **Item 1 / Item 2** | **Item 1 (ID _):** category \| name. **[in link: …]** means it's inside a linked model. Shows **…** for a moment while it looks the element up. |
| **Clash point** | The X, Y, Z from the report, or **"none in report"**. |
| **Focus** | Clears any temporary isolation, then selects both elements, zooms to them and (3D views) fits a section box around them. |
| **Isolate** | Same as **Focus**, plus temporarily isolates both elements. |
| **Clash Box Size (m)** | Size of the section-box cube for **Create Clash Box**, in **meters**. Default **3.0**. |
| **Create Clash Box** | Sets a section box around the clash point in the active 3D view and zooms to it. |
| **Status line** (bottom) | Progress and results. |

**Focus** and **Isolate** are greyed out until **both** elements are found. Hover over them to see why (e.g. **"Item 2 not found in this model or any loaded link."**).

---

## 5. Focus and Isolate in detail

| | **Focus** | **Isolate** |
|---|---|---|
| Selects and highlights both elements | ✅ Linked elements too, just like Tab-picking into a link | ✅ |
| Zooms to the two elements | ✅ | ✅ |
| Section box around the elements (3D view) | ✅ With **0.5 m** clearance on every side | ✅ |
| Hides everything else | ❌ It **removes** any temporary isolation left on the view | ✅ Temporary isolate of both elements |
| Linked elements | Only that element is selected | The **whole link** is isolated (Revit can't isolate one element inside a link) |

**In plan, section and elevation views** there's no section box. Both buttons still select and zoom, and **Isolate** still isolates. The status line says **"no section box (not a 3D view)"**.

**Moving from clash to clash:** clicking **Isolate** on the next clash first clears the previous isolation, so you never end up with half of a clash hidden. Clicking **Focus** clears it completely.

The status line sums up what happened, for example:

- **"Focus: section box set, 2 element(s) selected (1 linked)."**
- **"Isolate: isolated, no section box (not a 3D view), 2 element(s) selected."**
- **"Focus: isolation cleared, section box set, 2 element(s) selected."**

> 💡 The section box stays on the 3D view after you move on. That's normal. See [Section 9](#9-undoing-and-resetting) to remove it.

---

## 6. Marking clashes as solved

- Tick the box in the **Solved** column when a clash is fixed. The line turns **grey** but stays in the list.
- The status line shows your progress: **"_ of _ clashes solved."**
- Ticks are saved **straight away**, in a small file next to the report called **\<report name\>.html.solved.json**.
  - Anyone who opens the **same report from the same folder** sees the same ticks. Handy for a shared coordination folder.
  - If that folder is **read-only**, the ticks are saved on **your computer** instead, so only you see them.
- Each clash is recognised by its **test name, clash name and both element IDs**, not by its position in the list. So if you **re-export the report with the same file name**, every clash that's still in it keeps its tick. A clash that disappears and comes back later comes back ticked.

> ⚠️ Don't delete or rename the **.solved.json** file next to the report, or the ticks are lost. If you rename or move the report, move the **.solved.json** file with it and rename it to match.

---

## 7. How elements are found

- The tool takes the **Element ID** of each item from the report.
- It looks in **your model** and in **every loaded link**, and only counts real model elements (not types, views or link instances).
- Element IDs aren't unique between models. The same number often exists in your model **and** in a link. When that happens, the tool picks the pair of elements that are **physically closest to each other**, because two clashing elements are always touching.
- If it's a tie, it prefers your own model over links, so a genuine clash inside your model is never pulled into a link.
- A link placed **more than once** works too. The tool picks the copy where the clash actually is.
- If an item isn't found, it shows **"(not found in host or any loaded link)"**, and **Focus** / **Isolate** stay greyed out.

> ⚠️ If the clashing element is in a link that isn't loaded, it can't be found. Load the link first, then click the clash again.

---

## 8. About the clash box and coordinates

- Navisworks usually writes clash points in **shared (survey) coordinates**.
- The first time you click **Create Clash Box** after opening the window, the tool works out how the report's coordinates relate to your model. It does this by checking which conversion puts the point **on top of the two clashing elements**.
- For this to work, **at least one element of that first clash should be found** in your model or links.
- The result is reused for the rest of the window session. The status line then shows e.g. **"Section box set (coordinate mode: …)."**

> 💡 Tip: for your first clash box, pick a clash where both items show a name (not "not found").

> 💡 **Focus** and **Isolate** don't use the clash point at all. They work from the elements themselves, so they still work when the report's coordinates are a problem.

---

## 9. Undoing and resetting

| You want to… | Do this |
|---|---|
| Show everything again after **Isolate** | Click **Focus** on any clash, or use Revit's **Temporary Hide/Isolate** (sunglasses icon in the view control bar) → **Reset Temporary Hide/Isolate**. |
| Remove a section box (from **Focus**, **Isolate** or **Create Clash Box**) | Untick **Section Box** in the 3D view's Properties, or undo it. |
| Clear the selection | Press **Esc** in the view. |
| Undo with Ctrl + Z | Each click is one Undo step: **Clash Navigator - Focus**, **Clash Navigator - Isolate** or **Clash Navigator - Clash Box**. |
| Untick a clash | Click its **Solved** box again. (Ticks aren't part of Revit's Undo.) |
| Close the tool | Click the window's **X**. Your ticks are already saved. Load the report again next time. |

> ℹ️ The tool never changes your **elements**. **Isolate** changes what's visible in the view temporarily. **Focus**, **Isolate** and **Clash Box** change the **section box of the active 3D view**.

---

## 10. Messages you may see

| Message | Why | What to do |
|---|---|---|
| 🔵 **"Reading …"** / **"Parsing … -- _ clashes so far..."** | The report is being read. | Wait. |
| 🟢 **"Loaded _ clashes from _ test(s); _ have clash points; _ already marked solved."** | Report loaded. | Pick a clash. |
| 🟢 **"Focus: …"** / **"Isolate: …"** | Summary of what Focus or Isolate did (see [Section 5](#5-focus-and-isolate-in-detail)). | — |
| 🟢 **"Section box set."** | Clash box worked. | — |
| 🟢 **"_ of _ clashes solved."** | You ticked or unticked a clash, and it was saved. | — |
| 🔵 **"_ of _ clashes shown."** | The filter is on. | Clear the filter box to see all clashes. |
| 🟡 **"no section box (not a 3D view)"** *(inside a Focus/Isolate summary)* | The active view is a plan, section or elevation. | Normal. Switch to a 3D view if you want the box. |
| 🟡 **"no section box (3D view is locked)"** | The 3D view is locked. | Unlock it, or use another 3D view. |
| 🟡 **"host element(s) selected -- linked selection failed"** | Revit couldn't select the linked element. | Try again. If it repeats, contact the author. |
| 🟡 **"No clashes were found in this report."** | The file isn't a Navisworks clash report, or it has no clash rows. | Check you picked the right HTML file. |
| 🟡 **"Select a clash first."** | No clash selected. | Click a clash in the list. |
| 🟡 **"Clash box size must be a number."** / **"…must be greater than zero."** | The size box has text or 0. | Type a number like `3` or `5`. |
| 🟡 **"Switch to a 3D view first -- Clash Box sets that view's section box."** | Active view isn't 3D. | Open a 3D view and try again. |
| 🟡 **"The active 3D view is locked; unlock it to set a section box."** | The 3D view is locked. | Unlock it, or use another 3D view. |
| 🟡 **"The active view can't show model elements this way. Switch to a plan, section or 3D view."** | E.g. a sheet, schedule or legend is active. | Switch views. |
| 🟡 **"This clash has no clash-point coordinates in the report."** | The report has no clash point for this clash. | Use **Focus** or **Isolate** instead. |
| 🟡 **"Neither Item 1 nor Item 2 could be resolved in the host model or any loaded link."** | Both IDs not found. | Load the right links. Check the report is from this model. |
| 🟡 **"No active Revit document. Open a project and try again."** | No project is open. | Open the project. |
| 🔴 **"Couldn't save the solved state -- neither the report folder nor %APPDATA% is writable."** | The tick couldn't be saved anywhere. It shows in the list but will be lost when you close the window. | Contact your IT or the author. |
| 🔴 **"Can't work out which coordinate system this report uses…"** | Neither element of this clash was found, so the tool can't check the coordinates. | Pick a clash where the items are found, and try **Create Clash Box** again. |
| 🔴 **"None of the coordinate conversions put this clash point anywhere near the elements…"** | The report's units or coordinates don't match, or the elements were moved since the clash test. | Contact the author. |
| 🔴 **"The clash point converts to a location about _ m from this model's internal origin…"** | The coordinates or units don't match this model. | Contact the author. |
| 🔴 **"Clash Navigator ran into an error: …"** | Something unexpected happened. | Screenshot it and contact the author. |

> ℹ️ Some red messages mention settings "at the top of the script". **Don't change anything yourself** — send the message to the author.

---

## 11. FAQ

**Can I keep working in Revit while the window is open?**
Yes. The window floats over Revit. If you're in the middle of a command, the tool waits until you finish it, then runs the action.

**I clicked the button again and nothing new opened.**
Normal. If the window is already open, it's brought to the front instead of opening a second one.

**What's the difference between Focus and Isolate?**
Both select, zoom and (in 3D) box in the two elements. **Isolate** also hides everything else. **Focus** shows everything, and even clears an isolation left from before.

**Why are Focus and Isolate greyed out?**
At least one of the two elements wasn't found. Hover over a button to see which. Load the missing link.

**Why did the whole linked model get isolated?**
Revit can't isolate one element inside a link, so **Isolate** isolates the link that contains it. Use **Focus** if you want just the element highlighted.

**The element is highlighted but I can't see it.**
It may be hidden behind other elements. Use **Isolate**, or switch to a 3D view so the section box crops around it.

**Will my colleague see my Solved ticks?**
Yes, if you both open the **same report file from the same shared folder**, and that folder isn't read-only.

**I re-exported the report. Did I lose my ticks?**
No, as long as the new report has the **same file name in the same folder**. Clashes still in the report keep their ticks.

**Does ticking Solved change anything in Navisworks?**
No. Update the status in Navisworks separately if your team tracks it there.

**Why is there no image?**
The report has no image for that clash, or the image folder isn't next to the HTML file any more.

**Which report units are supported?**
Clash points are read as **meters**. Export your report in meters.

**Can I see the clash status (New / Active / Approved)?**
Not in this tool. Use the report or Navisworks for that.

**Does the clash box size use meters even if my project is in mm?**
Yes. **Clash Box Size (m)** is always in meters.

---

## 12. Troubleshooting

| Symptom | Likely cause | What you can check | Contact author? |
|---|---|---|---|
| Can't find the button | B-Dare95 tab missing or not loaded | Restart Revit. Check the **B-Dare95** tab is on the ribbon. | ✅ If it's still missing |
| Loading takes very long | Very large report (many columns) | Wait. Watch the status line. Export fewer properties next time. | ✅ If Revit freezes |
| "No clashes were found" | Wrong file, or not a Navisworks clash report | Open the HTML in a browser to check | ✅ If it's a real clash report |
| Items show "not found" | Link not loaded, report from another model version, or no Element ID in the report | Load links. Check the report has Element IDs. | ✅ If links are loaded and IDs exist |
| Wrong element shown | Two candidates were equally close | Check the item category/name against the report | ✅ |
| Focus didn't box anything in | Active view isn't 3D, or it's locked | Read the status line. Switch to an unlocked 3D view. | ❌ |
| Clash box in the wrong place or not created | Units or coordinates don't match | Check the report is in meters. Use **Focus** meanwhile. | ✅ |
| Create Clash Box does nothing | Active view isn't 3D, or it's locked | Switch to an unlocked 3D view | ❌ |
| View still isolated | Temporary isolate is still on | Click **Focus**, or **Reset Temporary Hide/Isolate** | ❌ |
| Section box still on | Focus, Isolate and Clash Box leave it on | Untick **Section Box** in Properties | ❌ |
| My ticks disappeared | Report renamed or moved, or the **.solved.json** file deleted | Put the report back where it was, or move the **.solved.json** with it | ✅ If that doesn't help |
| Colleague can't see my ticks | Different copy of the report, or the shared folder is read-only (ticks saved on your PC) | Make sure you both open the same file. Check the folder is writable. | ✅ |
| "Couldn't save the solved state" | No write access to the report folder or your profile | Check folder permissions | ✅ |
| Red error window | Unexpected problem | Screenshot it | ✅ |

---

## 13. Contact the author

If your problem isn't solved by the steps above, **please don't try to fix the tool yourself**. Contact:

> 👤 **Mohamed Bedair**
> ✉️ [email] · 💬 [Teams / chat]

**Please include:**

1. A **screenshot** of the Clash Navigator window (including the status line) and of any message
2. The **report file** (HTML plus its image folder and its **.solved.json**), or tell us where it's saved
3. The **clash name** and **test name** you were on, and which button you clicked
4. Your **Revit version** (e.g. 2025), the **model name** and the **view** you were in
5. Which **links** were loaded, and **what you expected** to happen
