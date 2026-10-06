# -*- coding: utf-8 -*-
"""Revit is closing: start a hidden, detached git update.

It finishes after Revit has exited, so the next Revit start already loads the
newest B_Dare95 - new buttons included - with no second restart. Takes a few
milliseconds; never blocks or cancels the close. Only acts on the installer's
copy (%LOCALAPPDATA%\\B_Dare95_dist), never on a development folder.
"""

try:
    import bd_updater                      # lib/bd_updater.py
    bd_updater.launch_detached_update()
except Exception:
    pass
