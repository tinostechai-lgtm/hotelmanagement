"""Make release APKs use the committed Servora key, so every new version installs over the old one.

Works on the Groovy (build.gradle) and Kotlin (build.gradle.kts) files that `flutter create` generates.
Run from mobile/: python3 tool/patch_android_signing.py
"""
from pathlib import Path

KEYSTORE = "../../signing/servora-debug.keystore"  # relative to android/app

kts = Path("android/app/build.gradle.kts")
groovy = Path("android/app/build.gradle")

if kts.exists():
    p, s = kts, kts.read_text()
    block = (
        "    signingConfigs {\n"
        '        create("servora") {\n'
        f'            storeFile = file("{KEYSTORE}")\n'
        '            storePassword = "android"\n'
        '            keyAlias = "androiddebugkey"\n'
        '            keyPassword = "android"\n'
        "        }\n"
        "    }\n\n"
        "    buildTypes {"
    )
    old, new = 'signingConfig = signingConfigs.getByName("debug")', 'signingConfig = signingConfigs.getByName("servora")'
elif groovy.exists():
    p, s = groovy, groovy.read_text()
    block = (
        "    signingConfigs {\n"
        "        servora {\n"
        f'            storeFile file("{KEYSTORE}")\n'
        '            storePassword "android"\n'
        '            keyAlias "androiddebugkey"\n'
        '            keyPassword "android"\n'
        "        }\n"
        "    }\n\n"
        "    buildTypes {"
    )
    old, new = "signingConfig = signingConfigs.debug", "signingConfig = signingConfigs.servora"
else:
    raise SystemExit("android/app/build.gradle(.kts) not found - run flutter create first")

if new not in s:
    assert "    buildTypes {" in s and old in s, f"unexpected {p} layout"
    s = s.replace("    buildTypes {", block, 1).replace(old, new)
    p.write_text(s)
print(f"{p}: release builds signed with the Servora key")
