"""Packs dist/ into release/ZeroCompanySaveFix-<version>.zip with the game's folder layout.
Usage: python package.py <version>   (run build.sh first)"""
import os, sys, zipfile, hashlib

here = os.path.dirname(os.path.abspath(__file__))
version = sys.argv[1].lstrip("v") if len(sys.argv) > 1 else "dev"
os.makedirs(os.path.join(here, "release"), exist_ok=True)
out = os.path.join(here, "release", f"ZeroCompanySaveFix-{version}.zip")
prefix = "SWZeroCompany/Binaries/Win64/"  # forward slashes so Linux / Steam Machine unzip works
files = [("dist/version.dll", "version.dll"),
         ("dist/SWZeroCompanyFix.ini", "SWZeroCompanyFix.ini"),
         ("README.md", "SWZeroCompanyFix-README.md")]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for src, name in files:
        z.write(os.path.join(here, src), prefix + name)
digest = hashlib.sha256(open(out, "rb").read()).hexdigest()
print(out)
print("sha256", digest)
