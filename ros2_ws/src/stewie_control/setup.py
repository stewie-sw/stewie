from setuptools import find_packages, setup
package_name = "stewie_control"
setup(
    name=package_name, version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"], zip_safe=True,
    maintainer="STEWIE", maintainer_email="dev@stewie.space",
    description="control node: local_traj -> /cmd_vel (bounded, AG-08/SF-01)", license="SEE LICENSE",
    entry_points={"console_scripts": ["control = stewie_control.node:main"]},
)
