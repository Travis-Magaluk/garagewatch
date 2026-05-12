# PyArrow install blocked by 32-bit Python on 64-bit Pi hardware

**Date:** 2026-04-17
**Phase:** 2 — Pi Postgres → S3 export
**Outcome:** Pivoted to CSV staging + cloud-side Parquet conversion (medallion pattern)

---

## The problem

Needed to install `pyarrow` on the Raspberry Pi to write Parquet files as part of
the incremental S3 export. `pip install pyarrow` kept failing no matter what
I tried.

## What I tried (in order)

1. **`pip install pyarrow`** → `cmake: No such file or directory`
2. **`sudo apt install cmake`, retry** → cmake succeeds, CMake then fails with
   `Could NOT find Python3_NumPy_INCLUDE_DIRS`
3. **`pip install numpy` first, retry** → same NumPy error (build isolation
   meant cmake couldn't see the numpy I'd just installed)
4. **`pip install "pyarrow==14.0.2"`** → `ModuleNotFoundError: No module named 'pkg_resources'`
5. **`pip install --upgrade pip setuptools`, retry** → same pkg_resources error
   (setuptools 82+ removed `pkg_resources`, but pyarrow 14's setup.py imports it)
6. **`pip install pyarrow --only-binary=:all: --index-url https://pypi.org/simple/`** →
   `No matching distribution found for pyarrow`
7. **`sudo apt install python3-pyarrow`** → `Unable to locate package`
   (Raspbian doesn't ship it)
8. **Build from source with `--no-build-isolation`, pinned cython<3** → downloaded
   20+ source tarballs, all rejected with `inconsistent version: expected 'X.Y.Z', but metadata has '0.0.0'`,
   finally got to pyarrow 13 which then failed on Cython version check

## The actual root cause

Looking closely at a successful cython install, I noticed the wheel filename:

```
cython-3.2.4-cp311-cp311-linux_armv7l.whl
```

That `linux_armv7l` is the key. **Python on this Pi is 32-bit**, even though
the CPU is 64-bit (`uname -m` = `aarch64`).

- The Pi is running **Raspbian**, a 32-bit userspace OS
- Raspberry Pi OS (64-bit) is a separate distribution — "Raspbian" and "Raspberry
  Pi OS" are not the same thing despite common conflation
- `uname -m` reports the kernel architecture (aarch64), but userspace binaries
  including Python are compiled for `armv7l` (32-bit ARM)
- PyPI does not publish pyarrow wheels for 32-bit ARM — never has
- Source builds fail on 32-bit Pi because of a cascade of toolchain mismatches
  (and would likely OOM even if they got further)

## The decision

Two realistic paths:

1. **Reflash the Pi to 64-bit Raspberry Pi OS** — correct long-term fix, but
   requires a data migration and a few hours. Deferred to Phase 7.
2. **Skip Parquet on the Pi; stage CSV instead** — chosen.

The Pi now writes `.csv.gz` files to `s3://garagewatch-data/raw/readings/` with
the same Hive partitioning (`year=YYYY/month=MM/`) and the same watermark
pattern. A cloud-side job (Athena CTAS, Lambda, or Glue — TBD) converts
these to Parquet in `s3://garagewatch-data/curated/readings/`.

This is the **medallion architecture** — bronze (raw CSV) → silver (Parquet).
The edge device stays lightweight and the format work happens in the cloud,
which is how real IoT pipelines are built.

## What I'd say in an interview

> "I hit a classic edge-device platform mismatch. My Raspberry Pi is 64-bit
> hardware but was running a 32-bit OS — so the Python interpreter couldn't
> use the aarch64 wheels that pyarrow publishes. After burning a few hours
> trying to build from source and falling into a chain of version conflicts
> (setuptools removing pkg_resources, Cython 3 incompatibility, source
> tarball metadata issues), I stepped back and realized: the *correct*
> architecture for an edge pipeline doesn't do Parquet conversion on the
> edge anyway. I pivoted to staging gzipped CSV to S3 and moving the
> Parquet conversion to a cloud transform. It unblocked the pipeline in an
> afternoon, and the resulting architecture is actually more production-like
> — the Pi stops being on the critical path for compute, and the cloud
> handles the heavy format work where it scales better. The reflash to 64-bit
> is still on the roadmap but is no longer blocking."

## Lessons

- `uname -m` shows the **kernel** arch, not the **userspace** arch. Always
  also check `python3 -c "import platform; print(platform.architecture())"`
  and `file $(which python3)` when debugging wheel compatibility.
- Wheel filename tags (`cp311-cp311-linux_armv7l`) are the ground truth for
  what pip can install. If the platform tag doesn't match what a package
  publishes, you're out of luck regardless of what `--only-binary` you pass.
- When a dependency install cascades into multiple unrelated-looking errors
  (cmake → numpy → pkg_resources → version metadata → Cython), **step back**.
  The fifth error is rarely the real problem. Ask "why am I building from
  source at all?" — the answer often points to the real root cause.
- Working around a blocker by changing the architecture is often better than
  fighting the toolchain. A CSV + cloud transform isn't a hack — it's a
  separation of concerns that real pipelines want anyway.

## References

- [PEP 600 — manylinux platform tags](https://peps.python.org/pep-0600/)
- [pyarrow's supported wheels](https://pypi.org/project/pyarrow/#files) — note
  the absence of any `armv7l` entries
- Medallion architecture: Databricks coined the term but the bronze/silver/gold
  staging pattern predates it by decades — it's how every warehouse ingests
  raw data and progressively refines it.
