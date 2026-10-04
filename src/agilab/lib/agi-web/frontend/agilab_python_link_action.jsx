import React from "react";

export const safeURL = value => /^(https?:|mailto:|blob:|data:image\/|\/[^/]|#)/i.test(value ?? "") ? value : "#";

export function PythonLinkAction({ node, view }) {
  const p = node.props;
  const linkButton = node.kind === "link_button";
  const disabled = linkButton && Boolean(p.disabled);
  const onClick = disabled ? event => event.preventDefault()
    : node.kind === "page_link" && p.url.startsWith("/")
      ? event => { event.preventDefault(); view.navigate(p.url); }
      : undefined;
  return <a className="py-link-button" data-widget-kind={node.kind} data-widget-key={p.key}
    href={disabled ? undefined : safeURL(p.url)} download={p.filename}
    target={linkButton && !disabled ? p.target ?? "_blank" : undefined}
    rel={linkButton && !disabled ? "noopener" : undefined}
    aria-disabled={disabled || undefined} tabIndex={disabled ? -1 : undefined}
    onClick={onClick}>{p.label}</a>;
}
