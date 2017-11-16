# Always prefer setuptools over distutils
from setuptools import setup, find_packages
# To use a consistent encoding
from codecs import open
from os import path

here = path.abspath(path.dirname(__file__))

with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='githug_collaborator_manager',
    version='0.9',
    description='A tool to manage GitHub repo collaborators with files',
    long_description=long_description,
    url='https://github.com/gene1wood/github-collaborator-manager',
    author='Gene Wood',
    author_email='gene_wood@cementhorizon.com',
    license='GPL-3.0',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: System Administrators',
        'Topic :: Software Development :: Version Control :: Git',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
    ],
    keywords='aws lambda github collaborators',
    packages=find_packages(exclude=['contrib', 'docs', 'tests']),
    install_requires=[
        'agithub',
        'PyYAML',
        'python-dateutil']
)
