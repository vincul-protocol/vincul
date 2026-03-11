from setuptools import setup, find_packages

setup(
    name="vincul",
    version="0.2.0",
    package_dir={"": "src"},
    packages=find_packages(where="src", include=["vincul*"]),
    install_requires=["cryptography>=41.0"],
    extras_require={
        "dev": ["pytest>=8.0", "pytest-asyncio>=0.23"],
        "server": ["fastapi>=0.110", "uvicorn[standard]>=0.27", "websockets>=12.0", "pydantic>=2.0"],
        "samples": [
            "strands-agents>=1.0",
            "botocore>=1.30",
            "langgraph>=0.2",
            "langchain-core>=0.3",
            "langchain-aws>=0.2",
        ],
    },
)
