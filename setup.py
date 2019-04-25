from os.path import abspath, dirname, join
from setuptools import setup

# Read the README markdown data from README.md
with open(abspath(join(dirname(__file__), 'README.md')), 'rb') as readmeFile:
	__readme__ = readmeFile.read().decode('utf-8')

setup(
	name='deepdrive-ci',
	version='0.0.1',
	description='Common code for Deepdrive CI scripts',
	long_description=__readme__,
	long_description_content_type='text/markdown',
	classifiers=[
		'License :: OSI Approved :: MIT License',
		'Programming Language :: Python :: 3.5',
		'Programming Language :: Python :: 3.6',
		'Programming Language :: Python :: 3.7',
		'Topic :: Software Development :: Build Tools',
		'Environment :: Console'
	],
	keywords='deepdrive ci',
	url='http://github.com/deepdrive/deepdrive-ci',
	author='Deepdrive',
	author_email='craig@deepdrive.io',
	license='MIT',
	packages=['deepdrive_ci'],
	zip_safe=True,
	python_requires = '>=3.5',
	install_requires = [
		'arrow',
		'setuptools>=38.6.0',
		'tenacity',
		'termcolor',
		'twine>=1.11.0',
		'ue4-ci-helpers>=0.0.6',
		'wheel>=0.31.0'
	]
)
