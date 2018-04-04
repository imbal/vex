#!/usr/bin/env python3
import sqlite3
import os.path
import os
import shutil
import hashlib
from datetime import datetime, timezone
from uuid import uuid4

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
        def __init__(self, old, timestamp, new):
            self.old = old
            self.timestamp = timestamp
            self.new = new

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
        def __init__(self,uuid, prefix, branch, head, base, mode=None, state=None):
            self.uuid = uuid
            self.prefix = prefix
            self.branch = branch
            self.head = head
            self.base = base
            self.mode = mode
            self.state = state

    @codec.register
    class Branch:
        def __init__(self, uuid, head, base, upstream):
            self.uuid = uuid
            self.head = head
            self.base = base
            self.upstream = upstream

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

    def get(self, name):
        with open(self.filename(name), 'rb') as fh:
            return codec.parse(fh.read())

    def put(self, name, value):
        with open(self.filename(name),'w+b') as fh:
            fh.write(codec.dump(value))





class Project:
    def __init__(self, dir):    
        self.dir = dir
        self.store = BlobStore(os.path.join(dir, 'blobs'))
        self.sessions = DirStore(os.path.join(dir, 'sessions'))
        self.branches = DirStore(os.path.join(dir, 'branches'))
        self.names = DirStore(os.path.join(dir, 'branches', 'names'))
        self.state = DirStore(os.path.join(dir, 'state'))

    def makedirs(self):
        os.makedirs(self.dir, exist_ok=True)
        self.store.makedirs()
        self.sessions.makedirs()
        self.branches.makedirs()
        self.names.makedirs()
        self.state.makedirs()

    def init(self, options):
        self.makedirs()
        branch_uuid = UUID()
        prefix = '/latest'
        branch_name = 'latest'
        commit = objects.Init(NOW(), branch_uuid, {})
        commit_uuid = self.store.put_obj(commit)

        branch = objects.Branch(branch_uuid, commit_uuid, None, branch_uuid)
        self.branches.put(branch_uuid, branch)
        self.names.put(branch_name, branch_uuid)

        session_uuid = UUID()
        session = objects.Session(session_uuid, prefix, branch_uuid, commit_uuid, commit_uuid)
        self.sessions.put(session_uuid, session)

        self.state.put("session", session_uuid)

    def log(self):
        session_uuid = self.state.get("session")
        session = self.sessions.get(session_uuid)
        commit = session.head
        out = []
        while commit:
            obj = self.store.get_obj(commit)
            out.append('{}: {}'.format(obj.__class__.__name__, commit))
            commit = getattr(obj, 'prev', None)

        return out

    def prepare(self, files):
        session_uuid = self.state.get("session")
        session = self.sessions.get(session_uuid)
        commit = session.head
        # create changelog

        prepare = objects.Prepare(commit, NOW(), None)
        prepare_uuid = self.store.put_obj(prepare)

        session.head = prepare_uuid
        self.sessions.put(session_uuid, session)

    def commit(self, files):
        session_uuid = self.state.get("session")
        session = self.sessions.get(session_uuid)
        old_commit = session.head
        # create changelog

        commit = objects.Commit(old_commit, NOW(), None, None)
        commit_uuid = self.store.put_obj(commit)

        session.head = commit_uuid
        self.sessions.put(session_uuid, session)
        branch_uuid = session.branch

        branch = self.branches.get(branch_uuid)
        if branch.head != session.base:
            print('branch has diverged, not applying commit')
        else:
            branch.head = commit_uuid
            self.branches.put(branch_uuid, branch)
        print('done')
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


    @property
    def blobs(self):
        return


vex_cmd = Command('vex', 'a database for files')
vex_init = vex_cmd.subcommand('init')
@vex_init.run('[directory]')
def Init(directory):
    directory = directory or os.getcwd()
    directory = os.path.join(directory, DOTVEX)
    print(directory)
    p = Project(directory)
    print('Creating vex project in "{}"...'.format(directory))
    p.init({})

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


vex_cmd.main(__name__)
