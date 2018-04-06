#!/usr/bin/env python3
import sqlite3
import os.path
import os
import shutil
import hashlib
import fcntl
from datetime import datetime, timezone
from uuid import uuid4
from contextlib import contextmanager

from cli import Command
import rson

def UUID(): return str(uuid4())
def NOW(): return datetime.now(timezone.utc)
DOTVEX = '.vex'

class VexError(Exception): pass

class VexBug(VexError): pass

class VexCorrupt(VexError): pass

class VexMissing(VexError): pass

class VexEmpty(VexError): pass

class VexUnclean(VexError): pass

class Codec:
    classes = {}
    def __init__(self):
        self.codec = rson.Codec(self.to_tag, self.from_tag)
    def register(self, cls):
        self.classes[cls.__name__] = cls
        return cls
    def to_tag(self, obj):
        name = obj.__class__.__name__
        if name not in self.classes: raise VexBug('An {} object cannot be turned into RSON'.format(name))
        return name, obj.__dict__
    def from_tag(self, tag, value):
        return self.classes[tag](**value)
    def dump(self, obj):
        return self.codec.dump(obj).encode('utf-8')
    def parse(self, buf):
        return self.codec.parse(buf.decode('utf-8'))

codec = Codec()

class objects:
    @codec.register
    class Start:
        def __init__(self,n, timestamp, *, root, uuid, changelog):
            self.n = n
            self.timestamp = timestamp
            self.uuid = uuid
            self.root = root
            self.changelog = changelog

    @codec.register
    class Fork:
        def __init__(self, n, timestamp, *, base, uuid, changelog):
            self.n =n
            self.base = base
            self.timestamp = timestamp
            self.uuid = uuid
            self.changelog = changelog

    @codec.register
    class Stop:
        def __init__(self, n, timestamp, *, prev, uuid, changelog):
            self.n =n
            self.prev = prev
            self.timestamp = timestamp
            self.uuid = uuid
            self.changelog = changelog

    @codec.register
    class Restart:
        def __init__(self, n,timestamp, *, prev, base, changelog):
            self.n =n
            self.prev = prev
            self.base = base
            self.timestamp = timestamp
            self.changelog = changelog
    
    @codec.register
    class Prepare:
        def __init__(self, n, timestamp, *, prev, changes):
            self.n =n
            self.prev = prev
            self.timestamp = timestamp
            self.changes = changes
    
    @codec.register
    class Commit:
        def __init__(self, n, timestamp, *, prev, root, changelog):
            self.n =n
            self.prev = prev
            self.timestamp = timestamp
            self.root = root
            self.changelog = changelog

    @codec.register
    class Amend:
        def __init__(self, n, timestamp, *, prev, root, changelog):
            self.n =n
            self.prev = prev
            self.timestamp = timestamp
            self.root = root
            self.changelog = changelog

    @codec.register
    class Revert:
        def __init__(self, n, timestamp, *, prev, root, changelog):
            self.n =n
            self.prev = prev
            self.timestamp = timestamp
            self.root = root
            self.changelog = changelog


    @codec.register
    class Apply:
        def __init__(self, n, timestamp, *, prev, src, root, uuid, changelog):
            self.n =n
            self.prev = prev
            self.src=src
            self.timestamp = timestamp
            self.root = root
            self.uuid = uuid
            self.changelog = changelog
    # Apply


    @codec.register
    class Purge:
        pass

    @codec.register
    class Truncate:
        pass

    @codec.register
    class Changelog:
        def __init__(self, prev, changes):
            self.changes = changes
            self.prev = prev
    @codec.register
    class AddFile:
        def __init__(self, filename, timestamp, message): 
            self.timestamp = timestamp
            self.filename = filename
            self.message = message

    # Add File, Remove File, 
    # Manifest
    
    @codec.register
    class Tree:
        def __init__(self, contents):
            self.contents = contents

    @codec.register
    class TreeEntry:
        pass

    @codec.register
    class BlobList:
        pass

    # No types for Files, stored directly

    # Non Blob store:
    
    @codec.register
    class Session:
        def __init__(self,uuid, prefix, branch, prepare, commit, mode=None, state=None):
            self.uuid = uuid
            self.prefix = prefix
            self.branch = branch
            self.prepare = prepare
            self.commit = commit
            self.mode = mode
            self.state = state

    @codec.register
    class Branch:
        def __init__(self, uuid, head, base, upstream):
            self.uuid = uuid
            self.head = head
            self.base = base
            self.upstream = upstream

    @codec.register
    class Action:
        def __init__(self, time, command, changes=(), blobs=()):
            self.time = time
            self.command = command
            self.changes = changes
            self.blobs = blobs

    @codec.register
    class Do:
        def __init__(self, prev, action):
            self.prev = prev
            self.action = action

    @codec.register
    class Redo:
        def __init__(self, next, dos):
            self.next = next
            self.dos = dos

    @codec.register
    class WorkingCopy:
        def __init__(self, session, branch, prefix, files):
            self.session = session
            self.branch = branch
            self.prefix = prefix
            self.files = files

    @codec.register
    class WorkingFile:
        def __init__(self, state, path):
            self.state = state
            self.path = path

# Stores

class DirStore:
    def __init__(self, dir):
        self.dir = dir

    def makedirs(self):
        os.makedirs(self.dir, exist_ok=True)
    def filename(self, name):
        return os.path.join(self.dir, name)
    def all(self):
        return os.listdir(self.dir())
    def exists(self, addr):
        return os.path.exists(self.filename(addr))
    def get(self, name):
        with open(self.filename(name), 'rb') as fh:
            return codec.parse(fh.read())
    def set(self, name, value):
        with open(self.filename(name),'w+b') as fh:
            fh.write(codec.dump(value))



class BlobStore:
    def __init__(self, dir):
        self.dir = dir

    def makedirs(self):
        os.makedirs(self.dir, exist_ok=True)

    def move_from(self, other, addr):
        if other.exists(addr) and not self.exists(addr):
            src, dest = other.filename(addr), self.filename(addr)
            os.rename(src, dest)
        elif not self.exists(addr):
            raise VexCorrupt('Missing file {}'.format(other.filename(addr)))

    def addr_for_file(self, file):
        hash = hashlib.shake_256()
        with open(file,'b') as fh:
            hash.update(fh.read())
        return "shake-256-20-{}".format(hash.hexdigest(20))

    def addr_for_buf(self, buf):
        hash = hashlib.shake_256()
        hash.update(buf)
        return "shake-256-20-{}".format(hash.hexdigest(20))

    def filename(self, addr):
        return os.path.join(self.dir, addr)

    def exists(self, addr):
        return os.path.exists(self.filename(addr))

    def put_file(self, file):
        addr = self.addr_for_file(file)
        shutil.copyfile(file, self.filename(addr))
        return addr

    def put_buf(self, buf, addr=None):
        addr = addr or self.addr_for_buf(buf)
        with open(self.filename(addr), 'xb') as fh:
            fh.write(buf)
        return addr

    def put_obj(self, obj):
        buf = codec.dump(obj)
        return self.put_buf(buf)

    def get_file(self, addr):
        return self.filename(addr)

    def get_obj(self, addr):
        with open(self.filename(addr), 'rb') as fh:
            return codec.parse(fh.read())


class ActionLog:
    START = 'init'
    def __init__(self, dir):
        self.dir = dir
        self.store = BlobStore(os.path.join(dir,'entries'))
        self.redos = DirStore(os.path.join(dir,'redos' ))
        self.settings = DirStore(dir)

    def makedirs(self):
        os.makedirs(self.dir, exist_ok=True)
        self.store.makedirs()
        self.redos.makedirs()
        self.settings.set("current", self.START)
        self.settings.set("next", self.START)

    def empty(self):
        return self.current() == self.START

    def clean_state(self):
        if self.settings.exists("current") and self.settings.exists("next"):
            return self.settings.get("current") == self.settings.get("next")

    def current(self):
        return self.settings.get("current")

    def entries(self):
        current = self.current()
        out = []
        while current != self.START:
            obj = self.store.get_obj(current)
            redos = ()
            if self.redos.exists(current):
                redos = [self.store.get_obj(x).action.command for x in self.redos.get(current).dos]
            out.append((obj.action, redos))
            current = obj.prev

        return out


    @contextmanager
    def do(self, action):
        if not self.clean_state():
            raise VexCorrupt('Project history not in a clean state.')
        obj = objects.Do(self.current(), action)

        addr = self.store.put_obj(obj)
        self.settings.set("next", addr) 

        yield action

        self.settings.set("current", addr) 

    @contextmanager
    def undo(self):
        if not self.clean_state():
            raise VexCorrupt('Project history not in a clean state.')
        current = self.current()
        if current == self.START:
            yield None
            return

        obj = self.store.get_obj(current)

        if self.redos.exists(current):
            next = self.redos.get(current)
        else:
            next = None
        dos = [current] 
        if obj.prev and self.redos.exists(obj.prev):
            dos.extend(self.redos.get(obj.prev).dos) 
        redo = objects.Redo(next, dos)
        self.settings.set("next", obj.prev) 

        yield obj.action

        new_next = self.redos.set(obj.prev, redo)
        self.settings.set("current", obj.prev)

    @contextmanager
    def redo(self, n=0):
        if not self.clean_state():
            raise VexCorrupt('Project history not in a clean state.')
        current = self.current()

        if not self.redos.exists(current):
            yield None
            return

        next = self.redos.get(current)

        do = next.dos.pop(n)

        obj = self.store.get_obj(do)
        redo = objects.Redo(next.next, next.dos)
        self.settings.set("next", do) 

        yield obj.action

        self.redos.set(current, redo)
        self.settings.set("current", do)

    @contextmanager
    def rollback_new(self):
        if self.clean_state():
            yield
            return

        next = self.settings.get("next")
        obj = self.store.get_obj(next)
        old_current = obj.prev
        current = self.settings.get("current")
        if current != old_current:
            raise VexCorrupt('History is really corrupted: Interrupted transaction did not come after current change')
        yield obj.action
        self.settings.set("next", current)

    @contextmanager
    def restart_new(self):
        if self.clean_state():
            yield
            return
        next = self.settings.get("next")
        obj = self.store.get_obj(next)
        old_current = obj.prev
        current = self.settings.get("current")
        if current != old_current:
            raise VexCorrupt('History is really corrupted: Interrupted transaction did not come after current change')
        yield obj.action
        self.settings.set("current", next)


    def redo_choices(self):
        current = self.current()

        if not self.redos.exists(current):
            return

        next = self.redos.get(current)

        if next is None:
            return
        out = []
        for do in next.dos:
            obj = self.store.get_obj(do)
            out.append(obj.action)
        return out

        
class StateChange:
    def __init__(self, project, command):
        self.project = project
        self.command = command
        self.now = NOW()
        self.old_state = {}
        self.new_state = {}

    def get_change(self, uuid):
        return self.project.changes.get_obj(uuid)

    def get_branch(self, uuid):
        return self.project.changes.get_obj(uuid)

    def get_session(self, uuid):
        return self.project.changes.get_obj(uuid)

    def set_working_copy(self, value):
        name = "working"
        if name not in self.old_state:
            if self.project.state.exists(name):
                self.old_state[name] = self.project.state.get(name)
            else:
                self.old_state[name] = None
        self.new_state[name] = value

    def working_copy(self):
        return self.project.working_copy()

    def current_session(self):
        return self.project.sessions.get(self.working_copy().session)

    def action(self):
        if self.new_state:
            changes = dict(state=dict(old=self.old_state, new=self.new_state))
            return objects.Action(self.now, self.command, changes, ())
        else:
            return objects.Action(self.now, self.command, {}, ())

    def build_working_copy(self, session, prefix):
        s = self.sessions.get(session)
        branch= s.branch
        return objects.WorkingCopy(session, branch, prefix, files)

    def refresh_working_copy(self, old):
        pass

class ProjectChange:
    working_copy = StateChange.working_copy
    set_working_copy = StateChange.set_working_copy
    current_session = StateChange.current_session

    def __init__(self, project, scratch, command):
        self.project = project
        self.scratch = scratch
        self.command = command
        self.now = NOW()
        self.old_branches = {}
        self.new_branches = {}
        self.old_names = {}
        self.new_names = {}
        self.old_sessions = {}
        self.new_sessions = {}
        self.old_state = {}
        self.new_state = {}
        self.new_changes = set()
        self.new_manifests = set()
        self.new_files = set()


    def get_change(self, addr):
        if addr in self.new_changes:
            return self.scratch.get_obj(addr)
        return self.project.changes.get_obj(addr)

    def put_change(self, obj):
        addr = self.scratch.put_obj(obj)
        self.new_changes.add(addr)
        return addr

    def put_session(self, session):
        if session.uuid not in self.old_sessions:
            if self.project.sessions.exists(session.uuid):
                self.old_sessions[session.uuid] = self.project.sessions.get(session.uuid)
            else:
                self.old_sessions[session.uuid] = None
        self.new_sessions[session.uuid] = session

    def get_branch(self, uuid):
        if uuid in self.new_branches:
            return self.new_branches[uuid]

        return self.project.branches.get(uuid)

    def put_branch(self, branch):
        if branch.uuid not in self.old_branches:
            if self.project.branches.exists(branch.uuid):
                self.old_branches[branch.uuid] = self.project.branches.get(branch.uuid)
            else:
                self.old_branches[branch.uuid] = None

        self.new_branches[branch.uuid] = branch

    def set_name(self, name, branch):
        if name not in self.old_names:
            if self.project.names.exists(name):
                self.old_names[name] = self.project.names.get(name)
            else:
                self.old_names[name] = None
        self.new_names[name] = branch.uuid

    def next_commit_number(self, old_obj, new_kind):
        n = old_obj.n
        if new_kind in ("prepare", "amend"):
            return n
        return n+1

    def action(self):
        if self.new_branches or self.new_names or self.new_sessions or self.new_state or self.new_changes or self.new_manfiests or self.new_files:
            branches = dict(old=self.old_branches, new=self.new_branches)
            names = dict(old=self.old_names, new=self.new_names)
            sessions = dict(old=self.old_sessions, new=self.new_sessions)
            state = dict(old=self.old_state, new=self.new_state)

            blobs = dict(changes=self.new_changes, manifests=self.new_manifests, files=self.new_files, prepared={})
            changes = dict(branches=branches,names=names, sessions=sessions, state=state)
            return objects.Action(self.now, self.command, changes, blobs)
        else:
            return objects.Action(self.now, self.command, {}, ())

class Project:
    def __init__(self, config_dir, working_dir):    
        self.working_dir = working_dir
        self.dir = config_dir
        blobs = os.path.join(config_dir, 'blobs')
        self.changes = BlobStore(os.path.join(blobs, 'changes'))
        self.manifests = BlobStore(os.path.join(blobs, 'manifests'))
        self.files = BlobStore(os.path.join(blobs, 'files'))
        self.branches = DirStore(os.path.join(config_dir, 'branches'))
        self.names = DirStore(os.path.join(config_dir, 'branches', 'names'))
        self.sessions = DirStore(os.path.join(config_dir, 'sessions'))
        self.state = DirStore(os.path.join(config_dir, 'state'))
        self.lockfile = os.path.join(config_dir, 'lock')
        self.actions = ActionLog(os.path.join(config_dir, 'history'))
        self.scratch = BlobStore(os.path.join(config_dir, 'scratch'))

    def makedirs(self):
        os.makedirs(self.dir, exist_ok=True)
        self.changes.makedirs()
        self.manifests.makedirs()
        self.files.makedirs()
        self.sessions.makedirs()
        self.branches.makedirs()
        self.names.makedirs()
        self.state.makedirs()
        self.actions.makedirs()
        self.scratch.makedirs()

    def exists(self):
        return os.path.exists(self.dir)

    __locked = object()

    @contextmanager
    def lock(self, command):
        try:
            with open(self.lockfile, 'wb+') as fh:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fh.truncate(0)
                fh.write(b'# locked by %d at %a\n'%(os.getpid(), str(NOW())))
                fh.write(codec.dump(command))
                fh.write(b'\n')
                fh.flush()
                yield self
                fh.write(b'# released by %d %a\n'%(os.getpid(), str(NOW())))
        except (IOError, FileNotFoundError):
            raise VexError('Cannot open project lockfile: {}'.format(self.lockfile))

    def clean_state(self):
        return self.actions.clean_state()

    def rollback_new_action(self):
        with self.actions.rollback_new() as action:
            if action:
                self.apply_changes('old', action.changes)
            return action

    def restart_new_action(self):
        with self.actions.restart_new() as action:
            if action:
                self.copy_blobs(action.blobs)
                self.apply_changes('new', action.changes)
            return action

    @contextmanager
    def do_nohistory(self, command):
        txn = StateChange(self, command)
        yield txn
        action = txn.action()
        if action.changes:
            self.apply_changes('new', {'state': action.changes['state']})

    @contextmanager
    def do(self, command):
        if not self.actions.clean_state():
            raise VexCorrupt('Project history not in a clean state.')

        txn = ProjectChange(self, self.scratch, command)
        yield txn
        with self.actions.do(txn.action()) as action:
            if not action:
                return
            self.copy_blobs(action.blobs)
            self.apply_changes('new', action.changes)

    # Take Action.changes and applies them to project
    def apply_changes(self, kind, changes):
        for key in changes:
            if key == 'branches':
                for name,value in changes['branches'][kind].items():
                    self.branches.set(name, value)
            elif key == 'names':
                for name,value in changes['names'][kind].items():
                    self.names.set(name, value)
            elif key == 'sessions':
                for name,value in changes['sessions'][kind].items():
                    self.sessions.set(name, value)
            elif key == 'state':
                for name,value in changes['state'][kind].items():
                    self.state.set(name, value)
            else:
                raise VexBug('Project change has unknown values')

    # Takes Action.blobs and copies them out of the scratch directory
    def copy_blobs(self, blobs):
        for key in blobs:
            if key == 'changes':
                for addr in blobs['changes']:
                    self.changes.move_from(self.scratch, addr)
            elif key == 'manifests':
                for addr in blobs['manifests']:
                    self.manifests.move_from(self.scratch, addr)
            elif key =='files':
                for addr in blobs['files']:
                    self.files.move_from(self.scratch, addr)
            elif key == 'prepared':
                pass
            else:
                raise VexBug('Project change has unknown values')

    def undo(self):
        with self.actions.undo() as action:
            if not action:
                return
            self.apply_changes('old', action.changes)

    def redo(self, choice):
        with self.actions.redo(choice) as action:
            if not action:
                return
            self.apply_changes('old', action.changes)

    def redo_choices(self):
        return self.actions.redo_choices()

    def history_isempty(self):
        return self.actions.empty()

    def history(self):
        return self.actions.entries()

    def working_copy(self):
        return self.state.get("working")

    def log(self):
        with self.do_nohistory() as txn:
            session = txn.current_session()

        commit = session.prepare
        out = []
        while commit != session.commit:
            obj = self.changes.get_obj(commit)
            out.append('{}: *uncommitted* {}: {}'.format(obj.n, obj.__class__.__name__, commit))
            commit = getattr(obj, 'prev', None)
            # print \t date, file, message

        while commit != None:
            obj = self.changes.get_obj(commit)
            out.append('{}: committed {}: {}'.format(obj.n, obj.__class__.__name__, commit))
            commit = getattr(obj, 'prev', None)
        return out



    def status(self):
        with self.do_nohistory('status') as txn:
            out = {}
            working_copy = txn.working_copy()
        for filename, entry in working_copy.files.items():
            filename = os.path.relpath(filename, working_copy.prefix)
            out[filename] = entry
        return out
        

    def init(self, prefix, options):
        self.makedirs()
        if not self.history_isempty():
            return None
        with self.do('init') as txn:
            branch_uuid = UUID()
            branch_name = 'latest'
            # root = objects.Tree
            root = None
            commit = objects.Start(0, txn.now, uuid=branch_uuid, changelog=None, root=None)
            commit_uuid = txn.put_change(commit)

            branch = objects.Branch(branch_uuid, commit_uuid, None, branch_uuid)
            txn.put_branch(branch)
            txn.set_name(branch_name, branch) 

            session_uuid = UUID()
            session = objects.Session(session_uuid, prefix, branch_uuid, commit_uuid, commit_uuid)
            txn.put_session(session)

            txn.set_working_copy(objects.WorkingCopy(session_uuid, branch_uuid, os.path.join('/',prefix), {}))

    def prepare(self, files):
        with self.do('prepare') as txn:
            session = txn.current_session()
            commit = session.prepare

            old = txn.get_change(commit)
            n = txn.next_commit_number(old, 'prepare')
            prepare = objects.Prepare(n, txn.now, prev=commit, changes=[])
            prepare_uuid = txn.put_change(prepare)

            session.prepare = prepare_uuid
            txn.put_session(session)

    def commit(self, files):
        with self.do('commit') as txn:
            session = txn.current_session()

            old = txn.get_change(session.prepare)
            n = txn.next_commit_number(old, 'commit')
            commit = objects.Commit(n, txn.now, prev=session.prepare, root=None, changelog=None)
            commit_uuid = txn.put_change(commit)

            branch = txn.get_branch(session.branch)
            if branch.head != session.commit: # descendent check
                print('branch has diverged, not applying commit')
            else:
                branch.head = commit_uuid
                txn.put_branch(branch)
            session.prepare = commit_uuid
            session.commit = commit_uuid
            txn.put_session(session)

    def add(self, files):
        with self.do('add') as txn:
            working_copy = txn.working_copy()
            names = {}
            for filename in files:
                if not filename.startswith(self.working_dir):
                    raise VexError("{} is outside project".format(filename))
                name = os.path.join(working_copy.prefix, os.path.relpath(filename, self.working_dir))
                names[name] = filename
                for name, filename in names.items():
                    if name in working_copy.files:

                        working_copy.files[name] = objects.WorkingFile("modified", filename)
                    else:
                        working_copy.files[name] = objects.WorkingFile("added", filename)
                txn.set_working_copy(working_copy)

    def ignore(self, files):
        # set prepare
        pass

    def remove(self, files):
        # set prepare
        pass

def get_project(check=True):
    working_dir = os.getcwd()
    while True:
        config_dir = os.path.join(working_dir, DOTVEX)
        if os.path.exists(config_dir):
            break
        new_working_dir = os.path.split(working_dir)[0]
        if new_working_dir == working_dir:
            raise VexMissing('No vex project found in {}'.format(os.getcwd()))
        working_dir = new_working_dir
    p = Project(config_dir, working_dir)
    if check:
        if p.history_isempty():
            raise VexEmpty('Vex project exists, but `vex init` has not been run (or has been undone)')
        elif not p.clean_state(): 
            raise VexUnclean('Another change is already in progress. Try `vex debug:status`')
    return p

# CLI bits. Should handle environs, cwd, etc
vex_cmd = Command('vex', 'a database for files')
@vex_cmd.on_error()
def Error(path, args, exception, traceback):
    message = str(exception)
    if path:
        print("{}: {}".format(':'.join(path), message))
    else:
        print("vex: {}".format(message))

    if not isinstance(exception, VexError):
        print()
        print("Worse still, it's an error vex doesn't recognize yet. A python traceback follows:")
        print()
        print(traceback)

    p = get_project(check=False)

    if p.exists() and not p.clean_state():
        p.rollback_new_action()

        if not p.clean_state():
            print('This is bad: The project history is corrupt, try `vex debug:status` for more information')
        else:
            print('Good news: The changes that were attempted have been undone')


vex_init = vex_cmd.subcommand('init')
@vex_init.run('--working --config --prefix [directory]')
def Init(directory, working, config, prefix):
    working_dir = working or directory or os.getcwd()
    config_dir = config or os.path.join(working_dir, DOTVEX)
    prefix = prefix or os.path.split(working_dir)[1] or '/root'

    p = Project(config_dir, working_dir)

    if p.exists() and not p.clean_state():
        print('This vex project is unwell. Try `vex debug:status`')
    elif p.exists():
        if not p.history_isempty():
            print('A vex project already exists here')
            sys.exit(-1)
        else:
            print('A empty project was round, re-creating project in "{}"...'.format(directory))
            with p.lock('init') as p:
                p.init(prefix, {})
    else:
        print('Creating vex project in "{}"...'.format(directory))
        p.init(prefix, {})

vex_add = vex_cmd.subcommand('add','add files to the project')
@vex_add.run('[file...]')
def Add(file):
    p = get_project()
    with p.lock('add') as p:
        cwd = os.getcwd()
        files = [os.path.join(cwd, f) for f in file]
        p.add(files)


vex_prepare = vex_cmd.subcommand('prepare')
@vex_prepare.run('[files...]')
def Prepare(files):
    p = get_project()
    print('Preparing')
    with p.lock('prepare') as p:
        p.prepare(files)

vex_commit = vex_cmd.subcommand('commit')
@vex_commit.run('[files...]')
def Commit(files):
    p = get_project()
    print('Committing')
    with p.lock('commit') as p:
        p.commit(files)

vex_log = vex_cmd.subcommand('log')
@vex_log.run()
def Log():
    p = get_project()
    for entry in p.log():
        print(entry)
        print()

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

        print(entry.time, entry.command,alternative)
        print()

vex_status = vex_cmd.subcommand('status')
@vex_status.run()
def Status():
    p = get_project()
    with p.lock('status') as p:
        for filename, entry in p.status().items():
            path = os.path.relpath(entry.path)

            print(entry.state, filename, sep='\t')

vex_undo = vex_cmd.subcommand('undo')
@vex_undo.run()
def Undo():
    p = get_project()

    with p.lock('undo') as p:
        action = p.undo()
    if action:
        print('undid', action.command)

vex_redo = vex_cmd.subcommand('redo')
@vex_redo.run('--list? --choice')
def Redo(list, choice):
    p = get_project()

    with p.lock('redo') as p:
        choices = p.redo_choices()

        if list:
            if choices:
                for n, choice in enumerate(choices):
                    print(n, choice.time, choice.command)
            else:
                print('Nothing to redo')
        elif choices:
            choice = choice or 0
            action = p.redo(choice)
            if action:
                print('redid', action.command)
        else:
            print('Nothing to redo')

vex_debug = vex_cmd.subcommand('debug', 'run a command without capturing exceptions')
@vex_debug.run()
def Debug():
    print('Use vex debug <cmd> to run <cmd>, or use `vex debug:status`')

debug_status = vex_debug.subcommand('status')
@debug_status.run()
def DebugStatus():
    p = get_project(check=False)
    with p.lock('debug:status') as p:
        print("Clean history", p.clean_state())
        working_copy = p.working_copy()
        session_uuid = working_copy.session
        out = []

        if session_uuid and p.sessions.exists(session_uuid):
            session = p.sessions.get(session_uuid)
            out.append("session: {}".format(session_uuid))
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
            print('There is no change in progress to restart')
            return
        print('Restarting current action...')
        p.restart_new_action()
        if p.clean_state():
            print('Project has recovered')
        else:
            print('Oh dear')

debug_rollback = vex_debug.subcommand('rollback')
@debug_rollback.run()
def DebugRollback():
    p = get_project(check=False)
    with p.lock('debug:rollback') as p:
        if p.clean_state():
            print('There is no change in progress to rollback')
            return
        print('Rolling back current action...')
        p.rollback_new_action()
        if p.clean_state():
            print('Project has recovered')
        else:
            print('Oh dear')

vex_cmd.main(__name__)
