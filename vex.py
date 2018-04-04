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
        def __init__(self, prefix, branch, head, base, mode=None, state=None):
            self.mode = mode
            self.state = state
            self.prefix = prefix
            self.head = head
            self.base = base
            self.branch = branch

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
        with open(self.filename(addr), 'b'):
            return parse(fh.read())

class Sessions:
    def __init__(self, dir):
        self.dir = dir

    def makedirs(self):
        os.makedirs(self.dir, exist_ok=True)

    def all(self):
        pass
    def active(self):
        pass

class Branches:
    def __init__(self, dir):
        self.dir = dir

    def makedirs(self):
        os.makedirs(self.dir, exist_ok=True)

    def all(self):
        pass

    def get(self, name):
        pass

    def create(self, name, commit, base, upstream):
        pass

    def delete(self, name):
        pass

    def rename(self, old_name, new_name):
        pass

    def update(self, name, new):
        pass



class Project:
    def __init__(self, dir):    
        self.dir = dir
        self.store = BlobStore(os.path.join(dir, 'blobs'))
        self.sessions = Sessions(os.path.join(dir, 'sessions'))
        self.branches = Branches(os.path.join(dir, 'branches'))

    def makedirs(self):
        os.makedirs(self.dir, exist_ok=True)
        self.store.makedirs()
        self.sessions.makedirs()
        self.branches.makedirs()

    @property
    def session(self):
        pass

    def init(self, options):
        self.makedirs()
        branch_uuid = UUID()
        prefix = '/latest'
        branch_name = 'latest'
        commit = objects.Init(NOW(), branch_uuid, {})
        commit_uuid = self.store.put_obj(commit)
        branch = objects.Branch(branch_uuid, commit_uuid, commit_uuid, branch_uuid)
        session = objects.Session(prefix, branch_uuid, commit_uuid, commit_uuid)

        # create project directory
        # create blobstore, session, branch directory
        # create initial commit
        # create branch 'latest'
        # create session 0 on branch latest
        pass


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

    def prepare(self):
        # find changed files
        # create changelog
        # add to store
        # set prepare in session
        pass

    def commit(self, message):
        # prepare
        # find parent commit from prepare in session
        # build up history file of changes
        # create a commit record 
        # add it to the store
        # find the branch of the current session
        # update the branch to point to this commit
        pass

    def log(self):
        # find current prepare, branch start
        # go back until session start point
        # go back until branch start
        return ()

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

vex_commit = vex_cmd.subcommand('commit')
@vex_commit.run('[files....]')
def Commit(files):
    directory = get_project_directory(os.getcwd())
    p = Project(directory)
    print('Committing')
    p.commit()

vex_log = vex_cmd.subcommand('log')
@vex_log.run()
def Log():
    directory = get_project_directory(os.getcwd())
    p = Project(directory)
    for entry in p.log():
        print(entry)
        print()


vex_cmd.main(__name__)
