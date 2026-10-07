# Packaging and releasing

Public distribution uses **GitHub Actions to build/test and Maven Central to host
dependencies**. GitHub Releases carries release notes, signed bundles and evidence.
GitHub Packages may host authenticated previews later; it is not required to use
the public library. The website is a separate presentation layer over these docs.

No public version has been published yet. The release automation is implemented;
namespace ownership, signing credentials, environment configuration and public
release acceptance must be established before triggering a real release.

## Artifacts

One release contains `io.github.biscutlabs:chisel-async_2.13:<version>` with a binary
JAR, sources JAR, API documentation (`-javadoc.jar`) and POM. The binary includes
SV model resources, schemas and the license. The POM records normal transitive
dependencies, project/license/developer/SCM metadata and `early-semver`.
Examples and test projects are not published. There are no OS-specific JAR builds
or bundled native tools.

Published versions are immutable. A bad release requires a corrected version,
not replacement bytes under an existing coordinate. The release script uses a
new output directory and records the tag, commit and SHA-256 of all four files.
See [Sonatype requirements](https://central.sonatype.org/publish/requirements/)
and its [immutability policy](https://central.sonatype.org/publish/requirements/immutability/).

## Tags and workflow

[`tools/release.py`](../tools/release.py) accepts `vMAJOR.MINOR.PATCH` or
`vMAJOR.MINOR.PATCH-RCn`, for example `v0.1.0-RC1`. The tag supplies the Maven
version; the leading `v` is removed. No Chisel version is encoded in it. The
[compatibility matrix](../README.md#compatibility-matrix) records the tested pairing.

The [release workflow](../.github/workflows/release.yml) runs on a `v*` tag push
or manual dispatch:

1. Validate the tag, build the four artifacts on Linux, run Scala tests, and
   validate packaged content and POM metadata. A real build requires a clean
   checkout exactly at that tag.
2. Pass that distribution to the complete native Windows/Linux qualification
   workflow. Each host also compiles the standalone quickstart against the staged
   Maven repository, validates its export and runs its ScalaTest simulation.
   The resolved JAR hash must equal the candidate hash.
3. After both hosts pass, the `maven-central` environment job checks the manifest
   and host evidence, signs the existing files, adds required checksums and uploads
   a Maven-layout bundle using the Central Portal API. It does not rebuild the JAR.
4. Wait for Central to report `PUBLISHED`, then create the GitHub Release with
   the artifacts, manifest, signed bundle, receipt and consumer reports. RC tags
   become GitHub prereleases. Complete native logs remain in the workflow artifacts.

The uploader uses the current
[Central Portal API](https://central.sonatype.org/publish/publish-portal-api/), not
the retired OSSRH endpoints. `AUTOMATIC` publication means that a successful
Central validation proceeds to public publication. Merely resolving a GitHub
Actions job or uploading an Actions artifact does not publish to Central.

## One-time setup

Verify the `io.github.biscutlabs` namespace in the Central Portal. Create a dedicated
signing key and make its public key discoverable as required by Central. Configure
the GitHub environment **`maven-central`**, restricting deployment to release tags
and adding any desired repository release-review protection.

Provide these environment secrets:

| Secret | Value |
| --- | --- |
| `SONATYPE_USERNAME` | Username part of a Central Portal user token |
| `SONATYPE_PASSWORD` | Password part of that token, not the account password |
| `PGP_SECRET` | Base64-encoded exported private signing key |
| `PGP_PASSPHRASE` | Key passphrase |
| `PGP_FINGERPRINT` | Full fingerprint of the key to use |

The publishing runner requires GnuPG. Key import uses an isolated temporary
keyring; key material and passphrases are passed on stdin, not echoed or placed
in process arguments. Build/qualification jobs have no publishing secrets.
GitHub's normal workflow token supplies permissions for creating the GitHub Release.

## Dry-run and local commands

With the configured contributor JDK/firtool, build an **unsigned, unpublishable**
candidate from the current development checkout:

```text
python tools/release.py build --tag v0.1.0-RC1 --dry-run --output target/release-preview
python tools/release.py verify --directory target/release-preview
python tools/check_quickstart.py --distribution target/release-preview
```

Use the repository Python environment and simulator prerequisites for the final
command. Dry-run accepts an untagged/dirty working tree so packaging can be
reviewed before a release commit. Its manifest permanently marks it unpublishable.
It performs no signing, Central upload, tag creation or GitHub Release creation.
Choose a new output directory for another attempt.

For a real build from a clean, already tagged checkout:

```text
python tools/release.py build --tag v0.1.0-RC1 --output target/release-candidate
```

The workflow handles cross-host evidence and publication. The corresponding local
publication command, after obtaining the two matching native reports and setting
credentials, is:

```text
python tools/release.py publish --directory target/release-candidate --evidence target/release-consumer
```

That command **publishes publicly**. It rejects dry-run output, wrong/dirty source,
altered artifact bytes, and missing or mismatched Windows/Linux evidence. It is not
a replacement for reviewing the candidate's complete release scope.

## Preparing a release

Update the README and quickstart dependency/version text for the actual candidate,
state the supported tool/host matrix and migration notes, and verify the complete
catalog and user workflow. Keep physical qualification claims separate. The
historical acceptance records do not automatically close complete-release acceptance.

Commit the reviewed changes, create an annotated tag, and push that specific tag
when ready to trigger publication. A manual workflow dispatch defaults to dry-run;
turning dry-run off requires an existing release tag. No release tag or credentials
are created by the scripts.

## Interrupted publication

The script records `central-receipt.json` as soon as Central returns a deployment
ID. Retain it together with `central-bundle.zip` and the manifest. A retry with
those files polls the same deployment instead of uploading again. The workflow
retains these files even on failure and restores them when the publishing job is rerun.

If upload started but no deployment ID was received, `upload-started.json` prevents
an automatic retry with an unknown outcome. Inspect the Portal and recover the
existing deployment identity before proceeding. Do not delete that marker and
blindly repeat a potentially successful upload.

If Central succeeded but GitHub Release creation failed, keep the immutable Maven
artifacts and receipt; rerun only the failed publication job. Do not rebuild or
replace the Maven version. Check the Portal for validation errors and retain
failure evidence rather than reporting a merely uploaded candidate as published.
