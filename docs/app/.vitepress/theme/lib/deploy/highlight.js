// Syntax colouring for the file panel, as tokens the template renders (no HTML strings).

/**
 * @typedef {object} Token
 * @property {string} text
 * @property {string} [className] CSS class of the span; plain text when absent.
 */

const COMMENT_LINE = /^\s*#/;
const TRAILING_COMMENT = /(?=  # )/;
const MAPPING_KEY = /^(\s*-?\s*)([\w.]+)(:)/;
const MAPPING_VALUE = /(: )(.+)$/;
const SHELL_COMMAND = /^(kubectl|helm)/;

/** Push a token, merging plain text into the previous plain token. */
function pushToken(tokens, text, className) {
  if (!text) return;
  const last = tokens[tokens.length - 1];
  if (!className && last && !last.className) last.text += text;
  else tokens.push(className ? { text, className } : { text });
}

/**
 * One values.yaml line: keys, values, comments; example values get the "exv" mark.
 * @param {string} line
 * @returns {Token[]}
 */
export function highlightYamlLine(line) {
  if (COMMENT_LINE.test(line)) return line ? [{ text: line, className: "c" }] : [];
  const [main, ...rest] = line.split(TRAILING_COMMENT);
  const comment = rest.join("");
  const isExample = /example/.test(comment);
  const tokens = [];

  let position = 0;
  const keyMatch = MAPPING_KEY.exec(main);
  if (keyMatch) {
    pushToken(tokens, keyMatch[1]);
    pushToken(tokens, keyMatch[2], "k");
    position = keyMatch[0].length - 1;
  }
  const valueMatch = MAPPING_VALUE.exec(main.slice(position));
  if (valueMatch) {
    const valueStart = position + valueMatch.index + valueMatch[1].length;
    pushToken(tokens, main.slice(position, valueStart));
    pushToken(tokens, valueMatch[2], isExample ? "s exv" : "s");
  } else {
    pushToken(tokens, main.slice(position));
  }
  if (comment) pushToken(tokens, comment, isExample ? "ex" : "c");
  return tokens;
}

/**
 * One install.sh line: comments, and the kubectl/helm command name.
 * @param {string} line
 * @returns {Token[]}
 */
export function highlightShellLine(line) {
  if (COMMENT_LINE.test(line)) return [{ text: line, className: "c" }];
  const tokens = [];
  const command = SHELL_COMMAND.exec(line);
  if (command) pushToken(tokens, command[1], "k");
  pushToken(tokens, line.slice(command ? command[1].length : 0));
  return tokens;
}
