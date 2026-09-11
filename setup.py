"""
Ghostly Analytics - Privacy-first web analytics platform.

Setup script for ghostly-analytics package.
"""

from setuptools import setup, find_packages
from pathlib import Path

this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding="utf-8")

setup(
    name="ghostly-analytics",
    version="1.0.0",
    author="Ghostly Contributors",
    author_email="ghostly@example.com",
    description="Privacy-first web analytics platform. No cookies, no tracking, just truth.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/ghostly",
    project_urls={
        "Bug Tracker": "https://github.com/yourusername/ghostly/issues",
        "Documentation": "https://github.com/yourusername/ghostly#readme",
        "Source Code": "https://github.com/yourusername/ghostly",
    },
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "aiohttp>=3.9.0",
        "aiosqlite>=0.19.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "pytest-cov>=4.0.0",
            "ruff>=0.1.0",
            "mypy>=1.0.0",
            "pre-commit>=3.0.0",
        ],
        "build": [
            "pyinstaller>=6.0.0",
            "build>=1.0.0",
            "twine>=4.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "ghostly=ghostly.__main__:main",
        ],
    },
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: Dynamic Content",
        "Topic :: Scientific/Engineering :: Information Analysis",
        "Topic :: Security",
        "Typing :: Typed",
    ],
    keywords="analytics privacy gdpr compliance self-hosted open-source",
    license="MIT",
)
