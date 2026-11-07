# -*- coding: utf-8 -*-
"""DLC Select By Parameter - selection logic.

No Revit imports here: everything that touches the model goes through a
"provider" object (see RevitProvider in bd_family_cleaner.py). That keeps this file
testable outside Revit. IronPython 2.7 and CPython 3 compatible.

Provider contract
-----------------
    provider.available_scopes()          -> list of scope keys that can be used now
    provider.categories(scope)           -> list of (key, name, [element ids])
    provider.parameter_names(ids)        -> list of parameter labels
    provider.values(ids, param_label)    -> dict {element id: raw value or None}
"""
import re

SCOPE_VIEW = "view"
SCOPE_MODEL = "model"
SCOPE_SELECTION = "selection"
SCOPE_ORDER = [SCOPE_VIEW, SCOPE_MODEL, SCOPE_SELECTION]

EMPTY_LABEL = u"<empty>"
NO_FILTER_LABEL = u"(no filter - all elements of the category)"
TYPE_PREFIX = u"[Type] "

try:
    _TEXT = unicode  # noqa: F821  (IronPython 2.7)
except NameError:
    _TEXT = str


def to_text(value):
    """Any value -> unicode text, never raises."""
    if value is None:
        return u""
    if isinstance(value, _TEXT):
        return value
    try:
        return _TEXT(value)
    except Exception:
        try:
            return str(value).decode("utf-8", "replace")
        except Exception:
            return u"?"


_DIGITS = re.compile(r"(\d+)")


def natural_key(value):
    """Sort key so 'L2' < 'L10' and 'Room 9' < 'Room 10'.

    re.split with a capture group always alternates text / number, so two
    keys hold the same type at the same position and compare safely.
    """
    parts = _DIGITS.split(to_text(value).lower())
    key = []
    for i, part in enumerate(parts):
        if i % 2:
            key.append((int(part), len(part)))
        else:
            key.append((part, 0))
    return key


def normalize_value(value):
    text = to_text(value).strip()
    if not text:
        return EMPTY_LABEL
    return text


def matches_search(text, search):
    """Every word typed in the search box must appear (any order, any case)."""
    words = to_text(search).lower().split()
    if not words:
        return True
    haystack = to_text(text).lower()
    for w in words:
        if w not in haystack:
            return False
    return True


def count_label(text, count):
    return u"%s  (%d)" % (to_text(text), count)


class CategoryEntry(object):
    def __init__(self, key, name, ids):
        self.key = key
        self.name = to_text(name)
        self.ids = list(ids)

    @property
    def label(self):
        return count_label(self.name, len(self.ids))


class ValueEntry(object):
    def __init__(self, value, ids):
        self.value = value
        self.ids = list(ids)

    @property
    def label(self):
        return count_label(self.value, len(self.ids))


def build_categories(raw):
    """[(key, name, ids)] -> sorted CategoryEntry list, empty ones dropped,
    duplicate keys merged."""
    merged = {}
    order = []
    for key, name, ids in raw:
        if key not in merged:
            merged[key] = CategoryEntry(key, name, [])
            order.append(key)
        seen = set(merged[key].ids)
        for i in ids:
            if i not in seen:
                merged[key].ids.append(i)
                seen.add(i)
    entries = [merged[k] for k in order if merged[k].ids]
    entries.sort(key=lambda e: natural_key(e.name))
    return entries


def build_value_index(id_to_value):
    """{id: raw value} -> ValueEntry list, naturally sorted, <empty> last."""
    groups = {}
    for eid, raw in id_to_value.items():
        groups.setdefault(normalize_value(raw), []).append(eid)
    entries = []
    for value, ids in groups.items():
        ids.sort()
        entries.append(ValueEntry(value, ids))
    entries.sort(key=lambda e: (e.value == EMPTY_LABEL, natural_key(e.value)))
    return entries


class SelectController(object):
    """State behind the window. The window only renders what this says."""

    def __init__(self, provider):
        self.provider = provider
        self.scopes = [s for s in SCOPE_ORDER if s in provider.available_scopes()]
        self.scope = None
        self.categories = []
        self.category = None
        self.param_names = []
        self.param = None
        self.values = []
        self.checked = set()
        self.category_search = u""
        self.value_search = u""
        if self.scopes:
            self.set_scope(self.scopes[0])

    # ---- scope -------------------------------------------------------
    def set_scope(self, scope):
        if scope not in self.scopes:
            raise ValueError("Scope not available: %s" % scope)
        previous = self.category.key if self.category else None
        previous_param = self.param
        previous_checked = set(self.checked)
        self.scope = scope
        self.categories = build_categories(self.provider.categories(scope))
        self.category = None
        self._clear_param()
        if previous is None:
            return
        cat = self.find_category(previous)
        if cat is None:
            return
        # Carry the user's choices over; values missing in the new scope drop.
        self.category = cat
        self.param_names = sorted(
            set(self.provider.parameter_names(cat.ids)), key=natural_key)
        if previous_param in self.param_names:
            self.checked = previous_checked
            self.set_param(previous_param, keep_checked=True)

    # ---- category ----------------------------------------------------
    def visible_categories(self):
        return [c for c in self.categories
                if matches_search(c.name, self.category_search)]

    def find_category(self, key):
        for c in self.categories:
            if c.key == key:
                return c
        return None

    def set_category(self, key):
        cat = self.find_category(key)
        previous_param = self.param
        self.category = cat
        self._clear_param(keep_checked=True)
        if cat is None:
            self.checked = set()
            return
        self.param_names = sorted(
            set(self.provider.parameter_names(cat.ids)), key=natural_key)
        if previous_param in self.param_names:
            self.set_param(previous_param, keep_checked=True)
        else:
            self.checked = set()

    # ---- parameter ---------------------------------------------------
    def _clear_param(self, keep_checked=False):
        self.param_names = [] if self.category is None else self.param_names
        self.param = None
        self.values = []
        if not keep_checked:
            self.checked = set()

    def param_choices(self):
        return [NO_FILTER_LABEL] + list(self.param_names)

    def set_param(self, name, keep_checked=False):
        if name is None or name == NO_FILTER_LABEL or self.category is None:
            self.param = None
            self.values = []
            self.checked = set()
            return
        if name not in self.param_names:
            raise ValueError("Unknown parameter: %s" % name)
        self.param = name
        self.values = build_value_index(
            self.provider.values(self.category.ids, name))
        present = set(v.value for v in self.values)
        if keep_checked:
            self.checked = set(v for v in self.checked if v in present)
        else:
            self.checked = set()

    # ---- values ------------------------------------------------------
    def visible_values(self):
        return [v for v in self.values
                if matches_search(v.value, self.value_search)]

    def set_checked(self, value, state):
        if state:
            self.checked.add(value)
        else:
            self.checked.discard(value)

    def check_visible(self, state):
        for v in self.visible_values():
            self.set_checked(v.value, state)

    # ---- result ------------------------------------------------------
    def matched_ids(self):
        if self.category is None:
            return []
        if self.param is None:
            return list(self.category.ids)
        ids = []
        for v in self.values:
            if v.value in self.checked:
                ids.extend(v.ids)
        return sorted(set(ids))

    def can_apply(self):
        return len(self.matched_ids()) > 0

    def status_text(self):
        if not self.scopes:
            return u"Nothing to select from - open a model view first."
        if self.category is None:
            if not self.categories:
                return u"No selectable elements in this scope."
            return u"Pick a category."
        total = len(self.category.ids)
        if self.param is None:
            return u"%d %s will be selected." % (total, self.category.name)
        n = len(self.matched_ids())
        if not self.checked:
            return u"Tick one or more values of '%s'." % self.param
        return u"%d of %d %s will be selected." % (n, total, self.category.name)
