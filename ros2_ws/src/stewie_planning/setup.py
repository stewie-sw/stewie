from setuptools import find_packages, setup
package_name = "stewie_planning"
setup(
    name=package_name, version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"], zip_safe=True,
    maintainer="STEWIE", maintainer_email="dev@stewie.space",
    description="planning node: costmap + Plan-IR -> path/local_traj (AS-11/AS-12)", license="SEE LICENSE",
    entry_points={"console_scripts": ["planning = stewie_planning.node:main"]},
)
