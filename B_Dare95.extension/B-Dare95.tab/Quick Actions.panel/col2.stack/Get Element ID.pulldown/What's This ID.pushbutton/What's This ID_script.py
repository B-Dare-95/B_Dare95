# -*- coding: utf-8 -*-

# Imports
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import forms
from System.Collections.Generic import List

# Revit Variables
doc    = __revit__.ActiveUIDocument.Document
uidoc  = __revit__.ActiveUIDocument

# ── Ask for ID ──────────────────────────────────────────────────────────────
raw = forms.ask_for_string(
    default='',
    prompt='Enter Element ID to inspect:',
    title="What's This ID?")
try:
    if not raw:
        TaskDialog.Show("What's This ID?", "No ID entered.")
    else:
        try:
            unknown_id = int(raw.strip())
        except ValueError:
            TaskDialog.Show("What's This ID?", "Invalid ID — please enter a whole number.")
            unknown_id = None

        if unknown_id is not None:

            # ── Find Element ─────────────────────────────────────────────────────
            elem_id = ElementId(unknown_id)
            element = doc.GetElement(elem_id)          # faster than a full collector loop

            if element is None:
                TaskDialog.Show("What's This ID?", "No element found with ID: {}".format(unknown_id))
            else:

                # ── Gather Info ──────────────────────────────────────────────────
                def safe(fn):
                    """Run fn(), return its string or '—' on any failure."""
                    try:
                        result = fn()
                        return str(result) if result is not None else "—"
                    except:
                        return "—"

                # Category
                category = safe(lambda: element.Category.Name)

                # Family & Type
                el_type = doc.GetElement(element.GetTypeId())
                if el_type:
                    type_name   = safe(lambda: el_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString())
                    family_name = safe(lambda: el_type.get_Parameter(BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM).AsString())
                else:
                    type_name   = "—"
                    family_name = "—"

                # Level
                level_id = safe(lambda: element.LevelId)
                if level_id != "—":
                    level_elem = doc.GetElement(element.LevelId)
                    level_name = safe(lambda: level_elem.Name) if level_elem else "—"
                else:
                    level_name = "—"

                # Phase Created
                phase = safe(lambda: doc.GetElement(
                    element.get_Parameter(BuiltInParameter.PHASE_CREATED).AsElementId()).Name)

                # Workset (workshared models only)
                if doc.IsWorkshared:
                    workset_id = element.WorksetId
                    workset    = safe(lambda: doc.GetWorksetTable().GetWorkset(workset_id).Name)
                else:
                    workset = "Not workshared"

                # Mark & Comments parameters
                mark_param     = element.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
                comment_param  = element.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                mark     = safe(lambda: mark_param.AsString())     if mark_param    else "—"
                comments = safe(lambda: comment_param.AsString())  if comment_param else "—"

                # Bounding Box (in active view)
                bb = element.get_BoundingBox(None)
                if bb:
                    loc = "Min({:.2f}, {:.2f}, {:.2f})  Max({:.2f}, {:.2f}, {:.2f})".format(
                        bb.Min.X, bb.Min.Y, bb.Min.Z,
                        bb.Max.X, bb.Max.Y, bb.Max.Z)
                else:
                    loc = "—"

                # ── Build Report ─────────────────────────────────────────────────
                info = (
                    "ID          : {}\n"
                    "Category    : {}\n"
                    "Family      : {}\n"
                    "Type        : {}\n"
                    "Level       : {}\n"
                    "Phase       : {}\n"
                    "Workset     : {}\n"
                    "Mark        : {}\n"
                    "Comments    : {}\n"
                    "Bounding Box: {}"
                ).format(
                    unknown_id, category, family_name, type_name,
                    level_name, phase, workset, mark, comments, loc)

                # ── Select Element (if selectable) ───────────────────────────────
                selected = False
                try:
                    id_list = List[ElementId]()
                    id_list.Add(elem_id)
                    uidoc.Selection.SetElementIds(id_list)
                    uidoc.ShowElements(id_list)          # zoom to it
                    selected = True
                except:
                    pass

                footer = "\n\n✔ Element selected and view zoomed." if selected else \
                         "\n\n✘ Element could not be selected (view-only or non-graphical)."

                TaskDialog.Show("What's This ID?", info + footer)
except:
    pass