from setuptools import setup

setup(name='erum_data_data',
      version='0.1',
      description='setup for downloading data comparison data',
      url='https://github.com/erikbuh/erum_data_data',
      author='Erik Buhmann',
      author_email='erik.buhmann@uni-hamburg.de',
      license='MIT',
      packages=['erum_data_data'],
      install_requires=[
         'numpy >= 1.14.0',
         'six >= 1.10.0',
      ],
      zip_safe=False)
