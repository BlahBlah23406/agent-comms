from pathlib import Path

from setuptools import find_packages, setup

setup(
    name="agent-comms",
    version="1.0.0",
    description=(
        "Context handover and live relay for AI coding agents across sessions and machines"
    ),
    long_description=Path("README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    author="Shayaan Haq",
    url="https://github.com/BlahBlah23406/agent-comms",
    license="MIT",
    packages=find_packages(exclude=["tests", "tests.*", "docs", "docs.*"]),
    install_requires=[
        "pydantic>=2.0.0",
        "fastapi>=0.100.0",
        "uvicorn>=0.20.0",
        "websockets>=12.0",
    ],
    extras_require={"dev": ["pytest>=7.0.0"]},
    entry_points={
        "console_scripts": [
            "agent-comms = agent_comms.cli:main",
        ],
    },
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.9",
)
