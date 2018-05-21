#!/usr/bin/env python3
"""

vex is a command line program for saving changes to a project, switching
between different versions, and sharing those changes.

vex supports bash completion: run `complete -o nospace -C vex vex`

"""
import os
import sys
import types
import os.path
import traceback
import subprocess
import tempfile

from contextlib import contextmanager

from vexlib.cli import Command, argspec
from vexlib.project import Project
from vexlib.errors import VexBug, VexNoProject, VexNoHistory, VexUnclean, VexError, VexArgument, VexUnimplemented

DEFAULT_CONFIG_DIR = ".vex"
DEFAULT_INCLUDE = ["*"] 
DEFAULT_IGNORE =  [".*", DEFAULT_CONFIG_DIR, ".DS_Store", "*~", "*.swp", "__*__"]

fake = False

@contextmanager
def watcher():
    p = subprocess.run('fswatch --version', stdout=subprocess.DEVNULL, shell=True)
    if p.returncode: raise VexBug('fswatch is not installed')

    p = subprocess.Popen('fswatch .', shell=True, stdout=subprocess.PIPE)
    def watch_files():
        line = None
        while True:
            try:
                line = p.stdout.readline()
                if not line: break
                yield line.decode('utf-8').rstrip()
            except KeyboardInterrupt:
                break
    try:
        yield watch_files
    finally:
        p.terminate()

def get_project():
    working_dir = os.getcwd()
    while True:
        config_dir = os.path.join(working_dir,  DEFAULT_CONFIG_DIR)
        if os.path.exists(config_dir):
            break
        new_working_dir = os.path.split(working_dir)[0]
        if new_working_dir == working_dir:
            return None
        working_dir = new_working_dir
    git = os.path.exists(os.path.join(config_dir, "git"))
    return Project(config_dir, working_dir, fake=fake, git=git)

def open_project(allow_empty=False):
    p = get_project()
    if not p:
        raise VexNoProject('no vex project found in {}'.format(os.getcwd()))
    if not allow_empty and p.history_isempty():
        raise VexNoHistory('Vex project exists, but `vex init` has not been run (or has been undone)')
    elif not p.clean_state():
        raise VexUnclean('Another change is already in progress. Try `vex debug:status`')
    return p
    

# CLI bits. Should handle environs, cwd, etc
vex_cmd = Command('vex', 'a database for files', long=__doc__, prefixes=['fake'])

@vex_cmd.on_complete()
def Complete(prefix, field, argtype):
    out = []
    if argtype == 'path':
        if prefix:
            out.extend("{} ".format(p) for p in os.listdir() if p.startswith(prefix))
        else:
            out.extend("{} ".format(p) for p in os.listdir() if not p.startswith('.'))
    elif argtype in ('bool', 'boolean'):
        vals = ('true ','false ')
        if prefix:
            out.extend(p for p in vals if p.startswith(prefix))
        else:
            out.extend(vals)

    elif argtype == 'branch':
        p = open_project()
        if p:
            vals = p.list_branches()
            if prefix:
                out.extend("{} ".format(name) for name, uuid in vals if name and name.startswith(prefix))
            else:
                out.extend("{} ".format(name) for name, uuid in vals if name)

    return out


@vex_cmd.on_call()
def Call(mode, path, args, callback):
    """ calling vex foo:bar args, calls this function with 'call', ['foo', 'bar'], args, and
        a callback that is the right function to call
    """
    global fake # so sue me
    if mode == 'fake':
        fake = True
    try:
        result = callback()
        if sys.stderr.isatty() and sys.stdout.isatty():
            env = {}
            env.update(os.environ)
            env["LESS"] = "FRX"
            env["LV"] = "-c"
            p = subprocess.Popen('less', env=env, stdin=subprocess.PIPE, encoding='utf8')

            if isinstance(result, types.GeneratorType):
                for line in result:
                    if line is not None:
                        print(line, file=p.stdin)
            elif result is not None:
                print(result, file=p.stdin)
            p.stdin.close()
            p.wait()
        elif isinstance(result, types.GeneratorType):
            for line in result:
                if line is not None:
                    print(line)
        elif result is not None:
            print(result)
        return 0

    except Exception as e:
        if mode =="debug":
            raise
        result= "".join(traceback.format_exception(*sys.exc_info()))
        message = str(e)
        if not message: message = e.__class__.__name__
        vex_error = isinstance(e, VexError)

    if path:
        print("{}: error: {}".format(':'.join(path), message))
    else:
        print("vex: error: {}".format(message))

    if not vex_error:
        print("\nWorse still, it's an error vex doesn't recognize yet. A python traceback follows:\n")
        print(result)

    p = get_project()

    if p and p.exists() and not p.clean_state():
        with p.lock('rollback') as p:
            p.rollback_new_action()

            if not p.clean_state():
                print('This is bad: The project history is corrupt, try `vex debug:status` for more information')
            else:
                print('Good news: The changes that were attempted have been undone')
    return -1


vex_init = vex_cmd.subcommand('init')
@vex_init.on_run()
@argspec('''
    --working:path    # Working directory, where files are edited/changed
    --config:path     # Normally /working_dir/.vex if not given 
    --prefix:path     # Subdirectory to check out of the repository, normally the working directory name
    --include:str... # files to include whe using vex add, can be passed multiple times 
    --ignore:str...  # files to ignore when using vex add, can be passed multiple times
    --git? # git backed
    [directory]  #
''')
def Init(directory, working, config, prefix, include, ignore, git):
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

        `--include`, `--ignore`, can be passed multiple times, and work the 
        same as `vex include 'pattern'` and `vex ignore 'pattern'`

    """

    working_dir = working or directory or os.getcwd()
    config_dir = config or os.path.join(working_dir,  DEFAULT_CONFIG_DIR)
    prefix = prefix or os.path.split(working_dir)[1] or ''
    prefix = os.path.join('/', prefix)

    include = include or DEFAULT_INCLUDE
    ignore = ignore or DEFAULT_IGNORE

    p = Project(config_dir, working_dir, fake, git=git)

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
        p.makedirs()
        p.makelock()
        with p.lock('init') as p:
            yield ('Creating vex project in "{}"...'.format(working_dir))
            p.init(prefix, include, ignore)


vex_undo = vex_cmd.subcommand('undo')
@vex_undo.on_run()
def Undo():
    """
        Undo the last command.

        `vex undo` will return the project to how it was before the last command changed 
        things. running `vex undo:list` will show the list of commands that can be undone.

        for example:

        - `vex diff` / `vex status` / `vex log` and some other commands do not do anything
        and so cannot be undone.

        - calling `vex undo` after `vex commit` will not change the working copy, but will 
        remove the commit from the list of changes to the project

        - calling `vex undo` after calling `vex switch` to change which directory inside the
        repo to work on, will change the directory back. Edits to files are not undone.

        - calling `vex undo` after creating a branch with `vex new` will switch back
        to the old branch, but save the existing local changes incase `vex redo` is called.

        `vex undo:list` shows the list of commands that have been performed,
        and the order they will be undone in.

        similarly `vex redo:list` shows the actions that can be redone.
    """

    p = open_project()

    with p.lock('undo') as p:
        action = p.undo()
    if action:
        yield 'undid {}'.format(action.command)

vex_undo_list = vex_undo.subcommand('list')
@vex_undo_list.on_run()
def UndoList():
    """
        List the commands that can be undone.

        `vex undo` will return the project to how it was before the last command changed 
        things. running `vex undo:list` will show the list of commands that can be undone.

        `vex undo:list` shows the list of commands that have been performed,
        and the order they will be undone in.

        similarly `vex redo:list` shows the actions that can be redone.
    """

    p = open_project()

    count = 0
    for entry,redos in p.list_undos():
        count -= 1
        alternative = ""
        if len(redos) == 1:
            alternative = "(then ran but undid: {})".format(redos[0].command)
        elif len(redos) > 0:
            alternative = "(then ran but undid: {}, and {} )".format(",".join(r.command for r in redos[:-1]), redos[-1].command)

        yield "{}: {}, ran {}\t{}".format(count, entry.time, entry.command,alternative)
        yield ""

vex_redo = vex_cmd.subcommand('redo')
@vex_redo.on_run()
@argspec('''
    --choice:int # Which command to redo. `--choice=0` means the last action uandone.     
''')
def Redo(choice):
    """
        Redo the last undone command.

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

        `vex redo:list` shows the actions that can be redone and `vex redo --choice=<n>` picks one.

        The order of the list changes when you pick a different item to redo. 
    """
    p = open_project(allow_empty=True)

    with p.lock('redo') as p:
        choices = p.list_redos()

        if choices:
            choice = choice or 0
            action = p.redo(choice)
            if action:
                yield 'redid {}'.format(action.command)
        else:
            yield ('Nothing to redo')


vex_redo_list = vex_redo.subcommand('list')
@vex_redo_list.on_run()
def RedoList():
    """
        List the commands that can be redone.

        `vex redo` will redo the last action undone. `vex redo:list` will show the
        list of commands to choose from.
    """
    p = open_project(allow_empty=True)

    with p.lock('redo') as p:
        choices = p.list_redos()

        if choices:
            for n, choice in enumerate(choices):
                yield "{}: {}, {}".format(n, choice.time, choice.command)
        else:
            yield ('Nothing to redo')


vex_status = vex_cmd.subcommand('status')
@vex_status.on_run()
@argspec('''
    --all?      # Show all files inside the repo, even ones outside working copy
    --missing?  # Show untracked files
''')
def Status(all, missing):
    """
        Show the files and directories tracked by vex.

        `vex status` shows the state of each visible file, `vex status --all` shows the status 
        of every file in the current session/branch.
    """
    p = open_project()
    cwd = os.getcwd()
    with p.lock('status') as p:
        files = p.status()
        for reponame in sorted(files, key=lambda p:p.split(':')):
            entry = files[reponame]
            path = os.path.relpath(reponame, p.prefix())
            if entry.working is None:
                if all:
                    yield "hidden:{:9}\t{} ".format(entry.state, path)
            elif reponame.startswith('/.vex/') or reponame == '/.vex':
                if all:
                    yield "{}:{:8}\t{}".format('setting', entry.state, path)
            else:
                yield "{:16}\t{}{}".format(entry.state, path, ('*' if entry.stash else '') )
        yield ""
        if all or missing:
            for f in p.untracked(os.getcwd()):
                path = os.path.relpath(f)
                yield "{:16}\t{}".format('untracked', path)


vex_log = vex_cmd.subcommand('log', aliases=['changelog'])
@vex_log.on_run()
@argspec('''
        --all? # Show all changes
''')
def Log(all):
    """
        List changes made to the project.

        `vex changelog` or `vex log` shows the list of commits inside a branch, using 
        the current branch if none given.
    """
    
    p = open_project()
    for entry in p.log(all=all):
        yield (entry)
        yield ""


vex_diff = vex_cmd.subcommand('diff')
vex_diff_file = vex_diff.subcommand('file')
@vex_diff.on_run()
@vex_diff_file.on_run()
@argspec('''
    [file:path...] # difference between two files
''')
def Diff(file):
    """
        Show the changes, line by line, that have been made since the last commit.

        `vex diff` shows the changes waiting to be committed for the given files
    """
    p = open_project()
    with p.lock('diff') as p:
        cwd = os.getcwd()
        files = file if file else None # comes in as []
        for name, diff in  p.active_diff_files(files).items():
            yield diff

vex_cmd_files = vex_cmd.group('files')

vex_add = vex_cmd_files.subcommand('add')
@vex_add.on_run()
@argspec('''
    --include:str... # files to include whe using vex add, can be passed multiple times 
    --ignore:str...  # files to ignore when using vex add, can be passed multiple times
    [file:path...]     # filename or directory to add
''')
def Add(include, ignore, file):
    """
        Add files to the project.

        `vex add` will add all files given to the project, and recurse through
        subdirectories too.

        it uses the settings in `vex ignore` and `vex include`

    """
    cwd = os.getcwd()
    if not file:
        files = [cwd]
    else:
        files = file
    missing = [f for f in file if not os.path.exists(f)]
    if missing:
        raise VexArgument('cannot find {}'.format(",".join(missing)))
    p = open_project()
    include = include if include else None
    ignore = ignore if ignore else None
    with p.lock('add') as p:
        for f in p.add(files, include=include, ignore=ignore):
            f = os.path.relpath(f)
            yield "add: {}".format(f)

vex_forget = vex_cmd_files.subcommand('forget','remove files from the project, without deleting them')
@vex_forget.on_run('''
        [file:path...] # Files to remove from next commit
''')
def Forget(file):
    """
        `vex forget` will instruct vex to stop tracking a file, and it will not appear
        inside the next commit.

        it does not delete the file from the working copy.
    """
    if not file:
        return

    file = [f for f in file if os.path.exists(f)]
    p = open_project()
    with p.lock('forget') as p:
        for f in p.forget(file).values():
            f = os.path.relpath(f)
            yield "forget: {}".format(f)

vex_remove = vex_cmd_files.subcommand('remove','remove files from the project, deleting them')
@vex_remove.on_run('''
        [file:path...] # Files to remove from working copy
''')
def Remove(file):
    """
        `vex remove` will instruct vex to stop tracking a file, and it will not appear
        inside the next commit.

        it will delete the file from the working copy.
    """
    if not file:
        return

    file= [f for f in file if os.path.exists(f)]
    p = open_project()
    with p.lock('remove') as p:
        for f in p.remove(file).values():
            f = os.path.relpath(f)
            yield "remove: {}".format(f)

vex_restore = vex_cmd_files.subcommand('restore','restore files from the project, overwriting modifications')
@vex_restore.on_run('''
        [file:path...] # Files to restore to working copy
''')
def Restore(file):
    """
        `vex restore` will change a file back to how it was 
    """
    if not file:
        return

    p = open_project()
    with p.lock('restore') as p:
        for f in p.restore(file).values():
            f = os.path.relpath(f)
            yield "restore: {}".format(f)
vex_missing = vex_cmd_files.subcommand('missing','files in current directory but not in project', aliases=['untracked'])
@vex_missing.on_run('')
def Missing():
    """
        `vex missing` shows missing files
    """
    p = open_project()
    for f in p.untracked(os.getcwd()):
            f = os.path.relpath(f)
            yield "missing: {}".format(f)
vex_cmd_commit = vex_cmd.group("commit")

vex_id = vex_cmd_commit.subcommand('id', short='what was the last change')
@vex_id.on_run()
def Id():
    raise VexUnimplemented()

vex_commit = vex_cmd_commit.subcommand('commit', short="save the working copy and add an entry to the project changes")
@vex_commit.on_run('''
    --add?          # Run `vex add` before commiting
    [file:path...]       # Commit only a few changed files
''')
def Commit(add, file):
    """
        `vex commit` saves the current state of the project.

    """
    p = open_project()
    with p.lock('commit') as p:
        if add:
            for f in p.add([os.getcwd()]):
                f = os.path.relpath(f)
                yield "add: {}".format(f)

        cwd = os.getcwd()
        files = file if file else None

        changes = p.commit_active(files)

        if changes:
            for name, entries in changes.items():
                entries = [entry.text for entry in entries]
                name = os.path.relpath(name, p.prefix())
                yield "commit: {}, {}".format(', '.join(entries), name)

        else:
            yield 'commit: Nothing to commit'

vex_prepare = vex_commit.subcommand('prepare', short="save current working copy to prepare for commit", aliases=['save'])
@vex_prepare.on_run('''
        --add?          # Run `vex add` before commiting
        --watch?         # Unsupported
        [file:path...] # Files to add to the commt 
''')
def Prepare(file,watch, add):
    """
        `vex prepare` is like `vex commit`, except that the next commit will inherit all of the 
        changes made.

        preparory commits are not applied to branches.
    """
    p = open_project()
    yield ('Preparing')
    with p.lock('prepare') as p:
        if add:
            for f in p.add([os.getcwd()]):
                f = os.path.relpath(f)
                yield "add: {}".format(f)

        cwd = os.getcwd()
        files = file if file else None
        if watch:
            active = p.active()
            prefix = p.prefix()
            with watcher() as files:
                for file in files():
                    if p.check_file(file):
                        repo = p.full_to_repo_path(prefix, file)
                        if repo in active.files:
                            p.prepare([file])
                            yield os.path.relpath(file)
        else:
            p.prepare(files)

vex_commit_prepared = vex_commit.subcommand('prepared', short="commit prepared files")
@vex_commit_prepared.on_run()
def CommitPrepared():
    """
        `vex commit:prepared` transforms earlier `vex prepare` into a commit

    """
    p = open_project()
    with p.lock('commit:prepared') as p:
        changes = p.commit_prepared()
        if changes:
            for name, entries in changes.items():
                entries = [entry.text for entry in entries]
                name = os.path.relpath(name, p.prefix())
                yield "commit: {}, {}".format(', '.join(entries), name)
        else:
            yield 'commit: Nothing to commit'


vex_amend = vex_commit.subcommand('amend', short="replace the last commit with the current changes in the project")
@vex_amend.on_run('''
        [file:path...] # files to change
''')
def Amend(file):
    """
        `vex amend` allows you to re-commit, indicating that the last commit
        was incomplete.

        `vex amend` is like `vex prepare`, except that it operates on the last commit, 
        instead of preparing for the next.

    """
    p = open_project()
    yield ('Amending')
    with p.lock('amend') as p:
        cwd = os.getcwd()
        files = file if file else None
        if p.amend(files):
            yield 'Committed'
        else:
            yield 'Nothing to commit'
        # check that session() and branch()

vex_message = vex_cmd_commit.subcommand('message', short="edit commit message")
vex_message_edit = vex_message.subcommand('edit', short='edit commit message')
@vex_message.on_run('--editor [message]')
@vex_message_edit.on_run('--editor [message]')
def EditMessage(editor, message):
    p = open_project()
    if message:
        with p.lock('message:set') as p:
            p.state.set('message', message)
            return "set"

    with p.lock('editor') as p:
        if not editor and p.state.exists('editor'):
            editor = p.state.get('editor')
        if not editor:
            editor = os.environ.get('EDITOR')
        if not editor:
            editor = os.environ.get('VISUAL')
        file = p.state.filename('message')
        if not editor:
            path = os.path.relpath(file)
            raise VexArgument('with what editor?, you can open ./{} directly too'.format(path))
        p.state.set('editor', editor)
    os.execvp(editor, [editor, file])


vex_message_get = vex_message.subcommand('get', 'get commit message')
@vex_message_get.on_run('')
def GetMessage():
    p = open_project()
    if p.state.exists('message'):
        yield p.state.get('message')

vex_message_filename = vex_message.subcommand('filename', 'commit message filename', aliases=['path'])
@vex_message_filename.on_run('')
def MessageFilename():
    p = open_project()
    yield p.state.filename('message')

vex_message_set = vex_message.subcommand('set', 'set commit message')
@vex_message_set.on_run('message')
def SetMessage(message):
    p = open_project()
    with p.lock('message:set') as p:
        p.state.set('message', message)
        yield "set"

vex_template = vex_message.subcommand('template', short="edit commit template")
vex_template_edit = vex_template.subcommand('edit', short='edit commit template')
@vex_template.on_run('--editor')
@vex_template_edit.on_run('--editor')
def EditTemplate(editor):
    p = open_project()
    with p.lock('editor') as p:
        if not editor and p.state.exists('editor'):
            editor = p.state.get('editor')
        if not editor:
            editor = os.environ.get('EDITOR')
        if not editor:
            editor = os.environ.get('VISUAL')
        file = p.settings.filename('template')
        if not editor:
            path = os.path.relpath(file)
            raise VexArgument('with what editor?, you can open ./{} directly too'.format(path))
        p.state.set('editor', editor)
    os.execvp(editor, [editor, file])


vex_template_get = vex_template.subcommand('get', 'get commit template')
@vex_template_get.on_run('')
def GetTemplate():
    p = open_project()
    if p.settings.exists('template'):
        yield p.settings.get('template')

vex_template_filename = vex_template.subcommand('filename', 'commit template filename', aliases=['path'])
@vex_template_filename.on_run('')
def TemplateFilename():
    p = open_project()
    yield p.settings.filename('template')

vex_template_set = vex_template.subcommand('set', 'set commit template')
@vex_template_set.on_run('template')
def SetTemplate(template):
    p = open_project()
    with p.lock('template:set') as p:
        p.settings.set('template', template)
        yield "set"

vex_commit_apply = vex_commit.subcommand('apply', 'apply changes from other branch to current session')
@vex_commit_apply.on_run('branch:branch')
def Apply(branch):
    p = open_project()
    with p.lock('apply') as p:
        if not p.names.exists(branch):
            raise VexArgument('{} doesn\'t exist'.format(branch))
        p.apply_changes_from_branch(branch)

vex_commit_append = vex_commit.subcommand('append', 'append changes from other branch to current session')
@vex_commit_append.on_run('branch:branch')
def Append(branch):
    p = open_project()
    with p.lock('append') as p:
        if not p.names.exists(branch):
            raise VexArgument('{} doesn\'t exist'.format(branch))
        changes = p.append_changes_from_branch(branch)

        if changes:
            for name, entries in changes.items():
                entries = [entry.text for entry in entries]
                name = os.path.relpath(name, p.prefix())
                yield "append: {}, {}".format(', '.join(entries), name)

        else:
            yield 'append: nothing to commit'

vex_commit_replay = vex_commit.subcommand('replay', 'replay changes from other branch to current session')
@vex_commit_replay.on_run('branch:branch')
def Replay(branch):
    p = open_project()
    with p.lock('replay') as p:
        if not p.names.exists(branch):
            raise VexArgument('{} doesn\'t exist'.format(branch))
        p.replay_changes_from_branch(branch)

vex_commit_squash = vex_commit.subcommand('squash', '* flatten commits into one')
@vex_commit_squash.on_run()
def Squash():
    raise VexUnimplemented()

vex_rollback = vex_commit.subcommand('rollback', '* take older version and re-commit it')
@vex_rollback.on_run()
def Rollback():
    raise VexUnimplemented()

vex_revert = vex_commit.subcommand('revert','* new commit without changes made in an old version')
@vex_revert.on_run()
def Revert():
    raise VexUnimplemented()

vex_rewind = vex_cmd_commit.subcommand('rewind','* rewind session to earlier change')
@vex_rewind.on_run()
def Rewind():
    raise VexUnimplemented()

vex_update = vex_cmd_commit.subcommand('update','* update branch to start from new upstream head')
@vex_update.on_run()
def Update():
    raise VexUnimplemented()

# Rollback, Revert, Squash, Update,

vex_cmd_branch = vex_cmd.group('branch')

vex_branch = vex_cmd_branch.subcommand('branch', short="open/create branch")
@vex_branch.on_run('[name:branch]')
def Branch(name):
    """

    """
    p = open_project()
    with p.lock('open') as p:
        if name:
            p.open_branch(name, create=True)
        active = p.active()
        branch = p.branches.get(active.branch)
        yield branch.name

vex_branch_list = vex_branch.subcommand('list', short="list branches")
vex_branches = vex_cmd_branch.subcommand('branches', short="list branches")
@vex_branch_list.on_run()
@vex_branches.on_run()
def Branches():
    p = open_project()
    with p.lock('branches') as p:
        branches = p.list_branches()
        active = p.active()
        for (name, branch) in branches:
            if branch.uuid == active.branch:
                if name:
                    yield "{} *".format(name)
                else:
                    yield "{} *".format(branch.uuid)
            elif name:
                yield name
            else:
                yield branch.uuid

vex_branch_get = vex_branch.subcommand('get', short="get branch info", aliases=["show", "info"])
@vex_branch_get.on_run('[name:branch]')
def BranchInfo(name):
    """

    """
    p = open_project()
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

vex_open = vex_branch.subcommand('open', short="open or create a branch")
@vex_open.on_run('name:branch')
def OpenBranch(name):
    """

    """
    p = open_project()
    with p.lock('open') as p:
        p.open_branch(name, create=False)

vex_new = vex_branch.subcommand('new', short="create a new branch")
@vex_new.on_run('name:branch')
def NewBranch(name):
    """

    """
    p = open_project()
    with p.lock('new') as p:
        if p.names.exists(name):
            raise VexArgument('{} exists'.format(name))
        p.new_branch(name)

vex_saveas = vex_branch.subcommand('saveas', short="save session as a new branch, leaving old one alone")
@vex_saveas.on_run('name:branch')
def SaveAsBranch(name):
    """

    """
    p = open_project()
    with p.lock('saveas') as p:
        if p.names.get(name):
            raise VexArgument('{} exists'.format(name))
        p.save_as(name)
        return name

vex_rename = vex_branch.subcommand('rename', short="rename current branch")
@vex_rename.on_run('name:branch')
def RenameBranch(name):
    """

    """
    p = open_project()
    with p.lock('rename') as p:
        if p.names.get(name):
            raise VexArgument('{} exists'.format(name))
        p.rename_branch(name)

vex_swap = vex_branch.subcommand('swap', short="swap name with another branch")
@vex_swap.on_run('name:branch')
def SwapBranch(name):
    """

    """
    p = open_project()
    with p.lock('swap') as p:
        if not p.names.get(name):
            raise VexArgument("{} doesn't exist".format(name))
        p.swap_branch(name)


vex_diff_branch = vex_diff.subcommand('branch')
vex_branch_diff = vex_branch.subcommand('diff')
argspec= ('''
        [branch:branch] # name of branch to check, defaults to current branch
''')
@vex_diff_branch.on_run(argspec)
@vex_branch_diff.on_run(argspec)
def DiffBranch(branch):
    """
        `vex diff:branch` shows the changes bewtween working copy and a branch
    """
    p = open_project()
    with p.lock('diff') as p:
        if not branch:
            branch = p.active().branch
            branch = p.get_branch(branch)
            commit = branch.base
        else:
            branch = p.get_branch_uuid(branch)
            branch = p.get_branch(branch)
            commit = branch.head


        for name, diff in  p.active_diff_commit(commit).items():
            yield diff

vex_switch = vex_cmd.subcommand('switch', short="change which directory (inside the project) is worked on")
@vex_switch.on_run('[prefix]')
def Switch(prefix):
    """

    """
    p = open_project()
    if os.getcwd() != p.working_dir:
        raise VexArgument("it's best if you don't call this while in a subdirectory")
    if prefix:
        with p.lock('switch') as p:
            prefix = os.path.normpath(os.path.join(p.prefix(), prefix))
            p.switch(prefix)
    else:
        yield p.prefix()

vex_session = vex_cmd_branch.subcommand('session',short="describe the active session for the current branch")
vex_sessions = vex_cmd_branch.subcommand('sessions',short="show all sessions for current branch")

@vex_sessions.on_run()
def Sessions():
    p = open_project()
    with p.lock('sessions') as p:
        sessions = p.list_sessions()
        active = p.active()
        for s in sessions:
            if s.uuid == active.uuid:
                yield "{} *".format(s.uuid)
            else:
                yield s.uuid

# XXX: vex session:open session:new session:attach session:detach session:remove


vex_ignore = vex_cmd_files.subcommand('ignore', short="add ignored files")
vex_ignore_add = vex_ignore.subcommand('add', 'add ignored files')
@vex_ignore.on_run('[file...]')
@vex_ignore_add.on_run('[file...]')
def AddIgnore(file):
    p = open_project()
    if file:
        with p.lock('ignore:add') as p:
            old = p.settings.get('ignore')
            old.extend(file)
            p.settings.set('ignore', old)
    else:
        for entry in p.settings.get('ignore'):
            yield entry


vex_include = vex_cmd_files.subcommand('include', short="add include files")
vex_include_add = vex_include.subcommand('add', 'add include files')
@vex_include.on_run('[file...]')
@vex_include_add.on_run('[file...]')
def AddInclude(file):
    p = open_project()
    if file:
        with p.lock('include:add') as p:
            old = p.settings.get('include')
            old.extend(file)
            p.settings.set('include', old)
    else:
        for entry in p.settings.get('include'):
            yield entry


props_cmd = vex_cmd_files.subcommand('fileprops', short="get/set properties on files", aliases=['props', 'properties', 'property'])
props_list_cmd = props_cmd.subcommand('get', short="list properties")
@props_cmd.on_run('file')
@props_list_cmd.on_run('file')
def ListProps(file):
    p = open_project()
    with p.lock('fileprops:list') as p:
        for key,value in p.get_fileprops(file).items():
            file = os.path.relpath(file)
            yield "{}:{}:{}".format(file, key,value)

props_set_cmd = props_cmd.subcommand('set', short='set property')
@props_set_cmd.on_run('file name value:scalar')
def SetProp(file, name, value):
    p = open_project()
    with p.lock('fileprops:list') as p:
        p.set_fileprop(filename, name, value)


vex_cmd_debug = vex_cmd.group('debug')
vex_debug = vex_cmd_debug.subcommand('debug', 'internal: run a command without capturing exceptions, or repairing errors')
@vex_debug.on_run()
def Debug():
    """
    `vex debug commit` calls `vex commit`, but will always print a full traceback
    and never attempt to recover from incomplete changes.

    use with care.
    """
    yield ('Use vex debug <cmd> to run <cmd>, or use `vex debug:status`')


debug_status = vex_debug.subcommand('status')
@debug_status.on_run()
def DebugStatus():
    p = open_project(check=False)
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
@debug_restart.on_run()
def DebugRestart():
    p = get_project()
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
@debug_rollback.on_run()
def DebugRollback():
    p = get_project()
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
vex_cmd_git = vex_cmd.group('_git')
git_cmd = vex_cmd_git.subcommand('git', short="* interact with a git repository")

def shell(args):
    print('shell:', args)
    p= subprocess.run(args, stdout=subprocess.PIPE, shell=True)
    if p.returncode:
        sys.stdout.write(p.stdout)
        raise Exception('error')
    return p.stdout

class Vex:
    def __init__(self, path, command=()):
        self.path = path
        self.command = command

    def __getattr__(self, name):
        return self.__class__(self.path, self.command+(name,))

    def __call__(self, *args, **kwargs):
        cmd = []
        cmd.append(self.path)
        if self.command:
            cmd.append(":".join(self.command))
        for name, value in kwargs.items():
            if isinstance(value, (list, tuple)):
                for v in value:
                    cmd.append("--{}={}".format(name, v))
            else:
                cmd.append("--{}={}".format(name, value))
        for value in args:
            cmd.append(value)

        p=  subprocess.run(cmd, stdout=subprocess.PIPE)
        if p.returncode:
            sys.stdout.buffer.write(p.stdout)
            raise Exception('Error')
        print("vex {}:".format(" ".join(cmd[1:])))
        for line in p.stdout.splitlines():
            print(">  ", line.decode('utf-8'))

debug_test = vex_debug.subcommand('test', short="self test")
@debug_test.on_run()
def DebugTest():

    vex = Vex(os.path.normpath(os.path.join(os.path.split(os.path.abspath(__file__))[0], "..", "vex")))

    with tempfile.TemporaryDirectory() as dir:
        print("Using:", dir)
        os.chdir(dir)
        shell('mkdir repo')
        dir = os.path.join(dir, 'repo')
        os.chdir(dir)

        vex.init()

        shell('date >> date')
        shell('mkdir -p dir1 dir2 dir3/dir3.1 dir3/dir3.2')
        shell('echo yes >> dir1/a')
        shell('echo yes >> dir1/b')
        shell('echo yes >> dir1/c')

        vex.add()
        vex.commit()

        vex.undo()
        vex.commit.prepare()
        vex.commit.prepared()

        vex.undo()
        vex.undo()
        vex.redo(choice=1)
        vex.log()
        shell('date >> date')
        vex.switch('dir1')
        shell('rm a')
        shell('mkdir a')
        vex.switch('/repo')
        vex.undo()
        vex.redo()
        vex.commit()
        shell('rmdir dir2')
        shell('date >> dir2')
        vex.commit()
        vex.undo()
        vex.branch.saveas('other')
        vex.branch('latest')
        vex.undo()
        vex.commit()
        vex.branch('latest')
        vex.status()

    
debug_soak = vex_debug.subcommand('soak', short="soak test")
@debug_soak.on_run()
def DebugSoak():
    pass

debug_argparse = vex_debug.subcommand('args')
@debug_argparse.on_run('''
    --switch?       # a demo switch
    --value:str     # pass with --value=...
    --bucket:int... # a list of numbers
    pos1            # positional
    [opt1]          # optional 1
    [opt2]          # optional 2
    [tail...]       # tail arg
''')
def run(switch, value, bucket, pos1, opt1, opt2, tail):
    """a demo command that shows all the types of options"""
    return [switch, value, bucket, pos1, opt1, opt2, tail]



vex_cmd.main(__name__)
