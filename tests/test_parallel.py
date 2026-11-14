"""Parallel-safety tests: two pull_data runs at the same time (threads and real processes) must
never corrupt each other's outputs or the shared raw cache. Uses the fake earthaccess (no network)."""
import subprocess
import sys
import textwrap
import threading

import numpy as np
import xarray as xr

import common
import pull_data
from test_cache import FAKE_SRC, N, ROOT, T2M, WIND, env, leftovers, make_fake, read_out  # noqa: F401


def test_two_threads_same_collection_at_once(env, monkeypatch):
    """Two runs hitting the same empty cache at the same time (worst case): both outputs are
    complete and correct, every cached file is valid, no temp files are left."""
    fake, ea, _ = make_fake(delay=0.02)
    monkeypatch.setitem(sys.modules, "earthaccess", ea)
    errors = []

    def run(entry):
        try:
            pull_data.pull_collection([entry], "2001-01", None)
        except BaseException as ex:  # noqa: BLE001
            errors.append(ex)

    threads = [threading.Thread(target=run, args=(e,)) for e in (T2M, WIND)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    assert N <= len(fake.calls) <= 2 * N                  # duplicates allowed, corruption not
    for f in env.cache.iterdir():
        with xr.open_dataset(f, engine="h5netcdf") as ds:
            assert ds["T2M"].size == 20
    t = read_out(env, "FAKE_T2M.nc")
    assert [float(t.isel(time=k)[0, 0]) for k in range(N)] == list(range(280, 286))
    assert np.allclose(read_out(env, "FAKE_U50M+V50M.nc").values, 5)
    assert leftovers(env) == []


RUNNER = textwrap.dedent('''
    import sys, types
    sys.path.insert(0, sys.argv[1])
    src = types.ModuleType("fake_src"); exec(open(sys.argv[2]).read(), src.__dict__)
    fake = src.Fake(int(sys.argv[5]), delay=0.03)
    ea = types.ModuleType("earthaccess"); ea.search_data, ea.download = fake.search_data, fake.download
    sys.modules["earthaccess"] = ea
    from pathlib import Path
    import common, pull_data
    for m in (common, pull_data):
        m.RAW_DIR, m.PROCESSED_DIR = Path(sys.argv[3]) / "raw", Path(sys.argv[3]) / "processed"
    entry = {"T2M": {"id": "FAKE/T2M", "short_name": "FAKE", "variable": "T2M", "units": "K"},
             "WIND": {"id": "FAKE/WIND50M", "short_name": "FAKE", "variable": ["U50M", "V50M"],
                      "derive": "speed", "units": "m s-1"}}[sys.argv[4]]
    sys.exit(pull_data.pull_collection([entry], "2001-01", None))
''')


def test_two_processes_share_cache_safely(tmp_path):
    """Same as above with two real OS processes (like two terminals)."""
    (tmp_path / "fake.py").write_text(FAKE_SRC)
    (tmp_path / "runner.py").write_text(RUNNER)
    procs = [subprocess.Popen([sys.executable, str(tmp_path / "runner.py"), str(ROOT),
                               str(tmp_path / "fake.py"), str(tmp_path), which, str(N)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
             for which in ("T2M", "WIND")]
    outs = [p.communicate(timeout=120)[0] for p in procs]
    assert [p.returncode for p in procs] == [0, 0], outs
    proc = tmp_path / "processed"
    with xr.open_dataset(proc / "FAKE_T2M.nc", engine="h5netcdf") as ds:
        assert [float(ds["T2M"].isel(time=k)[0, 0]) for k in range(N)] == list(range(280, 286))
    with xr.open_dataset(proc / "FAKE_U50M+V50M.nc", engine="h5netcdf") as ds:
        assert np.allclose(ds["WIND50M"].values, 5)
    cache = tmp_path / "raw" / "FAKE"
    assert sorted(p.name for p in cache.iterdir()) == sorted(f"FAKE.2001{m:02d}.nc4" for m in range(1, N + 1))
    assert not [p for p in proc.iterdir() if ".part-" in p.name]


def test_categories_never_share_an_output_file():
    """Parallel streams run different categories; they must not write the same file."""
    owner = {}
    for cat, e in common.iter_entries(common.load_catalog()):
        path = common.processed_path(e)
        assert path not in owner, f"{e['id']} ({cat}) and {owner[path]} write the same file"
        owner[path] = f"{e['id']} ({cat})"
