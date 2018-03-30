#!/usr/bin/env python3
from cli import Command

vexcmd = Command('vex', 'a database for files')

vex_init = vexcmd.subcommand('init')
vex_add = vexcmd.subcommand('add')

@vex_add.run("--all? file...")
def Add(all, file):
    pass

vex_remove = vexcmd.subcommand('remove')
vex_ignore = vexcmd.subcommand('ignore')

vex_undo = vexcmd.subcommand('undo')
@vex_undo.run()
def Undo():
    pass

vex_redo = vexcmd.subcommand('redo')
@vex_redo.run()
def Redo():
    pass


vexcmd.main(__name__)
