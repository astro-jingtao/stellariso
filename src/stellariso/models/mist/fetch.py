"""MIST data acquisition: interp-form subsets and full tarballs.

Both channels talk to the model team's own infrastructure (mist.science /
waps.cfa.harvard.edu). The interp form returns one zip per request holding
one ``.iso`` covering the requested (version, v/vcrit, [Fe/H], [alpha/Fe],
age list); the form is deterministic, so identical requests regenerate
identical rows. The tarball channel fetches a complete published suite once
and is the preferred route when whole grids are needed.

Proxy note: requests honors ``HTTP_PROXY``/``HTTPS_PROXY`` environment
variables; stellariso adds no proxy configuration of its own.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
import zipfile
from pathlib import Path

import requests

from ...exceptions import DataIntegrityError, SourceUnavailableError
from ...provenance import (
    DataAsset,
    Provenance,
    SourceClass,
    SourceRecord,
    SourceStatus,
)
from ...retrieval.cache import product_dir
from ...retrieval.integrity import sha256_bytes, verify_checksum

__all__ = [
    "FORM_URL",
    "TARBALL_URL_TEMPLATE",
    "fetch_mist_subset",
    "fetch_mist_tarball",
    "mist_subset_filename",
]

FORM_URL = "https://mist.science/iso_form.php"
TARBALL_URL_TEMPLATE = (
    "http://waps.cfa.harvard.edu/MIST/data/tarballs_v{version}/"
    "MIST_v{version}_vvcrit{vvcrit}_{kind}.txz"
)

_ZIP_LINK_RE = re.compile(r'href="(output/[^"]+\.zip)"')
_TIMEOUT_POST = 300
_TIMEOUT_GET = 1800


def _sign_tag(value: float, digits: int = 2) -> str:
    return ("m" if value < 0 else "p") + f"{abs(value):.{digits}f}"


def mist_subset_filename(feh: float, log_ages, vvcrit: float, afe: float,
                         mist_version: str) -> str:
    ages = sorted(float(a) for a in log_ages)
    age_part = f"logage{ages[0]:g}-{ages[-1]:g}" if len(ages) > 1 else f"logage{ages[0]:g}"
    return (
        f"MIST_v{mist_version}_feh_{_sign_tag(feh)}_afe_{_sign_tag(afe, 1)}_"
        f"vvcrit{vvcrit:g}_{age_part}.iso"
    )


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "stellariso (isochrone data access library)"
    return s


def fetch_mist_subset(
    feh: float,
    log_ages,
    vvcrit: float = 0.4,
    afe: float = 0.0,
    version: str = "MIST1",
    cache_dir: Path | None = None,
    session: requests.Session | None = None,
) -> tuple[Path, Provenance]:
    """Fetch one composition's isochrone subset through the interp form.

    Returns the path of the cached (uncompressed) ``.iso`` file and the
    provenance of its acquisition. Existing files with matching registry
    checksums are reused — the cache is the offline backup.
    """
    ages = sorted(float(a) for a in log_ages)
    if not ages:
        raise ValueError("log_ages must contain at least one value")

    release = "1.2" if version == "MIST1" else version
    target_dir = Path(cache_dir) if cache_dir else product_dir(
        "mist", release, f"vvcrit{vvcrit:g}"
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = mist_subset_filename(feh, ages, vvcrit, afe, release)
    target = target_dir / filename

    reg = _plain_registry(target_dir)
    entry = reg.get("assets", {}).get(filename)
    if target.exists() and entry and entry.get("sha256"):
        try:
            verify_checksum(target, entry["sha256"])
            return target, _provenance_from_entry(entry, target)
        except DataIntegrityError:
            # cached copy corrupted: re-fetch below rather than serving it
            pass

    s = session or _session()
    form = {
        "version": version,
        "v_div_vcrit": f"vvcrit{vvcrit:g}",
        "age_scale": "log10",
        "age_type": "list",
        "age_list": " ".join(f"{a:g}" for a in ages),
        "FeH_value": f"{feh:+.2f}",
        "alpha_value": _sign_tag(afe, 1),
        "output_option": "theory",
        "output": "UBVRIplus",
        "Av_value": "0",
    }
    resp = s.post(FORM_URL, data=form, timeout=_TIMEOUT_POST)
    resp.raise_for_status()
    m = _ZIP_LINK_RE.search(resp.text)
    if not m:
        raise SourceUnavailableError(
            f"{FORM_URL} returned no result zip for request {form}"
        )
    zip_url = f"https://mist.science/{m.group(1)}"
    zresp = s.get(zip_url, timeout=_TIMEOUT_GET)
    zresp.raise_for_status()
    zip_sha = sha256_bytes(zresp.content)

    zf = zipfile.ZipFile(io.BytesIO(zresp.content))
    members = [n for n in zf.namelist() if n.endswith(".iso")]
    if len(members) != 1:
        raise DataIntegrityError(
            f"expected one .iso inside the result zip, found {zf.namelist()}"
        )
    payload = zf.read(members[0])
    target.write_bytes(payload)

    entry = {
        "sha256": sha256_bytes(payload),
        "size_bytes": len(payload),
        "zip_sha256": zip_sha,
        "retrieved_at": _now_iso(),
        "source": {
            "source_class": SourceClass.OFFICIAL_ORIGIN.value,
            "url": FORM_URL,
            "status": SourceStatus.RETRIEVED.value,
            "note": f"interp-form POST {form}",
        },
    }
    _write_plain_registry(target_dir, filename, entry)
    return target, _provenance_from_entry(entry, target)


def fetch_mist_tarball(
    version: str = "1.2",
    vvcrit: float = 0.4,
    kind: str = "full_isos",
    extract: bool = True,
    cache_dir: Path | None = None,
    session: requests.Session | None = None,
) -> tuple[Path, Provenance]:
    """Download a complete published MIST isochrone tarball (about 660 MB
    for v1.2/vvcrit0.4 full) and optionally extract its ``.iso`` files.

    The upstream publishes no checksums; the downloaded archive's sha256 is
    computed and recorded so later runs can verify the cached copy.
    """
    url = TARBALL_URL_TEMPLATE.format(version=version, vvcrit=f"{vvcrit:g}", kind=kind)
    target_dir = Path(cache_dir) if cache_dir else product_dir("mist", version, f"vvcrit{vvcrit:g}")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / url.rsplit("/", 1)[-1]

    s = session or _session()
    h = hashlib.sha256()
    with s.get(url, stream=True, timeout=_TIMEOUT_GET) as resp:
        resp.raise_for_status()
        tmp = target.with_suffix(".part")
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
                h.update(chunk)
    tmp.replace(target)
    sha = h.hexdigest()

    provenance = Provenance(
        data_sources=(
            SourceRecord(
                source_class=SourceClass.OFFICIAL_ORIGIN,
                url=url,
                accessed_at=_now_iso(),
                status=SourceStatus.RETRIEVED,
                note="full suite tarball; upstream publishes no checksums",
            ),
        ),
        assets=(
            DataAsset(
                filename=target.name,
                size_bytes=target.stat().st_size,
                checksum=sha,
                retrieved_at=_now_iso(),
            ),
        ),
    )

    if extract:
        with tarfile.open(target, mode="r:xz") as tf:
            tf.extractall(target_dir)
    return target, provenance


# -- small helpers -----------------------------------------------------------


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _plain_registry(target_dir: Path) -> dict:
    p = target_dir / "registry.json"
    if not p.exists():
        return {"assets": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def _write_plain_registry(target_dir: Path, filename: str, entry: dict) -> None:
    reg = _plain_registry(target_dir)
    reg.setdefault("assets", {})[filename] = entry
    (target_dir / "registry.json").write_text(
        json.dumps(reg, indent=2, sort_keys=True), encoding="utf-8"
    )


def _provenance_from_entry(entry: dict, target: Path) -> Provenance:
    src = entry.get("source", {})
    return Provenance(
        data_sources=(
            SourceRecord(
                source_class=SourceClass(src.get("source_class", "official_origin")),
                url=src.get("url"),
                accessed_at=entry.get("retrieved_at"),
                status=SourceStatus(src.get("status", "retrieved")),
                note=src.get("note"),
            ),
        ),
        assets=(
            DataAsset(
                filename=target.name,
                size_bytes=entry.get("size_bytes"),
                checksum=entry.get("sha256"),
                checksum_algorithm="sha256",
                retrieved_at=entry.get("retrieved_at"),
            ),
        ),
    )
