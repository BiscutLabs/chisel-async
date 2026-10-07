"""Build a tag-derived Maven distribution, then sign/publish those exact files.

Build defaults to a clean checkout at the requested tag. --dry-run permits an
untagged development checkout and marks its output permanently unpublishable.
Publishing uses the Central Portal API; it never invokes a second compilation.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
GROUP = "io.github.biscutlabs"
ARTIFACT = "chisel-async_2.13"
TAG = re.compile(r"v((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-RC[1-9]\d*)?)")
API = "https://central.sonatype.com/api/v1/publisher/"


def version_from_tag(tag):
    match = TAG.fullmatch(tag)
    if not match:
        raise ValueError("Release tag must be vMAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCH-RCn")
    return match.group(1)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def git(*args, root=ROOT):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                          text=True).stdout.strip()


def check_tag(tag, root=ROOT):
    version_from_tag(tag)
    commit = git("rev-parse", "HEAD", root=root)
    if git("rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}", root=root) != commit:
        raise ValueError("Release tag does not point at HEAD")
    if git("status", "--porcelain", "--untracked-files=normal", root=root):
        raise ValueError("Release requires a clean working tree")
    return commit


def artifact_paths(directory, version):
    base = directory / "maven" / GROUP.replace(".", "/") / ARTIFACT / version
    prefix = f"{ARTIFACT}-{version}"
    return [base / f"{prefix}{suffix}" for suffix in
            (".jar", "-sources.jar", "-javadoc.jar", ".pom")]


def check_contents(paths, version):
    binary, sources, documentation, pom = paths
    ns = {"m": "http://maven.apache.org/POM/4.0.0"}
    model = ET.parse(pom).getroot()
    for field, expected in (("groupId", GROUP), ("artifactId", ARTIFACT), ("version", version)):
        if model.findtext(f"m:{field}", namespaces=ns) != expected:
            raise ValueError(f"POM {field} mismatch")
    for field in ("name", "description", "url", "licenses/license/name",
                  "developers/developer/name", "developers/developer/url", "scm/connection"):
        if not model.findtext("/".join("m:" + part for part in field.split("/")), namespaces=ns):
            raise ValueError(f"Missing POM metadata: {field}")
    with zipfile.ZipFile(binary) as bundle:
        required = ["META-INF/LICENSE", "chiselasync/core/AsyncModule.class",
                    "chiselasync/contract-v3.schema.json", "chiselasync/trace-v1.schema.json"]
        required += [str(p.relative_to(ROOT / "src/main/resources")).replace("\\", "/")
                     for p in sorted((ROOT / "src/main/resources/chiselasync/sv").glob("*.sv"))]
        if not all(name in bundle.namelist() and bundle.read(name) for name in required):
            raise ValueError("Binary JAR is missing required classes/models/schemas/license")
    with zipfile.ZipFile(sources) as bundle:
        if "META-INF/LICENSE" not in bundle.namelist() or not any(n.endswith(".scala") for n in bundle.namelist()):
            raise ValueError("Missing source JAR contents")
    with zipfile.ZipFile(documentation) as bundle:
        if "index.html" not in bundle.namelist() or not bundle.read("index.html"):
            raise ValueError("Missing API documentation")


def verify(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    version = version_from_tag(manifest["tag"])
    if manifest.get("schema") != 1 or manifest.get("version") != version:
        raise ValueError("Invalid release manifest")
    if not re.fullmatch(r"[0-9a-f]{40}", manifest.get("commit", "")):
        raise ValueError("Invalid release commit")
    paths = artifact_paths(directory, version)
    expected = {p.relative_to(directory).as_posix() for p in paths}
    if set(manifest["sha256"]) != expected:
        raise ValueError("Unexpected release artifact inventory")
    for path in paths:
        if path.is_symlink() or sha(path) != manifest["sha256"][path.relative_to(directory).as_posix()]:
            raise ValueError(f"Release artifact hash mismatch: {path.name}")
    check_contents(paths, version)
    return manifest


def check_test_reports(directory):
    reports = list(Path(directory).glob("*.xml"))
    count = 0
    for report in reports:
        suite = ET.parse(report).getroot()
        if any(node.tag in {"failure", "error", "skipped"} for node in suite.iter()):
            raise ValueError("Release Scala tests failed or were skipped")
        count += len(list(suite.iter("testcase")))
    if not reports or not count:
        raise ValueError("Release Scala test suite is empty")
    return count


def build(tag, output, dry_run=False):
    version = version_from_tag(tag)
    commit = git("rev-parse", "HEAD") if dry_run else check_tag(tag)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)  # Never reuse an older release attempt.
    log = output / "build.log"
    test_reports = output / "scala-tests"
    test_reports.mkdir()
    command = [sys.executable, str(ROOT / "tools/sbt.py"), "--bootstrap",
               f'set ThisBuild / version := "{version}"',
               'set Test / testOptions += Tests.Argument(TestFrameworks.ScalaTest, "-u", '
               + json.dumps(test_reports.as_posix()) + ")",
               "test", "package", "packageSrc", "packageDoc", "makePom"]
    with log.open("w", encoding="utf-8") as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=1800)
    paths = artifact_paths(output, version)
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "target/scala-2.13" / path.name, path)
    check_contents(paths, version)
    test_count = check_test_reports(test_reports)
    manifest = {"schema": 1, "tag": tag, "version": version, "commit": commit, "scala_tests": test_count,
                "publishable": not dry_run, "sha256": {
                    p.relative_to(output).as_posix(): sha(p) for p in paths}}
    write_json(output / "manifest.json", manifest)
    verify(output)
    print(f"Built {GROUP}:{ARTIFACT}:{version}; publishable={not dry_run}; {output}")


def check_evidence(directory, evidence, manifest):
    reports = sorted(Path(evidence).glob("consumer-*.json"))
    hosts = set()
    for report in reports:
        record = json.loads(report.read_text(encoding="utf-8"))
        if (record.get("status") != "PASS" or record.get("manifest_sha256") != sha(directory / "manifest.json")
                or record.get("commit") != manifest["commit"]
                or record.get("library_sha256") != sha(artifact_paths(directory, manifest["version"])[0])
                or record.get("qualification_status") != "PASS"):
            raise ValueError(f"Invalid release consumer evidence: {report.name}")
        host = record.get("system")
        if host in hosts or host not in {"Windows", "Linux"}:
            raise ValueError("Duplicate or unsupported release consumer host")
        hosts.add(host)
    if hosts != {"Windows", "Linux"}:
        raise ValueError("Release requires Windows and Linux consumer/qualification evidence")


def gpg_path(path, executable):
    """MSYS GnuPG expects POSIX paths even when called by native Python."""
    parent = Path(executable).parent
    if (parent / "msys-2.0.dll").is_file():
        return subprocess.check_output([str(parent / "cygpath.exe"), "-u", str(path)],
                                       text=True, timeout=10).strip()
    return str(path)


def sign_bundle(directory, manifest):
    fingerprint = os.environ["PGP_FINGERPRINT"]
    if not re.fullmatch(r"[0-9A-Fa-f]{40}|[0-9A-Fa-f]{64}", fingerprint):
        raise ValueError("PGP_FINGERPRINT must be a full fingerprint")
    secret = base64.b64decode("".join(os.environ["PGP_SECRET"].split()), validate=True)
    passphrase = os.environ["PGP_PASSPHRASE"].encode() + b"\n"
    bundle_path = directory / "central-bundle.zip"
    executable = shutil.which("gpg")
    if not executable:
        raise RuntimeError("GnuPG is required to sign a release")
    with tempfile.TemporaryDirectory(prefix="chisel-async-sign-") as temporary:
        environment = {**os.environ, "GNUPGHOME": gpg_path(temporary, executable)}
        # Secrets travel on stdin, never command-line arguments or logs.
        def gpg(arguments, data=None):
            result = subprocess.run([executable, "--batch", *arguments], input=data, env=environment,
                                    capture_output=True, timeout=60)
            if result.returncode:
                raise RuntimeError("GPG operation failed; check the signing key, fingerprint and passphrase")
        try:
            gpg(["--import"], secret)
            with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for path in artifact_paths(directory, manifest["version"]):
                    signature = Path(temporary) / (path.name + ".asc")
                    gpg(["--yes", "--pinentry-mode", "loopback", "--passphrase-fd", "0",
                         "--local-user", fingerprint, "--armor", "--detach-sign",
                         "--output", gpg_path(signature, executable), gpg_path(path, executable)], passphrase)
                    gpg(["--verify", gpg_path(signature, executable), gpg_path(path, executable)])
                    relative = path.relative_to(directory / "maven").as_posix()
                    content = path.read_bytes()
                    bundle.writestr(relative, content)
                    bundle.writestr(relative + ".asc", signature.read_bytes())
                    for algorithm in ("md5", "sha1", "sha256"):
                        bundle.writestr(relative + "." + algorithm, hashlib.new(algorithm, content).hexdigest())
        finally:
            gpgconf = Path(executable).with_name("gpgconf" + Path(executable).suffix)
            if gpgconf.is_file():
                subprocess.run([str(gpgconf), "--kill", "all"], env=environment,
                               capture_output=True, timeout=15, check=False)
    return bundle_path


def portal(endpoint, token, data=b"", content_type="application/octet-stream"):
    request = urllib.request.Request(API + endpoint, data=data, method="POST",
                                     headers={"Authorization": "Bearer " + token, "Content-Type": content_type})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        # Do not echo request headers, credential data, or arbitrary response text.
        raise RuntimeError(f"Central request failed with HTTP {error.code}") from None


def publish(directory, evidence):
    directory = Path(directory).resolve()
    manifest = verify(directory)
    if manifest.get("publishable") is not True:
        raise ValueError("Dry-run artifacts cannot be published")
    if check_tag(manifest["tag"]) != manifest["commit"]:
        raise ValueError("Release source commit mismatch")
    check_evidence(directory, evidence, manifest)
    username, password = os.environ["SONATYPE_USERNAME"], os.environ["SONATYPE_PASSWORD"]
    if not username or not password:
        raise ValueError("Central Portal token is required")
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    receipt_path = directory / "central-receipt.json"
    started_path = directory / "upload-started.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (receipt["manifest_sha256"] != sha(directory / "manifest.json")
                or receipt["bundle_sha256"] != sha(directory / "central-bundle.zip")):
            raise ValueError("Existing deployment does not match release files")
    else:
        if started_path.exists():
            raise ValueError("Previous upload outcome is unknown; inspect Central before retrying")
        bundle_path = sign_bundle(directory, manifest)
        boundary = "chiselasync" + uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"bundle\"; "
                'filename="central-bundle.zip"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
        body += bundle_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        write_json(started_path, {"manifest_sha256": sha(directory / "manifest.json"),
                                 "bundle_sha256": sha(bundle_path)})
        endpoint = "upload?" + urllib.parse.urlencode({
            "name": f"{ARTIFACT}-{manifest['version']}", "publishingType": "AUTOMATIC"})
        deployment = str(uuid.UUID(portal(endpoint, token, body, f"multipart/form-data; boundary={boundary}").strip()))
        receipt = {"deployment_id": deployment, "manifest_sha256": sha(directory / "manifest.json"),
                   "bundle_sha256": sha(bundle_path), "state": "UPLOADED"}
        write_json(receipt_path, receipt)
    # Retain the deployment identity before waiting. Reruns poll it without uploading again.
    deployment = str(uuid.UUID(receipt["deployment_id"]))
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        status = json.loads(portal("status?" + urllib.parse.urlencode({"id": deployment}), token))
        if status.get("deploymentId") != deployment:
            raise RuntimeError("Central returned status for a different deployment")
        state = status.get("deploymentState")
        receipt["state"] = state
        write_json(receipt_path, receipt)
        print(f"Central deployment {deployment}: {state}", flush=True)
        if state == "PUBLISHED":
            return
        if state not in {"PENDING", "VALIDATING", "VALIDATED", "PUBLISHING"}:
            raise RuntimeError("Central deployment failed or returned an unknown state; inspect the Portal")
        time.sleep(15)
    raise RuntimeError("Central publication is still pending; rerun publish to resume this deployment")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build")
    builder.add_argument("--tag", required=True)
    builder.add_argument("--output", type=Path, required=True)
    builder.add_argument("--dry-run", action="store_true")
    validator = commands.add_parser("verify")
    validator.add_argument("--directory", type=Path, required=True)
    publisher = commands.add_parser("publish")
    publisher.add_argument("--directory", type=Path, required=True)
    publisher.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        build(args.tag, args.output, args.dry_run)
    elif args.command == "verify":
        result = verify(args.directory)
        print(f"Release artifacts verified: {result['tag']} at {result['commit']}")
    else:
        publish(args.directory, args.evidence)


if __name__ == "__main__":
    main()
