"""Stamp a build so a modded unit can be identified.

  version_stamp:<tag>        tag: up to 11 printable ASCII characters, e.g. kiteless0.1

* `__FVERSION__` record (both cores): the git-hash field becomes <tag>. The bootloader
  writes this into INFO.TXT on the SD card ("Current Controller (CM4) version:
  1.3.0 - <tag>"). The version numbers are left alone, so they still name the official
  base firmware. The apps never read this record.
* UART boot banner (both cores): repointed to a new string with `banner` appended
  (default: "+ <tag>"), keeping the original version and git hash.

Found by marker, not address, so it applies to any official version.
"""
import struct

TARGET = None  # any version
SUMMARY = 'Identify the build: __FVERSION__ tag (shows in INFO.TXT) + boot banner'
RISK = 'low'

MARKER = b'__FVERSION__'
GIT_FIELD = 12          # bytes, NUL padded
BANNER_PREFIX = b'FW version: %d.%d.%d @ '


def _find_one(data, needle, what):
    i = data.find(needle)
    if i < 0 or data.find(needle, i + 1) >= 0:
        raise ValueError(f'{what}: expected exactly one occurrence')
    return i


def apply(p, arg=None, banner=None):
    tag = (arg or '').encode('ascii')
    if not 1 <= len(tag) < GIT_FIELD or not all(0x21 <= c < 0x7f for c in tag):
        raise ValueError(f'version_stamp needs a tag of 1-{GIT_FIELD - 1} printable characters')
    banner = (banner or f'+ {arg}').encode('ascii')
    for seg in ('m4', 'm7'):
        s = p.img.segment(seg)
        data = p.read(seg, s.addr, len(s.data))
        rec = _find_one(data, MARKER, f'{seg} __FVERSION__')
        major, minor, patch = struct.unpack_from('<3I', data, rec + len(MARKER))
        # sanity check that this is the right record; official 1.1.1 says 1.1.0 here
        if (major, minor) != (p.img.major, p.img.minor):
            raise ValueError(f'{seg} __FVERSION__ {major}.{minor}.{patch} != image header v{p.img.version}')
        field = rec + len(MARKER) + 12
        old = data[field:field + GIT_FIELD]
        p.write(seg, s.addr + field, tag.ljust(GIT_FIELD, b'\0'), old, f'{seg} __FVERSION__ tag -> {arg}')

        b = _find_one(data, BANNER_PREFIX, f'{seg} boot banner')
        end = data.index(b'\0', b)
        text = data[b:end].rstrip(b'\r\n')
        nl = data[b + len(text):end]
        new = text + b' ' + banner + nl + b'\0'
        addr = p.append(seg, new, f'{seg} boot banner string')
        refs = [i for i in range(0, len(data) - 3, 4) if struct.unpack_from('<I', data, i)[0] == s.addr + b]
        if len(refs) != 1:
            raise ValueError(f'{seg} boot banner: expected one literal reference, found {len(refs)}')
        p.write_u32(seg, s.addr + refs[0], addr, s.addr + b, f'{seg} boot banner -> stamped string')
