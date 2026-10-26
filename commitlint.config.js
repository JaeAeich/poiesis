const path = require("node:path");

const configDir = process.env.COMMITLINT_CONFIG_DIR || __dirname;

module.exports = {
  // mise's native npm launcher overwrites NODE_PATH; resolve both install layouts.
  extends: [require.resolve("@commitlint/config-conventional", {
    paths: [configDir, path.join(configDir, "lib")],
  })],
};
