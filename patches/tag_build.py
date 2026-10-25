"""Mark the build as modified in the UART boot banner of both cores.

Both cores print "FW version: %d.%d.%d @ gd5b5810" at boot over the debug UART.
We change the git tag to "re-patch". Nothing user-visible changes; the point is a
first hardware flash that only tests whether the bootloader accepts an image we
built with our own CRCs.
"""
TARGET = 'v1.3.0'
SUMMARY = 'Change the boot-banner git tag in M4 and M7 to "re-patch"'
RISK = 'none'

OLD = b'gd5b5810'
NEW = b're-patch'


def apply(p):
    for seg in ('m4', 'm7'):
        data = p.read(seg, p.img.segment(seg).addr, len(p.img.segment(seg).data))
        # only the format-string occurrence ("... @ gd5b5810"); leave __FVERSION__ alone
        idx = data.find(b'@ ' + OLD)
        if idx < 0:
            raise RuntimeError(f'banner not found in {seg}')
        addr = p.img.segment(seg).addr + idx + 2
        p.write(seg, addr, NEW, OLD, f'{seg} boot banner tag')
