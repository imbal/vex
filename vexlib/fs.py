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


