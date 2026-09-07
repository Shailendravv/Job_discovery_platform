import DOMPurify from "dompurify";

export function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [
      "p", "h1", "h2", "h3", "h4", "h5", "h6",
      "ul", "ol", "li",
      "strong", "b", "em", "i", "u",
      "a", "br", "span",
    ],
    ALLOWED_ATTR: ["href", "target", "rel"],
  });
}

export function isHtmlContent(text: string): boolean {
  return /<[a-z][\s\S]*?>/i.test(text);
}

export function isTreeFormat(text: string): boolean {
  return /^\s*- [a-z]/.test(text.trim());
}

export function extractTreeText(text: string): string {
  const lines = text.split("\n");
  const parts: string[] = [];
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const content = trimmed.replace(/^- /, "");
    const nodeType = content.split(":")[0].split(" ")[0];
    const skipTypes = ["img", "button", "combobox", "separator", "log", "iframe",
                        "banner", "navigation", "contentinfo", "main", "/url"];
    if (skipTypes.includes(nodeType)) continue;
    let value = "";
    if (content.includes(":")) {
      value = content.substring(content.indexOf(":") + 1).trim();
    } else {
      const quoteMatch = content.match(/["']([^"']*)["']/);
      if (quoteMatch) value = quoteMatch[1];
    }
    value = value.replace(/\[([^\]]+)\]/g, "").trim();
    value = value.replace(/^["']|["']$/g, "").trim();
    if (value) parts.push(value);
  }
  return parts.join("\n");
}
