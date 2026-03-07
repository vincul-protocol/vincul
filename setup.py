from setuptools import setup, find_packages

setup(
    name="vincul",
    version="0.2.0",
    package_dir={
        "": "src",             # vincul package lives under src/
        "samples": "samples",  # samples package lives at project root
        "samples.cross_vendor_tool_marketplace": "samples/cross_vendor_tool_marketplace",
    },
    packages=(
        find_packages(where="src", include=["vincul*"])
        + find_packages(where=".", include=["samples*"])
    ),
    package_data={"samples": ["**/spec.md"]},
    install_requires=["cryptography>=41.0"],
    extras_require={
        "dev": ["pytest>=8.0", "pytest-asyncio>=0.23"],
        "server": ["fastapi>=0.110", "uvicorn[standard]>=0.27", "websockets>=12.0"],
        "samples": [],
    },
)
