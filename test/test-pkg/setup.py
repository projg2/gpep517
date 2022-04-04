from setuptools import setup

setup(
    name="test",
    version="1",
    description="a test wheel",
    packages=["testpkg"],
    package_data={
        "testpkg": ["datafile.txt"],
    },
    include_package_data=True,
    scripts=["oldscript"],
    entry_points={
        "console_scripts": [
            "newscript = testpkg:entry_point",
        ],
    },
    data_files=[
        ("share/test", ["testpkg/datafile.txt"]),
    ],
    headers=['test.h'],
)
