from os.path import join

Import("env")

platform = env.PioPlatform()
framework_dir = platform.get_package_dir("framework-arduinoadafruitnrf52")

if framework_dir:
    env.Append(
        LIBPATH=[
            join(
                framework_dir,
                "libraries",
                "Adafruit_nRFCrypto",
                "src",
                "cortex-m4",
                "fpv4-sp-d16-hard",
            )
        ]
    )
