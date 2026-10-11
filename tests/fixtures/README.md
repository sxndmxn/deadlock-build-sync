# Test fixtures

`keyvalues3-v5.kv3.b64` is the base64-encoded
[`v5.kv3.bin`](https://github.com/kristiker/keyvalues3/blob/main/tests/documents/binary/v5.kv3.bin)
fixture from the MIT-licensed `keyvalues3` project. It exercises the same KV3 v5
decoder used for current Deadlock caches without including personal Steam data.

Run `cargo run --package deadlock-build-sync --example check_safety` to check the fixture and temporary Steam caches.
The executable checks cache preservation, repeated installation, write guards, backup validation, restoration, and interrupted artifact installation.
These checks do not certify live builds.
