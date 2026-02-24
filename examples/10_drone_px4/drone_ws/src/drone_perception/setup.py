import os
from glob import glob

from setuptools import find_packages, setup

package_name = "drone_perception"

setup(
    name=package_name,
    version="0.0.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="husl-ai",
    maintainer_email="husl-ai@todo.todo",
    description="Drone perception tools for static 3D object grounding",
    license="TODO: License declaration",
    extras_require={"test": ["pytest"]},
    entry_points={
        "console_scripts": [
            "object_grounding = drone_perception.object_grounding_node:main",
        ],
    },
)
