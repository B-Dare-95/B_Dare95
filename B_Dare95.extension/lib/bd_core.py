# -*- coding: utf-8 -*-
"""bd_core - shared helpers for every B-Dare95 tool.

One place for the small pieces every button used to carry its own copy of:
ElementId numbers, mm <-> feet, names, plurals, parameters, transactions,
silent Revit warnings, picking, selecting, message boxes and loading
themed WPF windows from ui.xaml files.

Usage in a button script:

    import bd_core as bd

    uidoc = __revit__.ActiveUIDocument
    doc = uidoc.Document
    shaft = bd.pick_element(uidoc, u"Pick the source shaft",
                            bd.CategoryFilter(BuiltInCategory.OST_ShaftOpening))

Rules for this file (it reaches every user on the next auto-update):
- IronPython 2.7 only: no f-strings, no nonlocal, u"..." for \\u escapes.
- Every function takes doc / uidoc as an argument. Nothing here reads
  __revit__ or caches a document, so it is always the active one.
- Change a function's behaviour only if every tool using it still works.
  Add a new function instead of changing an old one when in doubt.

Author: Mohamed Bedair
"""

import os
import re

import System
from System.Collections.Generic import List

from Autodesk.Revit import DB
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI import (TaskDialog, TaskDialogCommonButtons,
                               TaskDialogResult, TaskDialogCommandLinkId)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType


# =============================================================================
# ELEMENT IDS
# =============================================================================
def eid_int(eid):
    """Number of an ElementId on Revit 2024-2027 (.Value, .IntegerValue
    fallback). None gives -1, the same as ElementId.InvalidElementId."""
    if eid is None:
        return -1
    try:
        return int(eid.Value)
    except AttributeError:
        return int(eid.IntegerValue)


def to_eid(number):
    """ElementId from a number. Int64 first (Revit 2024+), int as fallback."""
    try:
        return DB.ElementId(System.Int64(int(number)))
    except Exception:
        return DB.ElementId(int(number))


def is_valid_eid(eid):
    """True for an ElementId that points at something."""
    return eid is not None and eid != DB.ElementId.InvalidElementId


# =============================================================================
# UNITS (Revit works in feet internally)
# =============================================================================
MM_PER_FT = 304.8


def mm_to_ft(mm):
    return float(mm) / MM_PER_FT


def ft_to_mm(ft):
    return float(ft) * MM_PER_FT


def fmt_mm(ft, decimals=0, unit=True):
    """Feet to readable mm text: 4.1010 -> u"1,250 mm".
    decimals > 0 keeps up to that many decimals and drops trailing zeros."""
    mm = ft_to_mm(ft)
    if decimals <= 0:
        text = u"{0:,}".format(int(round(mm)))
    else:
        text = u"{0:,.{1}f}".format(mm, decimals).rstrip(u"0").rstrip(u".")
        if text in (u"-0", u""):
            text = u"0"
    return text + u" mm" if unit else text


def fmt_signed_mm(ft, decimals=0):
    """Like fmt_mm, with a + or minus sign in front (0 has no sign)."""
    text = fmt_mm(abs(ft), decimals)
    if text.startswith(u"0 ") or text == u"0":
        return text
    return (u"+" if ft > 0 else u"\u2212") + text


def parse_mm(text, allow_negative=False, default=None):
    """Number typed in a mm box -> float mm, or default when it isn't valid.
    Accepts "1250", "1,250", "1250 mm" and a decimal comma ("12,5")."""
    if text is None:
        return default
    t = u"{0}".format(text).strip().lower().replace(u"mm", u"").strip()
    t = t.replace(u" ", u"")
    if t.count(u",") == 1 and u"." not in t and len(t.split(u",")[1]) != 3:
        t = t.replace(u",", u".")          # decimal comma: 12,5
    else:
        t = t.replace(u",", u"")           # thousands: 1,250
    try:
        value = float(t)
    except ValueError:
        return default
    if value < 0 and not allow_negative:
        return default
    return value


# =============================================================================
# NAMES AND WORDING
# =============================================================================
def element_name(el, fallback=u"<unnamed>"):
    """Element.Name read safely. ElementType re-declares Name, so el.Name
    raises in IronPython on WallType, FamilySymbol, ViewFamilyType and so on;
    binding the base-class getter avoids that."""
    if el is None:
        return fallback
    try:
        name = DB.Element.Name.GetValue(el)
        if name:
            return name
    except Exception:
        pass
    try:
        name = el.Name
        if name:
            return name
    except Exception:
        pass
    for bip in (DB.BuiltInParameter.SYMBOL_NAME_PARAM,
                DB.BuiltInParameter.ALL_MODEL_TYPE_NAME):
        try:
            p = el.get_Parameter(bip)
            if p is not None and p.AsString():
                return p.AsString()
        except Exception:
            pass
    return fallback


def type_name(el, with_family=False, fallback=u"<no type>"):
    """Name of an element's type. with_family gives u"Family : Type"."""
    if el is None:
        return fallback
    etype = el if isinstance(el, DB.ElementType) else None
    if etype is None:
        try:
            etype = el.Document.GetElement(el.GetTypeId())
        except Exception:
            etype = None
    if etype is None:
        return fallback
    name = element_name(etype, fallback)
    if with_family:
        family = u""
        try:
            family = etype.FamilyName
        except Exception:
            pass
        if family:
            return u"{0} : {1}".format(family, name)
    return name


def category_name(el, fallback=u"<no category>"):
    try:
        return el.Category.Name if el.Category is not None else fallback
    except Exception:
        return fallback


def plural(n, word, word_pl=None):
    """plural(1, u"wall") -> u"1 wall", plural(1250, u"wall") -> u"1,250 walls"."""
    return u"{0:,} {1}".format(n, word if n == 1 else (word_pl or word + u"s"))


# =============================================================================
# PARAMETERS
# =============================================================================
def get_param(el, key):
    """A parameter by BuiltInParameter or by name (string), or None."""
    if el is None or key is None:
        return None
    try:
        if isinstance(key, DB.BuiltInParameter):
            return el.get_Parameter(key)
        return el.LookupParameter(key)
    except Exception:
        return None


def read_raw(param):
    """The stored value as-is (double in feet, int, string or ElementId),
    or None for a missing parameter."""
    if param is None:
        return None
    st = param.StorageType
    if st == DB.StorageType.Double:
        return param.AsDouble()
    if st == DB.StorageType.Integer:
        return param.AsInteger()
    if st == DB.StorageType.String:
        return param.AsString()
    if st == DB.StorageType.ElementId:
        return param.AsElementId()
    return None


def write_raw(param, value):
    """Set a stored value. False when the parameter is missing, read-only
    or Revit refuses the value. Call it inside a transaction."""
    if param is None or param.IsReadOnly:
        return False
    if value is None:
        if param.StorageType != DB.StorageType.String:
            return False
        value = u""
    try:
        return bool(param.Set(value))
    except Exception:
        return False


def copy_params(source, target, keys):
    """Copy parameter values from source to target. keys are
    BuiltInParameters or names. Returns the keys that couldn't be copied.
    Call it inside a transaction."""
    failed = []
    for key in keys:
        src = get_param(source, key)
        if src is None or not write_raw(get_param(target, key), read_raw(src)):
            failed.append(key)
    return failed


# =============================================================================
# TRANSACTIONS AND REVIT WARNINGS
# =============================================================================
class FailureLog(object):
    """What SilentFailures did during one or more transactions."""

    def __init__(self):
        self.handled = {}       # {(message, answer): count}
        self.fatal = []         # messages that forced a rollback

    def summary_lines(self):
        """Readable lines for a report, most frequent first."""
        lines = []
        for (text, action), n in sorted(self.handled.items(),
                                        key=lambda kv: -kv[1]):
            lines.append(u"{0} ({1}) x{2}".format(text, action, n))
        for text in self.fatal:
            lines.append(u"Rolled back: {0}".format(text))
        return lines


class SilentFailures(DB.IFailuresPreprocessor):
    """Answers Revit's warning and error dialogs the way you would by hand:
    warnings get OK, errors get their default answer (e.g. Unjoin Elements).
    An error with no answer rolls the change back and is logged instead of
    shown. Only use it in tools where silent answers were asked for."""

    def __init__(self, log):
        self.log = log

    def PreprocessFailures(self, accessor):
        resolved = False
        for fm in accessor.GetFailureMessages():
            try:
                text = fm.GetDescriptionText()
            except Exception:
                text = u"Revit message"
            severity = fm.GetSeverity()
            if severity == DB.FailureSeverity.Warning:
                accessor.DeleteWarning(fm)
                action = u"OK"
            elif severity == DB.FailureSeverity.Error and fm.HasResolutions():
                try:
                    action = fm.GetDefaultResolutionCaption()
                except Exception:
                    action = u"resolved"
                accessor.ResolveFailure(fm)
                resolved = True
            else:
                self.log.fatal.append(text)
                continue
            key = (text, action)
            self.log.handled[key] = self.log.handled.get(key, 0) + 1
        if self.log.fatal:
            return DB.FailureProcessingResult.ProceedWithRollBack
        if resolved:
            return DB.FailureProcessingResult.ProceedWithCommit
        return DB.FailureProcessingResult.Continue


def make_silent(transaction, log):
    """Attach SilentFailures to a started transaction."""
    opts = transaction.GetFailureHandlingOptions()
    opts.SetFailuresPreprocessor(SilentFailures(log))
    opts.SetClearAfterRollback(True)
    transaction.SetFailureHandlingOptions(opts)


def run_transaction(doc, name, action, failure_log=None):
    """Run action() inside one transaction and return what it returns.
    Commits on success; on an exception rolls back and re-raises it.
    Pass a FailureLog to answer Revit's warnings silently (opt-in)."""
    t = DB.Transaction(doc, name)
    t.Start()
    if failure_log is not None:
        make_silent(t, failure_log)
    try:
        result = action()
        t.Commit()
        return result
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise


def run_group(doc, name, action):
    """Run action() inside a TransactionGroup so all its transactions undo
    as one step. Assimilates on success; rolls back and re-raises on error."""
    g = DB.TransactionGroup(doc, name)
    g.Start()
    try:
        result = action()
        g.Assimilate()
        return result
    except Exception:
        if g.HasStarted() and not g.HasEnded():
            g.RollBack()
        raise


# =============================================================================
# PICKING AND SELECTING
# =============================================================================
class CategoryFilter(ISelectionFilter):
    """Lets only the given categories be picked. Works on category ids, so it
    doesn't depend on the Revit language (unlike Category.Name)."""

    def __init__(self, *categories):
        if len(categories) == 1 and isinstance(categories[0], (list, tuple, set)):
            categories = categories[0]
        self.ids = set(int(c) for c in categories)

    def AllowElement(self, el):
        try:
            return el.Category is not None and eid_int(el.Category.Id) in self.ids
        except Exception:
            return False

    def AllowReference(self, ref, point):
        return False


class ClassFilter(ISelectionFilter):
    """Lets only elements of the given Revit classes be picked, e.g.
    ClassFilter(RevitLinkInstance) or ClassFilter(Stairs, MultistoryStairs)."""

    def __init__(self, *classes):
        if len(classes) == 1 and isinstance(classes[0], (list, tuple)):
            classes = classes[0]
        self.classes = tuple(classes)

    def AllowElement(self, el):
        return isinstance(el, self.classes)

    def AllowReference(self, ref, point):
        return False


def pick_element(uidoc, prompt, selection_filter=None):
    """Pick one element in the active document. None when Esc is pressed."""
    try:
        if selection_filter is not None:
            ref = uidoc.Selection.PickObject(ObjectType.Element,
                                             selection_filter, prompt)
        else:
            ref = uidoc.Selection.PickObject(ObjectType.Element, prompt)
    except OperationCanceledException:
        return None
    return uidoc.Document.GetElement(ref.ElementId)


def pick_repeat(uidoc, prompt, on_pick, selection_filter=None, bar_title=None):
    """Keep picking elements until Esc, calling on_pick(element) each time.
    bar_title shows pyRevit's orange bar at the top while picking.
    Returns how many elements were picked."""
    count = [0]

    def loop():
        while True:
            el = pick_element(uidoc, prompt, selection_filter)
            if el is None:
                return
            on_pick(el)
            count[0] += 1

    if bar_title:
        from pyrevit import forms
        with forms.WarningBar(title=bar_title, handle_esc=True):
            loop()
    else:
        loop()
    return count[0]


def select_ids(uidoc, ids):
    """Replace the current selection with these ElementIds (or elements)."""
    id_list = List[DB.ElementId]()
    for item in ids:
        id_list.Add(item if isinstance(item, DB.ElementId) else item.Id)
    uidoc.Selection.SetElementIds(id_list)


# =============================================================================
# MESSAGES (Revit TaskDialog everywhere)
# =============================================================================
def _dialog(title, message, heading=None, details=None):
    td = TaskDialog(title)
    try:
        td.TitleAutoPrefix = False      # no add-in name in front of the title
    except Exception:
        pass
    if heading:
        td.MainInstruction = heading
        td.MainContent = message
    else:
        td.MainInstruction = message
    if details:
        td.ExpandedContent = details
    return td


def alert(message, title, heading=None, details=None, exit=False):
    """Show a message with an OK button. exit=True stops the tool afterwards.
    details go in the expandable 'Show details' section. Returns True."""
    td = _dialog(title, message, heading, details)
    td.CommonButtons = TaskDialogCommonButtons.Ok
    td.Show()
    if exit:
        from pyrevit import script
        script.exit()
    return True


def confirm(message, title, heading=None, details=None, default_yes=True,
            exit=False):
    """Yes / No question. True for Yes. exit=True stops the tool on No or
    when the dialog is closed."""
    td = _dialog(title, message, heading, details)
    td.CommonButtons = TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No
    td.DefaultButton = TaskDialogResult.Yes if default_yes else TaskDialogResult.No
    answer = td.Show() == TaskDialogResult.Yes
    if exit and not answer:
        from pyrevit import script
        script.exit()
    return answer


_LINKS = [TaskDialogCommandLinkId.CommandLink1, TaskDialogCommandLinkId.CommandLink2,
          TaskDialogCommandLinkId.CommandLink3, TaskDialogCommandLinkId.CommandLink4]
_LINK_RESULTS = [TaskDialogResult.CommandLink1, TaskDialogResult.CommandLink2,
                 TaskDialogResult.CommandLink3, TaskDialogResult.CommandLink4]


def choose(message, title, options, heading=None, details=None):
    """Up to 4 big choice buttons. options are strings, or (text, note)
    pairs. Returns the chosen index, or None when the dialog is closed."""
    td = _dialog(title, message, heading, details)
    for i, opt in enumerate(options[:4]):
        if isinstance(opt, (list, tuple)):
            td.AddCommandLink(_LINKS[i], opt[0], opt[1])
        else:
            td.AddCommandLink(_LINKS[i], opt)
    td.CommonButtons = TaskDialogCommonButtons.Cancel
    result = td.Show()
    for i, res in enumerate(_LINK_RESULTS):
        if result == res:
            return i
    return None


def choose_option(message, title, options, heading=None, details=None,
                  exit=False):
    """Like choose, but returns the chosen option's text (or None).
    exit=True stops the tool when the dialog is closed or cancelled."""
    index = choose(message, title, options, heading, details)
    if index is None:
        if exit:
            from pyrevit import script
            script.exit()
        return None
    opt = options[index]
    return opt[0] if isinstance(opt, (list, tuple)) else opt


# =============================================================================
# REVIT VERSION
# =============================================================================
def revit_version(app_or_doc):
    """Revit version as a number (2024, 2025...). Takes __revit__, a doc or
    an Application."""
    app = getattr(app_or_doc, "Application", app_or_doc)
    try:
        return int(app.VersionNumber)
    except Exception:
        return 0


# =============================================================================
# WINDOWS (ui.xaml + lib/bd_theme.xaml)
# =============================================================================
# Each tool keeps its window layout in a ui.xaml next to its script. The shared
# colours and styles live once in lib/bd_theme.xaml and are merged in here, so
# a ui.xaml only holds layout plus any styles unique to that tool.
_THEME_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bd_theme.xaml")
_RES_OPEN = re.compile(r"<Window\.Resources\s*>")
_RES_CLOSE = u"</Window.Resources>"
_WINDOW_OPEN = re.compile(r"<Window\b[^>]*>")


def _read_text(path):
    """Whole text file as unicode (UTF-8, with or without a BOM)."""
    return System.IO.File.ReadAllText(path)


def _theme_inner():
    """The inside of bd_theme.xaml, without its <ResourceDictionary> root."""
    text = _read_text(_THEME_FILE)
    root = text.find(u"<ResourceDictionary")
    start = text.find(u">", root) + 1
    end = text.rfind(u"</ResourceDictionary>")
    if root < 0 or end < start:
        raise ValueError(u"bd_theme.xaml has no <ResourceDictionary> root")
    return text[start:end]


def _one_line(text):
    """XAML on a single line, so error line numbers still match the tool's file."""
    return u" ".join(line.strip() for line in text.splitlines())


def theme_resources():
    """The inside of bd_theme.xaml on a single line."""
    return _one_line(_theme_inner())


_TOKEN = re.compile(r"<!--.*?-->|<[^<>]+>", re.S)
_FIRST_TAG = re.compile(r"<([\w.:]+)([^>]*)>", re.S)


def _item_key(text):
    """x:Key of a resource, or the TargetType of an implicit Style."""
    m = _FIRST_TAG.match(text)
    if not m:
        return None
    attrs = dict(re.findall(r'([\w.:]+)\s*=\s*"([^"]*)"', m.group(2)))
    if u"x:Key" in attrs:
        return attrs[u"x:Key"]
    target = attrs.get(u"TargetType")
    if m.group(1) == u"Style" and target:
        return target.replace(u"{x:Type", u"").strip(u" {}")
    return None


def _top_items(fragment):
    """[(key, text)] for each top-level element of a XAML fragment."""
    items, depth, start = [], 0, 0
    for m in _TOKEN.finditer(fragment):
        tok = m.group(0)
        if tok.startswith(u"<!--") or tok.startswith(u"<?"):
            continue
        if tok.startswith(u"</"):
            depth -= 1
            if depth == 0:
                text = fragment[start:m.end()]
                items.append((_item_key(text), text))
        elif tok.endswith(u"/>"):
            if depth == 0:
                items.append((_item_key(tok), tok))
        else:
            if depth == 0:
                start = m.start()
            depth += 1
    return items


def _flat_xaml(xaml_text):
    """Theme resources added straight into <Window.Resources>, without a
    wrapping ResourceDictionary, for loaders that fill Window.Resources
    before parsing (pyRevit's forms.WPFWindow). A local resource with the
    same key wins: that theme entry is left out."""
    theme = _top_items(_theme_inner())
    m = _RES_OPEN.search(xaml_text)
    if m:
        end = xaml_text.find(_RES_CLOSE, m.end())
        if end < 0:
            raise ValueError(u"<Window.Resources> is not closed")
        local = set(k for k, _ in _top_items(xaml_text[m.end():end]) if k)
        add = u" ".join(_one_line(t) for k, t in theme if k not in local)
        return xaml_text[:m.end()] + add + xaml_text[m.end():]
    m = _WINDOW_OPEN.search(xaml_text)
    if not m:
        raise ValueError(u"No <Window> root element")
    add = u" ".join(_one_line(t) for k, t in theme)
    return (xaml_text[:m.end()] + u"<Window.Resources>" + add + u"</Window.Resources>"
            + xaml_text[m.end():])


def build_xaml(xaml_text):
    """Window XAML text with the theme merged into its resources.

    Local styles in <Window.Resources> stay and win over the theme, so a tool
    can override a theme style with the same key (or extend it with BasedOn).
    """
    theme = theme_resources()
    m = _RES_OPEN.search(xaml_text)
    if m:
        end = xaml_text.find(_RES_CLOSE, m.end())
        if end < 0:
            raise ValueError(u"<Window.Resources> is not closed")
        local = xaml_text[m.end():end]
        if local.lstrip().startswith(u"<ResourceDictionary"):
            raise ValueError(u"Put local styles straight inside <Window.Resources>, "
                             u"without a <ResourceDictionary>")
        merged = (u"<ResourceDictionary><ResourceDictionary.MergedDictionaries>"
                  u"<ResourceDictionary>" + theme + u"</ResourceDictionary>"
                  u"</ResourceDictionary.MergedDictionaries>")
        return (xaml_text[:m.end()] + merged + local + u"</ResourceDictionary>"
                + xaml_text[end:])
    m = _WINDOW_OPEN.search(xaml_text)
    if not m:
        raise ValueError(u"No <Window> root element")
    return (xaml_text[:m.end()] + u"<Window.Resources>" + theme + u"</Window.Resources>"
            + xaml_text[m.end():])


def _xaml_path(path, name):
    if path.lower().endswith(".xaml"):
        return path
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    return os.path.join(folder, name)


def _raw_xaml(path, name, replace):
    text = _read_text(_xaml_path(path, name))
    for old, new in (replace or {}).items():
        text = text.replace(old, new)
    return text


def window_xaml(path, name="ui.xaml", replace=None):
    """Themed XAML text for pyRevit's forms.WPFWindow:

        forms.WPFWindow.__init__(self, bd.window_xaml(__file__), literal_string=True)

    Same arguments as load_window. pyRevit puts its own brushes into the
    window's resources before loading, so the theme is added next to them
    here instead of replacing them.
    """
    return _flat_xaml(_raw_xaml(path, name, replace))


def load_window(path, name="ui.xaml", replace=None):
    """Load a themed WPF window.

    path: the tool's own __file__ (loads the ui.xaml next to it), its folder,
    or the full path of a .xaml file. name picks another file in that folder
    for tools with more than one window. replace swaps placeholder text in
    the file before loading, for parts only known at run time:

        window = bd.load_window(__file__)
        picker = bd.load_window(__file__, "picker.xaml")
        report = bd.load_window(__file__, "report.xaml", {"%%ROWS%%": rows})

    In the .xaml, the <Window> itself must use DynamicResource for its
    Background / Foreground; everything inside can use StaticResource.
    """
    import clr
    clr.AddReference("PresentationFramework")
    from System.Windows.Markup import XamlReader
    full = _xaml_path(path, name)
    xaml = build_xaml(_raw_xaml(full, name, replace))
    try:
        return XamlReader.Parse(xaml)
    except Exception as ex:
        raise Exception(u"{0}: {1}".format(os.path.basename(full), ex))


def show_modal(window, owner=None):
    """Show a window and wait here until it is closed (the extension's
    replacement for ShowDialog).

    owner: __revit__, a UIApplication or a window handle - keeps the window
    on top of Revit. Leave it out for no owner.
    """
    import clr
    clr.AddReference("PresentationFramework")
    clr.AddReference("WindowsBase")
    from System.Windows.Interop import WindowInteropHelper
    from System.Windows.Threading import Dispatcher, DispatcherFrame

    frame = DispatcherFrame()

    def _closed(sender, args):
        frame.Continue = False

    window.Closed += System.EventHandler(_closed)
    if owner is not None:
        try:
            WindowInteropHelper(window).Owner = getattr(owner, "MainWindowHandle", owner)
        except Exception:
            pass
    window.Show()
    Dispatcher.PushFrame(frame)
