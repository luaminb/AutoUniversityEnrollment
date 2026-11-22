from __future__ import print_function

import os
import py_compile
import sys
import zipfile

SOURCE = os.path.join(os.path.dirname(__file__), 'auto_university_enrollment.py')
OUTPUT = os.path.join(os.path.dirname(__file__), 'AutoUniversityEnrollment.ts4script')
TEMP_PYC = os.path.join(os.path.dirname(__file__), 'auto_university_enrollment.pyc')

if sys.version_info[:2] != (3, 7):
    raise SystemExit('Build requires Python 3.7.x. Detected: {}.{}.{}'.format(*sys.version_info[:3]))

py_compile.compile(SOURCE, cfile=TEMP_PYC, doraise=True)
with zipfile.ZipFile(OUTPUT, 'w', zipfile.ZIP_DEFLATED) as archive:
    archive.write(TEMP_PYC, 'auto_university_enrollment.pyc')
os.remove(TEMP_PYC)
print('Created: {}'.format(OUTPUT))
