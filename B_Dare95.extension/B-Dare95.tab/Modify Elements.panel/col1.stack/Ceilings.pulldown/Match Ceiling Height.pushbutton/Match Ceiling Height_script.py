# -*- coding: utf-8 -*-

__doc__ = """__________________________________________________
Description:

Copies the Height Offset From Level of one ceiling onto as many other ceilings as you click.
Only the offset changes; each ceiling keeps its own level, type and sketch.
__________________________________________________
How-to:

-> Click on the button
-> Pick the ceiling that has the right height
-> Click the other ceilings one by one
-> Each one takes the new height straight away
-> Press Esc when you are done
__________________________________________________
Author: Mohamed Bedair"""

from Autodesk.Revit.DB import BuiltInCategory, BuiltInParameter

import bd_core as bd

TOOL = u"Match Ceiling Height"
KEYS = [BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM]

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
only_ceiling = bd.CategoryFilter(BuiltInCategory.OST_Ceilings)

source = bd.pick_element(uidoc, u"Pick the source ceiling", only_ceiling)
if source is None:
    bd.alert(u"No source ceiling was picked.", TOOL, exit=True)

skipped = [0]


def match(target):
    failed = bd.run_transaction(doc, TOOL, lambda: bd.copy_params(source, target, KEYS))
    if failed:
        skipped[0] += 1


bd.pick_repeat(uidoc, u"Pick a ceiling to match (Esc to finish)", match,
               only_ceiling, bar_title=u"Pick ceilings to match the height:")

if skipped[0]:
    bd.alert(u"{0} couldn't take every value (read-only or missing).".format(
        bd.plural(skipped[0], u"ceiling")), TOOL)
