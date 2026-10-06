# Room Register — User Guide

> 📍 **Where to find it:** Revit ribbon → **B-Dare95** tab → **Modify** panel → **Rooms** dropdown → **Room Register**
> 🧩 **Works with:** Revit 2024 and newer · project files only (not families)
> 👤 **Tool author:** Mohamed Bedair — [contact email / Teams]
> 🗓️ **Last updated:** [Date]

---

## 1. What this tool does

**Room Register** brings back rooms that were **deleted** or became **unplaced**, with their number, name and other information, in the place they used to be.

It works like a **safety net that is always on**:

1. When you open a saved project that has rooms, the tool **automatically** starts a record of every room: where it is, its level, its phase and its information. This record is called the **Room Register**.
2. While Revit is open, it **updates that record by itself** as rooms are added, changed or deleted. You don't need to click anything.
3. When a room goes missing, click **Room Register**, **tick the rooms you want back**, and click **Restore selected**.

| Room situation | What Room Register does |
|---|---|
| **Unplaced** (still in the model, but not in any space, e.g. its walls were moved or deleted) | Places **the same room** back at its last location |
| **Deleted** (completely removed from the model) | Creates a **new room** at its last location and copies back its number, name and other information |

> 💡 Think of it as the **Recycle Bin for rooms**. It fills itself up in the background. You only open it when you need something back.

📸 *[Screenshot: the Room Register button in the Rooms dropdown]*

---

## 2. How it works in the background

| What | When it happens | Do you need to do anything? |
|---|---|---|
| **Tracking starts** | Every time Revit starts | ❌ No |
| **Register is created** | The first time you open a **saved** project that **has rooms**. Also when you add the first rooms to a saved project. | ❌ No |
| **Register is updated** | Whenever rooms are added, changed or deleted, and when you **open**, **sync** or **Reload Latest** | ❌ No |
| **Final check** | Every time you click **Room Register**, it double-checks the model before showing the list | ❌ No |

> 💡 The register is saved **on your own computer**, not inside the Revit model. **Shift + click** the button to see where it is.

---

## 3. What this tool does NOT do

| ❌ It does NOT… | What this means for you |
|---|---|
| Recover rooms from before the register existed | Rooms deleted before the register was created for that model can't be restored. |
| Track unsaved projects | A brand-new project gets a register only after it has been **saved** and has rooms. |
| Rebuild walls or room boundaries | A room needs an enclosed space. If the walls or room separation lines are gone, the room can't be placed. You can still rebuild it as unplaced ([Section 8](#8-rebuild-blocked-deleted-rooms-unplaced)). |
| Keep the old element ID for deleted rooms | A restored **deleted** room is a **new** room with a new ID. Tags that pointed to the old room don't come back, so re-tag it. *(Unplaced rooms keep their ID.)* |
| Share the register with your team | Each person's computer keeps its own register. |
| Track linked models or families | Only projects you have open yourself. |
| Place a room on top of another room | If another room now occupies that spot, the tool won't restore the missing room there. |
| Restore a room whose level or phase was deleted | It needs the original level and phase to still exist. |

---

## 4. Before you start

- [ ] The model is a **project** (not a family) and has been **saved**.
- [ ] The model has been opened on **this computer** since the register started. Usually that's automatic.
- [ ] **Shared (central) model?** The tool will offer to **Reload Latest** before restoring.

That's all. There's no setup step and nothing to switch on.

---

## 5. How to restore rooms

1. Click **Room Register** (normal click).
2. **Shared model?** You'll be asked **"Reload Latest before restoring?"**
   - **Reload Latest** *(recommended)* gets the latest changes from your team, so you don't restore a room someone else already brought back.
   - **Skip** continues without reloading.
3. The tool **checks each missing room** in the background. On big models this can take a moment. Nothing in the model changes during this check.
4. The **Room Register – Restore** window opens with the list of missing rooms.
5. **Tick** the rooms you want back, or click **Select ready**.
6. Click **Restore selected**.
7. A **Restore report** window opens showing the result for each room ([Section 11](#11-messages-you-may-see)).

📸 *[Screenshot: the Room Register – Restore window]*

### Window controls

| Control | What it does |
|---|---|
| **Search** | Filters the list by status, number, name, level or note. |
| **Column headers** | **Click** a header to sort by it. Click again to reverse. An arrow ▲ ▼ shows the active sort. Numbers sort naturally, so *Level 2* comes before *Level 10*. |
| **Status** | **Unplaced** or **Deleted**. **Hover over it** to see when it happened and who did it (if known). |
| **Number / Name / Level** | The room's details, as last recorded. |
| **Data as of** | When the tool last recorded this room's information. That's the version you'll get back. |
| **Note** | Whether the room can be restored, and any warnings (see [Section 7](#7-reading-the-note-column)). |
| **Rebuild blocked deleted rooms unplaced** | Brings back deleted rooms that can't be placed, as unplaced rooms (see [Section 8](#8-rebuild-blocked-deleted-rooms-unplaced)). |
| **"_ rooms \| _ selected (_ restorable, _ removable)"** | How many rooms are listed, how many you ticked, and how many of the ticked ones can be **restored** or **removed**. |
| 🔴 **Remove from register** | **Permanently** erases the ticked **deleted** rooms from the register (see [Section 9](#9-removing-rooms-from-the-register)). |
| **Select ready** | Ticks every room that **can be restored** and is currently shown (including 🟡 ones). |
| **Clear** | Unticks everything. |
| **Cancel** | Closes the window. Nothing changes. |
| **Restore selected** | Restores the ticked rooms that can be restored. It's greyed out until at least one is ticked. |

---

## 6. Quick reference: who does what

| You want to… | Do this |
|---|---|
| Get a missing room back | **Click** Room Register → tick → **Restore selected** |
| Bring back a deleted room whose spot is blocked | Turn on **Rebuild blocked deleted rooms unplaced** → tick → **Restore selected** |
| Clean old deleted rooms out of the list | Tick them → **Remove from register** → **Yes** |
| See where the register is saved | **Shift + click** Room Register |

---

## 7. Reading the Note column

The note's colour tells you what will happen:

| Colour | Note | Meaning | Can it be restored? |
|---|---|---|---|
| 🟢 | **Ready** | The room fits back in its spot. | ✅ |
| 🟡 | **Ready – number _ already in use** | It will be restored, but another room now has the same number. Renumber one of them afterwards. | ✅ |
| 🟡 | **Ready – … Revit may ask to adjust limits** / **…will ask to adjust limits** | It will be restored, but the room's stored height information is missing or gives zero height, so Revit may ask you to fix the height. Accept Revit's suggestion, or set the Upper Limit and offsets yourself. | ✅ |
| 🟡 | **Check could not place it – restore will try again (…)** | The trial didn't work, but the tool will try again when you restore. It may or may not succeed. | ✅ |
| 🟡 | **Will rebuild unplaced – …** | Shown when the rebuild toggle is on. The room will come back **unplaced**. | ✅ |
| 🔴 | **Location occupied by room _** | Another room now sits in that spot. | ❌ |
| 🔴 | **Owned by _** | *(Shared models)* Someone else has borrowed this room. | ❌ |
| 🔴 | **Level no longer exists** | The room's level was deleted. | ❌ *(deleted rooms: see [Section 8](#8-rebuild-blocked-deleted-rooms-unplaced))* |
| 🔴 | **No recorded location** | The tool never saw this room placed. | ❌ *(deleted rooms: see [Section 8](#8-rebuild-blocked-deleted-rooms-unplaced))* |
| 🔴 | **Phase no longer exists** | The room's phase was deleted. | ❌ |

> 💡 **Red deleted rooms can still be ticked**, so you can remove them from the register. Ticking them doesn't restore them. **Restore selected** skips anything that can't be restored. The counter at the bottom shows how many of your ticks are **restorable**.
> Hover over any note to read it in full.

---

## 8. Rebuild blocked deleted rooms unplaced

Sometimes a **deleted** room can't go back to its spot. For example, its walls are gone, or another room is there now. You can still get its **information** back:

1. Turn on **Rebuild blocked deleted rooms unplaced** (top right of the window).
2. Blocked deleted rooms change to **"Will rebuild unplaced – …"** and count as restorable.
3. Tick them and click **Restore selected**.
4. Each one comes back as an **unplaced room**, with its number, name and information.
5. **Place it yourself** with Revit's normal **Room** tool (pick the unplaced room from the list in the Options Bar). Or fix the walls and run Room Register again, where it will show as **Unplaced**.

> ⚠️ The toggle is greyed out when no rooms need it. It doesn't help with **unplaced** rooms, or rooms whose **phase** was deleted.

---

## 9. Removing rooms from the register

Over time the list can fill up with deleted rooms you **never** want back, e.g. rooms removed on purpose during a redesign. You can clear them out:

1. Tick the **deleted** rooms you want to get rid of.
2. Click the red **Remove from register** button.
3. A confirmation lists the rooms. Read it carefully, then click **Yes**. *(**No** is the default, so pressing Enter cancels.)*
4. The rooms disappear from the list.

> ⚠️ **This can't be undone.** The stored information is erased, and those rooms **can never be restored** by this tool again.
> Only **deleted** rooms can be removed. Ticked **unplaced** rooms are not affected, because they still exist in the model.
> Removing affects only **your** register. It doesn't touch the Revit model or anyone else's register.

---

## 10. Undoing a restore

- Press **Ctrl + Z** straight after. The whole restore is **one** step in the Undo list: **"Room Register – Restore rooms"**.
- The rooms go back to being unplaced or deleted, and will show in the tool's list again next time.
- *(Removing rooms from the register can't be undone. See [Section 9](#9-removing-rooms-from-the-register).)*

---

## 11. Messages you may see

### 🟡 "Open a project document first."
**Why:** No model is open, or you're in the Family Editor.
**What to do:** Open a project and try again.

### 🟡 "This document has no room register yet. Shift+Click the button to create one."
**Why:** The model has no register on this computer yet. Usually that's because it has **no rooms** yet, or hasn't been **saved**.
**What to do:** Nothing, if the model has no rooms. The register is created automatically once rooms are added. To start one right now, **Shift + click**.

### 🟡 "Save the model first. An unsaved document has no stable identity to register."
**Why:** You **Shift + clicked** in a model that has never been saved.
**What to do:** Save it, then try again.

### 🟢 "Register created for '…'. _ rooms recorded. Live tracking runs automatically in every Revit session."
**Why:** You Shift + clicked and a new register was created.
**What to do:** Nothing.

### 🟢 "No unplaced or deleted rooms in the register. Live tracking is active."
**Why:** Nothing is missing.
**What to do:** Nothing. Keep working.

### 🟡 "Reload Latest failed: …"
**Why:** *(Shared models)* Revit couldn't reload from central, e.g. central unavailable or network issue.
**What to do:** The tool continues anyway. If you're unsure, **Cancel** in the next window and try again later.

### 🟡 "Permanently remove _ deleted room(s) from the register? …"
**Why:** You clicked **Remove from register**.
**What to do:** Check the list. **Yes** erases them for good. **No** keeps them.

### 🔴 "Could not update the register, nothing was removed: …"
**Why:** The register file couldn't be saved, e.g. it's locked or the disk is full.
**What to do:** Try again. If it repeats, **screenshot** it and contact the author.

### 🔴 "Restore failed, nothing was changed" / "Revit did not commit the restore. Nothing was changed."
**Why:** Revit refused the restore as a whole. **Your model is unchanged.**
**What to do:** Try again with fewer rooms. If it repeats, **screenshot** it and contact the author.

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

- **Each person's register is their own**, on their own computer. It starts automatically the first time they open the model.
- The tool also catches rooms **deleted by others**. You'll see them after you **sync**, **Reload Latest** or reopen the model, with the deleter shown as unknown.
- For rooms deleted by others, the restored information is **as of the last time your register saw them**. Check the **Data as of** column.
- **Always choose Reload Latest** when asked, so two people don't restore the same room.
- **Sync** after restoring, so your team gets the rooms back too.

---

## 13. FAQ

**Do I need to turn anything on?**
No. Tracking starts with Revit, and registers are created automatically for saved projects with rooms.

**How do I know it's working?**
Click **Room Register**. If you see "Live tracking is active" or the list of rooms, it's working. Shift + click shows the register file.

**A room was deleted before the register existed. Can I get it back?**
No. The tool only knows rooms that existed when the register was created, or were added after.

**Will my room tags come back?**
For **unplaced** rooms, their tags usually stay. For **deleted** rooms, no: it's a new room, so tag it again.

**Why is a restored room's number flagged as a duplicate?**
Someone gave that number to another room after the original went missing. Renumber one of them.

**Does it restore room finishes, department, comments and so on?**
Yes. It restores any room information you can normally edit, as long as the parameter still exists in the project.

**The list is full of old deleted rooms. Can I clean it?**
Yes. Tick them and click **Remove from register** ([Section 9](#9-removing-rooms-from-the-register)). This is permanent.

**I ticked a red room and clicked Restore, but it wasn't in the report.**
Red rooms can't be restored. **Restore selected** skips them. They're only tickable so you can remove them.

**Can my colleague use my register?**
No. It's stored on your computer. Theirs is created automatically on their computer.

**I made a copy of the model (Save As / detach). Is it tracked?**
A copy counts as a different model. It gets its own register automatically once it's saved and opened with rooms in it.

**Does the check before the window change my model?**
No. It tests each room and then throws the test away.

**Is it safe to try?**
Yes. **Cancel** changes nothing, and a restore can be undone with **Ctrl + Z**. Only **Remove from register** is permanent, and it asks first.

---

## 14. Troubleshooting

| Symptom | Likely cause | What you can check | Contact author? |
|---|---|---|---|
| Can't find the button | B-Dare95 tab not loaded | Restart Revit. Look in **Modify → Rooms** dropdown for **Room Register**. | ✅ If still missing |
| "No room register yet" in a model with rooms | Model not saved, or not reopened since the update | Save the model, close and reopen it. Or **Shift + click**. | ✅ If it keeps happening |
| A room I know was deleted isn't in the list | Deleted before the register existed, already restored, or removed from the register | Reload Latest. Ask whether someone removed it. | ✅ If you're sure it should be there |
| Restored room has old information | It was last changed by someone else, or before your register saw it | Check **Data as of**. Update the values manually. | ❌ |
| **Restore selected** is greyed out | Nothing restorable is ticked | Tick a 🟢 or 🟡 room. Check the "restorable" count. | ❌ |
| **Remove from register** is greyed out | No **deleted** room is ticked | Tick a room with status **Deleted** | ❌ |
| Rebuild toggle is greyed out | No blocked **deleted** rooms need it | — | ❌ |
| 🟡 "Check could not place it" and restore also fails | Room boundary is not enclosed | Check walls and room separation lines around that area. Use the rebuild toggle for deleted rooms. | ✅ If boundaries look fine |
| "Owned by …" / "could not borrow" | A colleague has borrowed the room | Ask them to sync and relinquish, then try again | ❌ |
| Restored room asks to adjust height | Stored height limits missing or give zero height | Accept Revit's fix, or set **Upper Limit / Limit Offset** manually | ❌ |
| Window takes long to open | Big model, many missing rooms | Wait. The tool is testing each room. | ✅ If Revit freezes |
| Red pyRevit error window | Unexpected problem | Screenshot it | ✅ |

---

## 15. Contact the author

If your problem isn't solved by the steps above, **please don't try to fix the tool or edit the register files yourself**. Contact:

> 👤 **Mohamed Bedair**
> ✉️ [email] · 💬 [Teams / chat]

**Please include:**

1. A **screenshot** of the window, message or restore report
2. Your **Revit version** (e.g. 2025)
3. The **model name**, and whether it's a shared (central) model
4. The **room number(s)** involved
5. If asked: **Shift + click** the button to open the register folder, then send the **register file** for that model and the **tracker.log** file from the same folder.
