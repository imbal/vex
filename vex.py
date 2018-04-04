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

def get_project_directory(start_dir):
    # hunt down .vex
    return os.path.join(start_dir, DOTVEX)

class Codec:
    classes = {}
    def __init__(self):
        self.codec = rson.Codec(self.to_tag, self.from_tag)
    def register(self, cls):
        self.classes[cls.__name__] = cls
        return cls
    def to_tag(self, obj):
        name = obj.__class__.__name__
        if name not in self.classes: raise Exception('bad')
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
    class Init:
        def __init__(self, timestamp, uuid, settings):
            self.timestamp = timestamp
            self.uuid = uuid
            self.settings = settings

    @codec.register
    class Create:
        def __init__(self, base, timestamp, uuid, settings):
            self.base = base
            self.timestamp = timestamp
            self.uuid = uuid

    @codec.register
    class Close:
        def __init__(self, prev, timestamp, reason):
            self.prev = prev
            self.timestamp = timestamp
            self.reason = reason

    @codec.register
    class Update:
        def __init__(self, prev, timestamp, base, settings):
            self.prev = prev
            self.base = base
            self.timestamp = timestamp
            self.settings = settings
    
    @codec.register
    class Prepare:
        def __init__(self, prev, timestamp, changelog):
            self.prev = prev
            self.timestamp = timestamp
            self.changelog = changelog
    
    @codec.register
    class Commit:
        def __init__(self, prev, timestamp, root, changelog):
            self.prev = prev
            self.timestamp = timestamp
            self.root = root
            self.changelog = changelog

    @codec.register
    class Revert:
        def __init__(self, prev, timestamp, root, changelog):
            self.prev = prev
            self.timestamp = timestamp
            self.root = root
            self.changelog = changelog

    @codec.register
    class Amend:
        def __init__(self, prev, timestamp, root, changelog):
            self.prev = prev
            self.timestamp = timestamp
            self.root = root
            self.changelog = changelog

    # Revert
    # Apply


    @codec.register
    class Purge:
        pass

    @codec.register
    class Truncate:
        pass

    @codec.register
    class Changelog:
        def __init__(self, changes, older):
            self.changes = changes
            self.older = older

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
        def __init__(self, time, command, changes=()):
            self.time = time
            self.command = command
            self.changes = changes

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

    def put_buf(self, buf):
        addr = self.addr_for_buf(buf)
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


class HistoryStore:
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
        self.settings.set("last", self.START)

    def last(self):
        return self.settings.get("last")

    @contextmanager
    def do(self, action):
        obj = objects.Do(self.last(), action)
        addr = self.store.put_obj(obj)
        yield action
        self.settings.set("last", addr) 

    @contextmanager
    def undo(self):
        last = self.last()
        if last == self.START:
            yield None
            return

        obj = self.store.get_obj(last)

        if self.redos.exists(last):
            next = self.redos.get(last)
        else:
            next = None
        dos = [last] 
        if obj.prev and self.redos.exists(obj.prev):
            dos.extend(self.redos.get(obj.prev).dos) 
        redo = objects.Redo(next, dos)
        yield obj.action
        new_next = self.redos.set(obj.prev, redo)
        self.settings.set("last", obj.prev)

    def entries(self):
        last = self.last()
        out = []
        while last != self.START:
            obj = self.store.get_obj(last)
            redos = ()
            if self.redos.exists(last):
                redos = [self.store.get_obj(x).action.command for x in self.redos.get(last).dos]
            out.append((obj.action, redos))
            last = obj.prev

        return out

    @contextmanager
    def redo(self, n=0):
        last = self.last()

        if not self.redos.exists(last):
            yield None
            return

        next = self.redos.get(last)

        do = next.dos.pop(n)

        obj = self.store.get_obj(do)
        redo = objects.Redo(next.next, next.dos)
        yield obj.action
        self.redos.set(last, redo)
        self.settings.set("last", do)

    def redo_choices(self):
        last = self.last()

        if not self.redos.exists(last):
            return

        next = self.redos.get(last)

        if next is None:
            return
        out = []
        for do in next.dos:
            obj = self.store.get_obj(do)
            out.append(obj.action)
        return out

class Transaction:
    def __init__(self, project, command):
        self.project = project
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

    def current_session(self):
        return self.project.sessions.get(self.project.state.get('session'))

    def put_change(self, obj):
        return self.project.changes.put_obj(obj)

    def get_branch(self, uuid):
        return self.project.branches.get(uuid)
    
    def put_session(self, session):
        if session.uuid not in self.old_sessions:
            if self.project.sessions.exists(session.uuid):
                self.old_sessions[session.uuid] = self.project.sessions.get(session.uuid)
            else:
                self.old_sessions[session.uuid] = None
        self.new_sessions[session.uuid] = session

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

    def set_state(self, name, value):
        if name not in self.old_state:
            if self.project.state.exists(name):
                self.old_state[name] = self.project.state.get(name)
            else:
                self.old_state[name] = None
        self.new_state[name] = value

    def action(self):
        branches = dict(old=self.old_branches, new=self.new_branches)
        names = dict(old=self.old_names, new=self.new_names)
        sessions = dict(old=self.old_sessions, new=self.new_sessions)
        state = dict(old=self.old_state, new=self.new_state)
        changes = dict(branches=branches,names=names, sessions=sessions, state=state)
        return objects.Action(self.now, self.command, changes)

class Project:
    def __init__(self, dir):    
        self.dir = dir
        blobs = os.path.join(dir, 'blobs')
        self.changes = BlobStore(os.path.join(blobs, 'changes'))
        self.manifests = BlobStore(os.path.join(blobs, 'manifests'))
        self.files = BlobStore(os.path.join(blobs, 'files'))
        self.branches = DirStore(os.path.join(dir, 'branches'))
        self.names = DirStore(os.path.join(dir, 'branches', 'names'))
        self.sessions = DirStore(os.path.join(dir, 'sessions'))
        self.state = DirStore(os.path.join(dir, 'state'))
        self.history_log = HistoryStore(os.path.join(dir, 'history'))
        self.lockfile = os.path.join(dir, 'lock')

    def makedirs(self):
        os.makedirs(self.dir, exist_ok=True)
        self.changes.makedirs()
        self.manifests.makedirs()
        self.files.makedirs()
        self.sessions.makedirs()
        self.branches.makedirs()
        self.names.makedirs()
        self.state.makedirs()
        self.history_log.makedirs()

    def exists(self):
        return os.path.exists(self.dir)

    def uncreated(self):
        return self.history_log.last() == self.history_log.START

    @contextmanager
    def _lock(self):
        try:
            with open(self.lockfile, 'wb+') as fh:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield
        except (IOError, FileNotFoundError):
            raise Exception('lock')

    @contextmanager
    def do(self, command):
        txn = Transaction(self, command)
        yield txn
        action = txn.action()

        with self._lock(), self.history_log.do(action):
            if not action:
                return
            for key in action.changes:
                if key == 'branches':
                    for name,value in action.changes['branches']['new'].items():
                        self.branches.set(name, value)
                elif key == 'names':
                    for name,value in action.changes['names']['new'].items():
                        self.names.set(name, value)
                elif key == 'sessions':
                    for name,value in action.changes['sessions']['new'].items():
                        self.sessions.set(name, value)
                elif key == 'state':
                    for name,value in action.changes['state']['new'].items():
                        self.state.set(name, value)
                else:
                    raise Exception('unknown')

    def undo(self):
        with self._lock(), self.history_log.undo() as action:
            if not action:
                return

            for key in action.changes:
                if key == 'branches':
                    for name,value in action.changes['branches']['old'].items():
                        self.branches.set(name, value)
                elif key == 'names':
                    for name,value in action.changes['names']['old'].items():
                        self.names.set(name, value)
                elif key == 'sessions':
                    for name,value in action.changes['sessions']['old'].items():
                        self.sessions.set(name, value)
                elif key == 'state':
                    for name,value in action.changes['state']['old'].items():
                        self.state.set(name, value)
                else:
                    raise Exception('unknown')

    def redo(self, choice):
        with self._lock(), self.history_log.redo(choice) as action:
            if not action:
                return
            for key in action.changes:
                if key == 'branches':
                    for name,value in action.changes['branches']['new'].items():
                        self.branches.set(name, value)
                elif key == 'names':
                    for name,value in action.changes['names']['new'].items():
                        self.names.set(name, value)
                elif key == 'sessions':
                    for name,value in action.changes['sessions']['new'].items():
                        self.sessions.set(name, value)
                elif key == 'state':
                    for name,value in action.changes['state']['new'].items():
                        self.state.set(name, value)
                else:
                    raise Exception('unknown')

    def redo_choices(self):
        return self.history_log.redo_choices()

    def init(self, prefix, options):
        self.makedirs()
        if not self.uncreated():
            return None
        with self.do('init') as txn:
            branch_uuid = UUID()
            branch_name = 'latest'
            commit = objects.Init(txn.now, branch_uuid, {})
            commit_uuid = txn.put_change(commit)

            branch = objects.Branch(branch_uuid, commit_uuid, None, branch_uuid)
            txn.put_branch(branch)
            txn.set_name(branch_name, branch) 

            session_uuid = UUID()
            session = objects.Session(session_uuid, prefix, branch_uuid, commit_uuid, commit_uuid)
            txn.put_session(session)

            txn.set_state("session", session_uuid)

    def history(self):
        return self.history_log.entries()

    def log(self):
        session_uuid = self.state.get("session")
        session = self.sessions.get(session_uuid)
        commit = session.prepare
        out = []
        while commit != session.commit:
            obj = self.changes.get_obj(commit)
            out.append('*uncommitted* {}: {}'.format(obj.__class__.__name__, commit))
            commit = getattr(obj, 'prev', None)

        while commit != None:
            obj = self.changes.get_obj(commit)
            out.append('committed {}: {}'.format(obj.__class__.__name__, commit))
            commit = getattr(obj, 'prev', None)
        return out

    def prepare(self, files):
        with self.do('prepare') as txn:
            session = txn.current_session()
            commit = session.prepare

            prepare = objects.Prepare(commit, txn.now, None)
            prepare_uuid = txn.put_change(prepare)

            session.prepare = prepare_uuid
            txn.put_session(session)

    def commit(self, files):
        with self.do('commit') as txn:
            session = txn.current_session()

            commit = objects.Commit(session.prepare, txn.now, None, None)
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

    def status(self):
        out = []
        session_uuid = self.state.get("session")
        if session_uuid and self.sessions.exists(session_uuid):
            session = self.sessions.get(session_uuid)
            out.append("session: {}".format(session_uuid))
            out.append("at {}, started at {}".format(session.prepare, session.commit))

            branch = self.branches.get(session.branch)
            out.append("commiting to branch {}".format(branch.uuid))

            commit = self.changes.get_obj(session.prepare)
            out.append("last commit: {}".format(commit.__class__.__name__))
        else:
            if self.uncreated():
                out.append("you undid the creation. try vex redo")
            else:
                out.append("no active session, but history, weird")
        out.append("")
        return "\n".join(out)


    def add(self, files):
        # get current session
        # get head commit
        # create a change entry
        # 
        # set prepare
        pass

    def ignore(self, files):
        # set prepare
        pass

    def remove(self, files):
        # set prepare
        pass



vex_cmd = Command('vex', 'a database for files')
vex_init = vex_cmd.subcommand('init')
@vex_init.run('[directory]')
def Init(directory):
    directory = directory or os.getcwd()
    directory = os.path.join(directory, DOTVEX)
    p = Project(directory)
    if p.exists() and not p.uncreated():
        print('A vex project already exists here')
    else:
        print('Creating vex project in "{}"...'.format(directory))
        p.init('/prefix', {})

vex_prepare = vex_cmd.subcommand('prepare')
@vex_prepare.run('[files...]')
def Prepare(files):
    directory = get_project_directory(os.getcwd())
    p = Project(directory)
    print('Preparing')
    p.prepare(files)

vex_commit = vex_cmd.subcommand('commit')
@vex_commit.run('[files...]')
def Commit(files):
    directory = get_project_directory(os.getcwd())
    p = Project(directory)
    print('Committing')
    p.commit(files)

vex_log = vex_cmd.subcommand('log')
@vex_log.run()
def Log():
    directory = get_project_directory(os.getcwd())
    p = Project(directory)
    for entry in p.log():
        print(entry)
        print()

vex_history = vex_cmd.subcommand('history')
@vex_history.run()
def History():
    directory = get_project_directory(os.getcwd())
    p = Project(directory)
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
    directory = get_project_directory(os.getcwd())
    p = Project(directory)
    print(p.status())

vex_undo = vex_cmd.subcommand('undo')
@vex_undo.run()
def Undo():
    directory = get_project_directory(os.getcwd())
    p = Project(directory)
    action = p.undo()
    if action:
        print('undid', action.command)
    if p.uncreated():
        print('vex project uninitalised')

vex_redo = vex_cmd.subcommand('redo')
@vex_redo.run('--list? --choice')
def Redo(list, choice):
    directory = get_project_directory(os.getcwd())
    p = Project(directory)
    if list:
        choices = p.redo_choices()
        if choices:
            for n, choice in enumerate(choices):
                print(n, choice.time, choice.command)
    else:
        choice = choice or 0
        action = p.redo(choice)
        if action:
            print('redid', action.command)

vex_debug = vex_cmd.subcommand('debug')

debug_nop = vex_debug.subcommand('nop')

vex_cmd.main(__name__)
