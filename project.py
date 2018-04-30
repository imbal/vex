#!/usr/bin/env python3
"""
    vex - a database for files

    this file depends on rson.py for serialization
    and is included in vex.py

    this file contains:

    - objects
        commits, changelogs, things written to and from disk
    - stores
        things to store the objects on disk
    - history
        a transactional-ish log of items 
    - transaction
        a class that represents changes to the project
        physical: old, new values of entire object
        logical: smaller updates to objects
    - project
        a class that wires up everything,
        a method inside will:
            ask for a transaction
            perform changes without applying them to project
            tell the history it is about to do something
            apply those changes
"""
import os
import fcntl
import time
import shutil
import sqlite3
import fnmatch
import os.path
import hashlib
import subprocess
import unicodedata

from datetime import datetime, timezone
from uuid import uuid4
from contextlib import contextmanager

import rson

def UUID(): return str(uuid4())
def NOW(): return datetime.now(timezone.utc)

# If you check a last modified time, it should be reasonably in the past
# if too close to current time, may miss any current modificatons

MTIME_GRACE_SECONDS = 0.5

class VexError(Exception): pass

# Should not happen: bad state reached internally
# always throws exception

class VexBug(Exception): pass
class VexCorrupt(Exception): pass

# Can happen: bad environment/arguments
class VexLock(Exception): pass
class VexArgument(VexError): pass

# Recoverable State Errors
class VexNoProject(VexError): pass
class VexNoHistory(VexError): pass
class VexUnclean(VexError): pass

class VexUnimplemented(VexError): pass


class LockFile:
    def __init__(self, lockfile):
        self.lockfile = lockfile

    def makelock(self):
        with open(self.lockfile, 'xb') as fh:
            fh.write(b'# created by %d at %a\n'%(os.getpid(), str(NOW())))

    @contextmanager
    def __call__(self, command):
        try:
            fh = open(self.lockfile, 'wb')
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, FileNotFoundError):
            raise VexLock('Cannot open project lockfile: {}'.format(self.lockfile))
        try:
            fh.truncate(0)
            fh.write(b'# locked by %d at %a\n'%(os.getpid(), str(NOW())))
            fh.write("{}".format(command).encode('utf-8'))
            fh.write(b'\n')
            fh.flush()
            yield self
            fh.write(b'# released by %d %a\n'%(os.getpid(), str(NOW())))
        finally:
            fh.close()

class Codec:
    def __init__(self):
        self.classes = {}
        self.literals = {}
        self.codec = rson.Codec(self.to_tag, self.from_tag)
    def register(self, cls):
        if cls.__name__ in self.classes or cls.__name__ in self.literals:
            raise VexBug('Duplicate wire type')
        self.classes[cls.__name__] = cls
        return cls
    def register_literal(self, cls):
        if cls.__name__ in self.classes or cls.__name__ in self.literals:
            raise VexBug('Duplicate wire type')
        self.literals[cls.__name__] = cls
        return cls
    def to_tag(self, obj):
        name = obj.__class__.__name__
        if name in self.literals:
            return name, next(iter(obj.__dict__.values()))
        if name not in self.classes: raise VexBug('An {} object cannot be turned into RSON'.format(name))
        return name, obj.__dict__
    def from_tag(self, tag, value):
        if tag in self.literals:
            return self.literals[tag](value)
        return self.classes[tag](**value)
    def dump(self, obj):
        return self.codec.dump(obj).encode('utf-8')
    def parse(self, buf):
        return self.codec.parse(buf.decode('utf-8'))

codec = Codec()

class objects:

    @codec.register
    class Commit:
        Kinds = set("""
            init prepare commit amend
            purge truncate
            apply 
        """.split())
        def __init__(self, kind, timestamp, *, previous, ancestors, root, changeset):
            self.kind = kind
            self.timestamp = timestamp
            self.previous = previous
            self.ancestors = ancestors
            self.root = root
            self.changeset = changeset


    # Manfest Objects: Directories and entries
    @codec.register
    class Root:
        def __init__(self, entries, properties):
            self.entries = entries
            self.properties = properties

    @codec.register
    class Tree:
        def __init__(self, entries):
            self.entries = entries

    # Entries in a Tree Object
    # properties used to indicate 'large file' , 'large dir' options, ...
    # large dir is 'take this tree but treat it as a tree of prefixes...'
    # large file is 'addr points to  tree but it's list of @Chunks

    @codec.register
    class Dir:
        def __init__(self, addr,  properties):
            self.addr = addr
            self.properties = properties

    @codec.register
    class File:
        def __init__(self, addr, properties):
            self.addr = addr
            self.properties = properties

    @codec.register
    class Chunk:
        def __init__(self, addr):
            self.addr = addr

    @codec.register
    class Changeset:
        def __init__(self, entries, *, author=None, message=None):
            self.author = author
            self.message = message
            self.entries = entries

        def append_changes(self, changeset):
            for name, changes in changeset.items():
                if name not in self.entries:
                    self.entries[name] = []
                self.entries[name].extend(changes)

        def prepend_changes(self, changeset):
            for name, changes in changeset.items():
                if name not in self.entries:
                    self.entries[name] = []
                for change in changes:
                    self.entries[name].insert(0, change)

        def items(self):
            return self.entries.items()

        def __bool__(self):
            return bool(self.entries)

    # changeset entries

    @codec.register
    class AddFile:
        text = "added file"
        def __init__(self, addr, properties):
            self.addr = addr
            self.properties = properties

    @codec.register
    class NewFile:
        text = "replaced with file"
        def __init__(self, addr, properties):
            self.addr = addr
            self.properties = properties

    @codec.register
    class DeleteFile:
        text = "deleted file"
        def __init__(self):
            pass

    @codec.register
    class ChangeFile:
        text = "changed file"
        def __init__(self, addr, properties):
            self.properties = properties
            self.addr = addr

    @codec.register
    class AddDir:
        text = "added directory"
        def __init__(self, properties):
            self.properties = properties

    @codec.register
    class NewDir:
        text = "replaced with directory"
        def __init__(self, properties):
            self.properties = properties
    @codec.register
    class DeleteDir:
        text= "deleted directory"
        def __init__(self):
            pass

    @codec.register
    class ChangeDir:
        text = "changed directory"
        def __init__(self, addr, properties):
            self.properties = properties
            self.addr = addr

    # End of Repository State

    # Transaction state

    @codec.register
    class Action:
        def __init__(self, time, command, changes=(), blobs=(), working=()):
            self.time = time
            self.command = command
            self.changes = changes
            self.blobs = blobs
            self.working = working

    @codec.register
    class Switch:
        def __init__(self, time, command, prefix, active, session_states, branch_states, names):
            self.time = time
            self.command = command
            self.prefix = prefix
            self.active = active
            self.session_states = session_states
            self.branch_states = branch_states 
            self.names = names

    # Working copy state

    @codec.register
    class Branch:
        States = set(('created', 'active','inactive','merged', 'closed'))
        def __init__(self, uuid, name, state, prefix, head, base, init, upstream, sessions):
            if not (uuid and state and head and init): raise Exception('no')
            if state not in self.States: raise Exception('no')
            self.uuid = uuid
            self.state = state
            self.prefix = prefix
            self.name = name
            self.head = head
            self.base = base
            self.init = init
            self.upstream = upstream
            self.sessions = sessions

    @codec.register
    class Session:
        States = set(('attached', 'detached', 'manual', 'update')) 
        def __init__(self,uuid, branch, state, prefix, prepare, commit, files):
            if not (uuid and branch and prepare and commit): raise Exception('no')
            if state not in self.States: raise Exception('no')
            self.uuid = uuid
            self.branch = branch
            self.prepare = prepare
            self.prefix = prefix
            self.commit = commit
            self.files = files
            self.state = state

    @codec.register
    class Tracked:
        Kinds = set(('dir', 'file', 'ignore', 'stash'))
        States = set(('tracked', 'replaced', 'added', 'modified', 'deleted'))
        Unchanged = set(('tracked'))
        Changed = set(('added', 'modified', 'deleted', 'replaced'))

        def __init__(self, kind, state, *, working=False, addr=None, stash=None, size=None, mode=None, mtime=None, properties=None, replace=None):
            if kind not in self.Kinds: raise VexBug('bad')
            if state not in self.States: raise VexBug('bad')
            self.kind = kind
            self.state = state
            self.working = working
            self.addr = addr
            self.mtime = mtime
            self.size = size
            self.mode = mode
            self.stash = stash
            self.properties = properties
            self.replace = replace

        def set_property(self, name, value):
            self.properties[name] = value
            if self.state == 'tracked':
                self.state = 'modified'

        def refresh(self, path, addr_for_file):
            if self.kind == "file":
                if not os.path.exists(path):
                    self.state = "deleted"
                    self.kind = self.replace or self.kind
                    self.addr, self.properties = None, None
                elif os.path.isdir(path):
                    if not self.replace: self.replace = self.kind
                    self.state = "replaced"
                    self.kind = "dir"
                elif self.state == 'deleted':
                    pass
                elif self.state == 'tracked':
                    modified = False
                    now = time.time()
                    stat = os.stat(path)
                    old_mtime = self.mtime

                    if self.mtime != None and (self.mtime < stat.st_mtime):
                        modified=True
                    elif self.size != None and (self.size != stat.st_size):
                        modified = True
                    elif self.mode != None and (self.mode != stat.st_mode):
                        modified = True
                    elif self.mtime is None or self.mode is None or self.size is None:
                        new_addr = addr_for_file(path)
                        if new_addr != self.addr:
                            modified = True
                        else:
                            self.mode = stat.st_mode
                            self.size = stat.st_size
                            if now - stat.st_mtime >= MTIME_GRACE_SECONDS:
                                self.mtime = stat.st_mtime
                            if stat.st_mode & 64:
                                self.properties['vex:executable'] = True
                            elif 'vex:executable' in self.properties:
                                self.properties.pop('vex:executable')

                    if modified:
                        self.state = "modified"
                        self.mode = stat.st_mode
                        self.size = stat.st_size
                        if stat.st_mode & 64:
                            self.properties['vex:executable'] = True
                        elif 'vex:executable' in self.properties:
                            self.properties.pop('vex:executable')
                        if now - stat.st_mtime >= MTIME_GRACE_SECONDS:
                            self.mtime = stat.st_mtime
                elif self.state in ('modified', 'added', 'replaced'):
                    stat = os.stat(path)
                    self.mode = stat.st_mode
                    self.size = stat.st_size
                    if stat.st_mode & 64:
                        self.properties['vex:executable'] = True
                    elif 'vex:executable' in self.properties:
                        self.properties.pop('vex:executable')
                else:
                    raise VexBug('welp')
            elif self.kind == "dir":
                if not os.path.exists(path):
                    self.kind = self.replace or self.kind
                    self.state = "deleted"
                    self.properties = None
                elif os.path.isfile(path):
                    self.state = "replaced"
                    if not self.replace: self.replace = self.kind
                    self.kind = "file"
                    self.properties = {}
                    self.addr = None
                elif self.state == 'added' or self.state =='replaced':
                    pass
                elif self.state == 'deleted':
                    pass
                elif self.state == 'modified':
                    pass
                elif self.state == 'tracked':
                    pass
                else:
                    raise VexBug('welp')
            elif self.kind == "ignore":
                pass

# Filename patterns

def match_filename(path, name, ignore, include):
    if ignore:
        if isinstance(ignore, str): ignore = ignore,
        for rule in ignore:
            if '**' in rule:
                raise VexUnimplemented()
            elif rule.startswith('/'):
                if rule == path:
                    return False
            elif fnmatch.fnmatch(name, rule):
                return False

    if include:
        if isinstance(include, str): include = include,
        for rule in include:
            if '**' in rule:
                raise VexUnimplemented()
            elif rule.startswith('/'):
                if rule == path:
                    return True
            elif fnmatch.fnmatch(name, rule):
                return True
def file_diff(name, old, new):
    # XXX Pass properties
    a,b = os.path.join('./a',name[1:]), os.path.join('./b', name[1:])
    p = subprocess.run(["diff", '-u', '--label', a, '--label', b, old, new], stdout=subprocess.PIPE)
    return p.stdout


def list_dir(dir, ignore, include):
    output = []
    scan = [dir]
    while scan:
        dir = scan.pop()
        for f in os.listdir(dir):
            p = os.path.join(dir, f)
            if not match_filename(p, f, ignore, include): continue
            if os.path.isdir(p):
                output.append(p)
                scan.append(p)
            elif os.path.isfile(p):
                output.append(p)
    return output
# Stores

class FileStore:
    def __init__(self, dir, codec):
        self.codec = codec
        self.dir = dir
    def makedirs(self):
        os.makedirs(self.dir, exist_ok=True)
    def filename(self, name):
        return os.path.join(self.dir, name)
    def list(self):
        for name in os.listdir(self.dir):
            if os.path.isfile(self.filename(name)):
                yield name
    def exists(self, addr):
        return os.path.exists(self.filename(addr))
    def get(self, name):
        if not self.exists(name):
            return None
        with open(self.filename(name), 'rb') as fh:
            return self.codec.parse(fh.read())
    def set(self, name, value):
        with open(self.filename(name),'w+b') as fh:
            fh.write(self.codec.dump(value))

class BlobStore:
    prefix = "vex:"
    def __init__(self, dir, codec):
        self.dir = dir
        self.codec = codec

    def hashlib(self):
        return hashlib.shake_256()

    def prefixed_addr(self, hash):
        return "{}{}".format(self.prefix, hash.hexdigest(20))

    def makedirs(self):
        os.makedirs(self.dir, exist_ok=True)

    def copy_from(self, other, addr):
        if other.exists(addr) and not self.exists(addr):
            src, dest = other.filename(addr), self.filename(addr)
            os.makedirs(os.path.split(dest)[0], exist_ok=True)
            shutil.copyfile(src, dest)
        elif not self.exists(addr):
            raise VexCorrupt('Missing file {}'.format(other.filename(addr)))

    def move_from(self, other, addr):
        if other.exists(addr) and not self.exists(addr):
            src, dest = other.filename(addr), self.filename(addr)
            os.makedirs(os.path.split(dest)[0], exist_ok=True)
            os.rename(src, dest)
        elif not self.exists(addr):
            raise VexCorrupt('Missing file {}'.format(other.filename(addr)))

    def make_copy(self, addr, dest):
        filename = self.filename(addr)
        shutil.copyfile(filename, dest)

    def addr_for_file(self, file):
        hash = self.hashlib()
        with open(file,'rb') as fh:
            buf = fh.read(4096)
            while buf:
                hash.update(buf)
                buf = fh.read(4096)
        return self.prefixed_addr(hash)


    def inside(self, file):
        return os.path.commonpath((file, self.dir)) == self.dir

    def addr_for_buf(self, buf):
        hash = self.hashlib()
        hash.update(buf)
        return self.prefixed_addr(hash)

    def filename(self, addr):
        if not addr.startswith(self.prefix):
            raise VexBug('bug')
        addr = addr[len(self.prefix):]
        return os.path.join(self.dir, addr[:2], addr[2:])

    def exists(self, addr):
        return os.path.exists(self.filename(addr))

    def put_file(self, file, addr=None):
        addr = addr or self.addr_for_file(file)
        if not self.exists(addr):
            filename = self.filename(addr)
            os.makedirs(os.path.split(filename)[0], exist_ok=True)
            shutil.copyfile(file, filename)
        return addr

    def put_buf(self, buf, addr=None):
        addr = addr or self.addr_for_buf(buf)
        if not self.exists(addr):
            filename = self.filename(addr)
            os.makedirs(os.path.split(filename)[0], exist_ok=True)
            with open(filename, 'xb') as fh:
                fh.write(buf)
        return addr

    def put_obj(self, obj):
        buf = self.codec.dump(obj)
        return self.put_buf(buf)

    def get_file(self, addr):
        return self.filename(addr)

    def get_obj(self, addr):
        with open(self.filename(addr), 'rb') as fh:
            return self.codec.parse(fh.read())


# History: Used to track undo/redo and changes to repository state

class HistoryStore:
    def __init__(self, file):
        self.file = file
        self._db = None
    
    @property
    def db(self):
        if self._db:
            return self._db
        self._db = sqlite3.connect(self.file)
        return self._db

    def makedirs(self):
        c = self.db.cursor()
        c.execute('''
            create table if not exists dos(
                addr text primary key,
                prev text not null, 
                timestamp datetime default current_timestamp,
                action text)
        ''')
        c.execute('''
            create table if not exists redos(
                addr text primary key,
                dos text not null)
        ''')
        c.execute('''
            create table if not exists next(
                id INTEGER PRIMARY KEY CHECK (id = 0) default 0,
                mode text not null,
                value text not null,
                current text)
        ''')
        c.execute('''
            create table if not exists current (
                id INTEGER PRIMARY KEY CHECK (id = 0) default 0,
                value text not null)
        ''')
        self.db.commit()

    def exists(self):
        if os.path.exists(self.file):
            c = self.db.cursor()
            c.execute('''SELECT name FROM sqlite_master WHERE name='current' ''')
            if bool(c.fetchone()):
                return bool(self.current())

    def current(self):
        c = self.db.cursor() 
        c.execute('select value from current where id = 0')
        row = c.fetchone()
        if row:
            return codec.parse(row[0])

    def next(self):
        c = self.db.cursor() 
        c.execute('select mode, value, current from next where id = 0')
        row = c.fetchone()
        if row:
            return str(row[0]), str(row[1]), str(row[2])

    def set_current(self, value):
        if not value: raise Exception()
        c = self.db.cursor() 
        buf = codec.dump(value)
        c.execute('update current set value = ? where id = 0', [buf])
        c.execute('insert or ignore into current (id,value) values (0,?)',[buf])
        self.db.commit()

    def set_next(self, mode, value, current):
        c = self.db.cursor() 
        c.execute('update next set mode = ?, value=?, current = ? where id = 0', [mode, value, current])
        c.execute('insert or ignore into next (id,mode, value,current) values (0,?,?,?)',[mode, value, current])
        self.db.commit()

    def get_entry(self, addr):
        c = self.db.cursor() 
        c.execute('select prev, action from dos where addr = ?', [addr])
        row = c.fetchone()
        if row:
            return (str(row[0]),codec.parse(row[1]))

    def put_entry(self, prev, obj):
        c=self.db.cursor()
        buf = codec.dump(obj)
        addr = UUID().split('-',1)[0]
        c.execute('insert into dos (addr, prev, action) values (?,?,?)',[addr, prev, buf])
        self.db.commit()
        return addr

    def get_redos(self, addr):
        c = self.db.cursor() 
        c.execute('select dos from redos where addr = ?', [addr])
        row = c.fetchone()
        if row and row[0]:
            row = str(row[0]).split(",")
            return row
        return []

    def set_redos(self, addr, redo):
        c = self.db.cursor() 
        buf = ",".join(redo) if redo else ""
        c.execute('update redos set dos = ? where addr = ?', [buf, addr])
        self.db.commit()
        c.execute('insert or ignore into redos (addr,dos) values (?,?)',[addr, buf])
        self.db.commit()

class History:
    START = 'init'
    Modes = set(('init', 'do', 'undo', 'redo', 'quiet'))
    def __init__(self, dir):
        self.store = HistoryStore(dir)

    def makedirs(self):
        self.store.makedirs()
        self.store.set_current(self.START)
        self.store.set_next('init', self.START, None)

    def empty(self):
        return self.store.exists() and self.store.current() in (self.START,)

    def clean_state(self):
        if self.store.exists():
            if self.store.current():
                return self.store.current() == self.store.next()[1]

    def entries(self):
        current = self.store.current()
        out = []
        while current != self.START:
            prev, obj = self.store.get_entry(current)
            redos = [self.store.get_entry(x)[1] for x in self.store.get_redos(current)]
            out.append((obj, redos))
            current = prev

        return out

    @contextmanager
    def do_without_undo(self, action):
        if not self.clean_state():
            raise VexCorrupt('Project history not in a clean state.')
        current = self.store.current()
        addr = self.store.put_entry(current, action)
        self.store.set_next('quiet', addr , current)

        yield action

        self.store.set_next('do', current, current)

    @contextmanager
    def do(self, obj):
        if not self.clean_state():
            raise VexCorrupt('Project history not in a clean state.')
        current = self.store.current()

        addr = self.store.put_entry(current, obj)
        self.store.set_next('do', addr,current)

        yield obj

        self.store.set_current(addr)

    @contextmanager
    def undo(self):
        if not self.clean_state():
            raise VexCorrupt('Project history not in a clean state.')
        current = self.store.current()
        if current == self.START:
            yield None
            return

        prev, obj = self.store.get_entry(current)

        redos = [current]
        redos.extend(self.store.get_redos(prev))
        self.store.set_next('undo', prev, current)

        yield obj

        self.store.set_redos(prev, redos)
        self.store.set_current(prev)

    @contextmanager
    def redo(self, n=0):
        if not self.clean_state():
            raise VexCorrupt('Project history not in a clean state.')
        current = self.store.current()

        redos = self.store.get_redos(current)

        if not redos:
            yield None
            return

        do = redos.pop(n)

        prev, obj = self.store.get_entry(do)
        self.store.set_next('redo', do, current)

        yield obj

        self.store.set_redos(current, redos)
        self.store.set_current(do)

    @contextmanager
    def rollback_new(self):
        if self.clean_state():
            yield
            return

        mode, next, old_current = self.store.next()
        if mode not in self.Modes:
            raise VexCorupt('Real bad')
        if mode == 'undo' or not old_current:
            raise VexBug('no')
        prev, obj = self.store.get_entry(next)
        current = self.store.current()
        if current != old_current:
            raise VexCorrupt('History is really corrupted: Interrupted transaction did not come after current change')
        yield mode, obj
        self.store.set_next('rollback', old_current, None)

    @contextmanager
    def restart_new(self):
        if self.clean_state():
            yield
            return
        mode, next, old_current = self.next()
        if mode not in self.Modes:
            raise VexCorupt('Real bad')
        if mode == 'undo' or not old_current:
            raise VexBug('no')
        prev, obj = self.store.get_entry(next)
        current = self.store.current()
        if current != old_current:
            raise VexCorrupt('History is really corrupted: Interrupted transaction did not come after current change')
        yield mode, obj
        if mode == 'quiet':
            self.store.set_next('restart', old_current, None)
        else:
            self.store.set_current(['restart', next, None])


    def redo_choices(self):
        current = self.store.current()

        redos = self.store.get_redos(current)

        out = []
        for do in redos:
            prev, obj = self.store.get_entry(do)
            out.append(obj)
        return out

class PhysicalTransaction:
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
        self.old_settings = {}
        self.new_settings = {}
        self.new_commits = set()
        self.new_manifests = set()
        self.new_files = set()
        self.new_working = {}
        self.old_working = {}

    def active(self):
        return self.get_session(self.active_uuid)

    def prefix(self):
        return self.get_state("prefix")

    def repo_to_full_path(self, file):
        return self.project.repo_to_full_path(self.prefix(),file)

    def full_to_repo_path(self, file):
        return self.project.full_to_repo_path(self.prefix(),file)

    def addr_for_file(self, file):
        return self.project.addr_for_file(file)

    def active(self):
        session_uuid = self.get_state("active")
        return self.get_session(session_uuid)

    def get_file(self, addr):
        if addr in self.new_files:
            return self.project.get_scratch_file(addr)
        return self.project.get_file(addr)

    def put_file(self, file):
        addr = self.project.put_scratch_file(file)
        self.new_files.add(addr)
        return addr

    def get_manifest(self, addr):
        if addr in self.new_manifests:
            return self.project.get_scratch_manifest(addr)
        return self.project.get_manifest(addr)

    def put_manifest(self, obj):
        addr = self.project.put_scratch_manifest(obj)
        self.new_manifests.add(addr)
        return addr

    def get_commit(self, addr):
        if addr in self.new_commits:
            return self.project.get_scratch_commit(addr)
        return self.project.get_commit(addr)

    def put_commit(self, obj):
        addr = self.project.put_scratch_commit(obj)
        self.new_commits.add(addr)
        return addr

    def get_session(self, uuid):
        if uuid in self.new_sessions:
            return self.new_sessions[uuid]
        return self.project.sessions.get(uuid)

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

    def get_branch_uuid(self, name):
        if name in self.new_names:
            return self.new_names[names]
        if self.project.names.exists(name):
            return self.project.names.get(name)

    def set_branch_uuid(self, name, branch):
        if name not in self.old_names:
            if self.project.names.exists(name):
                self.old_names[name] = self.project.names.get(name)
            else:
                self.old_names[name] = None
        self.new_names[name] = branch

    def get_state(self, name):
        return self.project.state.get(name)

    def set_setting(self, name, value):
        if name not in self.old_settings:
            if self.project.settings.exists(name):
                self.old_settings[name] = self.project.settings.get(name)
            else:
                self.old_settings[name] = None
        self.new_settings[name] = value

    def get_setting(self, name):
        if name in self.new_settings:
            return self.new_settings[name]

        return self.project.settings.get(name)

    def create_branch(self, name, prefix, from_commit, from_branch, fork):
        branch_uuid = UUID()
        origin = self.get_branch(from_branch)
        upstream = from_branch if not fork else None
        b = objects.Branch(branch_uuid, name, 'created', prefix, from_commit, from_commit, origin.init, upstream, [])
        self.put_branch(b)
        return b

    def create_session(self, branch_uuid, state, commit):
        session_uuid = UUID()
        b = self.get_branch(branch_uuid)
        files = self.build_files(commit)
        session = objects.Session(session_uuid, branch_uuid, state, b.prefix, commit, commit, files)
        b.sessions.append(session.uuid)
        self.put_branch(b)
        self.put_session(session)
        return session

    def update_active_files(self, files, remove):
        active = self.active()
        active.files.update(files)
        for r in remove:
            active.files.pop(r)
        self.put_session(active)

    def set_active_prepare(self, prepare_uuid):
        active = self.active()
        active.prepare = prepare_uuid
        self.put_session(active)

    def set_active_commit(self, commit_uuid):
        session = self.active()
        branch = self.get_branch(session.branch)
        if session.state == 'attached' and branch.head == session.commit: # descendent check
            branch.head = commit_uuid
            self.put_branch(branch)
        elif session.state == 'attached':
            session.state = 'detached'
        session.prepare = commit_uuid
        session.commit = commit_uuid
        self.put_session(session)

    def refresh_active(self):
        copy = self.active()
        for name, entry in copy.files.items():
            if entry.working is None:
                continue
            path = self.repo_to_full_path(name)
            entry.refresh(path, self.addr_for_file)

        self.put_session(copy)
        return copy

    def prepared_changeset(self, old_uuid):
        changes = objects.Changeset(entries={})
        old = self.get_commit(old_uuid)
        while old and old.kind == 'prepare':
            changes.prepend_changes(self.get_manifest(old.changeset))
            old_uuid = old.previous
            old = self.get_commit(old_uuid)
        return old_uuid, old, changes

    def active_changeset(self, files=None):
        active = self.active()
        out = {}
        if not files:
            files_to_check = active.files.keys()
        else:
            # add prefixes to list
            files_to_check = set()
            for file in files:
                old = file
                while old != '/':
                    files_to_check.add(old)
                    old = os.path.split(old)[0]

        for repo_name in files_to_check:
            entry = active.files[repo_name]
            # and stashed items...? eh nm
            if entry.kind == 'file':
                if entry.state == "added":
                    filename = self.repo_to_full_path(repo_name)
                    addr = self.addr_for_file(filename)
                    out[repo_name]=objects.AddFile(addr, properties=entry.properties)
                elif entry.state == "replaced":
                    filename = self.repo_to_full_path(repo_name)
                    addr = self.addr_for_file(filename)
                    out[repo_name]=objects.NewFile(addr, properties=entry.properties)
                elif entry.state == "modified":
                    filename = self.repo_to_full_path(repo_name)
                    addr = self.addr_for_file(filename)
                    out[repo_name]=objects.ChangeFile(addr, properties=entry.properties)
                elif entry.state == "deleted":
                    if entry.replace == "dir":
                        out[repo_name]=objects.DeleteDir()
                    else:
                        out[repo_name]=objects.DeleteFile()
                elif entry.state == 'tracked':
                    pass
                else:
                    raise VexBug('state {}'.format(entry.state))
            elif entry.kind =='dir':
                if entry.state == "added":
                    out[repo_name]=objects.AddDir(properties=entry.properties)
                elif entry.state == "replaced":
                    out[repo_name]=objects.NewDir(properties=entry.properties)
                elif entry.state == "modified":
                    out[repo_name]=objects.ChangeDir(properties=entry.properties)
                elif entry.state == "deleted":
                    if entry.replace == "file":
                        out[repo_name]=objects.DeleteFile()
                    else:
                        out[repo_name]=objects.DeleteDir()
                elif entry.state == 'tracked':
                    pass
                else:
                    raise VexBug('state {}'.format(entry.state))
            elif entry.kind == 'stash':
                if entry.state == "added":
                    addr = entry.stash
                    out[repo_name]=objects.AddFile(addr, properties=entry.properties)
                elif entry.state == "replaced":
                    addr = entry.stash
                    out[repo_name]=objects.NewFile(addr, properties=entry.properties)
                elif entry.state == "modified":
                    addr = entry.stash
                    if addr != entry.addr:
                        out[repo_name]=objects.ChangeFile(addr, properties=entry.properties)
                else:
                    raise VexBug('state {}'.format(entry.state))
            elif entry.kind == 'ignore':
                pass
            else:
                raise VexBug('kind')

        return objects.Changeset({k:[v] for k,v in out.items()})

    def update_active_from_changeset(self, changeset):
        active = self.active()
        for name, changes in changeset.items():
            entry = active.files.get(name)
            change = changes[-1]

            if not entry:
                if not isinstance(change, (objects.DeleteFile, objects.DeleteDir)):
                    raise VexBug('sync')
            elif isinstance(change, objects.DeleteDir):
                active.files.pop(name)
            elif isinstance(change, objects.DeleteFile):
                active.files.pop(name)
            else:
                mtime = None
                mode = None
                size = None
                if entry.working:
                    path = self.repo_to_full_path(name)
                    stat = os.stat(path)
                    if (time.time() - stat.st_mtime) < MTIME_GRACE_SECONDS:
                        mtime = None
                    else:
                        mtime = stat.st_mtime
                    mode = stat.st_mode
                    size = stat.st_size


                if isinstance(change, (objects.AddFile, objects.NewFile)):
                    active.files[name] = objects.Tracked("file", "tracked", working=entry.working, addr=change.addr, properties=change.properties, mtime=mtime, mode=mode, size=size)
                elif isinstance(change, objects.ChangeFile):
                    active.files[name] = objects.Tracked("file", "tracked", working=entry.working, addr=change.addr, properties=change.properties, mtime=mtime, mode=mode, size=size)
                elif isinstance(change, (objects.AddDir, objects.NewDir)):
                    active.files[name] = objects.Tracked("dir", "tracked",  working=entry.working, properties=change.properties, mtime=mtime, mode=mode, size=size)
                elif isinstance(change, objects.ChangeDir):
                    active.files[name] = objects.Tracked("dir", "tracked", working=entry.working, properties=change.properties, mtime=mtime, mode=mode, size=size)
                else:
                    raise VexBug(change)


        self.put_session(active)

    def store_changeset_files(self, changeset):
        active = self.active()
        for name, changes in changeset.items():
            change = changes[-1]
            entry = active.files.get(name)
            if not entry: 
                if not isinstance(change, (objects.DeleteFile, objects.DeleteDir)):
                    raise VexBug('sync')
                
            elif entry.kind == 'file' and entry.working:
                filename = self.repo_to_full_path(name)
                if os.path.isfile(filename) and isinstance(change, (objects.AddFile, objects.ChangeFile, objects.NewFile)):
                    addr = self.put_file(filename)
                    if addr != change.addr:
                        raise VexCorrupt('Sync')
            elif entry.kind == 'stash':
                self.new_files.add(entry.stash)


    def new_root_with_changeset(self, old, changeset):
        dir_changes = {}
        for path, entry in sorted((p.split('/'),e) for p,e in changeset.items()):
            prefix, name = "/".join(path[:-1]), path[-1]
            prefix = prefix or "/"
            name = name or "."
            if prefix not in dir_changes:
                dir_changes[prefix]  = {}
            dir_changes[prefix][name] = entry

        def apply_changes(prefix, addr, root=False):
            old_entries = {}
            entries = {}
            changes = dir_changes.get(prefix, None)
            changed = bool(changes)
            properties = {}
            names = set()
            if addr:
                old = self.get_manifest(addr)
                if root:
                    properties = old.properties
                old_entries = old.entries
                names.update(old_entries.keys())
            if changes:
                names.update(changes.keys())

            for name in sorted(names):
                if name == ".":
                    if not root: raise VexBug('...')
                    for change in changes.pop(name):
                        if isinstance(change, objects.ChangeDir):
                            properties = change.properties
                        elif not addr and isinstance(change, objects.AddDir):
                            properties = change.properties
                        else:
                            raise VexBug('welp')
                    continue

                entry = old_entries.get(name)
                if changes and name in changes:
                    entry_changes = changes.pop(name)
                    for change in entry_changes:
                        if isinstance(change, objects.NewFile):
                            if not isinstance(entry, objects.Dir): raise VexBug('overwrite sync')
                            entry = objects.File(change.addr, change.properties)
                        elif isinstance(change, objects.NewDir):
                            if not isinstance(entry, objects.File): raise VexBug('overwrite sync')
                            entry = objects.Dir(None, change.properties)
                        elif isinstance(change, objects.DeleteFile):
                            if not isinstance(entry, objects.File): raise VexBug('cant delete a file not in repo')
                            entry = None
                        elif isinstance(change, objects.DeleteDir):
                            if not isinstance(entry, objects.Dir): raise VexBug('cant delete a dir not in repo')
                            entry = None
                        elif isinstance(change, objects.ChangeFile):
                            if not isinstance(entry, objects.File): raise VexBug('no')
                            entry = objects.File(change.addr, change.properties)
                        elif isinstance(change, objects.ChangeDir):
                            if not isinstance(entry, objects.Dir): raise VexBug('no')
                            entry = objects.Dir(entry.addr, change.properties)
                        elif isinstance(change, objects.AddDir):
                            if entry: raise VexBug('wait, what')
                            entry = objects.Dir(None, change.properties)
                        elif isinstance(change, objects.AddFile):
                            if entry: raise VexBug('wait, what', name)
                            entry = objects.File(change.addr, change.properties)
                        else:
                            raise VexBug('nope', change)
                        
                if entry and isinstance(entry, objects.Dir):
                    path = os.path.join(prefix, name)
                    new_addr = apply_changes(path, entry.addr)
                    if new_addr != entry.addr:
                        changed = True
                        entry = objects.Dir(new_addr, entry.properties)

                if entry and not isinstance(entry, (objects.File, objects.Dir)):
                    raise VexBug('nope')

                if entry is not None:
                    entries[name] = entry

            if not entries:
                return None
            elif changed:
                entries = {k:entries[k] for k in sorted(entries)}
                if root:
                    return self.put_manifest(objects.Root(entries, properties))
                else:
                    return self.put_manifest(objects.Tree(entries))
            else:
                return addr

        return apply_changes('/', old, root=True)

    def build_files(self, commit):
        output = {}

        def walk(prefix, addr, root=False):
            old = self.get_manifest(addr)
            if root:
                output[prefix] = objects.Tracked('dir', 'tracked', properties=old.properties)
            for name, entry in old.entries.items():
                path = os.path.join(prefix, name)
                if isinstance(entry, objects.Dir):
                    output[path] = objects.Tracked('dir', 'tracked', properties=entry.properties)
                    if entry.addr:
                        walk(path, entry.addr)
                elif isinstance(entry, objects.File):
                    output[path] = objects.Tracked('file', 'tracked', addr=entry.addr, properties=entry.properties)

        def extract(changes):
            for path, changes in changes.items():
                for change in changes:
                    if isinstance(change, (objects.AddFile, objects.NewFile, objects.ChangeFile)):
                        output[name] = objects.Tracked("file", "tracked", addr=change.addr, properties=change.properties)
                    elif isinstance(change, (objects.AddDir, objects.NewDir, objects.ChangeDir)):
                        output[name] = objects.Tracked("dir", "tracked", properties=change.properties)
                    elif isinstance(change, (objects.DeleteDir, objects.DeleteFile)):
                        output.pop(name)
                    else:
                        raise VexBug(change)

        old_uuid, old, changes = self.prepared_changeset(commit)
        walk('/', old.root, root=True)

        extract(changes)

        return output

    def add_files_to_active(self, files, include, ignore):
        active = self.active()
        to_scan = set()
        names = {}
        dirs = {}
        for filename in files:
            name = self.full_to_repo_path(filename)
            if os.path.isfile(filename):
                names[name] = filename
            elif os.path.isdir(filename):
                dirs[name] = filename
                to_scan.add(filename)
            filename = os.path.split(filename)[0]
            name = os.path.split(name)[0]
            while name != '/' and name != self.project.VEX:
                dirs[name] = filename
                name = os.path.split(name)[0]
                filename = os.path.split(filename)[0]


        for dir in to_scan:
            for filename in list_dir(dir, ignore, include):
                name = self.full_to_repo_path(filename)
                if os.path.isfile(filename):
                    names[name] = filename
                elif os.path.isdir(filename):
                    dirs[name] = filename

        added = set()
        new_files = {}
        for name, filename in dirs.items():
            if name in active.files:
                entry = active.files[name]
                if entry.kind != 'dir':
                    replace = entry.replace
                    if replace == None and entry.kind != 'dir': replace = entry.kind
                    new_files[name] = objects.Tracked('dir', "replaced", working=True, properties={}, replace=replace)
                    added.add(filename)
            else:
                new_files[name] = objects.Tracked('dir', "added", working=True, properties={})
                added.add(filename)

        for name, filename in names.items():
            if name in active.files:
                entry = active.files[name]
                if entry.kind != 'file':
                    replace = entry.replace
                    if replace == None and entry.kind != 'file': replace = entry.kind
                    new_files[name] = objects.Tracked('file', "replaced", working=True, properties={}, replace=replace)
                    added.add(filename)
            else:
                new_files[name] = objects.Tracked('file',"added", working=True, properties={})
                added.add(filename)

        self.update_active_files(new_files, ())

        return added

    def forget_files_from_active(self, files):
        session = self.active()
        names = {}
        dirs = []
        changed = {}
        # XXX: forget empty directories
        for filename in files:
            name = self.full_to_repo_path(filename)
            if name in session.files:
                entry = session.files[name]
                changed[name]= filename
                if entry.working:
                    names[name] = entry
                    if entry.kind == 'dir':
                        p = "{}/".format(name)
                        for e in session.files:
                            if e.startswith(p):
                                names[e] = session.files[e]
                                changed[e] = self.repo_to_full_path(e)
        new_files = {}
        gone_files = set()

        for name, entry in names.items():
            if entry.state == 'added':
                gone_files.add(name)
            else:
                kind = entry.replace or entry.kind
                new_files[name] = objects.Tracked(kind, "deleted", working=True, properties={})

        self.update_active_files(new_files, gone_files)
        return changed 
    
    def remove_files_from_active(self, files):
        changed = self.forget_files_from_active(files)
        for path, file in changed.items():
            # XXX: dirs
            if not os.path.isfile(file):
                raise VexUnimplemented('crap')
            if os.path.exists(file) and os.path.isfile(file):
                addr = self.project.put_scratch_file(file)
                self.old_working[path] = addr
                self.new_working[path] = None
        return changed

    def restore_files_to_active(self, files):
        active = self.active()
        
        old_files = self.build_files(active.prepare)
        new_files = {}
        changed = {}
        for file in files:
            path = self.full_to_repo_path(file)
            if path not in old_files:
                continue
            changed[path] = file
            if os.path.exists(file):
                if not os.path.isfile(file):
                    raise VexUnimplemented('crap')
                addr = self.project.put_scratch_file(file)
                self.old_working[path] = addr
                self.new_working[path] = old_files[path].addr
            else:
                self.old_working[path] = None
                self.new_working[path] = old_files[path].addr
            print(self.old_working, self.new_working)

            new_files[path] = old_files[path]
            new_files[path].working = True
        self.update_active_files(new_files, ())
        return changed

    def action(self):
        if self.new_branches or self.new_names or self.new_sessions or self.new_settings:
            branches = dict(old=self.old_branches, new=self.new_branches)
            names = dict(old=self.old_names, new=self.new_names)
            sessions = dict(old=self.old_sessions, new=self.new_sessions)
            settings = dict(old=self.old_settings, new=self.new_settings)

            changes = dict(branches=branches,names=names, sessions=sessions, settings=settings)
        else:
            changes = {}

        if self.new_commits or self.new_manifests or self.new_files:
            blobs = dict(commits=self.new_commits, manifests=self.new_manifests, files=self.new_files)
        else:
            blobs = {}
        if self.new_working:
            working = dict(old=self.old_working, new=self.new_working)
        else:
            working = {}
        return objects.Action(self.now, self.command, changes, blobs, working)

class LogicalTransaction:
    def __init__(self, project, command):
        self.project = project
        self.command = command
        self.prefix = {}
        self.active_session = {}
        self.old_branch_states = {}
        self.new_branch_states = {}
        self.old_session_states = {}
        self.new_session_states = {}
        self.old_names = {}
        self.new_names = {}
        self.now = NOW()

    def switch_prefix(self, new_prefix):
        self.prefix = {'old': self.project.prefix(), 'new': new_prefix}

    def switch_session(self, new_session):
        if isinstance(new_session, objects.Session): raise VexBug()
        self.active_session = {'old': self.project.state.get('active'), 'new': new_session}

    def set_branch_state(self, uuid, state):
        if uuid in self.new_branch_states:
            self.new_branch_states[uuid] = state
        else:
            old = self.project.branches.get(uuid)
            self.new_branch_states[uuid] = state
            self.old_branch_states[uuid] = old.state


    def set_session_state(self, session_uuid, state):
        if session_uuid in self.new_session_states:
            self.new_session_states[uuid] = state
        else:
            old = self.project.sessions.get(uuid)
            self.new_session_states[uuid] = state
            self.old_session_states[uuid] = old.state

    def get_branch_uuid(self, name):
        if name in self.new_names:
            return self.new_names[names]
        if self.project.names.exists(name):
            return self.project.names.get(name)

    def set_branch_uuid(self, name, branch):
        if name not in self.old_names:
            if self.project.names.exists(name):
                self.old_names[name] = self.project.names.get(name)
            else:
                self.old_names[name] = None
        self.new_names[name] = branch

    def action(self):
        branches = dict(old=self.old_branch_states, new=self.new_branch_states)
        sessions = dict(old=self.old_session_states, new=self.new_session_states)
        names = dict(old=self.old_names, new=self.new_names)
        return objects.Switch(self.now, self.command, self.prefix, self.active_session, sessions, branches, names)

class Repo:
    def __init__(self, config_dir):
        self.dir = config_dir
        self.commits =   BlobStore(os.path.join(config_dir, 'objects', 'commits'), codec)
        self.manifests = BlobStore(os.path.join(config_dir, 'objects', 'manifests'), codec)
        self.files =     BlobStore(os.path.join(config_dir, 'objects', 'files'), codec)
        self.scratch =   BlobStore(os.path.join(config_dir, 'objects', 'scratch'), codec)

    def makedirs(self):
        os.makedirs(self.dir, exist_ok=True)
        self.commits.makedirs()
        self.manifests.makedirs()
        self.files.makedirs()
        self.scratch.makedirs()

    def addr_for_file(self, path):
        return self.scratch.addr_for_file(path)

    def get_commit(self, addr):
        return self.commits.get_obj(addr)

    def get_manifest(self, addr):
        return self.manifests.get_obj(addr)

    def get_file(self, addr):
        return self.files.get_file(addr)

    def get_scratch_file(self, addr):
        return self.scratch.get_file(addr)

    def get_scratch_commit(self,addr):
        return self.scratch.get_obj(addr)

    def get_scratch_manifest(self, addr):
        return self.scratch.get_obj(addr)

    def put_scratch_file(self, value, addr=None):
        return self.scratch.put_file(value, addr)

    def put_scratch_commit(self, value):
        return self.scratch.put_obj(value)

    def put_scratch_manifest(self, value):
        return self.scratch.put_obj(value)

    def add_commit_from_scratch(self, addr):
        self.commits.copy_from(self.scratch, addr)

    def add_manifest_from_scratch(self, addr):
        self.manifests.copy_from(self.scratch, addr)

    def add_file_from_scratch(self, addr):
        self.files.copy_from(self.scratch, addr)

    def get_file_path(self, addr):
        return self.files.filename(addr)

    def copy_from_scratch(self, addr, path):
        return self.scratch.make_copy(addr, path)

    def copy_from_file(self, addr, path):
        return self.files.make_copy(addr, path)

    def copy_from_any(self, addr, path):
        if self.files.exists(addr):
            return self.files.make_copy(addr, path)

        return self.scratch.make_copy(addr, path)

class Project:
    VEX = "/.vex"
    def __init__(self, config_dir, working_dir):
        self.working_dir = working_dir
        self.config_dir = config_dir
        self.repo = Repo(config_dir)


        self.branches =   FileStore(os.path.join(config_dir, 'branches'), codec)
        self.names =      FileStore(os.path.join(config_dir, 'branches', 'names'), codec)
        self.sessions =   FileStore(os.path.join(config_dir, 'branches', 'sessions'), codec)
        self.state =      FileStore(os.path.join(config_dir, 'state'), codec)
        self.history =   History(os.path.join(config_dir, 'history'))
        self.lockfile =  LockFile(os.path.join(config_dir, 'lock'))

        self.settings =  FileStore(os.path.join(config_dir, 'settings'), codec)

    # methods, look, don't ask, they're just plain methods, ok?

    def nfc_name(self, name):
        return unicodedata.normalize('NFC', name)

    def makedirs(self):
        os.makedirs(self.config_dir, exist_ok=True)
        self.repo.makedirs()
        self.branches.makedirs()
        self.names.makedirs()
        self.state.makedirs()
        self.sessions.makedirs()
        self.history.makedirs()
        self.settings.makedirs()

    def makelock(self):
        self.lockfile.makelock()

    @contextmanager
    def lock(self, command):
        with self.lockfile(command):
            yield self

    def exists(self):
        return os.path.exists(self.config_dir)

    def clean_state(self):
        return self.history.clean_state()

    def history_isempty(self):
        return self.history.empty()

    def prefix(self):
        if self.state.exists("prefix"):
            return self.state.get("prefix")

    def active(self):
        if self.state.exists("active"):
            return self.sessions.get(self.state.get("active"))

    def get_branch_uuid(self, name):
        return self.names.get(name)

    def get_branch(self, uuid):
        return self.branches.get(uuid)

    def get_session(self, uuid):
        return self.sessions.get(uuid)

    def addr_for_file(self, file):
        return self.repo.addr_for_file(file)

    def get_commit(self, addr):
        return self.repo.get_commit(addr)

    def get_manifest(self, addr):
        return self.repo.get_manifest(addr)

    def get_file(self, addr):
        return self.repo.get_file(addr)

    def get_scratch_commit(self, addr):
        return self.repo.get_scratch_commit(addr)

    def get_scratch_manifest(self, addr):
        return self.repo.get_scratch_manifest(addr)

    def get_scratch_file(self, addr):
        return self.repo.get_scratch_file(addr)

    def put_scratch_commit(self, value):
        return self.repo.put_scratch_commit(value)

    def put_scratch_manifest(self, value):
        return self.repo.put_scratch_manifest(value)

    def put_scratch_file(self, value, addr=None):
        return self.repo.put_scratch_file(value, addr)

    def repo_to_full_path(self, prefix, file):
        file = os.path.normpath(file)
        if os.path.commonpath((file, self.VEX)) == self.VEX:
            path = os.path.relpath(file, self.VEX)
            return os.path.normpath(os.path.join(self.settings.dir, path))
        else:
            path = os.path.relpath(file, prefix)
            return os.path.normpath(os.path.join(self.working_dir, path))

    def full_to_repo_path(self, prefix, file):
        file = os.path.normpath(file)
        if os.path.commonpath((self.settings.dir, file)) == self.settings.dir:
            path = os.path.relpath(file, self.settings.dir)
            path = self.nfc_name(path)
            return os.path.normpath(os.path.join(self.VEX, path))
        else:
            if file.startswith(self.config_dir):
                raise VexBug('nope. not .vex')
            path = os.path.relpath(file, self.working_dir)
            path = self.nfc_name(path)
            return os.path.normpath(os.path.join(prefix, path))

    def check_files(self, files):
        output = []
        for filename in files:
            filename = os.path.normpath(filename)
            if not filename.startswith(self.working_dir):
                raise VexError("{} is outside project".format(filename))
            if filename == self.config_dir: continue
            output.append(filename)
        return files

    def check_file(self, file):
        if not file.startswith(self.working_dir):
            return False
        if os.path.commonpath((self.settings.dir, file)) == self.settings.dir:
            return True
        if os.path.commonpath((self.config_dir, file)) == self.config_dir:
            return False
        return True

    # ... and so are these, but, they interact with the action log
    def rollback_new_action(self):
        with self.history.rollback_new() as (mode, action):
            if action:
                if isinstance(action, objects.Action):
                    self.apply_physical_changes('old', action.changes)
                elif isinstance(action, objects.Switch):
                    # raise VexUnimplemented('this should probably pass but ...')
                    pass
                else:
                    raise VexBug('welp')
            return action

    def restart_new_action(self):
        with self.history.restart_new() as (mode, action):
            if action:
                if isinstance(action, objects.Action):
                    self.copy_blobs(action.blobs)
                    self.apply_physical_changes('new', action.changes)
                elif isinstance(action, objects.Switch):
                    pass
                else:
                    raise VexBug('welp')
            return action

    # speaking of which

    @contextmanager
    def do_without_undo(self, command):
        active = self.state.get("active")
        txn = PhysicalTransaction(self, command)
        yield txn
        with self.history.do_without_undo(txn.action()) as action:
            if any(action.blobs.values()):
                raise VexBug(action.blobs)
            if action.changes:
                self.apply_physical_changes('new', action.changes)

    @contextmanager
    def do(self, command):
        if not self.history.clean_state():
            raise VexCorrupt('Project history not in a clean state.')

        txn = PhysicalTransaction(self, command)
        yield txn
        with self.history.do(txn.action()) as action:
            if not action:
                return
            if isinstance(action, objects.Action):
                self.copy_blobs(action.blobs)
                self.apply_working_changes('new', action.working)
                self.apply_physical_changes('new', action.changes)
            else:
                raise VexBug('action')

    @contextmanager
    def do_switch(self, command):
        if not self.history.clean_state():
            raise VexCorrupt('Project history not in a clean state.')

        txn = LogicalTransaction(self, command)
        yield txn
        with self.history.do(txn.action()) as action:
            if not action:
                return
            if isinstance(action, objects.Switch):
                self.apply_switch('new', action.prefix, action.active)
                self.apply_logical_changes('new', action.session_states, action.branch_states, action.names)
            else:
                raise VexBug('action')

    # Take Action.changes and applies them to project
    def apply_logical_changes(self, kind, session_states, branch_states, names):
        for name,value in session_states[kind].items():
            session = self.sessions.get(name)
            session.state = value
            self.sessions.set(name, branch)
        for name,value in branch_states[kind].items():
            branch = self.branches.get(name)
            branch.state = value
            self.branches.set(name, branch)
        for name,value in names[kind].items():
            self.names.set(name, value)

    # Take Action.changes and applies them to project
    def apply_physical_changes(self, kind, changes):
        prefix = self.prefix()
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
            elif key == 'settings':
                for name,value in changes['settings'][kind].items():
                    self.settings.set(name, value)

    def apply_working_changes(self, kind, changes):
        if not changes:
            return
        prefix = self.prefix()
        for name, addr in changes[kind].items():
            path = self.repo_to_full_path(prefix, name)
            if kind == 'new':
                old = changes['old'][name]
            elif kind == 'old':
                old = changes['new'][name]
            else:
                raise VexBug('nope')
            ### XXX check old value ...?
            if old is None and not os.path.exists(path):
                self.repo.copy_from_any(addr, path)
            elif old and os.path.exists(path) and self.addr_for_file(path) == old:
                os.remove(path)
                if addr:
                    self.repo.copy_from_any(addr, path)
            else:
                sys.stderr.write("ERR: Skipping {}\n".format(path))


    # Takes Action.blobs and copies them out of the scratch directory
    def copy_blobs(self, blobs):
        for key in blobs:
            if key == 'commits':
                for addr in blobs['commits']:
                    self.repo.add_commit_from_scratch(addr)
            elif key == 'manifests':
                for addr in blobs['manifests']:
                    self.repo.add_manifest_from_scratch(addr)
            elif key =='files':
                for addr in blobs['files']:
                    self.repo.add_file_from_scratch(addr)
            else:
                raise VexBug('Project change has unknown values')

    def apply_switch(self, kind, prefix, session):
        if prefix:
            active_prefix = self.prefix()
            new_prefix = prefix[kind]
            if (kind =='new' and active_prefix != prefix['old']) or (kind =='old' and active_prefix != prefix['new']):
                raise VexCorrupt('switch out of sync')
        else:
            active_prefix, new_prefix = self.prefix(), self.prefix()

        if session:
            active_session = self.state.get("active")
            new_session = session[kind]
            if (kind =='new' and active_session != session['old']) or (kind =='old' and active_session != session['new']):
                raise VexCorrupt('switch out of sync')
            new_prefix = self.sessions.get(new_session).prefix
        else:
            uuid = self.state.get('active')
            active_session, new_session = uuid, uuid

        active = self.sessions.get(active_session)
        active = self.stash_session(active)
        # check after stash, as it might be same
        new = self.sessions.get(new_session)
        self.clear_session(active_prefix, active)
        self.restore_session(new_prefix, new)


    def stash_session(self, session, files=None):
        files = session.files if files is None else files
        for name in files:
            entry = session.files[name]
            if name in ("/", self.VEX): continue
            new_addr = None
            if entry.working is None:
                continue
            path = self.repo_to_full_path(self.prefix(), name)
            entry.refresh(path, self.addr_for_file)

            if entry.kind == 'file' and entry.state in ('added', 'replaced', 'modified'):
                entry.stash = self.put_scratch_file(path, addr=new_addr)
                entry.kind = 'stash'

        self.sessions.set(session.uuid, session)
        return session

    def clear_session(self, prefix, session):
        if prefix != self.prefix() or session.uuid != self.state.get("active"):
            raise VexBug('no')
        dirs = set()
        for name, entry in session.files.items():
            if entry.kind == "ignore":
                continue
            if not entry.working:
                continue
            path = self.repo_to_full_path(prefix, name)
            if entry.kind == "file" or entry.kind == "stash":
                if os.path.commonpath((path, self.working_dir)) != self.working_dir:
                    raise VexBug('file outside of working dir inside tracked')
                if not os.path.isfile(path):
                    raise VexBug('sync')
                os.remove(path)
            elif entry.kind == "dir":
                if os.path.commonpath((path, self.working_dir)) != self.working_dir:
                    raise VexBug('file outside of working dir inside tracked')
                if name not in ("/", self.VEX, prefix):
                    dirs.add(path)
            elif entry.kind == "stash":
                pass
            else:
                raise VexBug('no')
            entry.working = None
            entry.mtime = None
            entry.mode = None
            entry.size = None

        for dir in sorted(dirs, reverse=True, key=lambda x: x.split("/")):
            if dir in (self.working_dir, self.settings.dir):
                continue
            if not os.path.isdir(dir):
                raise VexBug('sync')
            if not os.listdir(dir):
                os.rmdir(dir)
        self.state.set('prefix', None)
        self.state.set('active', None)

    def restore_session(self, prefix, session):
        for name in sorted(session.files, key=lambda x:x.split('/')):
            entry = session.files[name]
            if os.path.commonpath((name, prefix)) != prefix and os.path.commonpath((name, self.VEX)) != self.VEX:
                entry.working = None
                entry.mtime = None
                entry.mode = None
                entry.size = None
                continue
            else:
                entry.working = True
                entry.mtime = None
                entry.size = None
                entry.mode = None

            if entry.kind == 'ignore':
                continue

            path = self.repo_to_full_path(prefix, name)

            if entry.kind =='dir':
                if name not in ('/', self.VEX, prefix):
                    os.makedirs(path, exist_ok=True)
            elif entry.kind =="file":
                self.repo.copy_from_file(entry.addr, path)
                if entry.properties.get('vex:executable'):
                    stat = os.stat(path)
                    os.chmod(path, stat.st_mode | 64)
            elif entry.kind == "stash":
                self.repo.copy_from_scratch(entry.stash, path)
                entry.kind = "file"
                entry.stash = None
                if entry.properties.get('vex:executable'):
                    stat = os.stat(path)
                    os.chmod(path, stat.st_mode | 64)
            elif entry.kind == "ignore":
                pass
            else:
                raise VexBug('kind')
        session.prefix = prefix
        self.sessions.set(session.uuid, session)
        self.state.set('prefix', prefix)
        self.state.set('active', session.uuid)


    ###  Commands

    def get_fileprops(self,file):
        file = self.check_files([file])[0] if file else None
        with self.do_without_undo('fileprops:get') as txn:
            active = txn.active()
            file = txn.full_to_repo_path(file) 
            tracked = active.files[file]
            return tracked.properties

    def set_fileprop(self,file, name, value):
        file = self.check_files([file])[0] if file else None
        with self.do('fileprops:set') as txn:
            active = txn.active()
            file = txn.full_to_repo_path(file) 
            tracked = active.files[file]
            tracked.set_property(name, value)
            txn.put_session(active)

    def undo(self):
        with self.history.undo() as action:
            if not action:
                return
            if isinstance(action, objects.Action):
                self.apply_physical_changes('old', action.changes)
                self.apply_working_changes('old', action.working)
            elif isinstance(action, objects.Switch):
                self.apply_switch('old', action.prefix, action.active)
                self.apply_logical_changes('old', action.session_states, action.branch_states, action.names)
            else:
                raise VexBug('action')
            return action

    def list_undos(self):
        return self.history.entries()

    def redo(self, choice):
        with self.history.redo(choice) as action:
            if not action:
                return
            if isinstance(action, objects.Action):
                self.apply_physical_changes('new', action.changes)
                self.apply_working_changes('new', action.working)
            elif isinstance(action, objects.Switch):
                self.apply_switch('new', action.prefix, action.active)
                self.apply_logical_changes('new', action.session_states, action.branch_states, action.names)
            else:
                raise VexBug('action')
            return action

    def list_redos(self):
        return self.history.redo_choices()

    def log(self):
        with self.do_without_undo('log') as txn:
            session = txn.active()

        commit = session.prepare
        out = []
        while commit != session.commit:
            obj = self.get_commit(commit)
            out.append('*: *uncommitted* {}: {}'.format(obj.kind, commit))
            commit = obj.previous

        n= 0
        while commit != None:
            obj = self.get_commit(commit)
            out.append('{}: committed {}: {}'.format(n, obj.kind, commit))
            n-=1
            commit = obj.previous
        return out

    def status(self):
        with self.do_without_undo('status') as txn:
            return txn.refresh_active().files

    def switch(self, new_prefix):
        # check new prefix exists in repo
        if os.path.commonpath((new_prefix, self.VEX )) == self.VEX:
            raise VexArgument('bad arg')
        if new_prefix not in self.active().files and new_prefix != "/":
            raise VexArgument('bad prefix')
        with self.do_switch('switch') as txn:
            txn.switch_prefix(new_prefix)

    def init(self, prefix, include, ignore):
        self.makedirs()
        if not self.history_isempty():
            raise VexNoHistory('cant reinit')
        if not prefix.startswith('/'):
            raise VexArgument('crap prefix')
        with self.do_without_undo('init') as txn:
            txn.set_setting('ignore', ignore)
            txn.set_setting('include', include)

        with self.do('init') as txn:
            author_uuid = UUID() 
            branch_uuid = UUID()
            session_uuid = UUID()
            branch_name = 'latest'

            root_path = '/'

            ignore_addr = txn.put_file(txn.repo_to_full_path('/.vex/ignore'))
            include_addr = txn.put_file(txn.repo_to_full_path('/.vex/include'))
            
            changes = {
                    '/' : [ objects.AddDir(properties={}) ] ,
                    self.VEX : [ objects.AddDir(properties={}) ],
                    os.path.join(self.VEX, 'ignore'): [ objects.AddFile(addr=ignore_addr, properties={}) ],
                    os.path.join(self.VEX, 'include'): [ objects.AddFile(addr=include_addr, properties={}) ],
            }
            if prefix != '/':
                changes[prefix] = [ objects.AddDir(properties={})]
            changeset = objects.Changeset(message="", entries=changes, author=author_uuid)

            root_uuid = txn.new_root_with_changeset(None, changeset)

            changeset_uuid = txn.put_manifest(changeset)

            commit = objects.Commit('init', txn.now, previous=None, changeset=changeset_uuid, root=root_uuid, ancestors={})
            commit_uuid = txn.put_commit(commit)

            branch = objects.Branch(branch_uuid, branch_name, 'active', prefix, commit_uuid, None, commit_uuid, None, [session_uuid])
            txn.put_branch(branch)
            txn.set_branch_uuid(branch_name, branch.uuid)

            files = txn.build_files(commit_uuid)
            for name, entry in files.items():
                if os.path.commonpath((name, prefix)) == prefix or os.path.commonpath((name, self.VEX)) == self.VEX:
                    entry.working = True
                else:
                    entry.working = None

            session = objects.Session(session_uuid, branch_uuid, 'attached', prefix, commit_uuid, commit_uuid, files) 
            txn.put_session(session)


        self.state.set("author", author_uuid)
        self.state.set("active", session_uuid)
        self.state.set("prefix", prefix)

    def active_diff_files(self, files):
        files = self.check_files(files) if files else None
        with self.do_without_undo('diff') as txn:
            session = txn.refresh_active()
            files = [txn.full_to_repo_path(filename) for filename in files] if files else None
            changeset = txn.active_changeset(files)

            output = {}
            for name, c in changeset.items():
                e = session.files[name]
                if e.kind == 'file' and e.addr:
                    output[name] = dict(old=self.repo.get_file_path(e.addr), new=self.repo_to_full_path(self.prefix(),name))
            output2 = {}
            for name, d in output.items():
                output2[name] = file_diff(name, d['old'], d['new'])
            return output2


    def active_diff_commit(self, commit):
        with self.do_without_undo('diff:commit') as txn:
            session = txn.refresh_active()

            files = txn.build_files(commit)

            output = {}
            for name, c in session.files.items():
                e = files[name]
                if e.kind == 'file' and e.addr:
                    output[name] = dict(old=self.repo.get_file_path(e.addr), new=self.repo_to_full_path(self.prefix(),name))
            output2 = {}
            for name, d in output.items():
                output2[name] = file_diff(name, d['old'], d['new'])
            return output2
    def prepare(self, files):
        files = self.check_files(files) if files else None
        with self.do('prepare') as txn:
            session = txn.refresh_active()
            files = [txn.full_to_repo_path(filename) for filename in files] if files else None

            changeset = txn.active_changeset(files)

            if not changeset:
                return None

            prepare = session.prepare

            txn.store_changeset_files(changeset)
            txn.update_active_from_changeset(changeset)

            changeset.author = txn.get_state('author')

            changeset_uuid = txn.put_manifest(changeset)
            ancestors = {}
            prepare = objects.Commit('prepare', txn.now, previous=prepare, ancestors=ancestors, root=None, changeset=changeset_uuid)
            prepare_uuid = txn.put_commit(prepare)

            txn.set_active_prepare(prepare_uuid)
        return changeset

    def commit_prepared(self):
        with self.do('commit:prepared') as txn:
            session = txn.active()

            old_uuid, old, changeset = txn.prepared_changeset(session.prepare)

            if not changeset: return False

            root_uuid = txn.new_root_with_changeset(old.root, changeset)

            if root_uuid == old.root:
                txn.update_active_from_changeset(changeset)
                return False

            txn.store_changeset_files(changeset)
            txn.update_active_from_changeset(changeset)

            changeset.author = txn.get_state('author')

            changeset_uuid = txn.put_manifest(changeset)

            commit = objects.Commit('commit', timestamp=txn.now, previous=old_uuid, ancestors=dict(prepared=session.prepare), root=root_uuid, changeset=changeset_uuid)
            commit_uuid = txn.put_commit(commit)

            txn.set_active_commit(commit_uuid)

            return changeset
    
    def amend(self, files):
        return self.commit_active(files, kind='amend', command='amend')

    def commit_active(self, files, kind='commit', command = 'commit'):
        kind = 'commit'
        command = 'commit'
        files = self.check_files(files) if files else None

        with self.do(command) as txn:
            session = txn.refresh_active()
            files = [txn.full_to_repo_path(filename) for filename in files] if files else None

            old_uuid, old, changeset = txn.prepared_changeset(session.prepare)

            changeset.append_changes(txn.active_changeset(files))

            if not changeset:
                return None

            root_uuid = txn.new_root_with_changeset(old.root, changeset)

            if root_uuid == old.root:
                txn.update_active_from_changeset(changeset)
                return False

            txn.store_changeset_files(changeset)
            txn.update_active_from_changeset(changeset)

            changeset.author = txn.get_state('author')
            changeset_uuid = txn.put_manifest(changeset)

            commit = objects.Commit(kind, timestamp=txn.now, previous=old_uuid, ancestors=dict(prepared=session.prepare), root=root_uuid, changeset=changeset_uuid)
            commit_uuid = txn.put_commit(commit)

            txn.set_active_commit(commit_uuid)


            return changeset

    def add(self, files, include=None, ignore=None):
        files = self.check_files(files)

        with self.do('add') as txn:
            session = txn.refresh_active()
            include = include if include is not None else txn.get_setting('include')
            ignore = ignore if ignore is not None else txn.get_setting('ignore')

            added = txn.add_files_to_active(files, include, ignore)
            return added

    def forget(self, files):
        files = self.check_files(files)

        with self.do('forget') as txn:
            session = txn.refresh_active()
            changed = txn.forget_files_from_active(files)
            return changed

    def remove(self, files):
        files = self.check_files(files)

        with self.do('remove') as txn:
            session = txn.refresh_active()
            changed = txn.remove_files_from_active(files)
            return changed

    def restore(self, files):
        files = self.check_files(files)

        with self.do('restore') as txn:
            session = txn.refresh_active()
            changed = txn.restore_files_to_active(files)
            return changed

    def list_branches(self):
        branches = []
        uuids = set()
        for name in self.names.list():
            uuid = self.names.get(name)
            if uuid:
                uuids.add(uuid)
                branch = self.branches.get(uuid)
                branches.append((name, branch))
        for uuid in self.branches.list():
            if uuid in uuids: continue
            uuids.add(uuid)
            branch = self.branches.get(uuid)
            branches.append((None, branch))
        return branches

    def swap_branch(self, name, rename=False, swap=False):
        with self.do('branch:swap') as txn:
            active = self.active()
            me = txn.get_branch(active.branch)
            other = txn.get_branch_uuid(name)
            branch = txn.get_branch(other)
            old_name = me.name
            txn.set_branch_uuid(old_name, other)
            txn.set_branch_uuid(name, me.uuid)
            branch.name = old_name
            me.name = name
            txn.put_branch(me)
            txn.put_branch(branch)

    def rename_branch(self, name, rename=False, swap=False):
        with self.do('branch:rename') as txn:
            active = self.active()
            old = txn.get_branch(active.branch)
            txn.set_branch_uuid(old.name, None)
            old.name = name
            txn.set_branch_uuid(name, old.uuid)
            txn.put_branch(old)

    def save_as(self, name, rename=False, swap=False):
        with self.do('branch:saveas') as txn:
            active = self.active()
            old = txn.get_branch(active.branch)
            old.sessions.remove(active.uuid)
            buuid = UUID()
            branch = objects.Branch(buuid, name, 'active', txn.prefix(), old.head, old.base, old.init, upstream=old.upstream, sessions=[active.uuid])
            active.branch = buuid
            txn.set_branch_uuid(name, branch.uuid)
            txn.put_session(active)
            txn.put_branch(branch)
            txn.put_branch(old)

    def open_branch(self, name, branch_uuid=None, session_uuid=None, create=False):
        with self.do_without_undo('branch:open') as txn:
            # check for >1
            branch_uuid = txn.get_branch_uuid(name) if not branch_uuid else branch_uuid
            if branch_uuid is None:
                if not create:
                    raise VexArgument('{} does not exist'.format(name))
                active = self.active()
                from_branch = active.branch
                from_commit = active.commit
                prefix = active.prefix
                branch = txn.create_branch(name, prefix, from_commit, from_branch, fork=False)
                branch_uuid = branch.uuid
            else:
                branch = txn.get_branch(branch_uuid)
            sessions = [txn.get_session(uuid) for uuid in branch.sessions]
            if session_uuid:
                sessions = [s for s in sessions if s.uuid == session_uuid]
            else:
                sessions = [s for s in sessions if s.state == 'attached']
            if not sessions:
                session = txn.create_session(branch_uuid, 'attached', branch.head)
                session_uuid = session.uuid
                branch.sessions.append(session_uuid)
                txn.put_branch(branch)
            elif len(sessions) == 1:
                session_uuid = sessions[0].uuid
            else:
                raise VexArgument('welp, too many attached sessions')
        with self.do_switch('branch:open {}'.format(name)) as txn:
            txn.switch_session(session_uuid)

    def new_branch(self, name, from_branch=None, from_commit=None, fork=False):
        with self.do_without_undo('branch:new') as txn:
            if txn.get_branch_uuid(name):
                raise VexArgument('branch {} already exists'.format(name))
            active = self.active()
            # bug: should pick commit from branch...
            if not from_branch: prefix = active.prefix
            if not from_branch: from_branch = active.branch
            if not from_commit: from_commit = active.commit
            if not prefix: prefix = txn.get_branch(from_branch).prefix
            branch = txn.create_branch(name, prefix, from_commit, from_branch, fork)
            session = txn.create_session(branch.uuid, 'attached', branch.head)

        with self.do_switch('branch:new {}'.format(name)) as txn:
            txn.set_branch_state(branch.uuid, "active")
            txn.switch_session(session.uuid)
            txn.set_branch_uuid(name, branch.uuid)

    def list_sessions(self):
        out = []
        active = self.active()
        branch = self.get_branch(active.branch)
        for session in branch.sessions:
            out.append(self.get_session(session))
        return out


    # debug:stash
    def stash(self, files=None):
        files = self.check_files(files) if files is not None else None
        with self.do_without_undo('debug:stash') as txn:
            files = [txn.full_to_repo_path(filename) for filename in files] if files else None
            self.stash_session(txn.active(), files)

