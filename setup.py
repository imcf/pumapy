"""Setup for the pumapy package."""

from setuptools import setup

setup(
    name='pumapy',
    version='0.0.1',
    packages=['pumapy'],
    package_dir={'': 'src'},
    url='https://github.com/imcf/pumapy',
    license='GPLv3',
    author='Niko Ehrenfeuchter',
    author_email='nikolaus.ehrenfeuchter@unibas.ch',
    description="A Python 2 package to communicate with Stratocore's PUMAPI.",
    install_requires=['requests']
)
