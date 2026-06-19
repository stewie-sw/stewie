from setuptools import find_packages, setup
import glob
package_name = "stewie_bringup"
setup(name=package_name, version="0.1.0", packages=find_packages(exclude=["test"]),
      data_files=[("share/ament_index/resource_index/packages", ["resource/" + package_name]),
                  ("share/" + package_name, ["package.xml"]),
                  ("share/" + package_name + "/launch", glob.glob("launch/*"))],
      install_requires=["setuptools"], zip_safe=True, maintainer="STEWIE",
      maintainer_email="dev@stewie.space", description="STEWIE bring-up", license="SEE LICENSE",
      entry_points={"console_scripts": []})
