import importlib.metadata
import json

packages = ["scrapling", "browserforge", "curl_cffi", "playwright", "patchright",
            "PySide6", "dnspython", "msgspec", "aiohttp", "python-whois"]
print("PINS_JSON=" + json.dumps({name: importlib.metadata.version(name) for name in packages}))
try:
    print("BUILD_PIN=" + importlib.metadata.version("pyinstaller"))
except importlib.metadata.PackageNotFoundError:
    pass
