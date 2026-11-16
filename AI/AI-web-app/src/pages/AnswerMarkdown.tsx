import type { ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

// The site a link goes to, for example "example.org"; empty when the address is not a full web address.
const siteOf = (href: string | undefined): string => {
  try {
    return new URL(href ?? "").host;
  } catch {
    return "";
  }
};

// A browser loads an image as soon as it shows it. The image address can carry data
// (for example "?note=...") to any server, without anyone clicking. So: show the address as text.
function BlockedImage({ src, alt }: Readonly<{ src?: unknown; alt?: string }>) {
  const label = alt ? `image not loaded: ${alt}` : "image not loaded";
  return (
    <span className="answer-blocked-image">
      [{label}] {String(src ?? "")}
    </span>
  );
}

// A new tab, no "Referer" header for the other site, and the site's name next to the link,
// so a reader sees where "sign in again" really goes before clicking.
function SafeLink({ href, children }: Readonly<{ href?: string; children?: ReactNode }>) {
  const site = siteOf(href);
  return (
    <>
      <a href={href} target="_blank" rel="noopener noreferrer nofollow">
        {children}
      </a>
      {site && <span className="answer-link-site"> ({site})</span>}
    </>
  );
}

const SAFE_ELEMENTS: Components = {
  img: ({ src, alt }) => <BlockedImage src={src} alt={alt} />,
  a: ({ href, children }) => <SafeLink href={href}>{children}</SafeLink>,
};

// An LLM answer is untrusted input. In both modes, react-markdown shows HTML in the answer as text
// and removes script addresses from links. Safe mode (Controls page) also blocks images and makes links safer.
// Unsafe mode is the workshop's starting point: it shows the image leak.
function AnswerMarkdown({ text, safe }: Readonly<{ text: string; safe: boolean }>) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={safe ? SAFE_ELEMENTS : undefined}>
      {text}
    </ReactMarkdown>
  );
}

export default AnswerMarkdown;
