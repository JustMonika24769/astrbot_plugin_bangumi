from setuptools import setup, find_packages
from setuptools.command.install import install
from setuptools.command.develop import develop
import subprocess
import sys
import os

def install_playwright():
    print("Installing Playwright browsers...")
    try:
        subprocess.check_call([sys.executable, '-m', 'playwright', 'install', 'chromium'])
    except subprocess.CalledProcessError as e:
        print(f"Failed to install Playwright browsers: {e}")
    except Exception as e:
        print(f"Error installing Playwright browsers: {e}")

class PostInstall(install):
    """
    运行pip install -r requirements.txt后自动安装browser
    """
    def run(self):
        install.run(self)
        install_playwright()

class PostDevelop(develop):
    """
    运行pip install -e . 后自动安装browser
    """
    def run(self):
        develop.run(self)
        install_playwright()

setup(
    name='astrbot_plugin_bangumi',
    version='1.2.0',
    author='united_pooh',
    description='A tiny cli tool with playwright',
    packages=find_packages(),           # 自动包含 mytool/
    python_requires='>=3.8',
    install_requires=['playwright>=1.44'],   # 运行时依赖
    entry_points={                       # 生成命令行
        'console_scripts': [
            'mytool = mytool.cli:main',
        ]
    },
    cmdclass={
        'install': PostInstall,
        'develop': PostDevelop,
    },    # 关键：挂钩 post-install
)