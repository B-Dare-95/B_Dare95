# Warning Chart

> ⚡ **TL;DR**
> Shows every warning in your model as a **live pie chart**, one slice per warning type. Click a slice and Revit **selects the elements** behind it.
>
> 1. Click **Warning Chart**. The window opens on top of Revit and you can keep working.
> 2. **Hover** a slice for the full warning text and counts. **Click** a slice (or its row in the list) to select its elements.
> 3. Fix them. The chart **updates by itself** every few seconds.
>
> ⚠️ Only the **first 1,500 warnings** are read by default, and turning **Isolate on click** off clears **any** temporary hide/isolate in the active view, including your own.

🎬 *[GIF, ~10 s: open Warning Chart → hover a slice (it pops out, tooltip shows) → click it → elements are selected in Revit → fix one → the slice shrinks]*

*📍 B-Dare95 tab → Warnings panel → Warning Chart · 🧩 Revit 2024+ · 👤 Mohamed Bedair · 🗓️ 28 Oct 2026*

---

# 📖 Full guide

*Everything below is reference. You only need it if the TL;DR didn't answer your question.*

> 🔤 **Renamed:** this tool used to be called **War Chart** on the ribbon. It's the same tool and the same window.

## 1. What this tool does

**Warning Chart** shows all the warnings in your model as a **live pie chart**.

- Every **slice** is one **warning type** (e.g. *"Highlighted walls overlap"*).
- The **bigger the slice**, the more of that warning you have.
- **Click a slice** (or its row in the list) and Revit **selects every element** involved in that warning type: both the elements Revit marks as failing and any extra elements it lists with the warning.
- The chart **refreshes by itself** while you work, so you can watch slices shrink as you fix things.

> 💡 Think of it as a dashboard for Revit's *Review Warnings* list. Instead of scrolling a long text list, you see at a glance which problem is the biggest, and one click takes you to the elements.

📸 *[Screenshot: the Warning Chart window with the pie on the left and the list on the right]*

---

## 2. What this tool does NOT do

| ❌ It does NOT… | What this means for you |
|---|---|
| Fix warnings | It only **shows** and **selects**. You fix the elements yourself (or with the **Resolvers** tools). |
| Change your model elements | Nothing is moved, edited or deleted. The only thing it can change is the **temporary** hide/isolate state of your active view (see [Section 6](#6-isolate-on-click)). |
| Select elements inside linked models | If none of a warning's elements can be found in this model, a message tells you nothing could be selected. |
| Add to your current selection | Each click **replaces** what you had selected. |
| Always read every warning in huge models | By default it reads the **first 1,500 warnings**. You can raise this in Settings. |
| Show each warning on its own | It groups by **warning type**. For individual warnings, use Revit's **Review Warnings**. |

---

## 3. Before you start

- [ ] A **model** is open.
- [ ] For **Isolate on click**: the active view is one that allows *Temporary Hide/Isolate* (plans, sections, 3D views…).
- [ ] For selecting: the elements you want are in **this** model, not in a linked model.

---

## 4. How to use it

1. Click **Warning Chart** on the **Warnings** panel.
2. The chart window opens on top of Revit. You can **keep working** in Revit while it's open.
3. Look at the **header**: the big yellow number is your total, with the number of warning types under it.
4. **Hover** over a slice. It pops out with a yellow outline, its row in the list lights up, and a tooltip shows the full warning text, the number of warnings, the number of elements and the percentage.
5. **Click** the slice (or its row in the list on the right).
6. Revit **selects** all elements involved in that warning type. ✅
7. Fix the elements. Within a few seconds the chart **updates by itself**.
8. When you're done, click **✖** (top right) to close the window.

> 💡 Clicking **Warning Chart** on the ribbon again while the window is already open doesn't open a second copy. It brings the existing window to the front and refreshes it.

📸 *[Screenshot: hovering a slice, with the tooltip and the highlighted list row]*

### Window controls

| Control | What it does |
|---|---|
| **Header bar** (top) | Drag it to move the window. |
| **Big number + caption** | Total **warnings** (or total **elements**, depending on Settings) and the number of warning types. |
| ⚙️ **Chart settings** | Opens the **Chart Settings** window (see [Section 7](#7-chart-settings)). |
| 📷 **Save chart as PNG** | Copies a picture of the window to the clipboard, then asks where to save it as a PNG file (see [Section 8](#8-saving-the-chart-as-a-picture)). |
| 🔄 **Refresh now** | Re-reads the warnings straight away. |
| ✖ **Close** | Closes the window. |
| **Isolate on click** (top left of the chart) | When on (yellow), clicking a slice also isolates its elements in the active view. |
| **Pie slices** | Hover for details. Click to select. Big enough slices show their count and percentage inside. |
| **Search warnings...** (right) | Filters the list by warning text as you type (upper/lower case doesn't matter). The pie itself stays complete. |
| **List rows** | Count, colour dot and warning text. Hover to make its slice pop out and see a tooltip with the full text, warnings and elements. Click to select. |
| **Resize grip** (bottom-right corner) | Drag to make the window bigger or smaller. |

---

## 5. Reading the chart

| What you see | What it means |
|---|---|
| Slice size | That warning type's share of the total. |
| Number inside a slice | Count and percentage. Only shown on slices big enough to fit the text (about 3.6% of the pie or more). |
| Order | Biggest warning type first, both in the pie and in the list. Equal sizes are sorted by warning text. |
| Colours | Five colours are used in turn. With more than five types, colours **repeat**. Use hover or the list to tell them apart. |
| Yellow banner under the header | A notice from the tool (see [Section 10](#10-messages-you-may-see)). |
| "No warnings in this model." | There's nothing to show. |

### Hover details

| You hover… | You get |
|---|---|
| A **slice** | The slice pops out with a yellow outline, its list row lights up, and a tooltip shows: the full warning text, then **_ warning(s) \| _ element(s) \| _%**. |
| A **list row** | The row lights up, its slice pops out, and a tooltip shows the full warning text and **_ warning(s) \| _ element(s)** (no percentage). |

The tooltips always show **both** numbers, whichever slice size you chose in Settings.

### Warning count vs Element count

In Settings you can choose what the slice size is based on:

| Option | Slice size = | Good for |
|---|---|---|
| **Warning count** *(default)* | Number of warnings of that type | "Which problem shows up most often?" |
| **Element count** | Number of **different elements** involved in that type | "Which problem touches the most elements?" |

> ℹ️ With **Element count**, an element that appears in two warning types is counted in **both**, so the big total in the header can be higher than the number of distinct elements. Warning types that have no elements at all are left out of the chart in this mode.

---

## 6. Isolate on click

1. Click the **Isolate on click** button (top left of the chart). It turns **yellow**.
2. Click a slice. The elements are selected **and** temporarily isolated in the **active view**.
3. Click another slice. The previous isolation is replaced by the new one.
4. Click **Isolate on click** again to turn it off. The temporary isolation in the active view is removed.

> ⚠️ **Heads-up:**
> - Turning it on immediately selects and isolates the **last warning type you clicked** (if you clicked one).
> - Each click first removes **any** temporary hide/isolate already in the active view, including one you set yourself.
> - Turning it off removes **any** temporary hide/isolate in the view that is active **at that moment**. If you switched views in between, the earlier view keeps its isolation.

> 💡 When **Isolate on click** is on, the **Zoom to elements after selecting a slice** setting is not used.

Your choice (on or off) is remembered next time you open Warning Chart.

---

## 7. Chart Settings

Click ⚙️ to open **Chart Settings**. The chart window is locked until you close it. Changes only apply when you click **Save Changes**, and the chart then refreshes. They're remembered on **your computer** for every model you open.

| Setting | What it does | Default |
|---|---|---|
| **Maximum Warning Count** | *"Warnings beyond this number are not read (keeps huge models responsive)."* Allowed range 1 to 1,000,000: lower values become 1, higher values become 1,000,000. If you type something that isn't a whole number, it goes back to 1,500. | 1,500 |
| **Pie Chart Color Scheme** | *"Colors used for different warning types (click to change)"*. The five colours used for the slices, in order: the biggest warning type gets the first colour, the next one the second, and so on. Click a colour to change it. | Five colour-blind friendly shades |
| **Reset to Default** | Puts the five original colours back (still needs **Save Changes**). | — |
| **Slice Size Based On** | **Warning count** or **Element count** (see [Section 5](#5-reading-the-chart)). The header caption changes to match. | Warning count |
| **Auto-refresh the chart while I work** | Re-checks the warnings every 3 seconds and redraws when the totals change. Off = the chart only updates when you click 🔄. | On |
| **Zoom to elements after selecting a slice** | After a click, Revit zooms to the selected elements. Not used while **Isolate on click** is on. | Off |

**Cancel** closes the window without changing anything.

### Choosing a colour

Clicking one of the five colours opens **Choose a color**:

- Click any of the **swatches** (hover one to see its code), or type a colour code in the box (e.g. `#FFC800`).
- The **Selected:** box previews your choice.
- Click **OK** to use it, or **Cancel** to keep the old colour. If the code in the box isn't a valid colour when you click **OK**, the old colour is kept.

📸 *[Screenshot: the Chart Settings window]*

---

## 8. Saving the chart as a picture

1. Click 📷 **Save chart as PNG** in the header.
2. A picture of the **whole window** (header, chart and list, as you see them now) is copied to the **clipboard**.
3. A **Save** window opens with the name `WarChart.png`. Pick a folder and name, then click **Save**.

> 💡 Even if you **Cancel** the Save window, the picture is still on the clipboard. Paste it straight into an email or Teams chat.

---

## 9. Undoing

| You want to… | Do this |
|---|---|
| Clear the selection | Press **Esc** in the view, or click an empty spot. |
| Remove the isolation | Turn **Isolate on click** off, or use Revit's own **Reset Temporary Hide/Isolate** (sunglasses icon in the view control bar). |
| Undo a model change | Not needed. The tool doesn't change model elements. |

> ℹ️ Isolating and un-isolating are done as small Revit steps named **WarChart: Isolate Warning Elements** and **WarChart: Restore View**, so you may see these names in Revit's Undo list. They only affect the temporary view state.

---

## 10. Messages you may see

| Message | Where | Why | What to do |
|---|---|---|---|
| 🟡 **"Only the first _ of _ warnings were read. Raise 'Maximum Warning Count' in settings to include the rest."** | Yellow banner | Your model has more warnings than the current limit. | Open ⚙️ Settings and raise **Maximum Warning Count**. Very high values can make the chart slower in big models. |
| 🟡 **"No selectable element found for this warning (its elements may live in a linked model)."** | Yellow banner | None of the elements of that warning type exist in this model (they're in a link, or were deleted). | Open the linked model and check the warning there, or click 🔄 if you already fixed it. |
| 🟡 **"The active view does not support temporary isolation, so the elements were only selected."** | Yellow banner | **Isolate on click** is on, but the active view (e.g. a schedule or sheet) can't isolate. | Switch to a plan, section or 3D view and click again. |
| 🔵 **"No warnings in this model."** | Middle of the chart | Nothing to show. | Nothing. |
| 🔵 **"No warning matches this search."** | List | Your search text isn't in any warning text. | Shorten or clear the search. |
| 🔴 **A pyRevit error window** | Pop-up | Something unexpected happened. | Screenshot it and contact the author (see [Section 13](#13-contact-the-author)). |

> ℹ️ A yellow banner message stays until the chart next refreshes with a change. Click 🔄 **Refresh now** to clear it.

---

## 11. FAQ

**Does this change my model?**
No. It reads warnings and selects elements. The only thing it can change is the temporary hide/isolate of the active view, when **Isolate on click** is on.

**Can I keep working while the chart is open?**
Yes. The window stays on top of Revit, and you can model, select and fix things as usual.

**Why didn't the chart update right after I fixed something?**
Auto-refresh checks every 3 seconds, and only redraws when the totals change. Click 🔄 **Refresh now** to force it. If auto-refresh is off in Settings, the chart only updates when you click 🔄.

**Why do two slices have the same colour?**
There are only five colours, and they repeat. Hover over a slice or use the list to see which warning it is.

**I clicked a slice but fewer elements were selected than the count says.**
Elements that no longer exist, or that live in a linked model, can't be selected.

**Why doesn't Zoom to elements work?**
It's switched off by default. Turn it on in ⚙️ Settings. It's also not used while **Isolate on click** is on.

**Where does the PNG go?**
Wherever you choose in the Save window (default name `WarChart.png`). It's also copied to the clipboard, even if you cancel saving.

**Why does the window header and the PNG name still say "WarChart"?**
That's the tool's old name, still used inside the window. It's the same tool as **Warning Chart** on the ribbon.

**I switched to another open model. Does the chart follow?**
The chart reads the warnings of the **active** model when it refreshes. After switching, click 🔄 **before** clicking a slice, so you select elements from the right model.

**Can I see each individual warning?**
No. Warning Chart groups warnings by type. Use Revit's **Manage → Review Warnings** for the full list.

---

## 12. Troubleshooting

| Symptom | Likely cause | What you can check | Contact author? |
|---|---|---|---|
| Can't find the button | B-Dare95 tab missing or not loaded | Restart Revit. Check that the **B-Dare95** tab is on the ribbon. | ✅ If it's still missing |
| Clicking the button seems to do nothing | The window is already open, maybe behind another window or off-screen | Look for the chart window. Clicking the button brings it to the front. | ✅ If you can't find it |
| Chart is empty but Revit shows warnings | The chart didn't refresh yet, or **Element count** is on and those warnings have no elements | Click 🔄 **Refresh now**. Try **Warning count** in Settings. | ✅ If it stays empty |
| Chart doesn't update while I work | Auto-refresh is off, or totals didn't change | Check ⚙️ Settings. Click 🔄. | ❌ |
| Totals seem too low | **Maximum Warning Count** limit reached | Look for the yellow banner. Raise the limit. | ❌ |
| Nothing selected after clicking | Elements are in a linked model, or no longer exist | Read the yellow banner | ❌ |
| Not isolated, only selected | View doesn't support temporary isolation | Use a plan, section or 3D view | ❌ |
| My own temporary isolation disappeared | **Isolate on click** was turned off, or a slice was clicked while it was on | Re-apply your isolation after using the tool | ❌ |
| Settings don't stick | Clicked **Cancel** instead of **Save Changes** | Open Settings again and click **Save Changes** | ✅ If it still doesn't stick |
| Revit feels slow with the chart open | Very large model, high warning limit | Lower **Maximum Warning Count**, or turn auto-refresh off | ✅ If it stays slow |
| Red pyRevit error window | Unexpected problem | Screenshot it | ✅ |

---

## 13. Contact the author

If your problem isn't solved by the steps above, **please don't try to fix the tool yourself**. Contact:

> 👤 **Mohamed Bedair**

**Please include:**

1. A **screenshot** of the chart window (the 📷 button copies one to your clipboard)
2. A screenshot of any **error** or yellow banner
3. Your **Revit version** (e.g. 2025)
4. The **model name** and the **view** you were in
5. Which **slice / warning type** you clicked, and what you expected to happen
