# DLC Tab Designer v1.1.0 (pyRevit button)

Rename your tab and compact its buttons from inside Revit, then refresh
pyRevit - no closing Revit, no paths to edit.

## Install
Copy the two folders from `DLC.extension` in this zip into your
`DLC.extension` (wherever it lives):
```
DLC.extension\lib\dlc_tabdesigner\                    (engine)
DLC.extension\DLC.tab\Tools.panel\Tab Designer.pushbutton\  (button)
```
pyRevit > Reload once. The **Tab Designer** button appears in Tools.

## Use
Click **Tab Designer**. The window shows where it found your extension
(it reads its own location, so copies on other PCs/folders just work).

- **Tab name** - type the new name (e.g. DLC). Tick *Rename extension
  folder too* to rename `SDC.extension` as well.
- **Panels** (left) - pick a panel. For each tool choose **Large**,
  **Small** (stacked 3 per column) or **In "More" menu**; use the arrows to
  reorder (top = left on the ribbon). The preview updates as you go.
- **Title colour** - pick a swatch, **Custom...** (Windows colour picker)
  or **None** for the selected panel. Only the panel's title strip is
  coloured; the list shows a coloured dot per panel and the preview shows the
  strip. **Auto colours** gives every panel its own colour in ribbon order
  (red, blue, yellow, green, purple, orange, ...).
- **Suggest compact layout** - the tool with the most code in each panel
  stays Large, the rest become Small (overflow goes to More). Panels with
  1-2 tools stay as they are. Adjust anything after.
- **Apply and refresh** - backs up the whole extension, writes the layout,
  renames, and refreshes pyRevit. The old tab disappears, the new one shows.
- **Undo last apply** - puts the extension back as before the last Apply
  (each click steps back one more). Backups: `%LOCALAPPDATA%\DLC\TabDesigner`.

## Notes
- The designer itself always stays a Large button (it can't move itself
  while running).
- Two-line titles show on one line when a tool is Small.
- Renaming changes button IDs: Revit keyboard shortcuts on these buttons
  need assigning again.
- *Also update old folder names written inside files* replaces only the
  literal text `SDC.tab` / `SDC.extension` (never `SDC_` parameter names).

## Tests
`python tests/test_engine.py` (124) and `python tests/test_window.py` (56):
mock of your current tab, pyRevit ribbon rules, apply/re-apply/undo to an
exact copy of the original, copied extension in another folder, OneDrive
lock retries, a failure half-way, and every window button.

## Changelog
- **1.1.0** - Title colour per panel (swatches, custom picker, none, auto
  colours). Written as `background: title:` in the panel's bundle.yaml, so
  only the title strip is coloured; colours you set yourself on the panel body
  are kept. A panel's file is only touched when you change its colour.
- **1.0.3** - Fix: Apply on an existing tab saved the layout but the ribbon
  didn't change until Revit restarted (pyRevit only updates panels it already
  has). Each Apply/Undo now gives every panel a fresh internal name - same
  visible title plus invisible characters - so the refresh rebuilds it.
- **1.0.2** - Fix: "Couldn't remove DLC Stack 1.stack ... Access denied" when
  OneDrive held a folder. Leftover empty folders are now skipped (invisible on
  the ribbon) and cleaned up on a later run. Undo swaps folders by renaming,
  so a locked file can never leave a half-deleted extension. A tool switched
  from Small back to Large gets its normal two-line title again.
- **1.0.1** - Fix: second Apply refused with "your own folder 'DLC Stack 1.stack'"
  when the hidden marker file had gone missing; the designer now recognises
  its own stacks by name. Titles written as `title: |-` (multi-line) or as a
  language map now show correctly (no more "|-" labels).
- **1.0.0** - First release.
