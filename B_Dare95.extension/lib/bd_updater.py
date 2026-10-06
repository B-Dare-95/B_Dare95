# -*- coding: utf-8 -*-
"""B_Dare95 auto-updater core.

Used by:
    startup.py          start_background_update()  - every Revit start / Reload
    hooks/app-closing   launch_detached_update()   - every time Revit closes

Design rules
    * The install folder (%LOCALAPPDATA%\\B_Dare95_dist) is a distribution
      copy, not a working copy. GitHub is the only source of truth, so every
      update ends with `checkout -f -B main origin/main`: local edits, a
      diverged history, a detached HEAD or a ZIP copy with no .git all
      converge to exactly what is on GitHub; leftover untracked files inside
      the extension (stale buttons) are cleaned, .gitignore'd files are kept.
    * Nothing here may ever block Revit or raise out of a background thread
      (an unhandled exception on a worker thread takes the Revit process down).
    * Every outcome is written to %LOCALAPPDATA%\\B_Dare95\\update.log.

IronPython 2.7: no f-strings, no nonlocal.
"""

import os
import json
import time

import clr
clr.AddReference('System')

from System import DateTime
from System.Diagnostics import Process, ProcessStartInfo, ProcessWindowStyle
from System.IO import Directory, File, FileInfo
from System.Text import UTF8Encoding
from System.Threading import (AbandonedMutexException, Mutex, Thread,
                              ThreadStart)


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------

REPO_URL = 'https://github.com/B-Dare-95/B_Dare95.git'
BRANCH = 'main'
EXT_NAME = 'B_Dare95.extension'

# lib/bd_updater.py -> B_Dare95.extension/ -> repo root
_LIB_DIR = os.path.dirname(os.path.abspath(__file__))
EXT_DIR = os.path.dirname(_LIB_DIR)
REPO_ROOT = os.path.dirname(EXT_DIR)
GIT_DIR = os.path.join(REPO_ROOT, '.git')

_LOCALAPPDATA = os.environ.get('LOCALAPPDATA', '')

# Must match DEST / BD_GIT_HOME / BD_DATA in B_Dare95_Installer.bat.
INSTALL_ROOT = os.path.join(_LOCALAPPDATA, 'B_Dare95_dist') if _LOCALAPPDATA else ''
PORTABLE_GIT = os.path.join(_LOCALAPPDATA, 'B_Dare95_git', 'cmd', 'git.exe') if _LOCALAPPDATA else ''
DATA_DIR = os.path.join(_LOCALAPPDATA or os.path.expanduser('~'), 'B_Dare95')
LOG_PATH = os.path.join(DATA_DIR, 'update.log')
STATE_PATH = os.path.join(DATA_DIR, 'updater_state.json')

MUTEX_NAME = 'Local\\B_Dare95_updater'
LOG_MAX_BYTES = 512 * 1024
LOG_KEEP_CHARS = 256 * 1024
STALE_LOCK_SECONDS = 10 * 60
OFF_NOTICE_EVERY = 24 * 3600          # "auto-updates are off" at most daily
UNREACHABLE_AFTER = 3 * 24 * 3600     # warn after 3 days without a good fetch

# Applied to every git call. -c is per-invocation only; nothing is written
# to the user's git config.
GIT_FLAGS = [
    '-c', 'safe.directory=*',         # clone made by an elevated installer
    '-c', 'credential.helper=',       # public repo: never pop a login window
    '-c', 'core.longpaths=true',
    '-c', 'core.quotePath=false',
    '-c', 'http.lowSpeedLimit=1000',  # abort a stalled download after 30 s
    '-c', 'http.lowSpeedTime=30',
]
_REFSPEC = '+refs/heads/{0}:refs/remotes/origin/{0}'.format(BRANCH)

_UTF8 = UTF8Encoding(False)


# ---------------------------------------------------------------------------
# log + state
# ---------------------------------------------------------------------------

def _ensure_data_dir():
    if not os.path.isdir(DATA_DIR):
        Directory.CreateDirectory(DATA_DIR)


def log(source, message):
    """Append one line to update.log. Never raises."""
    try:
        _ensure_data_dir()
        line = u'{0}  [{1}] {2}\r\n'.format(
            DateTime.Now.ToString('yyyy-MM-dd HH:mm:ss'), source, message)
        File.AppendAllText(LOG_PATH, line, _UTF8)
    except Exception:
        pass


def _rotate_log():
    try:
        if File.Exists(LOG_PATH) and FileInfo(LOG_PATH).Length > LOG_MAX_BYTES:
            text = File.ReadAllText(LOG_PATH)
            File.WriteAllText(LOG_PATH, text[-LOG_KEEP_CHARS:], _UTF8)
    except Exception:
        pass


def _load_state():
    try:
        with open(STATE_PATH) as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_state(data):
    try:
        _ensure_data_dir()
        with open(STATE_PATH, 'w') as handle:
            json.dump(data, handle)
    except Exception as err:
        log('state', 'could not save updater state: {0}'.format(err))


# ---------------------------------------------------------------------------
# paths + git discovery
# ---------------------------------------------------------------------------

def _same_path(a, b):
    return os.path.normcase(os.path.normpath(a)) == \
        os.path.normcase(os.path.normpath(b))


def is_install_copy():
    """True only when this extension is the installer's copy, never a dev copy."""
    return bool(INSTALL_ROOT) and _same_path(REPO_ROOT, INSTALL_ROOT)


def find_git():
    """Same search order as :FIND_GIT in the installer."""
    candidates = [PORTABLE_GIT]
    for folder in os.environ.get('PATH', '').split(os.pathsep):
        folder = folder.strip().strip('"')
        if folder:
            candidates.append(os.path.join(folder, 'git.exe'))
    for root in (os.environ.get('ProgramFiles'), os.environ.get('ProgramW6432'),
                 os.path.join(_LOCALAPPDATA, 'Programs') if _LOCALAPPDATA else None):
        if root:
            candidates.append(os.path.join(root, 'Git', 'cmd', 'git.exe'))
    for path in candidates:
        try:
            if path and os.path.isfile(path):
                return path
        except Exception:
            continue
    return None


def _short(sha):
    return sha[:7] if sha else 'none'


# ---------------------------------------------------------------------------
# running git
# ---------------------------------------------------------------------------

class GitStepFailed(Exception):
    def __init__(self, step, code, detail):
        Exception.__init__(self, step)
        self.step = step
        self.code = code
        self.detail = detail


def _quote(arg):
    """Windows command-line quoting (CommandLineToArgvW rules)."""
    if arg and not any(ch in arg for ch in ' \t"'):
        return arg
    out = ['"']
    backslashes = 0
    for ch in arg:
        if ch == '\\':
            backslashes += 1
            continue
        if ch == '"':
            out.append('\\' * (backslashes * 2 + 1))
        else:
            out.append('\\' * backslashes)
        out.append(ch)
        backslashes = 0
    out.append('\\' * (backslashes * 2))
    out.append('"')
    return ''.join(out)


def _apply_git_env(env):
    env['GIT_TERMINAL_PROMPT'] = '0'      # never wait on a prompt
    env['GCM_INTERACTIVE'] = 'never'


def _run_git(git, args, timeout_s):
    """Run git hidden. Returns (exit_code, stdout, stderr).

    exit_code is None on timeout. Raises if git.exe cannot be started.
    """
    psi = ProcessStartInfo(git)
    psi.Arguments = ' '.join(_quote(a) for a in (GIT_FLAGS + list(args)))
    psi.UseShellExecute = False
    psi.CreateNoWindow = True
    psi.WindowStyle = ProcessWindowStyle.Hidden
    psi.RedirectStandardOutput = True
    psi.RedirectStandardError = True
    psi.StandardOutputEncoding = _UTF8
    psi.StandardErrorEncoding = _UTF8
    psi.WorkingDirectory = REPO_ROOT
    _apply_git_env(psi.EnvironmentVariables)

    proc = Process.Start(psi)
    try:
        # Read both pipes asynchronously so neither can fill up and deadlock.
        out_task = proc.StandardOutput.ReadToEndAsync()
        err_task = proc.StandardError.ReadToEndAsync()
        if not proc.WaitForExit(int(timeout_s * 1000)):
            try:
                proc.Kill()
            except Exception:
                pass
            return None, '', 'timed out after {0} s'.format(timeout_s)
        proc.WaitForExit()
        return proc.ExitCode, (out_task.Result or ''), (err_task.Result or '')
    finally:
        proc.Dispose()


def _git_step(git, args, timeout_s, step):
    code, out, err = _run_git(git, ['-C', REPO_ROOT] + list(args), timeout_s)
    if code != 0:
        raise GitStepFailed(step, code, err)
    return out


def _first_lines(text, count=3):
    lines = [ln.strip() for ln in (text or '').splitlines() if ln.strip()]
    return ' | '.join(lines[:count]) or '(no message)'


def _head(git):
    code, out, _ = _run_git(
        git, ['-C', REPO_ROOT, 'rev-parse', '-q', '--verify', 'HEAD^{commit}'], 30)
    sha = out.strip()
    return sha if code == 0 and sha else None


def _commit_exists(git, sha):
    code, _, _ = _run_git(
        git, ['-C', REPO_ROOT, 'cat-file', '-e', sha + '^{commit}'], 30)
    return code == 0


# ---------------------------------------------------------------------------
# self-repair
# ---------------------------------------------------------------------------

def _clear_stale_locks(source):
    """A git process killed mid-write leaves *.lock files that block every
    later git command. Remove any older than STALE_LOCK_SECONDS."""
    if not os.path.isdir(GIT_DIR):
        return
    now = time.time()
    folders = [GIT_DIR]
    for root, _dirs, _files in os.walk(os.path.join(GIT_DIR, 'refs')):
        folders.append(root)
    for folder in folders:
        try:
            names = os.listdir(folder)
        except Exception:
            continue
        for name in names:
            if not name.endswith('.lock'):
                continue
            path = os.path.join(folder, name)
            try:
                if os.path.isfile(path) and now - os.path.getmtime(path) > STALE_LOCK_SECONDS:
                    os.remove(path)
                    log(source, 'removed stale lock {0}'.format(path))
            except Exception as err:
                log(source, 'could not remove stale lock {0}: {1}'.format(path, err))


def _quarantine_broken_repo(git, source):
    """If .git is unreadable, move it aside (never delete) so it is rebuilt."""
    if not os.path.isdir(GIT_DIR):
        return
    code, _, err = _run_git(git, ['-C', REPO_ROOT, 'rev-parse', '--git-dir'], 30)
    if code == 0:
        return
    target = '{0}.broken-{1}'.format(GIT_DIR, DateTime.Now.ToString('yyyyMMdd-HHmmss'))
    try:
        Directory.Move(GIT_DIR, target)
        log(source, 'git data was unreadable ({0}) - moved to {1}, rebuilding'.format(
            _first_lines(err, 1), target))
    except Exception as move_err:
        log(source, 'git data is unreadable and could not be moved aside: {0}'.format(move_err))


# ---------------------------------------------------------------------------
# the update itself
# ---------------------------------------------------------------------------

def _converge(git, source):
    """Make REPO_ROOT exactly origin/main. Raises GitStepFailed."""
    if not os.path.isdir(GIT_DIR):
        log(source, 'no .git folder - converting this copy into an auto-updating install')
        _git_step(git, ['init', '-q'], 60, 'init')
        _git_step(git, ['symbolic-ref', 'HEAD', 'refs/heads/' + BRANCH], 30, 'symbolic-ref')

    code, _, _ = _run_git(git, ['-C', REPO_ROOT, 'remote', 'set-url', 'origin', REPO_URL], 30)
    if code != 0:
        _git_step(git, ['remote', 'add', 'origin', REPO_URL], 30, 'remote add')

    _git_step(git, ['fetch', '-q', '--no-tags', 'origin', _REFSPEC], 180, 'fetch')
    _git_step(git, ['checkout', '-q', '-f', '-B', BRANCH, 'origin/' + BRANCH], 120, 'checkout')

    # Leftovers pyRevit would still load as buttons - typically folders a ZIP
    # copy had that were since renamed or deleted on GitHub. Only inside the
    # extension, and never .gitignore'd files.
    removed = [ln[len('Removing '):] for ln in
               _git_step(git, ['clean', '-fd', '--', EXT_NAME], 120, 'clean').splitlines()
               if ln.startswith('Removing ')]
    if removed:
        log(source, 'removed {0} leftover item(s): {1}{2}'.format(
            len(removed), ', '.join(removed[:5]), ' ...' if len(removed) > 5 else ''))


# --- describing what changed -------------------------------------------------

_BUNDLE_SUFFIXES = ('.tab', '.panel', '.stack', '.pulldown', '.splitbutton',
                    '.splitpushbutton', '.pushbutton', '.smartbutton',
                    '.linkbutton', '.invokebutton', '.urlbutton', '.content',
                    '.panelbutton', '.nobutton')
_COMMAND_SUFFIXES = ('.pushbutton', '.smartbutton', '.linkbutton',
                     '.invokebutton', '.urlbutton', '.content')
_ICON_EXTS = ('.png', '.ico', '.jpg', '.jpeg', '.svg', '.bmp', '.gif')
_PREFIX = EXT_NAME + '/'


def _command_bundle(path):
    """'X.tab/Y.panel/Z.pushbutton/script.py' -> 'X.tab/Y.panel/Z.pushbutton'.

    None when the path is not inside a pyRevit command bundle (folders without
    a bundle suffix are ignored by pyRevit, so their files never matter).
    """
    folders = path.split('/')[:-1]
    if not folders or not folders[0].lower().endswith('.tab'):
        return None
    for i, folder in enumerate(folders):
        low = folder.lower()
        if low.endswith(_COMMAND_SUFFIXES):
            return '/'.join(folders[:i + 1])  # sub-folders below it belong to it
        if not low.endswith(_BUNDLE_SUFFIXES):
            return None
    return None


def _title(bundle):
    name = bundle.rsplit('/', 1)[-1]
    return name[:name.rfind('.')]


def _needs_reload(status, path):
    """True when pyRevit has to rebuild the ribbon for this change to show."""
    if path.startswith('lib/'):
        return False                          # imported fresh on each click
    top = path.split('/', 1)[0]
    if top in ('hooks', 'resources', 'startup.py', 'bundle.yaml', 'extension.json'):
        return True
    if not top.lower().endswith('.tab'):
        return False                          # e.g. .idea, archives: ignored
    bundle = _command_bundle(path)
    if bundle is None:
        # container bundle.yaml/icons, or a folder pyRevit ignores
        parts = path.split('/')[:-1]
        if all(p.lower().endswith(_BUNDLE_SUFFIXES) for p in parts):
            return True
        return False
    name = path.rsplit('/', 1)[-1].lower()
    if name == 'bundle.yaml' or name.endswith(_ICON_EXTS):
        return True
    # Editing an existing script is live; adding/removing one changes the
    # button's entry point.
    return status != 'M'


def _diff(git, old, new):
    out = _git_step(git, ['diff', '--name-status', '--no-renames', old, new,
                          '--', EXT_NAME], 60, 'diff')
    rows = []
    for line in out.splitlines():
        bits = line.split('\t')
        if len(bits) >= 2 and bits[1].startswith(_PREFIX):
            rows.append((bits[0][:1], bits[1][len(_PREFIX):]))
    return rows


def _tree_bundles(git, commit):
    out = _git_step(git, ['ls-tree', '-r', '--name-only', commit, '--', EXT_NAME],
                    60, 'ls-tree')
    bundles = set()
    for line in out.splitlines():
        line = line.strip()
        if line.startswith(_PREFIX):
            bundle = _command_bundle(line[len(_PREFIX):])
            if bundle:
                bundles.add(bundle)
    return bundles


def _summarize(git, seen, loaded, new):
    """Tools added/updated/removed since `seen`; reload need since `loaded`."""
    result = {'kind': 'updated', 'new': [], 'updated': [], 'removed': [],
              'needs_reload': True, 'converted': loaded is None, 'commits': 0}
    if loaded is not None:
        result['needs_reload'] = any(
            _needs_reload(s, p) for s, p in _diff(git, loaded, new))
    if seen is None:
        return result

    code, out, _ = _run_git(git, ['-C', REPO_ROOT, 'rev-list', '--count',
                                  '{0}..{1}'.format(seen, new)], 30)
    if code == 0 and out.strip().isdigit():
        result['commits'] = int(out.strip())

    old_bundles = _tree_bundles(git, seen)
    new_bundles = _tree_bundles(git, new)
    touched = set()
    for _status, path in _diff(git, seen, new):
        bundle = _command_bundle(path)
        if bundle:
            touched.add(bundle)
    result['new'] = sorted(_title(b) for b in new_bundles - old_bundles)
    result['removed'] = sorted(_title(b) for b in old_bundles - new_bundles)
    result['updated'] = sorted(_title(b) for b in touched & old_bundles & new_bundles)
    return result


# --- one update pass ----------------------------------------------------------

def _off_notice(reason, source):
    """'auto-updates are off' result, throttled to once a day."""
    state = _load_state()
    now = time.time()
    last = state.get('off_notice_at')
    try:
        if last is not None and now - float(last) < OFF_NOTICE_EVERY:
            return None
    except Exception:
        pass
    state['off_notice_at'] = now
    _save_state(state)
    log(source, 'showing "auto-updates are off" notice ({0})'.format(reason))
    return {'kind': 'off', 'reason': reason}


def _update_once(source):
    git = find_git()
    if git is None:
        if os.path.isdir(GIT_DIR):
            log(source, 'auto-update OFF: git.exe not found on this PC')
            return _off_notice('git_missing', source)
        log(source, 'auto-update OFF: no git and no .git (ZIP install)')
        return _off_notice('zip_no_git', source)

    state = _load_state()
    try:
        _clear_stale_locks(source)
        _quarantine_broken_repo(git, source)
        loaded = _head(git) if os.path.isdir(GIT_DIR) else None
        _converge(git, source)
        new = _head(git)
    except GitStepFailed as fail:
        log(source, 'update failed at "{0}" (exit {1}): {2}'.format(
            fail.step, fail.code, _first_lines(fail.detail)))
        now = time.time()
        if 'first_fail_at' not in state:
            state['first_fail_at'] = now
            _save_state(state)
        elif now - float(state['first_fail_at']) > UNREACHABLE_AFTER:
            return _off_notice('unreachable', source)
        return None
    except Exception as err:                 # git.exe exists but will not start
        log(source, 'auto-update OFF: could not run {0}: {1}'.format(git, err))
        return _off_notice('git_broken', source)

    if new is None:
        log(source, 'update finished but HEAD is unreadable')
        return None

    if loaded == new:
        log(source, 'up to date at {0} (git: {1})'.format(_short(new), git))
    else:
        log(source, 'updated {0} -> {1} (git: {2})'.format(_short(loaded), _short(new), git))

    seen = state.get('last_seen') or loaded
    if seen and seen != new and not _commit_exists(git, seen):
        seen = loaded
    state['last_seen'] = new
    state['last_ok_at'] = time.time()
    state.pop('first_fail_at', None)
    state.pop('off_notice_at', None)
    _save_state(state)

    if seen == new and loaded is not None:
        return None
    try:
        result = _summarize(git, seen, loaded, new)
    except GitStepFailed as fail:
        log(source, 'could not describe the update ({0}): {1}'.format(
            fail.step, _first_lines(fail.detail)))
        result = {'kind': 'updated', 'new': [], 'updated': [], 'removed': [],
                  'needs_reload': loaded != new, 'converted': loaded is None,
                  'commits': 0}
    if result['new'] or result['removed'] or result['updated']:
        log(source, 'new: {0} | updated: {1} | removed: {2} | reload needed: {3}'.format(
            ', '.join(result['new']) or '-', ', '.join(result['updated']) or '-',
            ', '.join(result['removed']) or '-', result['needs_reload']))
    return result


# ---------------------------------------------------------------------------
# public entry points
# ---------------------------------------------------------------------------

def note_skipped():
    """Called by startup.py when this is not the install copy."""
    _rotate_log()
    log('startup', 'loaded from {0} (not the install folder) - auto-update skipped'.format(
        REPO_ROOT))
    if INSTALL_ROOT and os.path.isdir(os.path.join(INSTALL_ROOT, EXT_NAME)):
        log('startup', 'WARNING: a second copy is also installed at {0} - '
                       'pyRevit may load either one'.format(INSTALL_ROOT))


def _worker(callback):
    mutex = None
    owned = [False]
    try:
        _rotate_log()
        mutex = Mutex(False, MUTEX_NAME)
        try:
            owned[0] = mutex.WaitOne(0)
        except AbandonedMutexException:
            owned[0] = True
        if not owned[0]:
            log('startup', 'another update is already running - skipped')
            return
        result = _update_once('startup')
        if result is not None and callback is not None:
            callback(result)
    except Exception as err:
        log('startup', 'updater error: {0}'.format(err))
    finally:
        if mutex is not None:
            if owned[0]:
                try:
                    mutex.ReleaseMutex()
                except Exception:
                    pass
            try:
                mutex.Dispose()
            except Exception:
                pass


def start_background_update(callback=None):
    """Update on a background thread; never blocks the pyRevit load.

    callback(result) is called ON THE WORKER THREAD when there is something
    to tell the user; it must marshal to the UI thread itself.
    """
    def _run():
        _worker(callback)

    thread = Thread(ThreadStart(_run))
    thread.IsBackground = True               # never keeps Revit alive on exit
    thread.Name = 'B_Dare95 updater'
    thread.Start()
    return thread


def _cmd_arg(arg):
    return '"{0}"'.format(arg) if (' ' in arg or '&' in arg or not arg) else arg


def launch_detached_update():
    """Fire a hidden cmd.exe that fetches + checks out after Revit has exited,
    so the next Revit start already loads the new files. Never raises."""
    try:
        if not is_install_copy() or not os.path.isdir(GIT_DIR):
            return False
        git = find_git()
        if git is None:
            return False
        _rotate_log()

        def git_cmd(args):
            return ' '.join(_cmd_arg(a) for a in [git] + GIT_FLAGS + ['-C', REPO_ROOT] + args)

        logq = '"{0}"'.format(LOG_PATH)
        stamp = '%DATE% %TIME:~0,8%'
        script = (
            '{fetch} >>{log} 2>&1 && {checkout} >>{log} 2>&1 && {clean} >>{log} 2>&1 && '
            '(echo {stamp}  [closing] in sync with origin/{branch}>>{log}) || '
            '(echo {stamp}  [closing] FAILED - see git messages above>>{log})'
        ).format(
            fetch=git_cmd(['fetch', '-q', '--no-tags', 'origin', _REFSPEC]),
            checkout=git_cmd(['checkout', '-q', '-f', '-B', BRANCH, 'origin/' + BRANCH]),
            clean=git_cmd(['clean', '-fdq', '--', EXT_NAME]),
            log=logq, stamp=stamp, branch=BRANCH)

        psi = ProcessStartInfo(os.environ.get('ComSpec') or 'cmd.exe')
        psi.Arguments = '/d /s /c "{0}"'.format(script)
        psi.UseShellExecute = False
        psi.CreateNoWindow = True
        psi.WindowStyle = ProcessWindowStyle.Hidden
        psi.WorkingDirectory = REPO_ROOT
        _apply_git_env(psi.EnvironmentVariables)
        Process.Start(psi)                   # outlives Revit on purpose
        log('closing', 'Revit closing - background update started')
        return True
    except Exception as err:
        log('closing', 'could not start the closing update: {0}'.format(err))
        return False
