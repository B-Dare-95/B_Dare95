# -*- coding: utf-8 -*-
"""Tiny test harness - counts suites, tests and assertions."""
from __future__ import print_function
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIB = os.path.join(ROOT, 'DLC.extension', 'lib')
if LIB not in sys.path:
    sys.path.insert(0, LIB)

STATS = {'assertions': 0, 'tests': 0, 'failed_tests': []}


class Failure(AssertionError):
    pass


def check(cond, msg='check failed'):
    STATS['assertions'] += 1
    if not cond:
        raise Failure(msg)


def close(a, b, tol=1e-6, msg=''):
    STATS['assertions'] += 1
    if abs(a - b) > tol * max(1.0, abs(b)):
        raise Failure('%s expected %.9f got %.9f (diff %.3g)'
                      % (msg, b, a, a - b))


def run_suite(name, tests):
    passed = 0
    for fn in tests:
        STATS['tests'] += 1
        try:
            fn()
            passed += 1
        except Exception:
            STATS['failed_tests'].append('%s.%s' % (name, fn.__name__))
            print('  FAIL %s.%s' % (name, fn.__name__))
            traceback.print_exc()
    print('%-28s %3d / %3d tests passed' % (name, passed, len(tests)))
    return passed == len(tests)
