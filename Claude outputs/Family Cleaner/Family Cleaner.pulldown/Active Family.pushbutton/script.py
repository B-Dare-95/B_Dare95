# -*- coding: utf-8 -*-

TOOL_NAME = "Family Cleaner - Active Family"
__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Cleans the family you have open and the families nested inside it, down to four levels. Unused content (nested families, types, materials, patterns, styles) is purged, and family parameters that nothing uses are removed.

The whole clean is a single undo, and Preview only shows what would go without changing anything.
__________________________________________________
How-to:

-> Open the family (.rfa) you want to clean
-> Click on the button
-> Choose how many nested levels to clean and what to clean
-> Tick Preview only for a dry run, or leave it off to clean
-> Click Clean and read the report
-> Save the family if you're happy with it, or Undo
__________________________________________________
Author: Mohamed Bedair"""

__persistentengine__ = True

from datetime import datetime

from pyrevit import forms, script
from System.Windows import RoutedEventHandler
from Autodesk.Revit.DB import TransactionGroup

import bd_family_cleaner as fc
import bd_family_cleaner_report as fcr

uidoc = __revit__.ActiveUIDocument  # noqa: F821
if uidoc is None or not uidoc.Document.IsFamilyDocument:
    forms.alert("Open a family (.rfa) first. This button cleans the family you are editing.",
                title=TOOL_NAME, exitscript=True)
doc = uidoc.Document

family_name = doc.Title[:-4] if doc.Title.lower().endswith(".rfa") else doc.Title
nested_count = len(fc.editable_nested_ids(doc))
param_count = sum(1 for p in doc.FamilyManager.GetParameters() if fc.eid_int(p.Id) > 0)

# ─────────────────────────────────────────────────────────────
#  Window
# ─────────────────────────────────────────────────────────────

HEADER = u"""
<TextBlock Text="Family Cleaner" Style="{StaticResource H1}" Margin="0,0,0,4"/>
<TextBlock x:Name="Subtitle" Style="{StaticResource Hint}" Margin="0,0,0,14"/>
"""

window = fc.build_window(u"Family Cleaner - Active Family", 560,
                         HEADER + fc.OPTIONS_XAML + fc.PREVIEW_XAML + fc.BUTTONS_XAML,
                         __revit__.MainWindowHandle)  # noqa: F821
window.FindName("Subtitle").Text = u"{}  ·  {}  ·  {} nested families  ·  {} custom parameters".format(
    family_name, fc.family_category_name(doc) or u"No category", nested_count, param_count)
fc.wire_options(window)

choice = {"options": None}


def on_run(sender, args):
    choice["options"] = fc.read_options(window)
    window.Close()


def on_cancel(sender, args):
    window.Close()


window.FindName("BtnRun").Click += RoutedEventHandler(on_run)
window.FindName("BtnCancel").Click += RoutedEventHandler(on_cancel)
fc.show_blocking(window)

options = choice["options"]
if options is None:
    script.exit()

# ─────────────────────────────────────────────────────────────
#  Clean (one TransactionGroup = one undo; Preview rolls it back)
# ─────────────────────────────────────────────────────────────

started = datetime.now()
rows = []
tg = TransactionGroup(doc, "Family Cleaner")
tg.Start()
try:
    with forms.ProgressBar(title="Cleaning nested families ({value} of {max_value})",
                           cancellable=True) as pb:
        cleaner = fc.FamilyCleaner(options, rows, progress=pb)
        root, changed = cleaner.clean(doc, family_name)
    if options.preview:
        tg.RollBack()
    else:
        tg.Assimilate()
except Exception:
    if tg.HasStarted() and not tg.HasEnded():
        tg.RollBack()
    raise

notes = []
if not options.preview and changed:
    notes.append(u"Nothing is saved yet: save the family to keep the result, or Undo "
                 u"(\u201CFamily Cleaner\u201D is one step).")
fcr.show_report(__revit__, u"Family Cleaner: {}".format(family_name),  # noqa: F821
                u"Active family  \u00b7  {} nested levels".format(options.depth),
                rows, options.preview, started, notes, mode="family")
