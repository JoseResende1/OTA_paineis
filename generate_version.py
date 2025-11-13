import os, json, hashlib
import argparse

FILES = [
    "config.py",
    "controller.py",
    "drv887x.py",
    "main.py",
    "mcp23017.py",
    "rs485.py"
]

VERSION_FILE = "version.json"

def sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()

def load_version():
    if not os.path.exists(VERSION_FILE):
        return "1.0.0"
    try:
        with open(VERSION_FILE, "r") as f:
            data = json.load(f)
            return data.get("version", "1.0.0")
    except:
        return "1.0.0"

def bump_version(version, mode):
    major, minor, patch = map(int, version.split("."))

    if mode == "major":
        major += 1
        minor = 0
        patch = 0
    elif mode == "minor":
        minor += 1
        patch = 0
    else:  # patch
        patch += 1

    return f"{major}.{minor}.{patch}"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--major", action="store_true")
    parser.add_argument("--minor", action="store_true")
    args = parser.parse_args()

    mode = "patch"
    if args.major: mode = "major"
    if args.minor: mode = "minor"

    print("\n=== Gerar version.json ===")

    old_version = load_version()
    new_version = bump_version(old_version, mode)

    print(f"\nVersão anterior: {old_version}")
    print(f"Nova versão:     {new_version}\n")

    hashes = {}

    for fname in FILES:
        if os.path.exists(fname):
            print(f" - Hashing {fname}")
            hashes[fname] = sha256_of_file(fname)
        else:
            print(f" - Ficheiro não encontrado: {fname}")

    output = {"version": new_version, "files": hashes}

    with open(VERSION_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print("\n✔ version.json atualizado com sucesso!")
    print("Ficheiros incluídos:\n")
    for k, v in hashes.items():
        print(f" - {k}: {v}")

if __name__ == "__main__":
    main()
