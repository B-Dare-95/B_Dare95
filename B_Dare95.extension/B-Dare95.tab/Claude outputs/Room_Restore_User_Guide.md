# Room Restore — User Guide

> 📍 **Where to find it:** Revit ribbon → **B-Dare95** tab → **Modify** panel → **Rooms** dropdown → **Room Restore**
> 🧩 **Works with:** Revit 2024 and newer · project files only (not families)
> 👤 **Tool author:** Mohamed Bedair — [contact email / Teams]
> 🗓️ **Last updated:** [Date]

---

## 1. What this tool does

**Room Restore** brings back rooms that were **deleted** or became **unplaced**, with their number, name and other information, in the place they used to be.

It works like a **safety net**:

1. It keeps a **record** (called the **Room Register**) of every room in your model: where it is, its level, its phase and its information.
2. While **tracking** is on, it updates that record as rooms are added, changed or deleted.
3. When a room goes missing, you open the tool, **tick the rooms you want back**, and click **Restore**.

| Room situation | What Room Restore does |
|---|---|
| **Unplaced** (still in the model, but not in any space, e.g. its walls were moved or deleted) | Places **the same room** back at its last location |
| **Deleted** (completely removed from the model) | Creates a **new room** at its last location and copies back its number, name and other information |

> 💡 Think of it as the **Recycle Bin for rooms**. The tool can only give back what it saw before it went missing, so turn it on early.

📸 *[Screenshot: the Room Restore button in the Rooms dropdown]*

---

## 2. Two things to know first

### 🗂️ The Room Register (one-time setup per model)

The register is the tool's memory for one model. You create it **once per model** with **Shift + click** (see [Section 5](#5-step-1--create-the-register-once-per-model)). It's saved **on your own computer**, not inside the Revit model.

### 🟢 Tracking (once per Revit session)

The register only updates live while **tracking** is on. Tracking starts when you **click the Room Restore button** (normal click or Shift + click) and stays on **until you close Revit**.

> ⚠️ **Every time you open Revit, click Room Restore once** to turn tracking back on. If it's not on, the tool still notices missing rooms the next time it runs. But it only knows each room **as it was the last time tracking saw it**.

---

## 3. What this tool does NOT do

| ❌ It does NOT… | What this means for you |
|---|---|
| Recover rooms from before the register existed | Rooms deleted **before** you created the register can't be restored. |
| Rebuild walls or room boundaries | A room needs an enclosed space. If the walls or room separation lines are gone, the room can't be placed. You can still rebuild it as unplaced ([Section 9](#9-rebuild-blocked-deleted-rooms-unplaced)). |
| Keep the old element ID for deleted rooms | A restored **deleted** room is a **new** room with a new ID. Tags that pointed to the old room don't come back, so re-tag it. *(Unplaced rooms keep their ID.)* |
| Share the register with your team | The register lives on **your** computer. A colleague has their own register only if they created one. |
| Track linked models or families | Only the project you are working in. |
| Place a room on top of another room | If another room now occupies that spot, the tool won't restore the missing room there. |
| Restore a room whose level or phase was deleted | It needs the original level and phase to still exist. |

---

## 4. Before you start

- [ ] The model is a **project** (not a family) and has been **saved** at least once.
- [ ] A **register** exists for this model. If not, create one first ([Section 5](#5-step-1--create-the-register-once-per-model)).
- [ ] You've **clicked Room Restore once** in this Revit session so tracking is on ([Section 6](#6-step-2--turn-tracking-on-every-revit-session)).
- [ ] **Shared (central) model?** Know that the tool will offer to **Reload Latest** before restoring.

---

## 5. Step 1 — Create the register (once per model)

1. Open the model and make sure it's **saved**.
2. Hold **Shift** and click **Room Restore**.
3. A message confirms: **"Register created for '…'. _ rooms recorded. Live tracking is active for this Revit session."**

That's it. The tool now knows every room in the model.

> 💡 **Shift + click again later** opens the folder where the register is saved. That's handy if the author asks you for it. **Don't edit, move or delete** that file. It's the tool's memory.

---

## 6. Step 2 — Turn tracking on (every Revit session)

- **Click Room Restore once** after opening Revit. Either click works.
- If there's nothing to recover, you'll see **"No unplaced or deleted rooms in the register. Live tracking is active."** That's the confirmation. Click OK and keep working.
- Tracking covers **every open model that has a register**, and it stays on until you close Revit.

> ✅ Make it a habit: **Open Revit → open your model → click Room Restore once.**

---

## 7. Step 3 — Restore rooms

1. Click **Room Restore** (normal click).
2. **Shared model?** You'll be asked **"Reload Latest before restoring?"**
   - **Reload Latest** *(recommended)* gets the latest changes from your team, so you don't restore a room someone else already brought back.
   - **Skip** continues without reloading.
3. The tool **checks each missing room** in the background. On big models this can take a moment. Nothing in the model changes during this check.
4. The **Room Register – Restore** window opens with the list of **recoverable rooms**.
5. **Tick** the rooms you want back, or click **Select ready**.
6. Click **Restore selected**.
7. A **Restore report** window opens showing the result for each room ([Section 11](#11-messages-you-may-see)).

📸 *[Screenshot: the Room Register – Restore window]*

### Window controls

| Control | What it does |
|---|---|
| **Search** | Filters the list by status, number, name, level or note. |
| **Status** column | **Unplaced** or **Deleted**. **Hover over it** to see when it happened and who did it (if known). |
| **Number / Name / Level** | The room's details, as last recorded. |
| **Data as of** | When the tool last recorded this room's information. That's the version you'll get back. |
| **Note** column | Whether the room can be restored, and any warnings (see [Section 8](#8-reading-the-note-column)). |
| **Rebuild blocked deleted rooms unplaced** | Lets you bring back deleted rooms that can't be placed, as unplaced rooms (see [Section 9](#9-rebuild-blocked-deleted-rooms-unplaced)). |
| **"_ recoverable \| _ selected"** | How many rooms are in the list, and how many are ticked. |
| **Select ready** | Ticks every room that **can be ticked** and is currently shown (including 🟡 ones). |
| **Clear** | Unticks everything. |
| **Cancel** | Closes the window. Nothing changes. |
| **Restore selected** | Restores the ticked rooms. |

---

## 8. Reading the Note column

The note's colour tells you what will happen:

| Colour | Note | Meaning | Can you tick it? |
|---|---|---|---|
| 🟢 | **Ready** | The room fits back in its spot. | ✅ |
| 🟡 | **Ready – number _ already in use** | It will be restored, but another room now has the same number. Renumber one of them afterwards. | ✅ |
| 🟡 | **Ready – no stored height limits…** / **…give zero height…** | It will be restored, but Revit may ask you to adjust the room's height. Accept Revit's suggestion. | ✅ |
| 🟡 | **Check could not place it – restore will try again (…)** | The trial didn't work, but the tool will try again when you restore. It may or may not succeed. | ✅ |
| 🟡 | **Will rebuild unplaced – …** | Shown when the rebuild toggle is on. The room will come back **unplaced**. | ✅ |
| 🔴 | **Location occupied by room _** | Another room now sits in that spot. | ❌ |
| 🔴 | **Owned by _** | *(Shared models)* Someone else has borrowed this room. | ❌ |
| 🔴 | **Level no longer exists** | The room's level was deleted. | ❌ *(deleted rooms: see [Section 9](#9-rebuild-blocked-deleted-rooms-unplaced))* |
| 🔴 | **No recorded location** | The tool never saw this room placed. | ❌ *(deleted rooms: see [Section 9](#9-rebuild-blocked-deleted-rooms-unplaced))* |
| 🔴 | **Phase no longer exists** | The room's phase was deleted. | ❌ |

> 💡 Hover over any note to read it in full.

---

## 9. Rebuild blocked deleted rooms unplaced

Sometimes a **deleted** room can't go back to its spot. For example, its walls are gone, or another room is there now. You can still get its **information** back:

1. Turn on **Rebuild blocked deleted rooms unplaced** (top right of the window).
2. Blocked deleted rooms become tickable, with the note **"Will rebuild unplaced – …"**.
3. Tick them and click **Restore selected**.
4. Each one comes back as an **unplaced room**, with its number, name and information.
5. **Place it yourself** with Revit's normal **Room** tool (pick the unplaced room from the list in the Options Bar). Or fix the walls and run Room Restore again, where it will show as **Unplaced**.

> ⚠️ The toggle is greyed out when no rooms need it. It doesn't help with **unplaced** rooms, or rooms whose **phase** was deleted.

---

## 10. Undoing a restore

- Press **Ctrl + Z** straight after. The whole restore is **one** step in the Undo list: **"Room Register – Restore rooms"**.
- The rooms go back to being unplaced or deleted, and will show in the tool's list again next time.

---

## 11. Messages you may see

### 🟡 "Save the model first. An unsaved document has no stable identity to register."
**Why:** You tried to create a register for a model that has never been saved.
**What to do:** Save the model, then **Shift + click** again.

### 🟡 "Open a project document first."
**Why:** No model is open, or you're in the Family Editor.
**What to do:** Open a project and try again.

### 🟡 "This document has no room register yet. Shift+Click the button to create one."
**Why:** The register for this model hasn't been created (by you, on this computer).
**What to do:** **Shift + click** to create it. Rooms deleted before now can't be recovered.

### 🟢 "No unplaced or deleted rooms in the register. Live tracking is active."
**Why:** Nothing is missing. Tracking is now on.
**What to do:** Nothing. Keep working.

### 🟢 "Register created for '…'. _ rooms recorded."
**Why:** The register was created successfully.
**What to do:** Nothing.

### 🟡 "Reload Latest failed: …"
**Why:** *(Shared models)* Revit couldn't reload from central, e.g. central unavailable or network issue.
**What to do:** The tool continues anyway. Check your connection to central. If you're unsure, **Cancel** in the next window and try again later.

### 🔴 "Restore failed, nothing was changed" / "Revit did not commit the restore. Nothing was changed."
**Why:** Revit refused the restore as a whole. **Your model is unchanged.**
**What to do:** Try again with fewer rooms. If it repeats, **screenshot** the message and contact the author.

### 🔵 Restore report window
Opens after every restore:

- **"_ of _ rooms restored"** at the top.
- One line per room, with a **clickable ID** that takes you to the room.
- **"Placed back at its last location"** / **"Rebuilt at its last location"** means ✅ done.
- **"Rebuilt unplaced (…) – place it manually"** means ✅ back, but you still need to place it.
- **"could not place: …"**, **"location occupied…"**, **"could not borrow the room…"** means ❌ not restored, with the reason.
- **"skipped, no longer in the project: …"** means those parameters were removed from the project, so they couldn't be filled in.
- **"could not set: …"** means those values couldn't be written back. Check them manually.

---

## 12. Using it in shared (central) models

- **Each person's register is their own**, on their own computer. If you want the safety net, **create your own register** for the model.
- The tool also catches rooms **deleted by others**. You'll see them after you **sync** or **Reload Latest**, with the deleter shown as unknown.
- For rooms deleted by others, the restored information is **as of the last time your register saw them**. Check the **Data as of** column.
- **Always choose Reload Latest** when asked, so two people don't restore the same room.
- **Sync** after restoring, so your team gets the rooms back too.

---

## 13. FAQ

**Do I need to click the button every day?**
Yes, once after opening Revit. That turns tracking on for the session.

**What if I forgot to turn tracking on?**
The next time you click it, the tool still finds rooms that went missing. It just restores them with the information it last recorded, which may be older.

**A room was deleted last month, before I made the register. Can I get it back?**
No. The tool only knows rooms that existed when the register was created, or were added after.

**Will my room tags come back?**
For **unplaced** rooms, their tags usually stay. For **deleted** rooms, no: it's a new room, so tag it again.

**Why is a restored room's number flagged as a duplicate?**
Someone gave that number to another room after the original went missing. Renumber one of them.

**Does it restore room finishes, department, comments and so on?**
Yes. It restores any room information you can normally edit, as long as the parameter still exists in the project.

**Can my colleague use my register?**
No. It's stored on your computer. They need to create their own.

**Where is the register saved?**
Shift + click the button to open the folder. Please leave the file alone.

**I made a copy of the model (Save As / detach). Is it tracked?**
A copy counts as a different model. Create a new register for it with Shift + click.

**Does the check before the window change my model?**
No. It tests each room and then throws the test away.

**Is it safe to try?**
Yes. **Cancel** changes nothing, and a restore can be undone with **Ctrl + Z**.

---

## 14. Troubleshooting

| Symptom | Likely cause | What you can check | Contact author? |
|---|---|---|---|
| Can't find the button | B-Dare95 tab not loaded | Restart Revit. Look in **Modify → Rooms** dropdown. | ✅ If still missing |
| "No room register yet" every time | Register was created on another computer, or for a different copy of the model | **Shift + click** to create one here | ❌ |
| A room I know was deleted isn't in the list | Deleted before the register existed, or already restored | Check when you created the register. Reload Latest. | ✅ If you're sure it should be there |
| Restored room has old information | Tracking was off when it was last edited | Check **Data as of**. Update the values manually. | ❌ |
| Row is red and can't be ticked | Blocked (see [Section 8](#8-reading-the-note-column)) | Fix the cause (free the spot, ask the owner to release it) or use the rebuild toggle | ❌ |
| Rebuild toggle is greyed out | No blocked **deleted** rooms need it | — | ❌ |
| 🟡 "Check could not place it" and restore also fails | Room boundary is not enclosed | Check walls and room separation lines around that area. Use the rebuild toggle for deleted rooms. | ✅ If boundaries look fine |
| "Owned by …" / "could not borrow" | A colleague has borrowed the room | Ask them to sync and relinquish, then try again | ❌ |
| Window takes long to open | Big model, many missing rooms | Wait. The tool is testing each room. | ✅ If Revit freezes |
| "Restore failed, nothing was changed" | Revit refused the change | Try fewer rooms at once | ✅ If it repeats |
| Red pyRevit error window | Unexpected problem | Screenshot it | ✅ |

---

## 15. Contact the author

If your problem isn't solved by the steps above, **please don't try to fix the tool or edit the register file yourself**. Contact:

> 👤 **Mohamed Bedair**
> ✉️ [email] · 💬 [Teams / chat]

**Please include:**

1. A **screenshot** of the window, message or restore report
2. Your **Revit version** (e.g. 2025)
3. The **model name**, and whether it's a shared (central) model
4. The **room number(s)** you tried to restore
5. If asked: the **register file**. Shift + click the button to open its folder.
