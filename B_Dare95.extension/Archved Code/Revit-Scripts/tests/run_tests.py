# -*- coding: utf-8 -*-
"""Run every DLC Room Areas test suite:  python run_tests.py"""
from __future__ import print_function
import os
import sys
import warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.simplefilter('ignore')
import harness  # noqa: E402

SUITES = ['test_geometry', 'test_engine', 'test_revit_io', 'test_script',
          'test_report_xlsx', 'test_compat']


def main():
    ok = True
    for name in SUITES:
        mod = __import__(name)
        ok = mod.run() and ok
    s = harness.STATS
    print('-' * 60)
    print('%d suites, %d tests, %d assertions, %d failed'
          % (len(SUITES), s['tests'], s['assertions'],
             len(s['failed_tests'])))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
