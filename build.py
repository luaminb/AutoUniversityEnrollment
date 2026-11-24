from __future__ import print_function

import os
import py_compile
import sys
import zipfile

ROOT = os.path.dirname(__file__)
SOURCE = os.path.join(ROOT, 'university_class_preparation.py')
OUTPUT = os.path.join(ROOT, 'UniversityClassPreparation.ts4script')
TEMP_PYC = os.path.join(ROOT, 'university_class_preparation.pyc')

if sys.version_info[:2] != (3, 7):
    raise SystemExit('Build requires Python 3.7.x. Detected: {}.{}.{}'.format(*sys.version_info[:3]))

py_compile.compile(SOURCE, cfile=TEMP_PYC, doraise=True)
with zipfile.ZipFile(OUTPUT, 'w', zipfile.ZIP_DEFLATED) as archive:
    archive.write(TEMP_PYC, 'university_class_preparation.pyc')
os.remove(TEMP_PYC)
print('Created: {}'.format(OUTPUT))
