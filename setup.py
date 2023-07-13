from setuptools import setup

setup(
    name="mytools",
    description="My Python Tools",
    version="0.0.1",
    author="Sam Mason",
    author_email="sam@samason.uk",
    py_modules=["mytools"],
    python_requires=">=3.7",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: POSIX",
    ],
    project_urls={
        "Homepage": "https://github.com/smason/mypytools",
        "Bug Tracker": "https://github.com/smason/mypytools/issues",
    },
)
