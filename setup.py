from distutils.core import setup

setup(
    name='hatsu',
    version='0.1',
    description='A small cute nice asgi impl using wsproto and h11.',
    author='Arty',
    author_email='artythedev@gmail.com',
    url='https://github.com/ArtyTheDev/hatsu',
    packages=[
        "tinyws.core",
        "tinyws.protocols",
    ],
    python_requires=">=3.6",
    platforms="any",
)
