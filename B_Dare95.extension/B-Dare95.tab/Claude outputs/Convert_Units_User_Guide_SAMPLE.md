# Convert Units — User Guide

> 📍 **Where to find it:** Revit ribbon → **B-Dare95** tab → **Automations** panel → **Convert Units**
> 🧩 **Works with:** Revit 2024 and newer
> 👤 **Tool author:** [Author Name] — [contact email / Teams]
> 🗓️ **Last updated:** [Date]

---

## 1. What this tool does

**Convert Units** switches your model's **Project Units** between **Metric** and **Imperial** with a single click.

- If your model is in **Metric**, one click makes it **Imperial**.
- If your model is in **Imperial**, one click makes it **Metric**.

It updates the units for **every discipline** at once: Common, Structural, HVAC, Electrical, Piping, Energy and Infrastructure. It also applies the office's standard unit settings, such as millimeters for length and m² with two decimals for area, so you don't have to set anything by hand in *Manage → Project Units*.

> 💡 Think of it as changing the "language" your model's numbers are shown in. The model itself stays exactly the same.

---

## 2. What this tool does NOT do

Please read this section. It answers most of the questions people ask.

| ❌ It does NOT… | What this means for you |
|---|---|
| Resize or move anything | Walls, floors, pipes and every other element stay exactly where they are and keep their true size. A 3000 mm wall becomes a 9' 10 1/8" wall. It's the same wall. |
| Convert linked models | Only the model you are working in changes. Linked files keep their own units. |
| Convert your other open models | Each open model is separate. Run the tool in each one that needs converting. |
| Change text you typed | If you typed "3000 mm" into a text note, it stays "3000 mm". |
| Change Revit's own settings | Only this model's Project Units change. |
| Override custom formats | Dimension types, schedule fields or tags that someone set to a **specific unit** (instead of "Use project settings") keep that unit. |

---

## 3. Before you start

Tick these off before you click the button:

- [ ] A model is **open**, and its view window is **active**. Click inside the view once to make sure.
- [ ] The model is **not read-only**.
- [ ] **Shared (central) model?** Sync first and let your team know. Units apply to the whole project, so everyone will see the change after they sync.
- [ ] You know which system you're aiming for. The tool always switches to the **opposite** of the current system.

---

## 4. How to use it

1. Open the model you want to convert.
2. Go to **B-Dare95** tab → **Automations** panel.
3. Click **Convert Units**.
4. That's it. The switch happens **immediately**. You won't see a confirmation window.
5. **Check the result:**
   - Look at any dimension in a view. It should now show the new units.
   - Or open **Manage → Project Units** and check that **Length** shows the expected unit.

> ✅ **No pop-up = success.** The tool stays quiet when everything worked. It only opens a window when it has something to tell you (see [Section 9](#9-messages-you-may-see)).

📸 *[Screenshot: the Convert Units button on the ribbon]*

---

## 5. Reading the button icon

The button's icon changes to show which system your model was just switched to:

| Icon | Meaning |
|---|---|
| 📸 *[on icon]* | Model is now **Metric** |
| 📸 *[off icon]* | Model is now **Imperial** |
| 📸 *[default icon]* | You haven't used the tool yet in this Revit session, so the icon doesn't show either system yet |

> ⚠️ **Important:** The icon updates **only when you click the button**. If you restart Revit or switch to another open model, the icon may **not** match that model.
> **To be sure, check a dimension or *Manage → Project Units*.** The model is always the source of truth, not the icon.

---

## 6. Office unit standards applied

After conversion, these are the units you'll see:

| Quantity | Metric | Imperial |
|---|---|---|
| Length | Millimeters (no decimals) | Feet and fractional inches |
| Distance | Meters (0.001) | Feet and fractional inches |
| Area | m² (0.01) | ft² |
| Volume | m³ (0.01) | ft³ |
| Angle | Degrees (0.01) | Degrees (0.01) |
| Rotation Angle | Degrees (0.01) | Degrees (0.01) |
| Slope | Degrees (0.01) | Rise / 12" |
| Speed | m/s (0.1) | ft/s |
| Time | Seconds | Seconds |
| Mass Density | kg/m³ (0.01) | lb/ft³ |
| Cost per Area | Currency / m² (0.01) | Currency / ft² |
| Currency | 0.01 | 0.01 |

Everything else (for example, HVAC airflow, electrical current, pipe pressure) uses **Revit's standard default** for the chosen system.

> 💡 Numbers in brackets show the rounding. For example, (0.01) means two decimal places.

---

## 7. Undoing a conversion

Changed your mind? You have two options:

- **Undo:** press **Ctrl + Z** straight away. The undo list shows the step as **"Convert Project Units to Metric"** or **"… to Imperial"**.
- **Click again:** click **Convert Units** once more to switch back.

> ⚠️ Clicking again brings back the **office standard** settings, not any custom unit settings the model had before. If the model had special settings you want to keep, use **Ctrl + Z** instead.

---

## 8. Using it in shared (central) models

- The change is **project-wide**. After your next **Sync with Central**, everyone gets it.
- **Agree with your team first** so nobody is surprised by different numbers.
- If the conversion fails in a shared model, **sync, reload latest, and try again**. If it still fails, contact the author (see [Section 12](#12-contact-the-author)).

---

## 9. Messages you may see

### 🟡 "No active document. Open a model before running this tool."
**Why:** No model is open, or Revit doesn't see an active view.
**What to do:** Open a model, click inside a view, and click the button again.

### 🟡 "This document is read-only. Project Units cannot be changed."
**Why:** The model was opened as read-only (for example, it's locked, or opened from a protected location).
**What to do:** Close it and reopen it normally, or ask the file owner for edit access.

### 🔴 "Unit conversion failed and was rolled back."
**Why:** Revit refused the change. **Nothing in your model was changed**, so it's safe.
**What to do:** In a shared model, sync and try again. If the message comes back, **take a screenshot of the full message** and send it to the author.

### 🔵 Output window: "Convert Units — now Metric / Imperial … These overrides were skipped"
**Why:** The conversion **worked**, but one or more office standard settings from [Section 6](#6-office-unit-standards-applied) couldn't be applied in your Revit version. Those items use Revit's default instead.
**What to do:** You can keep working. **Screenshot the window and send it to the author** so the tool can be updated.

---

## 10. FAQ

**Will this change the size of my walls, pipes or anything else?**
No. Only the way numbers are **displayed** changes. The model geometry is untouched.

**I clicked the button and nothing happened. Did it work?**
Most likely, yes. The tool doesn't show a message when it succeeds. Check a dimension or *Manage → Project Units*.

**Do my schedules and tags update?**
Yes, as long as they're set to "Use project settings", which is the usual case. Fields that someone set to a specific unit keep that unit.

**Does it convert my linked models too?**
No. Only the model you're in. Open a linked model separately if it also needs converting.

**I have two models open. Will both change?**
No. Only the one whose view is active when you click.

**Why does the icon show the wrong system?**
The icon only updates when you click it. See [Section 5](#5-reading-the-button-icon). Always check the model itself.

**Can I convert just one discipline, for example only Electrical?**
No. The tool converts everything at once. To change a single discipline, use Revit's *Manage → Project Units* manually.

**Can I choose my own units, like centimeters instead of millimeters?**
Not through the tool. It always applies the office standard. You can adjust individual units afterwards in *Manage → Project Units*. Contact the author if the office standard itself needs to change.

**Does it work inside the Family Editor?**
Yes. It converts the units of the family you have open. It doesn't affect the project the family is loaded into.

**Is it safe to try?**
Yes. You can always go back with **Ctrl + Z** or by clicking again.

---

## 11. Troubleshooting

| Symptom | Likely cause | What you can check | Contact author? |
|---|---|---|---|
| I can't find the button | B-Dare95 tab missing or not loaded | Restart Revit. Check that the **B-Dare95** tab appears on the ribbon. | ✅ If the tab is still missing |
| Button is greyed out | No model open, or you're in a mode where tools are locked (e.g. editing a sketch) | Finish or cancel the current edit, then open a model | ✅ If it stays greyed out |
| Icon doesn't match the model | Icon only updates on click | Check *Manage → Project Units* | ❌ Normal behavior |
| Some dimensions didn't change | That dimension type uses its own unit setting | Select the dimension → **Edit Type** → **Units Format**. Is "Use project settings" ticked? | ❌ Normal behavior |
| A schedule column didn't change | That field has its own format | Schedule properties → **Formatting** → **Field Format** | ❌ Normal behavior |
| "Conversion failed and was rolled back" | Revit rejected the change | Sync (if shared), reopen the model, try again | ✅ If it repeats |
| Output window lists skipped items | A standard setting isn't supported in your Revit version | Nothing. The conversion still worked. | ✅ Send a screenshot |
| Wrong direction (went Imperial when I wanted Metric) | Model was already in the system you wanted | Click again, or press Ctrl + Z | ❌ |
| Anything else unexpected | — | Press **Ctrl + Z** first to return to a safe state | ✅ |

---

## 12. Contact the author

If your problem isn't solved by the steps above, **please don't try to fix the tool yourself**. Contact:

> 👤 **[Author Name]**
> ✉️ [email] · 💬 [Teams / chat]

**Please include:**

1. A **screenshot** of any message or output window
2. Your **Revit version** (e.g. 2025)
3. The **model name**, and whether it is a shared (central) model
4. **What you clicked** and what you expected to happen
