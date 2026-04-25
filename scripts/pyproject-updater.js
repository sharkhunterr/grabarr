/**
 * standard-version custom updater for `pyproject.toml`.
 *
 * Bumps the top-level `[project] version = "x.y.z"` line. Targets only
 * the FIRST occurrence anchored on a line start so other quoted version
 * strings deeper in the file (dependency pins like `httpx>=0.27`) are
 * left untouched.
 */

const versionRegex = /^version\s*=\s*["']([^"']+)["']/m;

module.exports.readVersion = function (contents) {
  const match = contents.match(versionRegex);
  if (match) {
    return match[1];
  }
  throw new Error('Could not find top-level `version = "..."` in pyproject.toml');
};

module.exports.writeVersion = function (contents, version) {
  return contents.replace(versionRegex, `version = "${version}"`);
};
