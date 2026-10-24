module.exports = {
  // Resolve via Node so NODE_PATH works with mise's separate npm installs.
  extends: [require.resolve("@commitlint/config-conventional")],
};
