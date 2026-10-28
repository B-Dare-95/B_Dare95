# Import CAD blocked

> ⚡ **TL;DR**
> **Import CAD** is switched off by the B-Dare95 extension. When you click it, nothing is imported. A small window asks you to **link** the CAD file instead.
>
> 1. Click **Link CAD** in that window (or press **Enter**).
> 2. Revit's own **Link CAD** window opens. Pick your file and settings as usual.
> 3. Not ready yet? **Close**, **✕** or **Esc** closes the window. Nothing is imported.
>
> ⚠️ There's no button or setting to import anyway. If you really need to import a CAD file, contact Mohamed.

*📍 Runs automatically on Insert → Import CAD · 🧩 Revit 2024+ · 👤 Mohamed Bedair · 🗓️ 28 Oct 2026*

---

# 📖 Full guide

*Everything below is reference. You only need it if the TL;DR didn't answer your question.*

## 1. What happens when you click Import CAD

This isn't a button you click. It runs **by itself** whenever anyone starts Revit's **Insert → Import CAD**, in any model, while the B-Dare95 extension is loaded.

1. Revit's **Import CAD** is **stopped before it opens**. No file dialog, nothing imported.
2. A small dark window appears in the middle of Revit instead.
3. You choose to go to **Link CAD**, or just close the window.

> ℹ️ The import is stopped **first**, before the window even shows. So even if the window fails to appear, Import CAD still doesn't run.

---

## 2. Why link instead of import

The extension's rule is simple: **CAD files are linked, not imported**.

A **linked** CAD stays a reference to the original file, so it can be reloaded, unloaded or removed in one place (**Manage Links**). An **imported** CAD is copied into the model itself.

---

## 3. The window

| Part | What it says / does |
|---|---|
| Top bar | **"B_Dare95 · Command blocked"**. Drag it to move the window. |
| Message | **"Import CAD is denied, please use Link CAD Instead"** |
| **Link CAD** *(yellow button)* | Closes the window and opens Revit's **Link CAD** window. **Enter** does the same. |
| **Close** | Closes the window. Nothing else happens. |
| **✕** *(top right)* | Same as **Close**. |
| **Esc** | Same as **Close**. |

---

## 4. Bringing your CAD in with Link CAD

1. In the window, click **Link CAD** (or press **Enter**).
2. Revit's normal **Link CAD** window opens, the same one you get from **Insert → Link CAD**.
3. Choose your file and settings, and click **Open**.

If you closed the window, you can always go to **Insert → Link CAD** yourself.

---

## 5. Can I import anyway?

**No.** The window has no option to carry on with the import, and there's no setting you can change.

If you really need to import a CAD file, **contact Mohamed** (see [Section 8](#8-contact-the-author)).

---

## 6. Messages you may see

| Message | Why | What to do |
|---|---|---|
| 🟡 **"B_Dare95 · Command blocked"** + **"Import CAD is denied, please use Link CAD Instead"** | You started **Import CAD**. | Click **Link CAD**, or **Close**. |
| 🟡 A plain Revit message box titled **"B_Dare95"** with **"Import CAD is denied, please use Link CAD Instead"** | The styled window couldn't be shown, so a simple one appears instead. It has **no Link CAD button**. | Close it, then go to **Insert → Link CAD**. |
| 🟡 You clicked **Link CAD** but nothing opened | Revit couldn't start Link CAD at that moment. | Go to **Insert → Link CAD** yourself. |

---

## 7. FAQ

**Does it block every way of starting Import CAD?**
It blocks Revit's **Import CAD** command, whether you start it from the **Insert** tab or another way that runs the same command.

**Does it affect Link CAD?**
No. **Link CAD** works normally. The window just gives you a shortcut to it.

**Is my attempt recorded?**
Each blocked attempt is written to a small log file in your Windows user folder (**pyrevit_hooks.log**), with the date, time and your Revit user name. Nothing is shown on screen apart from the window.

**The window has no logo.**
That's fine. The logo is optional and is hidden if its image file can't be found.

---

## 8. Contact the author

If your problem isn't solved by the steps above, **please don't try to change the extension yourself**. Contact:

> 👤 **Mohamed Bedair**

**Please include:** why you need to **import** rather than link, the **CAD file** involved, your **Revit version**, and the **model name**.
