"""Builds tiny fake Live projects for the tests and the demo. No real audio, no real sets."""
import gzip
import os

REF = """\
\t\t\t<FileRef>
\t\t\t\t<RelativePathType Value="3" />
\t\t\t\t<RelativePath Value="{rel}" />
\t\t\t\t<Path Value="{path}" />
\t\t\t\t<Type Value="2" />
\t\t\t\t<LivePackName Value="" />
\t\t\t\t<LivePackId Value="" />
\t\t\t\t<OriginalFileSize Value="{size}" />
\t\t\t\t<OriginalCrc Value="1234" />
\t\t\t</FileRef>
"""

LEGACY_REF = """\
\t\t\t<FileRef>
\t\t\t\t<HasRelativePath Value="true" />
\t\t\t\t<RelativePathType Value="3" />
\t\t\t\t<Name Value="old.wav" />
\t\t\t\t<Type Value="1" />
\t\t\t</FileRef>
"""


def make_als(path, refs, legacy=0):
    """refs: [(original_path, size)] -> gzip'd .als with one FileRef per entry."""
    body = ''.join(
        REF.format(rel='../../gone/' + os.path.basename(p.replace('\\', '/')), path=p, size=s)
        for p, s in refs) + LEGACY_REF * legacy
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<Ableton MajorVersion="5" Creator="Ableton Live 12.2.1">\n\t<LiveSet>\n'
           + body + '\t</LiveSet>\n</Ableton>\n')
    with gzip.open(path, 'wb') as f:
        f.write(xml.encode('utf-8'))


def write(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'\0' * size)
    return path
