import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_registry_metadata as verifier


PROVENANCE = {
    "repository": "FSQ-lab/AutoGenesis",
    "workflow_ref": "FSQ-lab/AutoGenesis/.github/workflows/publish-mcp-registry.yml@refs/heads/main",
    "ref": "refs/heads/main",
    "commit": "1" * 40,
    "run_id": "1234",
    "run_attempt": "1",
}


class Response:
    def __init__(self, document):
        self._raw = json.dumps(document).encode()

    def read(self):
        return self._raw


def wheel(filename="example_pkg-1.2.3-py3-none-any.whl", sha256="a" * 64, size=123):
    return {
        "filename": filename,
        "sha256": sha256,
        "size": size,
        "package": "example-pkg",
        "version": "1.2.3",
    }


def manifest(record=None):
    document = {
        "schema_version": verifier.RELEASE_MANIFEST_SCHEMA,
        "provenance": PROVENANCE,
        "wheels": [record or wheel()],
    }
    verifier._validate_release_manifest(document)
    return document


def pypi_document(urls):
    return {
        "info": {"name": "example-pkg", "version": "1.2.3"},
        "urls": urls,
    }


def pypi_file(record):
    return {
        "filename": record["filename"],
        "digests": {"sha256": record["sha256"]},
        "size": record["size"],
        "packagetype": "bdist_wheel",
    }


class ReleaseVerifierTests(unittest.TestCase):
    def test_absent_version_passes_release_preflight(self):
        def absent(url, timeout):
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)

        verifier._preflight_pypi_release(manifest(), opener=absent)

    def test_exact_existing_version_passes_resumable_preflight(self):
        record = wheel()

        def exact(_url, timeout):
            return Response(pypi_document([pypi_file(record)]))

        verifier._preflight_pypi_release(manifest(record), opener=exact)

    def test_different_same_version_collision_requires_version_bump(self):
        record = wheel()

        def different(_url, timeout):
            changed = pypi_file(record)
            changed["digests"]["sha256"] = "b" * 64
            return Response(pypi_document([changed]))

        with self.assertRaisesRegex(verifier.VerificationError, "collision.*bump"):
            verifier._preflight_pypi_release(manifest(record), opener=different)

    def test_partial_exact_release_allows_missing_packages_to_resume(self):
        existing = wheel()
        missing = wheel("other_pkg-4.5.6-py3-none-any.whl", "b" * 64, 456)
        missing["package"] = "other-pkg"
        missing["version"] = "4.5.6"
        document = manifest(existing)
        document["wheels"].append(missing)
        verifier._validate_release_manifest(document)

        def partial(url, timeout):
            if "other-pkg" in url:
                raise urllib.error.HTTPError(url, 404, "not found", {}, None)
            return Response(pypi_document([pypi_file(existing)]))

        verifier._preflight_pypi_release(document, opener=partial)

    def test_exact_post_publish_wheel_set_matches_manifest(self):
        record = wheel()

        def exact(_url, timeout):
            return Response(pypi_document([pypi_file(record)]))

        verifier._verify_pypi_release(manifest(record), opener=exact)

    def test_post_publish_rejects_extra_missing_or_different_files(self):
        record = wheel()
        for difference in ("extra", "missing", "different"):
            with self.subTest(difference=difference):
                files = [pypi_file(record)]
                if difference == "extra":
                    extra = wheel("example_pkg-1.2.3-py3-none-win_amd64.whl", "b" * 64, 456)
                    files.append(pypi_file(extra))
                elif difference == "missing":
                    files.clear()
                else:
                    files[0]["digests"]["sha256"] = "b" * 64

                def changed(_url, timeout):
                    return Response(pypi_document(files))

                with self.assertRaisesRegex(verifier.VerificationError, "wheel (filename set differs|bytes differ)"):
                    verifier._verify_pypi_release(manifest(record), opener=changed)

    def test_manifest_round_trip_binds_local_filename_hash_size_and_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel_path = root / "example_pkg-1.2.3-py3-none-any.whl"
            wheel_path.write_bytes(b"reviewed wheel bytes")
            record = wheel(
                filename=wheel_path.name,
                sha256=hashlib.sha256(wheel_path.read_bytes()).hexdigest(),
                size=wheel_path.stat().st_size,
            )
            manifest_path = root / "release-manifest.json"
            verifier._write_release_manifest(manifest_path, [record], PROVENANCE)
            loaded = verifier._load_release_manifest(manifest_path, PROVENANCE)
            verifier._verify_manifest_wheels(root, loaded)

            wheel_path.write_bytes(b"different bytes")
            with self.assertRaisesRegex(verifier.VerificationError, "differ from the reviewed release manifest"):
                verifier._verify_manifest_wheels(root, loaded)


if __name__ == "__main__":
    unittest.main()
