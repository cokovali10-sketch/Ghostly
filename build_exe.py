"""Build Ghostly EXE with PyInstaller."""
import subprocess, sys, os, shutil

def build():
    print("Building Ghostly EXE...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile", "--name", "Ghostly",
        "--add-data", "ghostly/templates;ghostly/templates",
        "--add-data", "ghostly/static;ghostly/static",
        "--add-data", "frontend;frontend",
        "--hidden-import", "aiosqlite",
        "--console",
        "launch.py"
    ]
    subprocess.run(cmd, check=True)
    os.makedirs("dist", exist_ok=True)
    if os.path.exists("dist/Ghostly.exe"):
        size = os.path.getsize("dist/Ghostly.exe") // (1024*1024)
        print(f"OK: dist/Ghostly.exe ({size} MB)")
    else:
        print("FAILED")

if __name__ == "__main__":
    build()
