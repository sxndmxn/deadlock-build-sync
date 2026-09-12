#!/bin/sh
set -eu

repository_directory=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
binary_path=${1:?Supply the absolute binary path.}
target_name=${2:?Supply the Rust target name.}

case "$binary_path" in
    /*) ;;
    *) echo "The binary path must be absolute." >&2; exit 1 ;;
esac
case "$target_name" in
    ''|*[!a-zA-Z0-9_-]*) echo "The target name is invalid." >&2; exit 1 ;;
esac

version_output=$("$binary_path" --version)
case "$version_output" in
    'deadlock-build-sync '*) version=${version_output#deadlock-build-sync } ;;
    *) echo "The binary has an invalid version response." >&2; exit 1 ;;
esac
case "$version" in
    ''|*[!a-zA-Z0-9.+-]*) echo "The package version is invalid." >&2; exit 1 ;;
esac

package_name="deadlock-build-sync-$version-$target_name"
temporary_directory=$(mktemp -d)
trap 'rm -rf -- "$temporary_directory"' EXIT HUP INT TERM
package_directory="$temporary_directory/$package_name"
mkdir "$package_directory"
cp "$binary_path" "$package_directory/deadlock-build-sync"
cp "$repository_directory/LICENSE" "$repository_directory/README.md" "$package_directory/"
mkdir -p "$repository_directory/dist"
archive_path="$repository_directory/dist/$package_name.tar.gz"
tar -C "$temporary_directory" -czf "$archive_path" "$package_name"

inspection_directory="$temporary_directory/inspection"
mkdir "$inspection_directory"
tar -C "$inspection_directory" -xzf "$archive_path"
cd "$inspection_directory/$package_name"
test -s LICENSE
test -s README.md
test "$(./deadlock-build-sync --version)" = "$version_output"
./deadlock-build-sync --help >/dev/null
for command in sync build status refresh-evidence recommend quality-report preview install install-artifacts export-context generate-narratives restore trace-summary; do
    ./deadlock-build-sync "$command" --help >/dev/null
done

cd "$repository_directory/dist"
if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$package_name.tar.gz" >"$package_name.tar.gz.sha256"
else
    shasum -a 256 "$package_name.tar.gz" >"$package_name.tar.gz.sha256"
fi
printf 'Verified release archive: %s\n' "$archive_path"
