# -*- coding: utf-8 -*-

__doc__ = """__________________________________________________
Description:

Copies the Top Constraint and Top Offset from one shaft to as many other shafts as you click.
__________________________________________________
How-to:

-> Click on the button
-> Pick the source shaft
-> Click each shaft to match; it updates straight away
-> Press Esc when you're done
__________________________________________________
Author: Mohamed Bedair"""

from Autodesk.Revit.DB import BuiltInCategory, BuiltInParameter

import bd_core as bd

TOOL = u"Match Shaft Top"
KEYS = [BuiltInParameter.WALL_HEIGHT_TYPE, BuiltInParameter.WALL_TOP_OFFSET]

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
only_shaft = bd.CategoryFilter(BuiltInCategory.OST_ShaftOpening)

source = bd.pick_element(uidoc, u"Pick the source shaft", only_shaft)
if source is None:
    bd.alert(u"No source shaft was picked.", TOOL, exit=True)

skipped = [0]


def match(target):
    failed = bd.run_transaction(doc, TOOL, lambda: bd.copy_params(source, target, KEYS))
    if failed:
        skipped[0] += 1


bd.pick_repeat(uidoc, u"Pick a shaft to match (Esc to finish)", match,
               only_shaft, bar_title=u"Pick shafts to match the top:")

if skipped[0]:
    bd.alert(u"{0} couldn't take every value (read-only or missing).".format(
        bd.plural(skipped[0], u"shaft")), TOOL)
