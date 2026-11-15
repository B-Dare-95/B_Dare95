# -*- coding: utf-8 -*-
__doc__ = """__________________________________________________
Description:

Writes the same Top, Bottom, Prefix and/or Suffix text into many dimensions, one click per dimension.
Only checked fields are changed (an empty checked field clears that text), and all changes are a single undo.
__________________________________________________
How-to:

-> Open the view with the dimensions
-> Click on the button
-> Type your text and uncheck the fields to leave alone
-> Choose All segments or Picked segment only
-> Click Start Picking, then click dimensions one by one
-> Press Esc to finish
__________________________________________________
Author: Mohamed Bedair"""

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System.Windows import RoutedEventHandler
from System.Windows.Input import Key, KeyEventHandler

from Autodesk.Revit.DB import Transaction, SubTransaction, Dimension, SpotDimension
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException
import bd_core as bd

uiapp = __revit__
uidoc = uiapp.ActiveUIDocument
doc = uidoc.Document


# =============================================================================
# Helpers
# =============================================================================
id_val = bd.eid_int


def flatten(pt, view_dir):
    """Project a point onto the view plane (remove the view-depth component)."""
    return pt.Subtract(view_dir.Multiply(pt.DotProduct(view_dir)))


def nearest_segment(segments, pick_pt, view_dir):
    """Segment whose text origin is closest to the pick point, measured in the view plane."""
    p = flatten(pick_pt, view_dir)
    best = [None, None]  # [segment, distance]
    for seg in segments:
        origin = seg.Origin
        if origin is None:
            continue
        d = flatten(origin, view_dir).DistanceTo(p)
        if best[1] is None or d < best[1]:
            best[0], best[1] = seg, d
    return best[0]


class DimensionFilter(ISelectionFilter):
    """Linear / angular / radial / diameter / arc-length dims only (no spot dims)."""
    def AllowElement(self, elem):
        return isinstance(elem, Dimension) and not isinstance(elem, SpotDimension)

    def AllowReference(self, reference, position):
        return False


# =============================================================================
# UI  (layout: ui.xaml, colours and styles: lib/bd_theme.xaml)
# =============================================================================
def show_ui():
    """Returns (values, mode) or None if cancelled. values = [(api_property, text), ...]"""
    window = bd.load_window(__file__)

    f = window.FindName
    fields = [
        ("Above",  f("CbAbove"),  f("TbAbove")),
        ("Below",  f("CbBelow"),  f("TbBelow")),
        ("Prefix", f("CbPrefix"), f("TbPrefix")),
        ("Suffix", f("CbSuffix"), f("TbSuffix")),
    ]
    tg_all, tg_picked = f("TgAll"), f("TgPicked")

    result = {"go": False, "values": [], "mode": "all"}

    def on_mode(sender, args):
        is_all = sender is tg_all
        tg_all.IsChecked = is_all
        tg_picked.IsChecked = not is_all

    def on_start(sender, args):
        values = [(prop, tb.Text or "") for prop, cb, tb in fields if cb.IsChecked == True]
        if not values:
            TaskDialog.Show("Dimension Text Writer", "Check at least one property to write.")
            return
        result["go"] = True
        result["values"] = values
        result["mode"] = "all" if tg_all.IsChecked == True else "picked"
        window.Close()

    def on_cancel(sender, args):
        window.Close()

    def on_key(sender, args):
        if args.Key == Key.Escape:
            args.Handled = True
            window.Close()
        elif args.Key == Key.Enter:
            args.Handled = True
            on_start(sender, args)

    tg_all.Click += RoutedEventHandler(on_mode)
    tg_picked.Click += RoutedEventHandler(on_mode)
    f("BtnStart").Click += RoutedEventHandler(on_start)
    f("BtnCancel").Click += RoutedEventHandler(on_cancel)
    window.PreviewKeyDown += KeyEventHandler(on_key)

    bd.show_modal(window, uiapp)

    if not result["go"]:
        return None
    return result["values"], result["mode"]


# =============================================================================
# Core
# =============================================================================
def write_text(dim, values, mode, pick_pt, view_dir):
    """Write the values into the dimension (or its segments). Raises on failure."""
    if dim.NumberOfSegments > 0:
        segments = list(dim.Segments)
        if mode == "picked":
            if pick_pt is None:
                raise Exception("Pick point unavailable - could not resolve segment")
            seg = nearest_segment(segments, pick_pt, view_dir)
            if seg is None:
                raise Exception("Could not resolve picked segment")
            targets = [seg]
        else:
            targets = segments
    else:
        targets = [dim]

    for target in targets:
        for prop, text in values:
            setattr(target, prop, text)


def run():
    ui = show_ui()
    if ui is None:
        return
    values, mode = ui

    view_dir = doc.ActiveView.ViewDirection
    sel_filter = DimensionFilter()
    done = [0]
    failures = []

    t = Transaction(doc, "Write Dimension Text")
    t.Start()
    try:
        while True:
            prompt = "Pick a dimension to write text  ({} done)  |  ESC to finish".format(done[0])
            try:
                ref = uidoc.Selection.PickObject(ObjectType.Element, sel_filter, prompt)
            except OperationCanceledException:
                break

            dim = doc.GetElement(ref.ElementId)
            st = SubTransaction(doc)
            st.Start()
            try:
                write_text(dim, values, mode, ref.GlobalPoint, view_dir)
                st.Commit()
                done[0] += 1
            except Exception as ex:
                st.RollBack()
                failures.append("Id {}: {}".format(id_val(dim.Id), ex))

            # show the change immediately while still inside the open transaction
            doc.Regenerate()
            uidoc.RefreshActiveView()

        t.Commit()
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        TaskDialog.Show("Dimension Text Writer", "Rolled back - unexpected error:\n\n{}".format(ex))
        return

    if failures:
        TaskDialog.Show(
            "Dimension Text Writer",
            "{} dimension(s) updated, {} failed:\n\n{}".format(done[0], len(failures), "\n".join(failures))
        )


run()