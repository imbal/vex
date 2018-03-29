from lib import Command

vexcmd = Command('vex', 'a database for files')

vex_init = vexcmd.subcommand('init')
vex_add = vexcmd.subcommand('add')
vex_remove = vexcmd.subcommand('remove')
vex_ignore = vexcmd.subcommand('ignore')

vexcmd.main(__name__)
