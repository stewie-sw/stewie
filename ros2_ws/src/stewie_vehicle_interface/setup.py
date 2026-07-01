from setuptools import find_packages, setup
package_name = "stewie_vehicle_interface"
setup(
    name=package_name, version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"], zip_safe=True,
    maintainer="STEWIE", maintainer_email="dev@stewie.space",
    description="vehicle interface: /cmd_vel -> hardware + wheel odom egress", license="SEE LICENSE",
    test_suite="test",
    entry_points={"console_scripts": ["vehicle_interface = stewie_vehicle_interface.node:main"]},
)
