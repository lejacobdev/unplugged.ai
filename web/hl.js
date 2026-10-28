// Small offline syntax highlighter for chat code blocks. No libraries: HTML/XML, CSS, JSON and a generic C-like / Python / shell tokenizer.
window.hl = (function () {
  const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const sp = (c, s) => `<span class="tk-${c}">${esc(s)}</span>`;
  const KW = new Set(('abstract as async await break case catch class const continue def default defer del do elif else enum except export extends false fn final finally for from func function go if impl implements import in instanceof interface is lambda let loop match mod mut new nil none None not null of or and package pass private protected pub public raise return self static struct super switch this throw true True False try type typeof union unsafe use using var void where while with yield echo fi then done esac local readonly select int float double char bool string str long short unsigned signed auto extern register volatile inline template typename namespace').split(' '));
  const HASH = new Set(['python', 'py', 'bash', 'sh', 'shell', 'zsh', 'yaml', 'yml', 'toml', 'ruby', 'rb', 'r', 'perl', 'makefile', 'dockerfile', 'ini', 'conf']);
  const SLASH = new Set(['js', 'javascript', 'jsx', 'ts', 'typescript', 'tsx', 'java', 'c', 'cpp', 'c++', 'cs', 'csharp', 'go', 'rust', 'rs', 'swift', 'kotlin', 'php', 'scala', 'dart', 'json', 'jsonc', 'objc', 'glsl', 'sql', 'css', 'scss', 'less']);

  function markup(code) {
    const re = /(<!--[\s\S]*?-->)|(<!DOCTYPE[^>]*>)|(<\/?)([A-Za-z][\w:.-]*)((?:"[^"]*"|'[^']*'|[^>"'])*)(\/?>)/gi;
    let out = '', i = 0, m;
    while ((m = re.exec(code))) {
      out += esc(code.slice(i, m.index)); i = re.lastIndex;
      if (m[1]) out += sp('c', m[1]);
      else if (m[2]) out += sp('k', m[2]);
      else {
        out += sp('p', m[3]) + sp('t', m[4]);
        out += m[5].replace(/(\s+)|([\w:@.-]+)|(=)|("[^"]*"|'[^']*')|([\s\S])/g, (x, ws, name, eq, str) => ws ? ws : name ? sp('a', name) : eq ? sp('p', eq) : str ? sp('s', str) : esc(x));
        out += sp('p', m[6]);
        const tag = m[4].toLowerCase();
        if ((tag === 'style' || tag === 'script') && m[3] === '<' && m[6] === '>') {  // highlight what is inside <style> / <script>
          const end = code.toLowerCase().indexOf('</' + tag, i);
          if (end > i) { out += run(code.slice(i, end), tag === 'style' ? 'css' : 'js'); i = re.lastIndex = end; }
        }
      }
    }
    return out + esc(code.slice(i));
  }

  function css(code) {
    const re = /(\/\*[\s\S]*?\*\/)|("[^"\n]*"|'[^'\n]*')|(#[0-9a-fA-F]{3,8}\b)|(-?\d*\.?\d+(?:px|em|rem|%|vh|vw|s|ms|deg|fr)?)|(@[\w-]+)|([\w-]+)(?=\s*:(?!:))|([.#]?[A-Za-z][\w-]*(?=[^{};]*\{))/g;
    let out = '', i = 0, m;
    while ((m = re.exec(code))) {
      out += esc(code.slice(i, m.index)); i = re.lastIndex;
      out += m[1] ? sp('c', m[1]) : m[2] ? sp('s', m[2]) : m[3] ? sp('n', m[3]) : m[4] ? sp('n', m[4]) : m[5] ? sp('k', m[5]) : m[6] ? sp('a', m[6]) : sp('t', m[7]);
    }
    return out + esc(code.slice(i));
  }

  function generic(code, lang) {
    const com = HASH.has(lang) ? '#[^\\n]*' : lang === 'sql' ? '--[^\\n]*' : '\\/\\/[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/';
    const re = new RegExp('(' + com + ')|("""[\\s\\S]*?"""|\'\'\'[\\s\\S]*?\'\'\'|"(?:\\\\.|[^"\\\\\\n])*"|\'(?:\\\\.|[^\'\\\\\\n])*\'|`(?:\\\\.|[^`\\\\])*`)|(\\b0x[0-9a-fA-F]+\\b|\\b\\d+(?:\\.\\d+)?(?:e[+-]?\\d+)?\\b)|([A-Za-z_$][\\w$]*)(\\s*\\()?', 'g');
    let out = '', i = 0, m;
    while ((m = re.exec(code))) {
      out += esc(code.slice(i, m.index)); i = re.lastIndex;
      if (m[1]) out += sp('c', m[1]);
      else if (m[2]) out += sp('s', m[2]);
      else if (m[3]) out += sp('n', m[3]);
      else if (KW.has(m[4]) || (lang === 'sql' && /^(select|from|where|insert|into|values|update|delete|create|table|join|left|right|inner|group|order|by|limit|having|as|on|and|or|not|null|primary|key|distinct)$/i.test(m[4]))) out += sp('k', m[4]) + esc(m[5] || '');
      else if (m[5]) out += sp('f', m[4]) + esc(m[5]);
      else out += esc(m[4]);
    }
    return out + esc(code.slice(i));
  }

  function json(code) {
    return code.replace(/("(?:\\.|[^"\\\n])*")(\s*:)?|\b(true|false|null)\b|(-?\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b)|([\s\S])/gi,
      (x, str, colon, kw, num) => str ? (colon ? sp('a', str) + esc(colon) : sp('s', str)) : kw ? sp('k', kw) : num ? sp('n', num) : esc(x));
  }

  function run(code, lang) {
    lang = (lang || '').toLowerCase();
    if (['html', 'xml', 'svg', 'vue', 'xhtml'].includes(lang)) return markup(code);
    if (['css', 'scss', 'less'].includes(lang)) return css(code);
    if (lang === 'json' || lang === 'jsonc') return json(code);
    if (HASH.has(lang) || SLASH.has(lang)) return generic(code, lang);
    return null;
  }
  return (code, lang) => { try { const r = run(code, lang); return r == null ? esc(code) : r; } catch (e) { return esc(code); } };
})();
