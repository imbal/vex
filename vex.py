#!/usr/bin/env python3
import os
import os.path

from cli import Command
from project import Project, VexBug, VexNoProject, VexNoHistory, VexUnclean, VexError, VexArgument
import rson

VEX = ".vex"

def get_project(check=True, empty=True):
    working_dir = os.getcwd()
    while True:
        config_dir = os.path.join(working_dir, VEX)
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
    """
        This gets called if an exception was thrown during normal operation.
    """
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


vex_init = vex_cmd.subcommand('init',short="create a new vex project")
@vex_init.run('--working --config --prefix --include... --ignore... [directory]')
def Init(directory, working, config, prefix, include, ignore):
    """
        Create a new vex project in a given directory. 

        - If no directory given, it is assumed to be the current directory.
        - Inside that directory, a `.vex` directory is created to store the project history.
        - An initial empty commit is added.
        - The subtree checkout defaults to `/directory_name`.
        
        i.e a `vex init` in `/a/b` creates a `/a/b/.vex` directory, an empty commit, and checks
        out `/b` in the repo, into `/a/b` on the filesystem.`

        If you make a mistake, `vex undo` will undo the initial commit, but not remove
        the `.vex` directory. 

        `init` takes multiple `--include=<file>` and `--ignore=<file>` arguments, 
        defaulting to `--include='*' --ignore='.vex' --ignore='.*'`

    """

    working_dir = working or directory or os.getcwd()
    config_dir = config or os.path.join(working_dir, VEX)
    prefix = prefix or os.path.split(working_dir)[1] or ''
    prefix = os.path.join('/', prefix)

    include = include or ["*"] 
    ignore = ignore or [".*",VEX]

    p = Project(config_dir, working_dir)

    if p.exists() and not p.clean_state():
        yield ('This vex project is unwell. Try `vex debug:status`')
    elif p.exists():
        if not p.history_isempty():
            raise VexError("A vex project already exists here")
        else:
            yield ('A empty project was round, re-creating project in "{}"...'.format(os.path.relpath(config_dir)))
            with p.lock('init') as p:
                p.init(prefix, include, ignore)
    else:
        yield ('Creating vex project in "{}"...'.format(working_dir))
        p.init(prefix, include, ignore)
        p.makelock()


vex_undo = vex_cmd.subcommand('undo', short="undo the last command")
@vex_undo.run('--list?')
def Undo(list):
    """
        `vex undo` will return the project to how it was before the last command changed 
        things. running `vex history` will show the list of commands that can be undone.

        for example:

        - `vex diff` / `vex status` / `vex log` and some other commands do not do anything
        and so cannot be undone.

        - calling `vex undo` after `vex commit` will not change the working copy, but will 
        remove the commit from the list of changes to the project

        - calling `vex undo` after calling `vex switch` to change which directory inside the
        repo to work on, will change the directory back. Edits to files are not undone.

        - calling `vex undo` after creating a branch with `vex new` will switch back
        to the old branch, but save the existing local changes incase `vex redo` is called.

        `vex undo --list` shows the list of commands that have been performed,
        and the order they will be undone in.

        similarly `vex redo --list` shows the actions that can be redone.
"""

    p = get_project()

    if list:
        count = 0
        for entry,redos in p.list_undos():
            count -= 1
            alternative = ""
            if len(redos) == 1:
                alternative = "(then undid {})".format(redos[0])
            elif len(redos) > 0:
                alternative = "(then undid {}, and {})".format(",".join(redos[:-1]), redos[-1])

            yield "{}: {}, ran {}\t{}".format(count, entry.time, entry.command,alternative)
            yield ""
    else:
        with p.lock('undo') as p:
            action = p.undo()
        if action:
            yield ('undid', action.command)

vex_redo = vex_cmd.subcommand('redo', "redo last undone command")
@vex_redo.run('--list? --choice')
def Redo(list, choice):
    """
        `vex redo` will redo the last action undone. `vex redo --list` will show the
        list of commands to choose from.

        `vex redo` is not the same as re-running the command, as `vex redo` will
        repeat the original changes made, without consulting the files in the working copy,
        or restoring the files if the command is something like `vex open`. 

        for example, redoing a `vex commit` will not commit the current versions of the files in the project
        
        redoing a `vex new <branch_name>` will reopen a branch, restoring the working copy
        with any local changes before `vex undo` was called.
        
        similarly, calling undo and redo on a `vex switch` operation, will just change which
        directory is checked out, saving and restoring local changes to files.

        if you do a different action after undo, you can still undo and redo.

        `vex redo --list` shows the actions that can be redone and `vex redo --choice=<n>` picks one.
    """
    p = get_project(empty=False)

    with p.lock('redo') as p:
        choices = p.list_redos()

        if list:
            if choices:
                for n, choice in enumerate(choices):
                    yield "{}: {}, {}".format(n, choice.time, choice.command)
            else:
                yield ('Nothing to redo')
        elif choices:
            choice = choice or 0
            action = p.redo(choice)
            if action:
                yield ('redid', action.command)
        else:
            yield ('Nothing to redo')



vex_status = vex_cmd.subcommand('status', short="list the files being tracked by vex")
@vex_status.run('--all?')
def Status(all):
    """
        `vex status` shows the state of each visible file, `vex status --all` shows the status 
        of every file in the current session/branch.
    """
    p = get_project()
    cwd = os.getcwd()
    with p.lock('status') as p:
        files = p.status()
        for reponame in sorted(files, key=lambda p:p.split(':')):
            entry = files[reponame]
            if entry.working is None:
                if all:
                    yield "hidden:{:9}\t{} ".format(entry.state, reponame)
            elif reponame.startswith('/.vex/') or reponame == '/.vex':
                path = os.path.relpath(reponame, '/.vex')
                if all:
                    yield "{}:{:8}\t{}".format('setting', entry.state, path)
            else:
                path = os.path.relpath(reponame, p.prefix())
                yield "{:16}\t{}{}".format(entry.state, path, ('*' if entry.stash else '') )
        yield ""

vex_log = vex_cmd.subcommand('changelog', aliases=['log'], short="list changes to project")
@vex_log.run()
def Log():
    """
        `vex changelog` or `vex log` shows the list of commits inside a branch, using 
        the current branch if none given.
    """
    
    p = get_project()
    for entry in p.log():
        yield (entry)
        yield ""


vex_diff = vex_cmd.subcommand('diff', short="show the differences between two parts of a project")
@vex_diff.run('[file...]')
def Diff(file):
    """
        `vex diff` shows the changes waiting to be committed.
    """
    p = get_project()
    with p.lock('diff') as p:
        cwd = os.getcwd()
        files = [os.path.join(cwd, f) for f in file] if file else None
        for name, diff in  p.diff(files).items():
            yield diff

vex_add = vex_cmd.subcommand('add','add files to the project')
@vex_add.run('file:str...')
def Add(file):
    """

    """
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

vex_forget = vex_cmd.subcommand('forget','remove files from the project, without deleting them')
@vex_forget.run('file...')
def Forget(file):
    """

    """
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

vex_prepare = vex_cmd.subcommand('prepare', short="save current working copy to prepare for commit", aliases=['save'])
@vex_prepare.run('--watch [file...]')
def Prepare(file,watch):
    """
    """
    p = get_project()
    yield ('Preparing')
    with p.lock('prepare') as p:
        cwd = os.getcwd()
        files = [os.path.join(cwd, f) for f in file] if file else None
        if watch:
            for file in watch_files(files):
                p.prepare([file])
                yield os.path.relpath(file)
        else:
            p.prepare(files)

vex_commit = vex_cmd.subcommand('commit', short="save the working copy and add an entry to the project changes")
@vex_commit.run('--add? --prepared? [file...]')
def Commit(prepared, add, file):
    """

    """
    p = get_project()
    yield ('Committing')
    with p.lock('commit') as p:
        if add:
            for f in p.add([os.getcwd()]):
                f = os.path.relpath(f)
                yield "add: {}".format(f)

        cwd = os.getcwd()
        files = [os.path.join(cwd, f) for f in file] if file else None
        if prepared and not files:
            done = p.commit_prepared()
        else:
            done = p.commit(files)

        if done:
            yield 'Committed'
        else:
            yield 'Nothing to commit'

vex_amend = vex_cmd.subcommand('amend', short="replace the last commit with the current changes in the project")
@vex_amend.run('[file...]')
def Amend(file):
    """

    """
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

vex_branches = vex_cmd.subcommand('branches', short="list branches")
@vex_branches.run()
def Branches():
    p = get_project()
    with p.lock('branches') as p:
        branches = p.list_branches()
        for (name, branch) in branches:
            if name:
                yield name
            else:
                yield branch.uuid


vex_open = vex_cmd.subcommand('open', short="open or create a branch")
@vex_open.run('name')
def Open(name):
    """

    """
    p = get_project()
    with p.lock('open') as p:
        p.open_branch(name)

vex_new = vex_cmd.subcommand('new', short="create a new branch")
@vex_new.run('name')
def New(name):
    """

    """
    p = get_project()
    with p.lock('new') as p:
        p.new_branch(name)

vex_saveas = vex_cmd.subcommand('saveas', short="rename current branch")
@vex_saveas.run('--rename? name')
def SaveAs(name, rename):
    """

    """
    p = get_project()
    with p.lock('saveas') as p:
        p.save_as(name, rename=rename)

vex_branch = vex_cmd.subcommand('branch', short="show branch information")
@vex_branch.run('[name]')
def Branch(name):
    """

    """
    p = get_project()
    with p.lock('branch') as p:
        if not name:
            active = p.active()
            branch = p.branches.get(active.branch)
        else:
            b = p.names.get(name)
            if b:
                branch = p.branches.get(b)
            else:
                raise VexArgument("{} isn't a branch".format(name)) 
        # session is ahead (in prepared? in commits?)
        # session has detached ...?
        # 
        yield branch.name

vex_switch = vex_cmd.subcommand('switch', short="change which directory (inside the project) is worked on")
@vex_switch.run('[prefix]')
def Switch(prefix):
    """

    """
    p = get_project()
    if prefix:
        with p.lock('switch') as p:
            prefix = os.path.join(p.prefix(), prefix)
            p.switch(prefix)
    else:
        yield p.prefix()

vex_debug = vex_cmd.subcommand('debug', 'internal: run a command without capturing exceptions, or repairing errors')
@vex_debug.run()
def Debug():
    """
    `vex debug commit` calls `vex commit`, but will always print a full traceback
    and never attempt to recover from incomplete changes.

    use with care.
    """
    yield ('Use vex debug <cmd> to run <cmd>, or use `vex debug:status`')

vex_stash = vex_debug.subcommand('stash', short="internal: save progress without making a commit or checkpoint to undo")
@vex_stash.run('--watch')
def Stash(watch):
    p = get_project()
    with p.lock('stash') as p:
        if not watch:
            p.stash()
        else:
            for file in watch_files():
                p.stash(files=[file])
                print(file)

debug_status = vex_debug.subcommand('status')
@debug_status.run()
def DebugStatus():
    p = get_project(check=False)
    with p.lock('debug:status') as p:
        yield ("Clean history", p.clean_state())
        head = p.active()
        out = []
        if head:

            out.append("head: {}".format(head.uuid))
            out.append("at {}, started at {}".format(head.prepare, head.commit))

            branch = p.branches.get(head.branch)
            out.append("commiting to branch {}".format(branch.uuid))

            commit = p.get_commit(head.prepare)
            out.append("last commit: {}".format(commit.__class__.__name__))
        else:
            if p.history_isempty():
                out.append("you undid the creation. try vex redo")
            else:
                out.append("no active head, but history, weird")
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

vex_ignore = vex_cmd.subcommand('ignore', short="add ignored files")
vex_ignore_add = vex_ignore.subcommand('add', 'add ignored files')
@vex_ignore.run('[file...]')
@vex_ignore_add.run('[file...]')
def AddIgnore(file):
    p = get_project()
    if file:
        with p.lock('ignore:add') as p:
            old = p.settings.get('ignore')
            old.extend(file)
            p.settings.set('ignore', old)
    else:
        for entry in p.settings.get('ignore'):
            yield entry


vex_include = vex_cmd.subcommand('include', short="add include files")
vex_include_add = vex_include.subcommand('add', 'add include files')
@vex_include.run('[file...]')
@vex_include_add.run('[file...]')
def AddInclude(file):
    p = get_project()
    if file:
        with p.lock('include:add') as p:
            old = p.settings.get('include')
            old.extend(file)
            p.settings.set('include', old)
    else:
        for entry in p.settings.get('include'):
            yield entry


props_cmd = vex_cmd.subcommand('fileprops', short="get/set properties on files", aliases=['props', 'properties', 'property'])
props_list_cmd = props_cmd.subcommand('get', short="list properties")
@props_cmd.run('file')
@props_list_cmd.run('file')
def ListProps(file):
    p = get_project()
    filename = os.path.join(os.getcwd(), file)
    with p.lock('fileprops:list') as p:
        for key,value in p.get_fileprops(filename).items():
            file = os.path.relpath(filename)
            yield "{}:{}:{}".format(file, key,value)

props_set_cmd = props_cmd.subcommand('set', short='set property')
@props_set_cmd.run('file name value:scalar')
def SetProp(file, name, value):
    p = get_project()
    filename = os.path.join(os.getcwd(), file)
    with p.lock('fileprops:list') as p:
        p.set_fileprop(filename, name, value)

git_cmd = vex_cmd.subcommand('git', short="interact with a git repository")

git_init_cmd = git_cmd.subcommand('init', short='create a new git project')
@git_init_cmd.run('--name --email directory')
def GitInit(name, email, directory):
    pass
    # call Init with new settings


git_set_cmd = git_cmd.subcommand('set', short='set git options')
@git_set_cmd.run('--number? --string? --boolean? name value')
def GitSet(number, string, boolean, name, value):
    pass

git_get_cmd = git_cmd.subcommand('get', short='get git options')
@git_get_cmd.run('name')
def GitGet(name):
    pass



vex_cmd.main(__name__)
