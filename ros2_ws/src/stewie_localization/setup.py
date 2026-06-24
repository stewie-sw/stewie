from setuptools import find_packages, setup
package_name = "stewie_localization"
setup(
    name=package_name, version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"], zip_safe=True,
    maintainer="STEWIE", maintainer_email="dev@stewie.space",
    description="localization node: odom/imu/points + Navigation factors -> /stewie/odom (AS-08/09)", license="SEE LICENSE",
    entry_points={"console_scripts": ["localization = stewie_localization.node:main"]},
)
