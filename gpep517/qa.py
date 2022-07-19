import importlib.util
import os
import os.path


def qa_verify_pyc(destdir, sitedirs):
    missing_pyc = []
    invalid_pyc = []
    stray_pyc = []

    for sitedir in sitedirs:
        top_path = destdir + sitedir
        if not os.path.isdir(top_path):
            continue

        py_files = set()
        pyc_files = set()

        for path, dirs, files in os.walk(top_path):
            for fn in files:
                if fn.endswith(".py"):
                    py_files.add(os.path.join(path, fn))
                elif fn.endswith((".pyc", ".pyo")):
                    pyc_files.add(os.path.join(path, fn))

        for py in py_files:
            for opt in ("", 1, 2):
                pyc = importlib.util.cache_from_source(py, optimization=opt)
                # 1. check for missing .pyc files
                if pyc not in pyc_files:
                    missing_pyc.append((pyc, py))
                    continue

                pyc_files.remove(pyc)
                # 2. check magic
                with open(pyc, "rb") as f:
                    magic = f.read(4)
                    if magic != importlib.util.MAGIC_NUMBER:
                        invalid_pyc.append((pyc, py))
                        continue

        # 3. any remaining .pyc files are stray
        stray_pyc.extend((pyc,) for pyc in pyc_files)

    return {
        "missing": missing_pyc,
        "invalid": invalid_pyc,
        "stray": stray_pyc,
    }
