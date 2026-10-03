"""Creates a throw-away demo project in /tmp/relink-demo for the terminal GIF."""
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tests'))
import fixtures as fx  # noqa: E402

root = '/tmp/relink-demo'
shutil.rmtree(root, ignore_errors=True)
proj = os.path.join(root, 'Night Drive Project')
lib = os.path.join(root, 'library')
os.makedirs(proj)
old = '/Users/me/Dropbox/Samples/'
files = [('kick_deep_01.wav', 88200), ('hat_closed_tight.wav', 22050), ('snare_clap_layer.wav', 44100),
         ('riser_long_16bars.wav', 352800), ('vocal_chop_dm.wav', 176400)]
for i, (name, size) in enumerate(files[:4]):
    fx.write(os.path.join(lib, 'Pack %d' % (i % 2 + 1), name), size)
fx.make_als(os.path.join(proj, 'Night Drive.als'), [(old + n, s) for n, s in files])
