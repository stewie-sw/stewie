from setuptools import find_packages, setup
package_name = "stewie_executive"
setup(
    name=package_name, version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"], zip_safe=True,
    maintainer="STEWIE", maintainer_email="dev@stewie.space",
    description="mission_executive node: monitor faults/cov/acks/reservations/acceptance -> "
                "/stewie/exec/decision (continue|pause|replan|relocalize|reverse|safe, AS-13)",
    license="SEE LICENSE",
    test_suite="test",
    entry_points={"console_scripts": ["executive = stewie_executive.node:main"]},
)
