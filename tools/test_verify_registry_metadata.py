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

def write_checksum_closure(assets):
    rows = []
    for path in sorted(assets.iterdir(), key=lambda item: item.name):
        if path.name != "SHA256SUMS":
            rows.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n")
    (assets / "SHA256SUMS").write_text("".join(rows), encoding="ascii")


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
            write_checksum_closure(assets)
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
            with self.assertRaisesRegex(verifier.VerificationError, "differs from SHA256SUMS"):
                verifier._verify_skill_review_manifest(assets, reviewed, release_path)

    def test_checksum_closure_rejects_mutation_extra_missing_and_self_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            assets = Path(temporary)
            (assets / "agent-install-prompt.txt").write_text("reviewed prompt", encoding="utf-8")
            (assets / "autogenesis-SKILL.md").write_text("reviewed skill", encoding="utf-8")
            write_checksum_closure(assets)

            (assets / "agent-install-prompt.txt").write_text("mutated prompt", encoding="utf-8")
            with self.assertRaisesRegex(verifier.VerificationError, "differs from SHA256SUMS"):
                verifier._verify_skill_checksum_closure(assets)

            (assets / "agent-install-prompt.txt").write_text("reviewed prompt", encoding="utf-8")
            (assets / "extra.txt").write_text("unlisted", encoding="utf-8")
            with self.assertRaisesRegex(verifier.VerificationError, "complete asset set"):
                verifier._verify_skill_checksum_closure(assets)

            (assets / "extra.txt").unlink()
            original = (assets / "SHA256SUMS").read_text(encoding="ascii")
            (assets / "autogenesis-SKILL.md").unlink()
            with self.assertRaisesRegex(verifier.VerificationError, "complete asset set"):
                verifier._verify_skill_checksum_closure(assets)

            (assets / "autogenesis-SKILL.md").write_text("reviewed skill", encoding="utf-8")
            self_digest = hashlib.sha256((assets / "SHA256SUMS").read_bytes()).hexdigest()
            (assets / "SHA256SUMS").write_text(original + f"{self_digest}  SHA256SUMS\n", encoding="ascii")
            with self.assertRaisesRegex(verifier.VerificationError, "checksum set is invalid"):
                verifier._verify_skill_checksum_closure(assets)

    def test_self_consistent_prompt_substitution_still_fails_external_review_anchor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assets = root / "skill-release"
            assets.mkdir()
            release_path = root / "release-manifest.json"
            release_raw = json.dumps(manifest(), sort_keys=True).encode()
            release_path.write_bytes(release_raw)
            (assets / "release-manifest.json").write_bytes(release_raw)
            (assets / "agent-install-prompt.txt").write_text("reviewed prompt", encoding="utf-8")
            (assets / "autogenesis-release.lock").write_text("reviewed lock", encoding="utf-8")
            (assets / "autogenesis-SKILL.md").write_text("reviewed skill", encoding="utf-8")
            write_checksum_closure(assets)
            review_path = root / "skill-review-manifest.json"
            verifier._write_skill_review_manifest(
                review_path, assets, release_path, verifier._load_release_manifest(release_path)
            )
            reviewed = verifier._load_skill_review_manifest(review_path, PROVENANCE)

            (assets / "agent-install-prompt.txt").write_text("attacker prompt", encoding="utf-8")
            write_checksum_closure(assets)
            verifier._verify_skill_checksum_closure(assets)
            with self.assertRaisesRegex(verifier.VerificationError, "external review manifest"):
                verifier._verify_skill_review_manifest(assets, reviewed, release_path)

    def test_self_consistent_review_manifest_from_another_run_fails_provenance_anchor(self):
        document = {
            "schema_version": verifier.SKILL_REVIEW_MANIFEST_SCHEMA,
            "provenance": dict(PROVENANCE, run_id="9999"),
            "assets": [{"filename": "SHA256SUMS", "sha256": "a" * 64, "size": 1}],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "skill-review-manifest.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(verifier.VerificationError, "current workflow run"):
                verifier._load_skill_review_manifest(path, PROVENANCE)


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
    @classmethod
    def setUpClass(cls):
        cls.workflow = (
            Path(__file__).resolve().parents[1] / ".github/workflows/publish-mcp-registry.yml"
        ).read_text()
        cls.candidate_workflow = (
            Path(__file__).resolve().parents[1] / ".github/workflows/quality-gates.yml"
        ).read_text()

    def test_final_prompt_build_precedes_checksum_review_and_public_upload(self):
        workflow = self.workflow
        build = workflow.index("python agent-contract/tools/build_skill_release.py")
        review = workflow.index("--write-skill-review-manifest", build)
        upload = workflow.index("name: Upload immutable Skill release assets", review)
        publish = workflow.index('gh release upload "$RELEASE_TAG" skill-release/*', upload)

        self.assertLess(build, review)
        self.assertLess(review, upload)
        self.assertLess(upload, publish)

    def test_candidate_bundle_is_run_bound_before_exact_artifact_upload(self):
        workflow = self.candidate_workflow
        build = workflow.index("python agent-contract/tools/build_candidate_release.py")
        run_anchor = workflow.index('--workflow-run-id "${{ github.run_id }}"', build)
        attempt_anchor = workflow.index('--workflow-run-attempt "${{ github.run_attempt }}"', run_anchor)
        upload = workflow.index("name: Upload exact Candidate channel", attempt_anchor)

        self.assertLess(build, run_anchor)
        self.assertLess(run_anchor, attempt_anchor)
        self.assertLess(attempt_anchor, upload)
        self.assertIn("autogenesis-candidate-${{ github.run_id }}-${{ github.run_attempt }}-${{ env.CANDIDATE_COMMIT }}", workflow[upload:])

    def test_tag_is_absent_or_exact_before_draft_and_rechecked_around_publish(self):
        workflow = self.workflow
        preflight = workflow.index('if resolved_tag="$(resolve_tag_commit)"')
        wrong_tag = workflow.index('if [[ "$resolved_tag" != "$GITHUB_SHA" ]]', preflight)
        establish = workflow.index('gh api --method POST "repos/${GITHUB_REPOSITORY}/git/refs"', wrong_tag)
        create = workflow.index('gh release create "$RELEASE_TAG" --draft')
        prepublish_tag = workflow.index("require_exact_tag", workflow.index("verify_release_assets", create))
        publish = workflow.index('gh api --method PATCH "repos/${GITHUB_REPOSITORY}/releases/${draft_id}"')
        postpublish_tag = workflow.index("require_exact_tag", publish)

        self.assertLess(preflight, wrong_tag)
        self.assertLess(wrong_tag, establish)
        self.assertLess(establish, create)
        self.assertLess(create, prepublish_tag)
        self.assertLess(prepublish_tag, publish)
        self.assertLess(publish, postpublish_tag)
        self.assertIn('tag_object="$(gh api "repos/${GITHUB_REPOSITORY}/git/tags/${object_sha}")"', workflow)
        self.assertIn('if [[ "$resolved_tag" != "$GITHUB_SHA" ]]', workflow)

    def test_same_commit_tag_only_state_can_continue_to_draft(self):
        workflow = self.workflow
        tag_gate = workflow.index('if resolved_tag="$(resolve_tag_commit)"')
        exact_comparison = workflow.index('if [[ "$resolved_tag" != "$GITHUB_SHA" ]]', tag_gate)
        gate_end = workflow.index("          fi\n\n          if gh release view", exact_comparison)
        create = workflow.index('gh release create "$RELEASE_TAG" --draft', gate_end)

        self.assertLess(tag_gate, exact_comparison)
        self.assertLess(exact_comparison, gate_end)
        self.assertLess(gate_end, create)

    def test_wrong_commit_tag_only_state_exits_before_any_draft(self):
        workflow = self.workflow
        wrong_commit = workflow.index("Pre-existing release tag resolves to another commit")
        reject = workflow.index("exit 1", wrong_commit)
        create = workflow.index('gh release create "$RELEASE_TAG" --draft')

        self.assertLess(wrong_commit, reject)
        self.assertLess(reject, create)

    def test_absent_or_uncaptured_draft_cleanup_proves_absence_before_owned_tag_delete(self):
        workflow = self.workflow
        recover = workflow.index("recover_uncaptured_draft() {")
        prove_absent = workflow.index('if [[ "$(jq -r \'length\' <<< "$matches")" == "0" ]]', recover)
        cleanup = workflow.index("cleanup_draft() {", prove_absent)
        delete_owned_tag = workflow.index("delete_created_tag || true", cleanup)

        self.assertLess(recover, prove_absent)
        self.assertLess(prove_absent, cleanup)
        self.assertLess(cleanup, delete_owned_tag)
        self.assertIn('if recover_uncaptured_draft; then', workflow[cleanup:delete_owned_tag])

    def test_draft_cleanup_is_database_id_bound_and_only_removes_owned_exact_tag(self):
        workflow = self.workflow
        cleanup = workflow[workflow.index("cleanup_draft() {"):workflow.index("verify_release_assets() {")]

        self.assertIn('delete_exact_draft "$draft_id"', cleanup)
        self.assertIn('require_release_identity "$release_id" true', workflow)
        self.assertIn('gh api --method DELETE "repos/${GITHUB_REPOSITORY}/releases/${release_id}"', workflow)
        self.assertIn('created_tag" == "true" && "$release_safe_for_tag_cleanup" == "true', cleanup)
        self.assertIn('test "$direct_type" = "commit"', workflow)
        self.assertIn('test "$direct_sha" = "$GITHUB_SHA"', workflow)
        self.assertNotIn("gh release delete", workflow)
        self.assertNotIn("--cleanup-tag", workflow)

    def test_mutable_public_release_burns_identity_and_is_not_cleaned_for_rerun(self):
        workflow = self.workflow
        publish = workflow.index('gh api --method PATCH "repos/${GITHUB_REPOSITORY}/releases/${draft_id}"')
        mark_public = workflow.index("published=true", publish)
        immutable = workflow.index('if [[ "$published_immutable" != "true" ]]', mark_public)
        burned = workflow.index("its tag and evidence are preserved and identity reuse is blocked", immutable)

        self.assertLess(publish, mark_public)
        self.assertLess(mark_public, immutable)
        self.assertLess(immutable, burned)
        self.assertNotIn("--method DELETE", workflow[mark_public:burned])
        self.assertIn("The public release identity is burned by a mutable release; refusing reuse", workflow)

    def test_skill_release_is_reviewed_uploaded_verified_then_published_once(self):
        workflow = self.workflow
        review = workflow.index("--verify-skill-review-manifest")
        create = workflow.index('gh release create "$RELEASE_TAG" --draft')
        upload = workflow.index('gh release upload "$RELEASE_TAG" skill-release/*')
        verify = workflow.index('verify_release_assets "$draft_id" true', upload)
        publish = workflow.index('gh api --method PATCH "repos/${GITHUB_REPOSITORY}/releases/${draft_id}"')
        immutable = workflow.index('published_immutable="$(', publish)

        self.assertLess(review, create)
        self.assertLess(create, upload)
        self.assertLess(upload, verify)
        self.assertLess(verify, publish)
        self.assertLess(publish, immutable)
        self.assertNotIn('gh release create "$RELEASE_TAG" skill-release/*', workflow)

    def test_release_and_publisher_downloads_have_byte_limits(self):
        workflow = self.workflow
        asset_bounds = workflow.index("readonly MAX_RELEASE_ASSET_BYTES=8388608")
        size_preflight = workflow.index("and .size <= $max_size", asset_bounds)
        metadata_compare = workflow.index('review/skill-review-manifest.json', size_preflight)
        asset_download = workflow.index("releases/assets/${asset_id}", metadata_compare)

        self.assertLess(asset_bounds, size_preflight)
        self.assertLess(size_preflight, metadata_compare)
        self.assertLess(metadata_compare, asset_download)
        self.assertIn('ulimit -f "$blocks"', workflow)
        self.assertIn('--max-filesize "$MAX_PUBLISHER_ARCHIVE_BYTES"', workflow)
        self.assertIn('--max-filesize "$MAX_SIGSTORE_BUNDLE_BYTES"', workflow)
        self.assertIn("readonly MAX_PUBLISHER_BINARY_BYTES=134217728", workflow)
        self.assertIn('ulimit -f "$(( (MAX_PUBLISHER_BINARY_BYTES + 1023) / 1024 + 1 ))"', workflow)


if __name__ == "__main__":
    unittest.main()
