
from setuptools import setup

version = "v0.8.4-fsmt"
filename = "v0.8.4-fsmt"

setup(name="pyscxml",
      version=filename,
      description="A pure Python SCXML parser/interpreter",
      long_description="Use PySCXML to parse and execute an SCXML document. PySCXML aims for full compliance with the W3C standard. Features include but are not limited to multisession support, HTTP serving with easily configured REST service configuration and complete HTTP IO processor. Supports the ECMAScript datamodel through PyV8 and XPATH through lxml.",
      author="Johan Roxendal",
      author_email="johan@roxendal.com",
      url="http://github.com/jroxendal/PySCXML",
      download_url="http://github.com/jroxendal/PySCXML",
      packages=["scxml"],
      package_dir={"" : "src"},
      license="LGPLv3",
      classifiers=[
          'Development Status :: 4 - Beta',
          'Environment :: Console',
          'Environment :: Web Environment',
          'Intended Audience :: Developers',
          'License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL)',
          'Operating System :: OS Independent',
          'Programming Language :: Python',
          'Topic :: Communications :: Telephony',
          'Topic :: Internet :: WWW/HTTP',
          'Topic :: Internet :: WWW/HTTP :: WSGI',
          'Topic :: Software Development :: Interpreters',
          'Topic :: Software Development :: Libraries :: Python Modules',
          'Topic :: Text Processing :: Markup :: XML'
          
      ],
      install_requires=['Louie', 'eventlet', 'suds', 'restlib', "lxml"]
     )
