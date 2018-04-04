#!/usr/bin/env python3
import sqlite3
import os.path
import os
import shutil
import hashlib
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



class HistoryStore:
    def __init__(self, dir):
        self.dir = dir
        self.store = BlobStore(os.path.join(dir,'entries'))
        self.redos = DirStore(os.path.join(dir,'redos' ))
        self.settings = DirStore(dir)

    def makedirs(self):
        os.makedirs(self.dir, exist_ok=True)
        self.store.makedirs()
        self.redos.makedirs()
        self.settings.set("last", None)

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
        if last is None:
            yield None
        obj = self.store.get_obj(last)

        if self.redos.exists(last):
            next = self.redos.get(last)
        else:
            next = None
        dos = [last] 
        if self.redos.exists(obj.prev):
            dos.extend(self.redos.get(obj.prev).dos) 
        redo = objects.Redo(next, dos)
        yield obj.action
        new_next = self.redos.set(obj.prev, redo)
        self.settings.set("last", obj.prev)

    def entries(self):
        last = self.last()
        out = []
        while last != None:
            obj = self.store.get_obj(last)
            out.append(obj.action)
            last = obj.prev

        return out

    @contextmanager
    def redo(self, n=0):
        last = self.last()
        if last is None:
            yield None
            return

        if not self.redos.exists(last):
            yield None
            return

        next = self.redos.get(last)

        if next is None:
            yield None
            return

        do = next.dos[n]


        obj = self.store.get_obj(do)
        yield obj.action
        self.settings.set("last", do)

    def redo_choices(self):
        last = self.last()
        if last is None:
            return None

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
        self.project.sessions.set(session.uuid, session)

    def put_branch(self, branch):
        self.project.branches.set(branch.uuid, branch)

    def set_name(self, name, branch):
        self.project.names.set(name, branch.uuid)

    def set_state(self, name, value):
        self.project.state.set(name, value)

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

    @contextmanager
    def transaction(self, command):
        txn = Transaction(self, command)
        yield txn
        action = txn.action()

        with self.history_log.do(action):
            pass

    def history(self):
        return self.history_log.entries()

    def undo(self):
        with self.history_log.undo() as action:
            return action

    def redo(self, choice):
        with self.history_log.redo(choice) as action:
            return action

    def redo_choices(self):
        return self.history_log.redo_choices()

    def init(self, prefix, options):
        self.makedirs()
        with self.transaction('init') as txn:
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
        with self.transaction('prepare') as txn:
            session = txn.current_session()
            commit = session.prepare

            prepare = objects.Prepare(commit, txn.now, None)
            prepare_uuid = txn.put_change(prepare)

            session.prepare = prepare_uuid
            txn.put_session(session)

    def commit(self, files):
        with self.transaction('commit') as txn:
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
        session_uuid = self.state.get("session")
        session = self.sessions.get(session_uuid)

        commit = self.changes.get_obj(session.prepare)

        branch = self.branches.get(session.branch)
        return "\n".join([
            "session: {}".format(session_uuid),
            "at {}, started at {}".format(session.prepare, session.commit),
            "commiting to branch {}".format(branch.uuid),
            "last commit: {}".format(commit.__class__.__name__),
            "",
        ])


    def add(self, files):
        # get current session
        # get head commit
        # create a change entry
        # 
        # add an update with it inside
        # set prepare
        pass

    def ignore(self, files):
        # add an update
        # set prepare
        pass

    def remove(self, files):
        # add an update
        pass



vex_cmd = Command('vex', 'a database for files')
vex_init = vex_cmd.subcommand('init')
@vex_init.run('[directory]')
def Init(directory):
    directory = directory or os.getcwd()
    directory = os.path.join(directory, DOTVEX)
    p = Project(directory)
    if p.exists():
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
    print('done')

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
    for entry in p.history():
        print(entry.time, entry.command)
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

vex_redo = vex_cmd.subcommand('redo')
@vex_redo.run('--list? --choice')
def Redo(list, choice):
    directory = get_project_directory(os.getcwd())
    p = Project(directory)
    if list:
        choices = p.redo_choices()
        if choices:
            for n, choice in enumerate(choices):
                print(n, choice.command)
    else:
        choice = choice or 0
        action = p.redo(choice)
        if action:
            print('redid', action.command)
vex_cmd.main(__name__)
