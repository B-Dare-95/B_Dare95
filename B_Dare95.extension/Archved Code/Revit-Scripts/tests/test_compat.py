# -*- coding: utf-8 -*-
"""Static IronPython 2.7 compatibility scan of every shipped .py file.

No Python 2 interpreter is available in the build sandbox, so the shipped
code is parsed with the Python 3 AST and rejected for any construct that
IronPython 2.7 cannot run.
"""
import ast
import os
from harness import check, run_suite, ROOT

EXT = os.path.join(ROOT, 'DLC.extension')


def shipped_files():
    out = []
    for d, _, files in os.walk(EXT):
        out += [os.path.join(d, f) for f in files if f.endswith('.py')]
    return out


PY3_ONLY_KW = {'exist_ok', 'encoding', 'newline', 'flush'}


def scan(path):
    src = open(path, 'rb').read().decode('utf-8')
    tree = ast.parse(src)
    problems = []
    has_print_fn = 'print_function' in src
    has_division = 'from __future__ import division' in src

    def bad(node, why):
        problems.append('%s:%d %s' % (os.path.basename(path),
                                      getattr(node, 'lineno', 0), why))
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            bad(node, 'f-string')
        elif isinstance(node, ast.NamedExpr):
            bad(node, 'walrus operator')
        elif isinstance(node, ast.AnnAssign):
            bad(node, 'variable annotation')
        elif isinstance(node, ast.Nonlocal):
            bad(node, 'nonlocal')
        elif isinstance(node, (ast.AsyncFunctionDef, ast.Await,
                               ast.AsyncFor, ast.AsyncWith)):
            bad(node, 'async')
        elif isinstance(node, ast.YieldFrom):
            bad(node, 'yield from')
        elif isinstance(node, ast.Raise) and node.cause is not None:
            bad(node, 'raise ... from')
        elif isinstance(node, (ast.FunctionDef, ast.Lambda)):
            a = node.args
            if a.kwonlyargs or getattr(a, 'posonlyargs', []):
                bad(node, 'keyword-only / positional-only args')
            if isinstance(node, ast.FunctionDef) and node.returns:
                bad(node, 'return annotation')
            for arg in a.args:
                if arg.annotation is not None:
                    bad(node, 'argument annotation')
        elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            if any(isinstance(e, ast.Starred) for e in node.elts):
                bad(node, 'star-unpacking in display')
        elif isinstance(node, ast.Dict):
            if any(k is None for k in node.keys):
                bad(node, '** in dict display')
        elif isinstance(node, ast.Call):
            stars = [x for x in node.args if isinstance(x, ast.Starred)]
            if len(stars) > 1:
                bad(node, 'multiple * in call')
            for kw in node.keywords:
                if kw.arg in PY3_ONLY_KW:
                    bad(node, 'py3-only keyword %s=' % kw.arg)
                if kw.arg in ('end', 'sep', 'file') and \
                        isinstance(node.func, ast.Name) and \
                        node.func.id == 'print' and not has_print_fn:
                    bad(node, 'print(end=/sep=) without print_function')
            if isinstance(node.func, ast.Name) and node.func.id == 'super' \
                    and not node.args:
                bad(node, 'zero-argument super()')
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == 'math' \
                    and node.attr in ('inf', 'nan', 'isclose', 'tau'):
                bad(node, 'math.%s (py3 only)' % node.attr)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.MatMult):
            bad(node, '@ operator')
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            if not has_division and 'lib' in path:
                bad(node, '/ without "from __future__ import division"')
    for name in ('print(',):
        pass
    return problems


def test_ironpython27_syntax():
    files = shipped_files()
    check(len(files) >= 7, 'found %d files' % len(files))
    allp = []
    for f in files:
        allp += scan(f)
    check(not allp, '\n'.join(allp))


def test_scanner_catches_known_bad():
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, 'lib_bad.py')
    open(p, 'w').write('x = f"{1}"\nif (y := 2): pass\n'
                       'def f(a, *, b): return a/b\nprint(1, end="")\n'
                       'open("x", encoding="utf8")\n')
    probs = scan(p)
    for k in ('f-string', 'walrus', 'keyword-only', 'print(end',
              'encoding='):
        check(any(k in q for q in probs), 'scanner missed %s' % k)


def test_no_hardcoded_user_paths():
    for f in shipped_files():
        src = open(f, 'rb').read().decode('utf-8')
        check('ahmed' not in src.lower() and 'C:\\\\Users' not in src,
              'hard-coded path in %s' % f)


def test_every_file_has_coding_header():
    for f in shipped_files():
        first = open(f, 'rb').read().decode('utf-8').splitlines()[0]
        check('coding' in first, 'missing coding header: %s' % f)


TESTS = [test_ironpython27_syntax, test_scanner_catches_known_bad,
         test_no_hardcoded_user_paths, test_every_file_has_coding_header]


def run():
    return run_suite('IronPython 2.7 compat', TESTS)
