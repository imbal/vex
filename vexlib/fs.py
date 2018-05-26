"""

    - filename matching to gitignore style globs

    - listing directories recursively using said patterns

    - blob store (content addressable thingy)

    - file store (read write objects to named files, using rson to ser/deser)
    
    - shelling out to diff

"""
import fnmatch
import hashlib
import subprocess
import os
import os.path
import sys
import shutil
import fcntl
import sqlite3


from contextlib import contextmanager
from uuid import uuid4
from datetime import datetime, timezone

def UUID(): return str(uuid4())
def NOW(): return datetime.now(timezone.utc)

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

# History: Used to track undo/redo and changes to repository state

class HistoryStore:
    def __init__(self, file, codec):
        self.file = file
        self._db = None
        self.codec = codec
    
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
            return self.codec.parse(row[0])

    def next(self):
        c = self.db.cursor() 
        c.execute('select mode, value, current from next where id = 0')
        row = c.fetchone()
        if row:
            return str(row[0]), str(row[1]), str(row[2])

    def set_current(self, value):
        if not value: raise Exception()
        c = self.db.cursor() 
        buf = self.codec.dump(value)
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
            return (str(row[0]),self.codec.parse(row[1]))

    def put_entry(self, prev, obj):
        c=self.db.cursor()
        buf = self.codec.dump(obj)
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

# Filename patterns

from .errors import *

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
    p = subprocess.run(["diff", '-u', '--label', a, '--label', b, old, new], stdout=subprocess.PIPE, encoding='utf8')
    return p.stdout


def list_dir(dir, ignore, include):
    output = []
    scan = [dir]
    while scan:
        dir = scan.pop()
        with os.scandir(dir) as ls:
            for f in ls:
                p = f.path
                if not match_filename(p, f.name, ignore, include): continue
                if f.is_dir():
                    output.append(p)
                    scan.append(p)
                elif f.is_file():
                    output.append(p)
    return output
# Stores

class FileStore:
    def __init__(self, dir, codec, rawkeys=()):
        self.codec = codec
        self.dir = dir
        self.rawkeys = rawkeys

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
            if name in self.rawkeys:
                return ""
            return None
        with open(self.filename(name), 'rb') as fh:
            return self.parse(name, fh.read())
    def set(self, name, value):
        with open(self.filename(name),'w+b') as fh:
            fh.write(self.dump(name, value))
    def parse(self, name, value):
        if name in self.rawkeys:
            return value.decode('utf-8')
        else:
            return self.codec.parse(value)
    def dump(self, name, value):
        if name in self.rawkeys:
            if value:
                return value.encode('utf-8')
            else:
                return b""
        else:
            return self.codec.dump(value)

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

class Repo:
    def __init__(self, config_dir, codec):
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
        # diff
        return self.files.filename(addr)

    def copy_from_scratch(self, addr, path):
        self.scratch.make_copy(addr, path)

    def copy_from_file(self, addr, path):
        self.files.make_copy(addr, path)

    def copy_from_any(self, addr, path):
        if self.files.exists(addr):
            return self.files.make_copy(addr, path)

        self.scratch.make_copy(addr, path)


class GitRepo:
    def __init__(self, config_dir, codec):
        self.dir = os.path.join(config_dir, 'git')
        self.codec = codec
        self.env = {'GIT_DIR':self.dir}

    def makedirs(self):
        os.makedirs(self.dir, exist_ok=True)
        subprocess.run(['git', 'init', '-q', '--bare', self.dir])
    
    def clone(self, url):
        os.makedirs(self.dir, exist_ok=True)
        p = subprocess.run(['git', 'clone',  '-q', '--bare', url, self.dir])
        return p.stdout

    def branches(self):
        dir = os.path.join(self.dir, 'refs', 'heads')
        branches = {}
        print(dir)
        for name in os.listdir(dir):
            with open(os.path.join(dir, name)) as fh:
                branches[name] = fh.read().strip()
        with open(os.path.join(self.dir, 'packed-refs')) as fh:
            for line in fh.readlines():
                line = line.split(' ',1)
                if len(line) != 2:
                    continue
                value, name = line
                name = name.strip()
                if name.startswith('refs/heads/'):
                    branches[name.rsplit('/',1)[1]] = value

        return branches
                
    def head(self):
        with open(os.path.join(self.dir, 'HEAD')) as fh:
            head = fh.read().strip()
            if head.startswith('ref: refs/heads/'):
                return head.rsplit('/',1)[1]
            raise VexBug('welp')


    def push(self, url, remote_branch, commit):
        p = subprocess.run(['git', 'push', url, '{}:refs/heads/{}'.format(commit[4:], remote_branch)], stdout=subprocess.PIPE, encoding='utf-8', env=self.env)
        return p.stdout
        

    def addr_for_file(self, path):
        p = subprocess.run(['git', 'hash-object','-t','blob', path], stdout=subprocess.PIPE, encoding='utf-8', env=self.env)
        return "git:{}".format(p.stdout.strip())

    def cat_file(self, addr):
        p = subprocess.run(['git', 'cat-file', '-p', addr[4:]], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
        return p.stdout

    def get_commit(self, addr):
        out = self.codec.parse_git_inline(addr)
        if out is not None: return out
        p = subprocess.run(['git', 'cat-file',  'commit', addr[4:]], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
        return self.codec.parse_git_commit(p.stdout)

    def get_manifest(self, addr):
        out = self.codec.parse_git_inline(addr)
        if out is not None: return out
        p = subprocess.run(['git', 'cat-file', 'tree', addr[4:]], stdout=subprocess.PIPE,stderr=subprocess.PIPE, env=self.env)
        return self.codec.parse_git_tree(p.stdout)

    def copy_from_any(self, addr, path):
        with open(path, 'xb') as fh:
            p = subprocess.run(['git', 'cat-file', 'blob', addr[4:]], stdout=fh, stderr=subprocess.PIPE, env=self.env)

    def put_scratch_file(self, value, addr=None):
        p = subprocess.run(['git', 'hash-object', '-w','-t', 'blob',  value], stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', env=self.env)
        o = p.stdout.strip()
        return "git:{}".format(o)

    def put_scratch_commit(self, value):
        out = self.codec.dump_git_inline(value)
        if out: return out

        buf = self.codec.dump_git_commit(value) # -t commit
        p = subprocess.Popen(['git', 'hash-object', '-t', 'commit', '-w', '--stdin'], stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
        p.stdin.write(buf)
        p.stdin.close()
        o= p.stdout.read().decode('utf-8').strip()
        return "git:{}".format(o)

    def put_scratch_manifest(self, value):
        out = self.codec.dump_git_inline(value)
        if out: return out
        ### inlining changelog objects
        buf = self.codec.dump_git_tree(value) # -t blob
        p = subprocess.Popen(['git', 'hash-object', '-w', '-t', 'tree', '--stdin'], stdout=subprocess.PIPE, stdin=subprocess.PIPE,  stderr=subprocess.PIPE, env=self.env)
        p.stdin.write(buf)
        p.stdin.close()
        o= p.stdout.read().decode('utf-8').strip()
        return "git:{}".format(o)
        
    def get_scratch_commit(self, addr):
        return self.get_commit(addr)

    def get_scratch_manifest(self, addr):
        return self.get_manifest(addr)

    def add_commit_from_scratch(self, addr):
        return

    def add_manifest_from_scratch(self, addr):
        return

    def add_file_from_scratch(self, addr):
        return

    def copy_from_scratch(self, addr, path):
        return self.copy_from_any(addr, path)

    def copy_from_file(self, addr, path):
        return self.copy_from_any(addr, path)

    def get_file(self, addr):
        raise Exception() # Unused

    def get_scratch_file(self, addr):
        raise Exception() # Unused

    def get_file_path(self, addr):
        raise Exception('nope')

