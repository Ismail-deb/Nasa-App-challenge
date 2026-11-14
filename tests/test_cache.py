"""Raw-cache and resume tests for pull_data, using a FAKE earthaccess (no network).
The fake writes small synthetic MERRA-2-like granules (T2M, U50M, V50M)."""
import os
import sys
import textwrap
import types
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

import common
import pull_data

ROOT = Path(__file__).resolve().parent.parent
N = 6  # granules (months) in the fake collection

FAKE_SRC = textwrap.dedent('''
    import os, time
    import numpy as np, pandas as pd, xarray as xr

    class Granule:
        def __init__(self, k, size_mb=None):
            self.k = k
            self.month = pd.Timestamp("2001-01-01") + pd.DateOffset(months=k)
            self.name = f"FAKE.{self.month:%Y%m}.nc4"
            self.size = size_mb              # like earthaccess: MB, may be absent
        def data_links(self):
            return [f"https://example.invalid/data/{self.name}"]

    def write_granule(path, g):
        lat, lon = np.arange(4.0), np.arange(5.0)
        ones = np.ones((1, 4, 5), "float32")
        xr.Dataset(
            {"T2M": (("time", "lat", "lon"), ones * (280 + g.k)),
             "U50M": (("time", "lat", "lon"), ones * 3),
             "V50M": (("time", "lat", "lon"), ones * 4)},
            coords={"time": [g.month.to_datetime64()], "lat": lat, "lon": lon},
        ).to_netcdf(path, engine="h5netcdf")

    class Fake:
        def __init__(self, n, delay=0.0):
            self.granules = [Granule(k) for k in range(n)]
            self.calls, self.fail_at, self.delay = [], None, delay
        def search_data(self, **kw):
            return list(self.granules)
        def download(self, granules, local_path):
            out = []
            for g in granules:
                if self.fail_at is not None and len(self.calls) + 1 >= self.fail_at:
                    raise KeyboardInterrupt("simulated Ctrl+C / killed process")
                self.calls.append(g.name)
                p = os.path.join(local_path, g.name)
                write_granule(p, g)
                if self.delay:
                    time.sleep(self.delay)
                out.append(p)
            return out
''')

T2M = {"id": "FAKE/T2M", "short_name": "FAKE", "variable": "T2M", "units": "K"}
WIND = {"id": "FAKE/WIND50M", "short_name": "FAKE", "variable": ["U50M", "V50M"],
        "derive": "speed", "units": "m s-1"}


def make_fake(n=N, delay=0.0):
    mod = types.ModuleType("fake_earthaccess_src")
    exec(FAKE_SRC, mod.__dict__)
    fake = mod.Fake(n, delay)
    ea = types.ModuleType("earthaccess")
    ea.search_data, ea.download = fake.search_data, fake.download
    return fake, ea, mod


@pytest.fixture()
def env(tmp_path, monkeypatch):
    raw, proc = tmp_path / "raw", tmp_path / "processed"
    for mod in (common, pull_data):
        monkeypatch.setattr(mod, "RAW_DIR", raw, raising=False)
        monkeypatch.setattr(mod, "PROCESSED_DIR", proc, raising=False)
    fake, ea, src = make_fake()
    monkeypatch.setitem(sys.modules, "earthaccess", ea)
    return types.SimpleNamespace(raw=raw, proc=proc, fake=fake, src=src, cache=raw / "FAKE")


def read_out(env, name):
    with xr.open_dataset(env.proc / name, engine="h5netcdf") as ds:
        return ds[list(ds.data_vars)[0]].load()


def leftovers(env):
    return sorted(p.name for d in (env.cache, env.proc) if d.exists()
                  for p in d.iterdir() if p.name.startswith(".dl-") or ".part-" in p.name)


def test_cache_shared_between_categories(env):
    """weather_climate then atmosphere_solar style: second run downloads nothing."""
    assert pull_data.pull_collection([T2M], "2001-01", None) == 0
    assert len(env.fake.calls) == N
    assert pull_data.pull_collection([WIND], "2001-01", None) == 0
    assert len(env.fake.calls) == N                       # all from cache
    t = read_out(env, "FAKE_T2M.nc")
    assert t.sizes["time"] == N and float(t.isel(time=5)[0, 0]) == 285
    assert np.allclose(read_out(env, "FAKE_U50M+V50M.nc").values, 5)
    assert leftovers(env) == []


def test_interrupted_run_resumes_from_cache(env):
    env.fake.fail_at = 4                                  # killed during the 4th download
    with pytest.raises(KeyboardInterrupt):
        pull_data.pull_collection([T2M], "2001-01", None)
    assert not (env.proc / "FAKE_T2M.nc").exists()        # no half-written output
    assert leftovers(env) == []                           # temp output + temp download removed
    assert sorted(p.name for p in env.cache.iterdir()) == [f"FAKE.20010{m}.nc4" for m in (1, 2, 3)]

    env.fake.fail_at = None
    before = len(env.fake.calls)
    assert pull_data.pull_collection([T2M], "2001-01", None) == 0
    assert len(env.fake.calls) - before == N - 3          # only the missing months
    t = read_out(env, "FAKE_T2M.nc")
    assert t.sizes["time"] == N and [float(t.isel(time=k)[0, 0]) for k in range(N)] == list(range(280, 286))


def test_truncated_or_junk_cache_file_is_redownloaded(env):
    pull_data.pull_collection([T2M], "2001-01", None)
    trunc, junk = env.cache / "FAKE.200102.nc4", env.cache / "FAKE.200104.nc4"
    data = trunc.read_bytes()
    trunc.write_bytes(data[: len(data) // 2])             # partial file
    junk.write_bytes(b"not a netcdf file")                # corrupted file
    before = len(env.fake.calls)
    assert pull_data.pull_collection([T2M], "2001-01", None) == 0
    assert sorted(env.fake.calls[before:]) == ["FAKE.200102.nc4", "FAKE.200104.nc4"]
    t = read_out(env, "FAKE_T2M.nc")
    assert [float(t.isel(time=k)[0, 0]) for k in range(N)] == list(range(280, 286))


def test_file_smaller_than_metadata_is_partial(env, tmp_path):
    g = env.src.Granule(0)
    p = tmp_path / g.name
    env.src.write_granule(p, g)
    real_mb = os.path.getsize(p) / 1024 / 1024
    g.size = real_mb                                      # matches -> ok
    assert pull_data.size_ok(p, g)
    g.size = real_mb * 2                                  # NASA says it should be twice as big
    assert not pull_data.size_ok(p, g)
    with pytest.raises(OSError, match="partial"):
        pull_data.read_granule(p, None, [T2M], g)
    g.size = None                                         # unknown size -> rely on full read
    assert pull_data.size_ok(p, g)


def test_stale_temp_files_removed_but_fresh_ones_kept(env):
    env.cache.mkdir(parents=True)
    old, new = env.cache / ".dl-1-aaaa", env.cache / ".dl-2-bbbb"
    old.mkdir(), new.mkdir()
    t = old.stat().st_mtime - pull_data.STALE_SECONDS - 10
    os.utime(old, (t, t))
    pull_data.remove_stale_temp(env.cache)
    assert not old.exists() and new.exists()


def test_cleanup_removes_only_this_categorys_cache(env):
    pull_data.pull_collection([T2M], "2001-01", None)
    other = env.raw / "OTHER"
    other.mkdir()
    (other / "x.nc4").write_bytes(b"x")
    pull_data.cleanup_cache([T2M])
    assert not env.cache.exists() and other.exists()


def test_transient_access_denied_is_retried_not_treated_as_corrupt(env, monkeypatch):
    """Windows briefly denies opening a file being renamed by another process: retry, keep file."""
    pull_data.pull_collection([T2M], "2001-01", None)
    real_open, calls = pull_data.open_granule, {"n": 0}

    def flaky_open(path, group):
        calls["n"] += 1
        if calls["n"] <= 2:                       # first two opens denied, then fine
            raise OSError(13, "[Errno 13] Unable to synchronously open file")
        return real_open(path, group)

    monkeypatch.setattr(pull_data, "open_granule", flaky_open)
    monkeypatch.setattr("time.sleep", lambda s: None)
    before = len(env.fake.calls)
    assert pull_data.pull_collection([T2M], "2001-01", None) == 0
    assert len(env.fake.calls) == before                 # nothing re-downloaded
    assert len(list(env.cache.glob("*.nc4"))) == N       # nothing deleted


def test_persistent_access_denied_never_deletes_cached_file(env, monkeypatch):
    pull_data.pull_collection([T2M], "2001-01", None)
    monkeypatch.setattr(pull_data, "open_granule",
                        lambda p, g: (_ for _ in ()).throw(PermissionError(13, "locked")))
    monkeypatch.setattr("time.sleep", lambda s: None)
    failed = pull_data.pull_collection([T2M], "2001-01", None)
    assert failed == N                                   # reported as gaps...
    assert len(list(env.cache.glob("*.nc4"))) == N       # ...but the good files are kept
