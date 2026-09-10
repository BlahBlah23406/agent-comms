from setuptools import setup, find_packages

setup(
    name="agent-comms",
    version="1.0.0",
    description="Universal Agent Handover & Live Relay Suite for Multi-Machine AI Collaboration",
    author="Antigravity Team",
    packages=find_packages(),
    install_requires=[
        "pydantic>=2.0.0",
        "fastapi>=0.100.0",
        "uvicorn>=0.20.0",
        "websockets>=12.0",
    ],
    entry_points={
        "console_scripts": [
            "agent-comms = agent_comms.cli:main",
        ],
    },
    python_requires=">=3.9",
)
