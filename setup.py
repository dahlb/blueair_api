from setuptools import setup, find_packages
import pathlib

here = pathlib.Path(__file__).parent.resolve()

# Get the long description from the README file
LONG_DESCRIPTION = (here / "README.md").read_text(encoding="utf-8")

VERSION = "1.8.1"

# Setting up
setup(
    name="blueair_api",
    version=VERSION,
    author="Brendan Dahl",
    author_email="dahl.brendan@gmail.com",
    description="Blueair Api Wrapper",
    long_description=LONG_DESCRIPTION,
    long_description_content_type="text/markdown",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=["aiohttp>=3.8.1"],
    keywords=["blueair", "api"],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Framework :: AsyncIO",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Operating System :: MacOS :: MacOS X",
    ],
    python_requires=">=3.9, <4",
    url="https://github.com/dahlb/blueair_api",
    project_urls={
        "Bug Reports": "https://github.com/dahlb/blueair_api/issues",
        "Source": "https://github.com/dahlb/blueair_api",
    },
)
