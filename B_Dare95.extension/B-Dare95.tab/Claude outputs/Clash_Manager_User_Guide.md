# Clash Manager

> 📍 **Where to find it:** Revit ribbon → **B-Dare95** tab → **Clashes** panel → **Clash Manager**
> 🧩 **Works with:** Revit 2024 and newer · Navisworks **HTML** clash reports
> 👤 **Tool author:** Mohamed Bedair — [contact email / Teams]
> 🗓️ **Last updated:** 13 Oct 2026

---

## 1. What this tool does

**Clash Manager** reads **Navisworks clash reports (HTML)** and lets you walk through the clashes **inside Revit**. You can open **several reports at once**, each in its own tab.

For each clash you can:

| Action | Button | What happens |
|---|---|---|
| **See the details** | *(click a clash in the list)* | The two clashing elements are looked up in your model and its loaded links. The report's clash image is shown if available. |
| **Go to the two elements** | **Focus** | The elements are **selected and highlighted** (even inside links), the view **zooms** to them, and in a 3D view a **section box** is fitted around them. |
| **Go to them and hide everything else** | **Isolate** | Same as **Focus**, plus the elements are **temporarily isolated**. |
| **Frame the clash point** | **Create Clash Box** | The active **3D view** gets a **section box** (a cube) around the clash point, and the view zooms to it. |
| **Track your progress** | **Solved** / **Approved** tick boxes | Tick a clash when it's fixed, or when it's accepted as it is. Ticks are saved and come back next time you (or a colleague) open the same report. |
| **Share the results** | **Export Results...** | Creates an **HTML results page** with totals, a per-test summary and every clash with its result, ready to send or print. |

The window is called **Clash Navigator**. It floats over Revit and stays open while you work.

> 💡 Think of it as the Navisworks clash list, brought into Revit, so you can jump to each clash, fix it on the spot, tick it off, and send a progress report when you're done.

📸 *[Screenshot: the Clash Navigator window with two report tabs, the summary bar, and a few clashes ticked]*

---

## 2. What this tool does NOT do

| ❌ It does NOT… | What this means for you |
|---|---|
| Run clash tests | You need reports already exported from Navisworks. |
| Read XML, Excel or PDF reports | Only **HTML** reports. |
| Change the clash status in Navisworks | **Solved** and **Approved** are saved for this tool only. Nothing is written back to Navisworks or into the report itself. |
| Filter the clash list | There's no search box in the window any more. Use the tabs to switch reports, and the **Export Results** page to search and filter. |
| Show status, distance or grid location in the window | The list shows test name, clash name and the two element IDs. The **exported results page** does include Navisworks status, distance and grid location. |
| Move or fix elements | It only selects, zooms, isolates and sets section boxes. You fix the model yourself. |
| Isolate a single element inside a link | With **Isolate**, an element in a linked model isolates the **whole link**. (**Focus** still selects just that element.) |
| Remember which reports were open | Each time the window opens, you load the reports again. Your ticks come back with them. |

---

## 3. Before you start

- [ ] The model (and the **links** the clashes come from) is **open and loaded** in Revit.
- [ ] You have one or more Navisworks clash reports exported as **HTML**.
- [ ] Each report includes the **Element ID** of each item. Without it, the tool can't find the elements.
- [ ] The reports' clash-point coordinates are in **meters** (the tool reads them as meters).
- [ ] If a report has images, keep its **image folder next to the HTML file**, as Navisworks exported it.
- [ ] *(Team use)* Keep the reports in a **shared folder** if you want colleagues to see the same ticks.
- [ ] For the section box parts of **Focus** / **Isolate**, and for **Create Clash Box**: a **3D view** is active and **not locked**.

---

## 4. How to use it

1. Click **Clash Manager**. The **Clash Navigator** window opens.
2. Click **Load HTML Reports...** and choose one or more report files. (Hold **Ctrl** or **Shift** in the file picker to choose several.)
3. Wait while they're read. The status line shows progress, e.g. **"[2/3] Parsing Level 01.html: MEP vs STR -- 125 clashes so far..."**. Big reports can take a while, but the window keeps updating.
4. Each report gets its own **tab**. The last one loaded is shown. The status line says e.g. **"3 report(s) opened, 742 clashes in total."**
5. Check the **summary bar** above the list for how many clashes are solved, approved and remaining.
6. Click a clash. On the right you see:
   - the clash **image** (if the report has one),
   - **Item 1** and **Item 2**: the element ID, category and name of each element, which link it's in, and (if it's only part of a bigger element) what **Focus** will select instead,
   - the **Clash point** coordinates.
7. Click **Focus** to select the elements, zoom to them and (in a 3D view) box them in.
   Or click **Isolate** to do the same and hide everything else.
8. Or switch to a **3D view**, set the **Clash Box Size (m)**, and click **Create Clash Box** to box in the clash point.
9. Fix the clash in Revit. The window stays open.
10. Tick **Solved** (fixed) or **Approved** (accepted as it is) on that clash's row. Pick the next clash.
11. Click another tab to work on another report. The tool remembers which clash you were on in each tab.
12. When you're done, click **Export Results...** to create a results page you can share.

> 💡 Each list line reads: **[Test name] Clash name (Item 1 ID vs Item 2 ID)**. Hover over a line to see it in full if it's cut off.

### Window controls

| Control | What it does |
|---|---|
| **Load HTML Reports...** | Opens a file picker. You can pick **several** reports at once. Each opens in its own tab. Picking a report that's **already open** reloads it in its existing tab. |
| **Report path** (next to the button) | The full path of the report in the active tab. |
| **Export Results...** | Creates an HTML results page (see [Section 7](#7-exporting-results)). |
| **Report tabs** | One tab per report, showing **file name (number of clashes)**. Click a tab to switch to it. The active tab is lighter. Hover for the full path and counts. |
| **Tab progress line** | The coloured line under each tab is a progress bar: **green** = solved, **blue** = approved, **red** = remaining. You can see every report's progress at a glance. |
| **✕** on a tab | Closes that report. (Its ticks are already saved.) |
| **Summary bar** | **Total**, **Solved**, **Approved** and **Remaining** for the active report, with percentages. **Remaining** = neither solved nor approved. |
| **Solved** column | One tick box per clash. Tick when the clash has been **fixed**. The line turns **green**. |
| **Approved** column | One tick box per clash. Tick when the clash is **accepted as it is** (no fix needed). The line turns **blue** (green if it's also solved). |
| **Clash** column | All individual clashes from all tests in the report. |
| **Image** (top right) | The clash image from the report, if found. |
| **Item 1 / Item 2** | **Item 1 (ID _):** category \| name. **[in link: …]** means it's inside a linked model. **→ selects: …** shows the main element Focus will select. Shows **…** for a moment while it looks the element up. |
| **Clash point** | The X, Y, Z from the report, or **"none in report"**. |
| **Focus** | Clears any temporary isolation, then selects the elements, zooms to them and (3D views) fits a section box around them. |
| **Isolate** | Same as **Focus**, plus temporarily isolates the elements. |
| **Clash Box Size (m)** | Size of the section-box cube for **Create Clash Box**, in **meters**. Default **3.0**. |
| **Create Clash Box** | Sets a section box around the clash point in the active 3D view and zooms to it. |
| **Status line** (bottom) | Progress and results. |

**Focus** and **Isolate** are greyed out until **both** elements are found. Hover over them to see why (e.g. **"Item 2 not found in this model or any loaded link."**).

---

## 5. Focus and Isolate in detail

| | **Focus** | **Isolate** |
|---|---|---|
| Selects and highlights the elements | ✅ Linked elements too, just like Tab-picking into a link | ✅ |
| Zooms to the clash | ✅ | ✅ |
| Section box around the clash (3D view) | ✅ With **0.5 m** clearance on every side | ✅ |
| Hides everything else | ❌ It **removes** any temporary isolation left on the view | ✅ Temporary isolate |
| Linked elements | Only that element is selected | The **whole link** is isolated (Revit can't isolate one element inside a link) |

**In plan, section and elevation views** there's no section box. Both buttons still select and zoom, and **Isolate** still isolates. The status line says **"no section box (not a 3D view)"**.

**Moving from clash to clash:** clicking **Isolate** on the next clash first clears the previous isolation, so you never end up with half of a clash hidden. Clicking **Focus** clears it completely.

### Parts of bigger elements

Navisworks reports the exact **piece** that clashed: one curtain panel, one mullion, one stair landing, one top rail. That piece is rarely what you want to edit, so **Focus** and **Isolate** select (and isolate) the **main element** it belongs to instead:

| Navisworks reports… | Focus / Isolate select… |
|---|---|
| Curtain panel or mullion | The **curtain wall** (or curtain system / sloped glazing) |
| Stair run, landing, stringer or support | The **stair** |
| Top rail or handrail | The **railing** |
| Baluster, railing support or termination | The **railing** |
| Part of a stacked wall | The **stacked wall** |
| Nested shared family | The **family it's nested in** |
| A door, window or anything else | **That element** (doors stay doors) |

- The **section box and zoom** still fit the **pieces that actually clash**, not the whole curtain wall or stair, so you don't lose sight of the clash.
- If both pieces belong to the same main element (e.g. a panel clashing with a mullion of the same curtain wall), it's selected **once**.
- In the **Item 1 / Item 2** details you'll see an extra line, e.g. **"→ selects: Walls | Curtain Wall 1 (ID 456789)"**.

The status line sums up what happened, for example:

- **"Focus: section box set, 2 element(s) selected (1 linked)."**
- **"Isolate: isolated, no section box (not a 3D view), 2 element(s) selected."**
- **"Focus: section box set, 1 element(s) selected, 2 sub-element(s) swapped for their main element."**

> 💡 The section box stays on the 3D view after you move on. That's normal. See [Section 10](#10-undoing-and-resetting) to remove it.

---

## 6. Solved and Approved

| Tick | Use it when… | Line colour |
|---|---|---|
| **Solved** | The clash has been **fixed** in the model. | Green |
| **Approved** | The clash is **accepted as it is**, no fix needed (e.g. an allowed penetration). | Blue |
| Both | It was fixed **and** signed off. | Green |
| Neither | Still to do. Counts as **Remaining**. | White |

- The two ticks are **independent**. You can tick one, both or neither.
- After each tick, the **summary bar**, the **tab progress line** and the status line update, e.g. **"Level 01.html: 12 solved, 3 approved, 85 open, of 100 clashes."**
- Ticks are saved **straight away**, in a small file next to the report called **\<report name\>.html.solved.json** (it holds both Solved and Approved).
  - Anyone who opens the **same report from the same folder** sees the same ticks. Handy for a shared coordination folder.
  - If that folder is **read-only**, the ticks are saved on **your computer** instead, so only you see them.
- Each clash is recognised by its **test name, clash name and both element IDs**, not by its position in the list. So if you **re-export the report with the same file name**, every clash that's still in it keeps its ticks. A clash that disappears and comes back later comes back ticked.
- Reports ticked with the older version of the tool (Solved only) still load. Nothing is approved until you tick it.

> ⚠️ Don't delete or rename the **.solved.json** file next to the report, or the ticks are lost. If you rename or move the report, move the **.solved.json** file with it and rename it to match.

---

## 7. Exporting results

1. Click **Export Results...**.
2. If more than one report is open, a list appears. Tick the reports to include and click **Export**.
3. Choose where to save the file. The suggested name is **"\<report\> - Results"** for one report, or **"Clash Results \<date\>"** for several.
4. The page is saved and opens in your web browser.

**What's on the results page:**

| Part | Shows |
|---|---|
| **Header** | Number of reports and the export date and time |
| **Totals** *(several reports only)* | Clashes, Open, Solved and Approved for all reports together, with percentages |
| **Show / Search bar** | Buttons to show **All**, **Open**, **Solved** or **Approved** clashes, and a search box (test, clash, element ID, grid…). It stays at the top while you scroll. |
| **One section per report** | The report's name and path, its own totals, and a **per-test table** (Clashes / Open / Solved / Approved). Click the report name to fold the section away. |
| **Clash table** | #, Test, Clash, **Result** (Open / Solved / Approved / Solved & Approved), **Navisworks status**, **Distance**, **Grid**, Item 1 ID, Item 2 ID, Clash point and a small **image** (click to open it full size). |

- **Open** on the page means the same as **Remaining** in the window: neither solved nor approved.
- To print just part of it, filter or search first, then press **Ctrl + P**. Only what's shown is printed, with each report on a new page.

> ⚠️ The images on the results page are **linked**, not copied into it. They only show while the report's image folder stays where it is, and only for people who can reach that folder. The numbers and table always work.

> ℹ️ The page is a snapshot of the ticks **at the moment you exported**. Export again to update it.

---

## 8. How elements are found

- The tool takes the **Element ID** of each item from the report.
- It looks in **your model** and in **every loaded link**, and only counts real model elements (not types, views or link instances).
- Element IDs aren't unique between models. The same number often exists in your model **and** in a link. When that happens, the tool picks the pair of elements that are **physically closest to each other**, because two clashing elements are always touching.
- If it's a tie, it prefers your own model over links, so a genuine clash inside your model is never pulled into a link.
- A link placed **more than once** works too. The tool picks the copy where the clash actually is.
- If an item isn't found, it shows **"(not found in host or any loaded link)"**, and **Focus** / **Isolate** stay greyed out.

> ⚠️ If the clashing element is in a link that isn't loaded, it can't be found. Load the link first, then click the clash again.

---

## 9. About the clash box and coordinates

- Navisworks usually writes clash points in **shared (survey) coordinates**.
- The first time you click **Create Clash Box** after opening the window, the tool works out how the report's coordinates relate to your model. It does this by checking which conversion puts the point **on top of the two clashing elements**.
- For this to work, **at least one element of that first clash should be found** in your model or links.
- The result is reused for the rest of the window session, for every tab. The status line then shows e.g. **"Section box set (coordinate mode: …)."**

> 💡 Tip: for your first clash box, pick a clash where both items show a name (not "not found").

> 💡 **Focus** and **Isolate** don't use the clash point at all. They work from the elements themselves, so they still work when the report's coordinates are a problem.

---

## 10. Undoing and resetting

| You want to… | Do this |
|---|---|
| Show everything again after **Isolate** | Click **Focus** on any clash, or use Revit's **Temporary Hide/Isolate** (sunglasses icon in the view control bar) → **Reset Temporary Hide/Isolate**. |
| Remove a section box (from **Focus**, **Isolate** or **Create Clash Box**) | Untick **Section Box** in the 3D view's Properties, or undo it. |
| Clear the selection | Press **Esc** in the view. |
| Undo with Ctrl + Z | Each click is one Undo step: **Clash Navigator - Focus**, **Clash Navigator - Isolate** or **Clash Navigator - Clash Box**. |
| Untick a clash | Click its **Solved** or **Approved** box again. (Ticks aren't part of Revit's Undo.) |
| Close one report | Click the **✕** on its tab. Its ticks are already saved. |
| Close the tool | Click the window's **X**. Your ticks are already saved. Load the reports again next time. |

> ℹ️ The tool never changes your **elements**. **Isolate** changes what's visible in the view temporarily. **Focus**, **Isolate** and **Clash Box** change the **section box of the active 3D view**.

---

## 11. Messages you may see

| Message | Why | What to do |
|---|---|---|
| 🔵 **"[_/_] Reading …"** / **"[_/_] Parsing … -- _ clashes so far..."** | The reports are being read. | Wait. |
| 🟢 **"_ report(s) opened, _ reloaded, _ clashes in total."** | Reports loaded. | Pick a clash. |
| 🟢 **"\<report\>: _ solved, _ approved, _ open, of _ clashes."** | You switched tabs, or ticked or unticked a clash and it was saved. | — |
| 🟢 **"Focus: …"** / **"Isolate: …"** | Summary of what Focus or Isolate did (see [Section 5](#5-focus-and-isolate-in-detail)). | — |
| 🟢 **"Section box set."** | Clash box worked. | — |
| 🟢 **"Exported _ report(s) to …"** | The results page was saved. It opens in your browser. | — |
| 🔵 **"Closed \<report\>."** | You closed a tab. | — |
| 🟡 **"no section box (not a 3D view)"** *(inside a Focus/Isolate summary)* | The active view is a plan, section or elevation. | Normal. Switch to a 3D view if you want the box. |
| 🟡 **"no section box (3D view is locked)"** | The 3D view is locked. | Unlock it, or use another 3D view. |
| 🟡 **"host element(s) selected -- linked selection failed"** | Revit couldn't select the linked element. | Try again. If it repeats, contact the author. |
| 🟡 **"No clashes found in: …"** | One or more of the files you picked isn't a Navisworks clash report, or has no clash rows. Other files still opened. | Check you picked the right HTML files. |
| 🟡 **"Could not be read: …"** | A file couldn't be opened or read. Other files still opened. | Check the file isn't open elsewhere or damaged. |
| 🟡 **"Load at least one clash report first."** | You clicked **Export Results...** with no report open. | Load a report. |
| 🟡 **"Select a clash first."** | No clash selected. | Click a clash in the list. |
| 🟡 **"Clash box size must be a number."** / **"…must be greater than zero."** | The size box has text or 0. | Type a number like `3` or `5`. |
| 🟡 **"Switch to a 3D view first -- Clash Box sets that view's section box."** | Active view isn't 3D. | Open a 3D view and try again. |
| 🟡 **"The active 3D view is locked; unlock it to set a section box."** | The 3D view is locked. | Unlock it, or use another 3D view. |
| 🟡 **"The active view can't show model elements this way. Switch to a plan, section or 3D view."** | E.g. a sheet, schedule or legend is active. | Switch views. |
| 🟡 **"This clash has no clash-point coordinates in the report."** | The report has no clash point for this clash. | Use **Focus** or **Isolate** instead. |
| 🟡 **"Neither Item 1 nor Item 2 could be resolved in the host model or any loaded link."** | Both IDs not found. | Load the right links. Check the report is from this model. |
| 🟡 **"No active Revit document. Open a project and try again."** | No project is open. | Open the project. |
| 🔴 **"Couldn't save the solved/approved state -- neither the report folder nor %APPDATA% is writable."** | The tick couldn't be saved anywhere. It shows in the list but will be lost when you close the window. | Contact your IT or the author. |
| 🔴 **"Can't work out which coordinate system this report uses…"** | Neither element of this clash was found, so the tool can't check the coordinates. | Pick a clash where the items are found, and try **Create Clash Box** again. |
| 🔴 **"None of the coordinate conversions put this clash point anywhere near the elements…"** | The report's units or coordinates don't match, or the elements were moved since the clash test. | Contact the author. |
| 🔴 **"The clash point converts to a location about _ m from this model's internal origin…"** | The coordinates or units don't match this model. | Contact the author. |
| 🔴 **"Clash Navigator ran into an error: …"** | Something unexpected happened. | Screenshot it and contact the author. |

> ℹ️ Some red messages mention settings "at the top of the script". **Don't change anything yourself** — send the message to the author.

---

## 12. FAQ

**Can I keep working in Revit while the window is open?**
Yes. The window floats over Revit. If you're in the middle of a command, the tool waits until you finish it, then runs the action.

**I clicked the button again and nothing new opened.**
Normal. If the window is already open, it's brought to the front instead of opening a second one.

**Can I open reports from different folders?**
Yes. Load them one batch at a time if they're in different folders. Each gets its own tab, and each keeps its own ticks file next to it.

**I loaded a report that was already open. What happened?**
It was reloaded in its existing tab, with its saved ticks. Useful after re-exporting it from Navisworks.

**What's the difference between Solved and Approved?**
**Solved** = you fixed it. **Approved** = it's acceptable as it is. Anything with neither tick is **Remaining** (or **Open** on the results page).

**Where did the filter box go?**
It's been replaced by the summary bar and the report tabs. To search or filter clashes, use **Export Results...**: the results page has a search box and Open / Solved / Approved buttons.

**What's the difference between Focus and Isolate?**
Both select, zoom and (in 3D) box in the clash. **Isolate** also hides everything else. **Focus** shows everything, and even clears an isolation left from before.

**I clicked Focus on a curtain panel clash and the whole curtain wall got selected.**
That's on purpose. The curtain wall (or stair, or railing) is what you'd normally edit. The section box and zoom still frame the panel that clashed. See [Section 5](#parts-of-bigger-elements).

**Why are Focus and Isolate greyed out?**
At least one of the two elements wasn't found. Hover over a button to see which. Load the missing link.

**Why did the whole linked model get isolated?**
Revit can't isolate one element inside a link, so **Isolate** isolates the link that contains it. Use **Focus** if you want just the element highlighted.

**Will my colleague see my ticks?**
Yes, if you both open the **same report file from the same shared folder**, and that folder isn't read-only. You can also send them the **results page**.

**I re-exported the report. Did I lose my ticks?**
No, as long as the new report has the **same file name in the same folder**. Clashes still in the report keep their ticks.

**The images don't show on the results page.**
They're linked to the report's image folder. If the page was moved to another computer, or the folder was moved or isn't shared, the images can't be found. The rest of the page still works.

**Does ticking Solved or Approved change anything in Navisworks?**
No. Update the status in Navisworks separately if your team tracks it there.

**Why is there no image in the window?**
The report has no image for that clash, or the image folder isn't next to the HTML file any more.

**Which report units are supported?**
Clash points are read as **meters**. Export your reports in meters.

**Does the clash box size use meters even if my project is in mm?**
Yes. **Clash Box Size (m)** is always in meters.

---

## 13. Troubleshooting

| Symptom | Likely cause | What you can check | Contact author? |
|---|---|---|---|
| Can't find the button | B-Dare95 tab missing or not loaded | Restart Revit. Check the **B-Dare95** tab is on the ribbon. | ✅ If it's still missing |
| Loading takes very long | Very large reports (many columns), or many reports at once | Wait. Watch the status line. Export fewer properties next time. | ✅ If Revit freezes |
| "No clashes found in: …" | Wrong file, or not a Navisworks clash report | Open the HTML in a browser to check | ✅ If it's a real clash report |
| Items show "not found" | Link not loaded, report from another model version, or no Element ID in the report | Load links. Check the report has Element IDs. | ✅ If links are loaded and IDs exist |
| Wrong element shown | Two candidates were equally close | Check the item category/name against the report | ✅ |
| Focus selected a whole wall / stair / railing | The clash was on a part of it (panel, landing, rail) | Expected. Check the **→ selects:** line in the details. | ❌ |
| Focus didn't box anything in | Active view isn't 3D, or it's locked | Read the status line. Switch to an unlocked 3D view. | ❌ |
| Clash box in the wrong place or not created | Units or coordinates don't match | Check the report is in meters. Use **Focus** meanwhile. | ✅ |
| Create Clash Box does nothing | Active view isn't 3D, or it's locked | Switch to an unlocked 3D view | ❌ |
| View still isolated | Temporary isolate is still on | Click **Focus**, or **Reset Temporary Hide/Isolate** | ❌ |
| Section box still on | Focus, Isolate and Clash Box leave it on | Untick **Section Box** in Properties | ❌ |
| My ticks disappeared | Report renamed or moved, or the **.solved.json** file deleted | Put the report back where it was, or move the **.solved.json** with it | ✅ If that doesn't help |
| Colleague can't see my ticks | Different copy of the report, or the shared folder is read-only (ticks saved on your PC) | Make sure you both open the same file. Check the folder is writable. Or send them an exported results page. | ✅ |
| "Couldn't save the solved/approved state" | No write access to the report folder or your profile | Check folder permissions | ✅ |
| Results page has no images | Image folder moved, or not reachable from that computer | Keep the report and its image folder together, in a shared location | ❌ |
| Results page didn't open | No default browser for .html files | Open the saved file yourself | ❌ |
| Red error window | Unexpected problem | Screenshot it | ✅ |

---

## 14. Contact the author

If your problem isn't solved by the steps above, **please don't try to fix the tool yourself**. Contact:

> 👤 **Mohamed Bedair**
> ✉️ [email] · 💬 [Teams / chat]

**Please include:**

1. A **screenshot** of the Clash Navigator window (including the tabs, summary bar and status line) and of any message
2. The **report file(s)** (HTML plus image folder and **.solved.json**), or tell us where they're saved
3. The **clash name** and **test name** you were on, and which button you clicked
4. Your **Revit version** (e.g. 2025), the **model name** and the **view** you were in
5. Which **links** were loaded, and **what you expected** to happen
