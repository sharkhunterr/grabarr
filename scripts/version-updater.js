/**
 * standard-version custom updater for `grabarr/__init__.py`.
 *
 * Mirrors Ghostarr's `version-updater.js` but for grabarr's package
 * init file (`__version__ = "x.y.z"`).
 */

const versionRegex = /__version__\s*=\s*["']([^"']+)["']/;

module.exports.readVersion = function (contents) {
  const match = contents.match(versionRegex);
  if (match) {
    return match[1];
  }
  throw new Error('Could not find __version__ in grabarr/__init__.py');
};

module.exports.writeVersion = function (contents, version) {
  return contents.replace(versionRegex, `__version__ = "${version}"`);
};
