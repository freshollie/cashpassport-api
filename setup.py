from setuptools import setup

setup(name='cashpassport-api',
      version='1.0',
      description='Python server which scrapes cashpassport and provides a simple API',
      author='Oliver Bell',
      author_email='freshollie@gmail.com',
      url='https://github.com/freshollie/cashpassport-api',
      install_requires=['mechanicalsoup',
                        'beautifulsoup4',
                        'python-dateutil',
                        'flask']
     )