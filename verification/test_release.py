"""Publication controls: reject wrong versions/bytes/evidence and resume uploads."""
import json
from pathlib import Path
import subprocess
import sys
import uuid
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import release


@pytest.mark.parametrize("tag", ["v0.1.0", "v1.2.3", "v0.1.0-RC1", "v2.0.0-RC12"])
def test_release_tag_versions(tag):
    assert release.version_from_tag(tag) == tag[1:]


@pytest.mark.parametrize("tag", ["0.1.0", "v01.2.3", "v1.2", "v1.2.3-SNAPSHOT", "v1.2.3-RC0",
                               "v1.2.3@publish", "v1.2.3;evil", "../v1.2.3", "v1.2.3\n"])
def test_release_rejects_noncanonical_tags(tag):
    with pytest.raises(ValueError, match="Release tag"):
        release.version_from_tag(tag)


def test_release_requires_exact_clean_tag(tmp_path):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()
    git("init")
    git("config", "user.name", "Release test")
    git("config", "user.email", "release-test@example.invalid")
    git("config", "commit.gpgsign", "false")
    git("config", "tag.gpgsign", "false")
    (tmp_path / "source").write_text("original")
    git("add", "source")
    git("commit", "-m", "base")
    git("tag", "v0.1.0")
    assert release.check_tag("v0.1.0", tmp_path) == git("rev-parse", "HEAD")
    (tmp_path / "source").write_text("changed")
    with pytest.raises(ValueError, match="clean working tree"):
        release.check_tag("v0.1.0", tmp_path)
    git("commit", "-am", "changed")
    with pytest.raises(ValueError, match="does not point"):
        release.check_tag("v0.1.0", tmp_path)


@pytest.fixture
def distribution(tmp_path):
    directory = tmp_path / "candidate"
    paths = release.artifact_paths(directory, "0.1.0")
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(paths[0], "w") as bundle:
        for name in ("META-INF/LICENSE", "chiselasync/core/AsyncModule.class",
                     "chiselasync/contract-v3.schema.json", "chiselasync/trace-v1.schema.json"):
            bundle.writestr(name, b"fixture")
        for model in (release.ROOT / "src/main/resources/chiselasync/sv").glob("*.sv"):
            bundle.writestr("chiselasync/sv/" + model.name, b"model")
    with zipfile.ZipFile(paths[1], "w") as bundle:
        bundle.writestr("META-INF/LICENSE", b"fixture")
        bundle.writestr("chiselasync/core/AsyncModule.scala", b"class Fixture")
    with zipfile.ZipFile(paths[2], "w") as bundle:
        bundle.writestr("index.html", b"API")
    paths[3].write_text("""<project xmlns="http://maven.apache.org/POM/4.0.0">
<groupId>io.github.biscutlabs</groupId><artifactId>chisel-async_2.13</artifactId><version>0.1.0</version>
<name>fixture</name><description>fixture</description><url>https://example.invalid</url>
<licenses><license><name>Apache-2.0</name></license></licenses>
<developers><developer><name>fixture</name><url>https://example.invalid</url></developer></developers>
<scm><connection>scm:git:fixture</connection></scm></project>""")
    manifest = {"schema": 1, "tag": "v0.1.0", "version": "0.1.0", "commit": "a" * 40,
                "publishable": True, "sha256": {p.relative_to(directory).as_posix(): release.sha(p) for p in paths}}
    release.write_json(directory / "manifest.json", manifest)
    return directory


def test_release_checks_all_artifact_hashes(distribution):
    assert release.verify(distribution)["version"] == "0.1.0"
    release.artifact_paths(distribution, "0.1.0")[0].write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        release.verify(distribution)


def test_release_rejects_wrong_pom_even_if_rehashed(distribution):
    pom = release.artifact_paths(distribution, "0.1.0")[-1]
    pom.write_text(pom.read_text().replace("<version>0.1.0</version>", "<version>0.1.1</version>"))
    manifest = json.loads((distribution / "manifest.json").read_text())
    manifest["sha256"][pom.relative_to(distribution).as_posix()] = release.sha(pom)
    release.write_json(distribution / "manifest.json", manifest)
    with pytest.raises(ValueError, match="POM version mismatch"):
        release.verify(distribution)


def test_release_rejects_extra_or_traversal_inventory(distribution):
    manifest = json.loads((distribution / "manifest.json").read_text())
    manifest["sha256"]["../../foreign.jar"] = "b" * 64
    release.write_json(distribution / "manifest.json", manifest)
    with pytest.raises(ValueError, match="inventory"):
        release.verify(distribution)


def test_dry_run_cannot_publish(distribution, monkeypatch):
    manifest = release.verify(distribution)
    manifest["publishable"] = False
    release.write_json(distribution / "manifest.json", manifest)
    monkeypatch.setattr(release, "portal", lambda *args: pytest.fail("dry-run reached network"))
    with pytest.raises(ValueError, match="Dry-run"):
        release.publish(distribution, distribution / "absent")


def evidence(directory, target):
    target.mkdir(exist_ok=True)
    manifest = release.verify(directory)
    for system in ("Windows", "Linux"):
        release.write_json(target / f"consumer-{system}.json", {
            "status": "PASS", "system": system, "commit": "a" * 40, "qualification_status": "PASS",
            "manifest_sha256": release.sha(directory / "manifest.json"),
            "library_sha256": release.sha(release.artifact_paths(directory, manifest["version"])[0])})


def test_release_requires_both_hosts_and_exact_candidate(distribution, tmp_path):
    reports = tmp_path / "evidence"
    evidence(distribution, reports)
    manifest = release.verify(distribution)
    release.check_evidence(distribution, reports, manifest)
    report = reports / "consumer-Windows.json"
    record = json.loads(report.read_text())
    record["library_sha256"] = "b" * 64
    release.write_json(report, record)
    with pytest.raises(ValueError, match="Invalid release consumer"):
        release.check_evidence(distribution, reports, manifest)
    report.unlink()
    with pytest.raises(ValueError, match="Windows and Linux"):
        release.check_evidence(distribution, reports, manifest)


def test_publish_uploads_once_and_resumes_same_deployment(distribution, tmp_path, monkeypatch):
    reports = tmp_path / "evidence"
    evidence(distribution, reports)
    monkeypatch.setattr(release, "check_tag", lambda tag: "a" * 40)
    monkeypatch.setenv("SONATYPE_USERNAME", "test-user")
    monkeypatch.setenv("SONATYPE_PASSWORD", "test-password")
    bundle = distribution / "central-bundle.zip"
    def sign(*args):
        bundle.write_bytes(b"signed fixture")
        return bundle
    monkeypatch.setattr(release, "sign_bundle", sign)
    calls = []
    deployment = str(uuid.uuid4())
    def portal(endpoint, *args):
        calls.append(endpoint)
        if endpoint.startswith("upload?"):
            assert "publishingType=AUTOMATIC" in endpoint
            return deployment
        raise RuntimeError("status temporarily unavailable")
    monkeypatch.setattr(release, "portal", portal)
    with pytest.raises(RuntimeError, match="temporarily"):
        release.publish(distribution, reports)
    assert json.loads((distribution / "central-receipt.json").read_text())["deployment_id"] == deployment
    def resumed(endpoint, *args):
        calls.append(endpoint)
        assert endpoint == "status?id=" + deployment
        return json.dumps({"deploymentId": deployment, "deploymentState": "PUBLISHED"})
    monkeypatch.setattr(release, "portal", resumed)
    monkeypatch.setattr(release, "sign_bundle", lambda *args: pytest.fail("resume re-signed"))
    release.publish(distribution, reports)
    assert len([c for c in calls if c.startswith("upload?")]) == 1
    assert json.loads((distribution / "central-receipt.json").read_text())["state"] == "PUBLISHED"


def test_unknown_upload_outcome_cannot_reupload(distribution, tmp_path, monkeypatch):
    reports = tmp_path / "evidence"
    evidence(distribution, reports)
    monkeypatch.setattr(release, "check_tag", lambda tag: "a" * 40)
    monkeypatch.setenv("SONATYPE_USERNAME", "test-user")
    monkeypatch.setenv("SONATYPE_PASSWORD", "test-password")
    (distribution / "upload-started.json").write_text("{}")
    monkeypatch.setattr(release, "portal", lambda *args: pytest.fail("unknown outcome retried"))
    with pytest.raises(ValueError, match="outcome is unknown"):
        release.publish(distribution, reports)


def test_release_rejects_empty_or_failed_scala_reports(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        release.check_test_reports(tmp_path)
    report = tmp_path / "suite.xml"
    report.write_text('<testsuite><testcase name="active"/></testsuite>')
    assert release.check_test_reports(tmp_path) == 1
    report.write_text('<testsuite><testcase name="broken"><failure/></testcase></testsuite>')
    with pytest.raises(ValueError, match="failed"):
        release.check_test_reports(tmp_path)
    report.write_text('<testsuite><testcase name="skipped"><skipped/></testcase></testsuite>')
    with pytest.raises(ValueError, match="skipped"):
        release.check_test_reports(tmp_path)


@pytest.mark.parametrize("version", ["0.1.0-SNAPSHOT", "0.1.0-RC1", "1.0.0"])
def test_consumers_follow_the_project_or_candidate_version(tmp_path, version):
    (tmp_path / "build.sbt").write_text(f'ThisBuild / version := "{version}"\n')
    assert release.project_version(tmp_path) == version
    original = 'val other = "0.1.0-SNAPSHOT"\nlibraryDependencies += "io.github.biscutlabs" %% "chisel-async" % "old"'
    changed = release.consumer_version(original, version)
    assert f'% "{version}"' in changed and 'val other = "0.1.0-SNAPSHOT"' in changed
    for invalid in ('val x = "0.1.0"', original + '\n' + original):
        with pytest.raises(ValueError, match="exactly one"):
            release.consumer_version(invalid, version)


@pytest.mark.parametrize("tag,requested,expected", [
    ("v0.1.0-RC1", "", "github"), ("v0.1.0", "", "maven-central"),
    ("v0.1.0-RC1", "maven-central", "maven-central"), ("v0.1.0-RC1", "github", "github")])
def test_publication_destinations(tag, requested, expected):
    assert release.publication_destination(tag, requested) == expected


def test_github_only_cannot_publish_stable_versions():
    with pytest.raises(ValueError, match="RC tag"):
        release.publication_destination("v0.1.0", "github")
    with pytest.raises(ValueError, match="Unknown"):
        release.publication_destination("v0.1.0-RC1", "elsewhere")


@pytest.fixture
def rc_distribution(distribution):
    manifest = release.verify(distribution)
    version = "0.1.0-RC1"
    paths = release.artifact_paths(distribution, version)
    for old, new in zip(release.artifact_paths(distribution, manifest["version"]), paths):
        new.parent.mkdir(parents=True, exist_ok=True)
        old.rename(new)
    paths[-1].write_text(paths[-1].read_text().replace("<version>0.1.0</version>", f"<version>{version}</version>"))
    manifest.update(tag="v" + version, version=version,
                    sha256={p.relative_to(distribution).as_posix(): release.sha(p) for p in paths})
    release.write_json(distribution / "manifest.json", manifest)
    return distribution


@pytest.mark.parametrize("fault", ["dry-run", "wrong-commit", "missing-host", "failed-host", "wrong-jar"])
def test_github_rc_rejects_unqualified_candidates(rc_distribution, tmp_path, monkeypatch, fault):
    reports = tmp_path / "evidence"
    evidence(rc_distribution, reports)
    monkeypatch.setattr(release, "check_tag", lambda tag: "b" * 40 if fault == "wrong-commit" else "a" * 40)
    monkeypatch.setattr(release.subprocess, "run", lambda *a, **kw: pytest.fail("invalid candidate reached GitHub"))
    if fault == "dry-run":
        manifest = release.verify(rc_distribution)
        manifest["publishable"] = False
        release.write_json(rc_distribution / "manifest.json", manifest)
    elif fault == "missing-host":
        (reports / "consumer-Windows.json").unlink()
    elif fault in ("failed-host", "wrong-jar"):
        record = json.loads((reports / "consumer-Windows.json").read_text())
        record["status" if fault == "failed-host" else "library_sha256"] = "ERROR"
        release.write_json(reports / "consumer-Windows.json", record)
    with pytest.raises(ValueError):
        release.github_release(rc_distribution, reports)


def test_github_rc_uploads_exact_qualified_bytes_before_publishing(rc_distribution, tmp_path, monkeypatch):
    reports = tmp_path / "evidence"
    evidence(rc_distribution, reports)
    monkeypatch.setattr(release, "check_tag", lambda tag: "a" * 40)
    monkeypatch.setattr(release, "portal", lambda *a: pytest.fail("GitHub RC contacted Central"))
    calls = []
    monkeypatch.setattr(release.subprocess, "run", lambda args, **kw: calls.append(args))
    release.github_release(rc_distribution, reports)
    assert len(calls) == 2 and calls[0][:4] == ["gh", "release", "create", "v0.1.0-RC1"]
    assert "--draft" in calls[0] and "--prerelease" in calls[0] and "--verify-tag" in calls[0]
    assert calls[1] == ["gh", "release", "edit", "v0.1.0-RC1", "--draft=false", "--prerelease", "--latest=false"]
    manifest = release.verify(rc_distribution)
    archive = rc_distribution / "chisel-async-0.1.0-RC1-maven.zip"
    with zipfile.ZipFile(archive) as bundle:
        for name, digest in manifest["sha256"].items():
            assert release.hashlib.sha256(bundle.read(name)).hexdigest() == digest
        assert json.loads(bundle.read("evidence/consumer-Windows.json"))["status"] == "PASS"
        assert b"not published to Maven Central" in bundle.read("README.txt")
    assets = {Path(arg).name: Path(arg) for arg in calls[0] if Path(arg).is_file()}
    for line in (rc_distribution / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ")
        assert release.sha(assets[name]) == digest


def test_github_upload_failure_does_not_publish_draft(rc_distribution, tmp_path, monkeypatch):
    reports = tmp_path / "evidence"
    evidence(rc_distribution, reports)
    monkeypatch.setattr(release, "check_tag", lambda tag: "a" * 40)
    calls = []
    def fail_upload(args, **kwargs):
        calls.append(args)
        raise subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(release.subprocess, "run", fail_upload)
    with pytest.raises(subprocess.CalledProcessError):
        release.github_release(rc_distribution, reports)
    assert len(calls) == 1 and "--draft" in calls[0]
