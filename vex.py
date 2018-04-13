#!/usr/bin/env python3
import os
import os.path

from cli import Command
from project import Project, VexBug, VexNoProject, VexNoHistory, VexUnclean, VexError, VexArgument
import rson

DOTVEX = ".vex"

def get_project(check=True, empty=True):
    working_dir = os.getcwd()
    while True:
        config_dir = os.path.join(working_dir, DOTVEX)
        if os.path.exists(config_dir):
            break
        new_working_dir = os.path.split(working_dir)[0]
        if new_working_dir == working_dir:
            raise VexNoProject('No vex project found in {}'.format(os.getcwd()))
        working_dir = new_working_dir
    p = Project(config_dir, working_dir)
    if check:
        if empty and p.history_isempty():
            raise VexNoHistory('Vex project exists, but `vex init` has not been run (or has been undone)')
        elif not p.clean_state():
            raise VexUnclean('Another change is already in progress. Try `vex debug:status`')
    return p

# CLI bits. Should handle environs, cwd, etc
vex_cmd = Command('vex', 'a database for files')
@vex_cmd.on_error()
def Error(path, args, exception, traceback):
    message = str(exception)
    if path:
        yield ("{}: {}".format(':'.join(path), message))
    else:
        yield ("vex: {}".format(message))

    if not isinstance(exception, VexError):
        yield ""
        yield ("Worse still, it's an error vex doesn't recognize yet. A python traceback follows:")
        yield ""
        yield (traceback)

    p = get_project(check=False)

    if p.exists() and not p.clean_state():
        p.rollback_new_action()

        if not p.clean_state():
            yield ('This is bad: The project history is corrupt, try `vex debug:status` for more information')
        else:
            yield ('Good news: The changes that were attempted have been undone')


vex_init = vex_cmd.subcommand('init')
@vex_init.run('--working --config --prefix --include... --ignore... [directory]')
def Init(directory, working, config, prefix, include, ignore):
    working_dir = working or directory or os.getcwd()
    config_dir = config or os.path.join(working_dir, DOTVEX)
    prefix = prefix or os.path.split(working_dir)[1] or 'root'
    prefix = os.path.join('/', prefix)

    include = include or ["*"] 
    ignore = ignore or [".*"]

    p = Project(config_dir, working_dir)

    if p.exists() and not p.clean_state():
        yield ('This vex project is unwell. Try `vex debug:status`')
    elif p.exists():
        if not p.history_isempty():
            raise VexError("A vex project already exists here")
        else:
            yield ('A empty project was round, re-creating project in "{}"...'.format(directory))
            with p.lock('init') as p:
                p.init(prefix, include, ignore)
    else:
        yield ('Creating vex project in "{}"...'.format(directory))
        p.init(prefix, include, ignore)
        p.makelock()

vex_add = vex_cmd.subcommand('add','add files to the project')
@vex_add.run('file...')
def Add(file):
    cwd = os.getcwd()
    if not file:
        files = [cwd]
    else:
        files = [os.path.join(cwd, f) for f in file]
    files = [os.path.normpath(f) for f in files]
    missing = [f for f in file if not os.path.exists(f)]
    if missing:
        raise VexArgument('cannot find {}'.format(",".join(missing)))
    p = get_project()
    with p.lock('add') as p:
        for f in p.add(files):
            f = os.path.relpath(f)
            yield "add: {}".format(f)

vex_forget = vex_cmd.subcommand('forget','remove files from the project, without deleting file')
@vex_forget.run('file...')
def Forget(file):
    if not file:
        return

    cwd = os.getcwd()
    files = [os.path.join(cwd, f) for f in file]
    files = [os.path.normpath(f) for f in files]
    missing = [f for f in file if not os.path.exists(f)]
    if missing:
        raise VexArgument('cannot find {}'.format(",".join(missing)))
    p = get_project()
    with p.lock('forget') as p:
        for f in p.forget(files):
            f = os.path.relpath(f)
            yield "forget: {}".format(f)

vex_diff = vex_cmd.subcommand('diff')
@vex_diff.run('[file...]')
def Diff(file):
    p = get_project()
    with p.lock('diff') as p:
        cwd = os.getcwd()
        files = [os.path.join(cwd, f) for f in file] if file else None
        for name, diff in  p.diff(files).items():
            yield name
            yield diff


vex_prepare = vex_cmd.subcommand('prepare', short="Save current working copy to prepare for commit", aliases=["save"])
@vex_prepare.run('[file...]')
def Prepare(file):
    p = get_project()
    yield ('Preparing')
    with p.lock('prepare') as p:
        cwd = os.getcwd()
        files = [os.path.join(cwd, f) for f in file] if file else None
        p.prepare(files)

vex_commit = vex_cmd.subcommand('commit')
@vex_commit.run('[file...]')
def Commit(file):
    p = get_project()
    yield ('Committing')
    with p.lock('commit') as p:
        cwd = os.getcwd()
        files = [os.path.join(cwd, f) for f in file] if file else None
        if p.commit(files):
            yield 'Committed'
        else:
            yield 'Nothing to commit'

vex_amend = vex_cmd.subcommand('amend')
@vex_commit.run('[file...]')
def Amend(file):
    p = get_project()
    yield ('Amending')
    with p.lock('amend') as p:
        cwd = os.getcwd()
        files = [os.path.join(cwd, f) for f in file] if file else None
        if p.amend(files):
            yield 'Committed'
        else:
            yield 'Nothing to commit'
        # check that session() and branch()

vex_log = vex_cmd.subcommand('log')
@vex_log.run()
def Log():
    p = get_project()
    for entry in p.log():
        yield (entry)
        yield ""

vex_history = vex_cmd.subcommand('history')
@vex_history.run()
def History():
    p = get_project()

    for entry,redos in p.history():
        alternative = ""
        if len(redos) == 1:
            alternative = "(can redo {})".format(redos[0])
        elif len(redos) > 0:
            alternative = "(can redo {}, or {})".format(",".join(redos[:-1]), redos[-1])

        yield "{}\t{}\t{}".format(entry.time, entry.command,alternative)
        yield ""

vex_status = vex_cmd.subcommand('status')
@vex_status.run()
def Status():
    p = get_project()
    cwd = os.getcwd()
    with p.lock('status') as p:
        files = p.status()
        for reponame in sorted(files, key=lambda p:p.split(':')):
            entry = files[reponame]
            if entry.working is None:
                yield "hidden:{:9}\t{} ".format(entry.state, reponame)
            elif reponame.startswith('/.vex/') or reponame == '/.vex':
                path = os.path.relpath(reponame, '/.vex')
                yield "{}:{:8}\t{}".format('setting', entry.state, path)
            else:
                path = os.path.relpath(reponame, p.prefix())
                yield "{:16}\t{} as {}".format(entry.state, path, reponame)

vex_switch = vex_cmd.subcommand('switch')
@vex_switch.run('prefix')
def switch(prefix):
    p = get_project()

    with p.lock('switch') as p:
        prefix = os.path.join(p.prefix(), prefix)
        p.switch(prefix)

vex_undo = vex_cmd.subcommand('undo')
@vex_undo.run()
def Undo():
    p = get_project()

    with p.lock('undo') as p:
        action = p.undo()
    if action:
        yield ('undid', action.command)

vex_redo = vex_cmd.subcommand('redo')
@vex_redo.run('--list? --choice')
def Redo(list, choice):
    p = get_project(empty=False)

    with p.lock('redo') as p:
        choices = p.redo_choices()

        if list:
            if choices:
                for n, choice in enumerate(choices):
                    yield (n, choice.time, choice.command)
            else:
                yield ('Nothing to redo')
        elif choices:
            choice = choice or 0
            action = p.redo(choice)
            if action:
                yield ('redid', action.command)
        else:
            yield ('Nothing to redo')

vex_debug = vex_cmd.subcommand('debug', 'run a command without capturing exceptions')
@vex_debug.run()
def Debug():
    yield ('Use vex debug <cmd> to run <cmd>, or use `vex debug:status`')

debug_status = vex_debug.subcommand('status')
@debug_status.run()
def DebugStatus():
    p = get_project(check=False)
    with p.lock('debug:status') as p:
        yield ("Clean history", p.clean_state())
        session = p.active()
        out = []
        if session:

            out.append("session: {}".format(session.uuid))
            out.append("at {}, started at {}".format(session.prepare, session.commit))

            branch = p.branches.get(session.branch)
            out.append("commiting to branch {}".format(branch.uuid))

            commit = p.changes.get_obj(session.prepare)
            out.append("last commit: {}".format(commit.__class__.__name__))
        else:
            if p.history_isempty():
                out.append("you undid the creation. try vex redo")
            else:
                out.append("no active session, but history, weird")
        out.append("")
        return "\n".join(out)


debug_restart = vex_debug.subcommand('restart')
@debug_restart.run()
def DebugRestart():
    p = get_project(check=False)
    with p.lock('debug:restart') as p:
        if p.clean_state():
            yield ('There is no change in progress to restart')
            return
        yield ('Restarting current action...')
        p.restart_new_action()
        if p.clean_state():
            yield ('Project has recovered')
        else:
            yield ('Oh dear')

debug_rollback = vex_debug.subcommand('rollback')
@debug_rollback.run()
def DebugRollback():
    p = get_project(check=False)
    with p.lock('debug:rollback') as p:
        if p.clean_state():
            yield ('There is no change in progress to rollback')
            return
        yield ('Rolling back current action...')
        p.rollback_new_action()
        if p.clean_state():
            yield ('Project has recovered')
        else:
            yield ('Oh dear')

vex_cmd.main(__name__)
