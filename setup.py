"""Ship executable examples and the generic VASP template in application wheels."""

from setuptools import setup
from setuptools.command.build_py import build_py


class ApplicationBuild(build_py):
    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        if package == "examples":
            return [
                m
                for m in modules
                if m[1]
                in {
                    "__init__",
                    "demo",
                    "gibbs_demo",
                    "phase_diagram_demo",
                    "parameter_fit_demo",
                }
            ]
        return modules


setup(cmdclass={"build_py": ApplicationBuild})
