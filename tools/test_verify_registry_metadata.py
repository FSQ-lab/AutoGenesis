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
    def __init__(self, document=None, raw=None):
        self._raw = raw if raw is not None else json.dumps(document).encode()

    def read(self, limit=-1):
        return self._raw if limit < 0 else self._raw[:limit]


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
        "provenance": dict(PROVENANCE),
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


def registry_candidate(key):
    expected = verifier.SERVERS[key]
    version = "0.5.0"
    return {
        "$schema": verifier.SCHEMA_URL,
        "name": expected["name"],
        "description": f"Reviewed {key} candidate.",
        "repository": {
            "url": verifier.REPOSITORY,
            "source": "github",
            "id": verifier.REPOSITORY_ID,
            "subfolder": expected["path"].rsplit("/", 1)[0],
        },
        "version": version,
        "packages": [
            {
                "registryType": "pypi",
                "registryBaseUrl": "https://pypi.org",
                "identifier": expected["package"],
                "version": version,
                "runtimeHint": "uvx",
                "transport": {"type": "stdio"},
            }
        ],
    }


def registry_response(candidate, status="active", is_latest=True):
    return {
        "server": json.loads(json.dumps(candidate)),
        "_meta": {
            "io.modelcontextprotocol.registry/official": {
                "status": status,
                "isLatest": is_latest,
            }
        },
    }


def registry_candidates():
    return {key: registry_candidate(key) for key in verifier.SERVERS}


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

    def test_failed_job_rerun_accepts_original_same_run_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "release-manifest.json"
            path.write_text(json.dumps(manifest()), encoding="utf-8")
            attempt_two = dict(PROVENANCE, run_attempt="2")

            loaded = verifier._load_release_manifest(path, attempt_two)

            self.assertEqual(loaded["provenance"]["run_attempt"], "1")

    def test_rerun_rejects_changed_run_commit_ref_or_workflow(self):
        changes = {
            "workflow_ref": "FSQ-lab/AutoGenesis/.github/workflows/other.yml@refs/heads/main",
            "ref": "refs/heads/other",
            "commit": "2" * 40,
            "run_id": "5678",
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "release-manifest.json"
            current = dict(PROVENANCE, run_attempt="2")
            for field, value in changes.items():
                with self.subTest(field=field):
                    document = manifest()
                    document["provenance"][field] = value
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaisesRegex(verifier.VerificationError, "current workflow run"):
                        verifier._load_release_manifest(path, current)

    def test_rerun_rejects_manifest_from_a_later_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "release-manifest.json"
            document = manifest()
            document["provenance"]["run_attempt"] = "3"
            path.write_text(json.dumps(document), encoding="utf-8")

            with self.assertRaisesRegex(verifier.VerificationError, "later workflow attempt"):
                verifier._load_release_manifest(path, dict(PROVENANCE, run_attempt="2"))

    def test_external_review_manifest_covers_prompt_lock_manifest_and_skill(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assets = root / "skill-release"
            assets.mkdir()
            release_path = root / "release-manifest.json"
            release_raw = json.dumps(manifest(), sort_keys=True).encode()
            release_path.write_bytes(release_raw)
            (assets / "release-manifest.json").write_bytes(release_raw)
            (assets / "agent-install-prompt.txt").write_text("install reviewed bytes", encoding="utf-8")
            (assets / "autogenesis-release.lock").write_text("locked bytes", encoding="utf-8")
            (assets / "autogenesis-SKILL.md").write_text("skill bytes", encoding="utf-8")
            (assets / "SHA256SUMS").write_text("bundle-local checks only", encoding="utf-8")
            review_path = root / "skill-review-manifest.json"

            verifier._write_skill_review_manifest(
                review_path, assets, release_path, verifier._load_release_manifest(release_path)
            )
            reviewed = verifier._load_skill_review_manifest(review_path, PROVENANCE)
            verifier._verify_skill_review_manifest(assets, reviewed, release_path)

            self.assertEqual(
                {record["filename"] for record in reviewed["assets"]},
                {
                    "SHA256SUMS",
                    "agent-install-prompt.txt",
                    "autogenesis-SKILL.md",
                    "autogenesis-release.lock",
                    "release-manifest.json",
                },
            )
            (assets / "agent-install-prompt.txt").write_text("substituted prompt", encoding="utf-8")
            with self.assertRaisesRegex(verifier.VerificationError, "external review manifest"):
                verifier._verify_skill_review_manifest(assets, reviewed, release_path)


class RegistryReleaseVerifierTests(unittest.TestCase):
    def test_exact_endpoint_percent_encodes_name_and_version(self):
        candidate = registry_candidate("appium")
        candidate["version"] = "0.5.0+reviewed"
        candidate["packages"][0]["version"] = candidate["version"]
        observed = {}

        def exact(url, timeout):
            observed.update(url=url, timeout=timeout)
            return Response(registry_response(candidate))

        verifier._registry_version(candidate, opener=exact)

        self.assertIn("io.github.FSQ-lab%2Fautogenesis-appium", observed["url"])
        self.assertIn("0.5.0%2Breviewed", observed["url"])
        self.assertEqual(observed["timeout"], verifier.PUBLIC_METADATA_TIMEOUT_SECONDS)

    def test_both_absent_records_produce_publish_plan(self):
        def absent(url, timeout):
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)

        states = verifier._preflight_registry_release(registry_candidates(), opener=absent)

        self.assertEqual(states, {"appium": "absent", "windows": "absent"})

    def test_same_version_collision_fails_whole_preflight(self):
        candidates = registry_candidates()

        def collision(url, timeout):
            key = "appium" if "autogenesis-appium" in url else "windows"
            response = registry_response(candidates[key])
            if key == "windows":
                response["server"]["packages"][0]["transport"] = {"type": "sse"}
            return Response(response)

        with self.assertRaisesRegex(verifier.VerificationError, "collision for windows"):
            verifier._preflight_registry_release(candidates, opener=collision)

    def test_partial_appium_publication_is_exact_and_resumable(self):
        candidates = registry_candidates()

        def partial(url, timeout):
            if "autogenesis-windows" in url:
                raise urllib.error.HTTPError(url, 404, "not found", {}, None)
            return Response(registry_response(candidates["appium"]))

        states = verifier._preflight_registry_release(candidates, opener=partial)

        self.assertEqual(states, {"appium": "exact", "windows": "absent"})

    def test_postcheck_retries_delayed_exact_record(self):
        candidate = registry_candidate("appium")
        responses = [None, registry_response(candidate)]
        sleeps = []

        def delayed(url, timeout):
            response = responses.pop(0)
            if response is None:
                raise urllib.error.HTTPError(url, 404, "not found", {}, None)
            return Response(response)

        verifier._verify_registry_record_with_retries(
            "appium", candidate, 2, 0.25, opener=delayed, sleeper=sleeps.append
        )

        self.assertEqual(sleeps, [0.25])

    def test_postcheck_exhaustion_rejects_nonlatest_record(self):
        candidate = registry_candidate("windows")
        attempts = 0

        def stale(_url, timeout):
            nonlocal attempts
            attempts += 1
            return Response(registry_response(candidate, is_latest=False))

        with self.assertRaisesRegex(verifier.VerificationError, "not the latest"):
            verifier._verify_registry_record_with_retries(
                "windows", candidate, 3, 0, opener=stale, sleeper=lambda _delay: None
            )
        self.assertEqual(attempts, 3)

    def test_final_proof_requires_both_exact_active_latest_records(self):
        candidates = registry_candidates()

        def exact(url, timeout):
            key = "appium" if "autogenesis-appium" in url else "windows"
            return Response(registry_response(candidates[key]))

        verifier._verify_registry_release_with_retries(
            candidates, 1, 0, opener=exact, sleeper=lambda _delay: None
        )

    def test_untrusted_or_oversized_registry_response_fails_without_echo(self):
        candidate = registry_candidate("appium")
        malicious = "untrusted-server-name-secret"
        changed = registry_response(candidate)
        changed["server"]["name"] = malicious

        with self.assertRaises(verifier.VerificationError) as mismatch:
            verifier._verify_registry_response("appium", candidate, changed)
        self.assertNotIn(malicious, str(mismatch.exception))

        oversized = b"x" * (verifier.MAX_PUBLIC_METADATA_BYTES + 2)
        with self.assertRaisesRegex(verifier.VerificationError, "too large"):
            verifier._registry_version(candidate, opener=lambda _url, timeout: Response(raw=oversized))


class ReleaseWorkflowSafetyTests(unittest.TestCase):
    def test_skill_release_is_completed_before_one_way_publication(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/publish-mcp-registry.yml").read_text()
        review = workflow.index("--verify-skill-review-manifest")
        create = workflow.index('gh release create "$RELEASE_TAG" --draft')
        upload = workflow.index('gh release upload "$RELEASE_TAG" skill-release/*')
        verify = workflow.index('verify_release_assets "$RELEASE_TAG"', upload)
        publish = workflow.index('gh release edit "$RELEASE_TAG" --draft=false')
        immutable = workflow.index('published_immutable="$(gh api')

        self.assertLess(review, create)
        self.assertLess(create, upload)
        self.assertLess(upload, verify)
        self.assertLess(verify, publish)
        self.assertLess(publish, immutable)
        self.assertNotIn('gh release create "$RELEASE_TAG" skill-release/*', workflow)


if __name__ == "__main__":
    unittest.main()
