import DOMPurify from "dompurify";
import {Marked} from "marked";
import katex from "katex";
import "katex/dist/katex.min.css";

const escapeHTML = text => String(text).replace(/[&<>"']/g, character =>
  ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[character]);

export function mathHTML(body, displayMode = true) {
  return katex.renderToString(String(body), {
    displayMode, throwOnError: false, trust: false, strict: "ignore",
    maxExpand: 1000, maxSize: 100,
  });
}

const markdown = new Marked({gfm: true, breaks: false});
markdown.use({
  renderer: {html({text}) {return escapeHTML(text);}},
  extensions: [
    {
      name: "blockMath", level: "block",
      start: source => source.indexOf("$$"),
      tokenizer(source) {
        const match = /^\$\$\s*\n?([\s\S]+?)\n?\$\$(?:\n|$)/.exec(source);
        if (match) return {type: "blockMath", raw: match[0], body: match[1].trim()};
      },
      renderer: token => mathHTML(token.body),
    },
    {
      name: "inlineMath", level: "inline",
      start: source => source.indexOf("$"),
      tokenizer(source) {
        const match = /^\$(?!\$)([^\s$](?:[^$\n]*?[^\s$])?)\$(?!\d)/.exec(source);
        if (match) return {type: "inlineMath", raw: match[0], body: match[1]};
      },
      renderer: token => mathHTML(token.body, false),
    },
  ],
});

export function sanitizeHTML(body) {
  return DOMPurify.sanitize(String(body), {
    FORCE_BODY: true,
    FORBID_TAGS: ["script", "iframe", "object", "embed", "form"],
  });
}

export function markdownHTML(body) {
  return sanitizeHTML(markdown.parse(String(body)));
}
