import {
  Children,
  isValidElement,
  useRef,
  useState,
  type ComponentPropsWithoutRef,
  type ReactElement,
  type ReactNode,
} from "react";
import Markdown, { type Components, type UrlTransform } from "react-markdown";
import rehypeSanitize, {
  defaultSchema,
  type Options as SanitizeSchema,
} from "rehype-sanitize";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

import styles from "./AiMessageContent.module.css";

type AiMessageContentProps = {
  content: string;
};

type CopyStatus = "idle" | "copied" | "manual";

const APDL_LANGUAGE_ALIASES = new Set(["apdl", "ansys", "ansys-apdl", "mapdl"]);
const LANGUAGE_CLASS_PATTERN = /^language-([a-z0-9_+-]+)$/i;
const EXPLICIT_HTTP_URL_PATTERN = /^https?:\/\//i;
const MAILTO_URL_PATTERN = /^mailto:/i;
const URL_SCHEME_PATTERN = /^[a-z][a-z0-9+.-]*:/i;
const CONTROL_CHARACTER_PATTERN = /[\u0000-\u001f\u007f]/;
const ALLOWED_ELEMENTS = [
  "a",
  "blockquote",
  "br",
  "code",
  "del",
  "em",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "hr",
  "img",
  "input",
  "li",
  "ol",
  "p",
  "pre",
  "strong",
  "table",
  "tbody",
  "td",
  "th",
  "thead",
  "tr",
  "ul",
] as const;

const SANITIZE_SCHEMA: SanitizeSchema = {
  ...defaultSchema,
  tagNames: [...ALLOWED_ELEMENTS],
  attributes: {
    a: ["href"],
    code: [["className", LANGUAGE_CLASS_PATTERN]],
    img: ["src", "alt", "title"],
    input: [
      ["type", "checkbox"],
      "checked",
      "disabled",
    ],
    td: ["align"],
    th: ["align"],
  },
  protocols: {
    href: ["http", "https", "mailto"],
    src: ["http", "https"],
  },
  required: {
    input: {
      disabled: true,
      type: "checkbox",
    },
  },
  strip: ["script", "style"],
};

const safeUrlTransform: UrlTransform = (url, key) => {
  const normalized = url.trim();
  if (!normalized || CONTROL_CHARACTER_PATTERN.test(normalized) || normalized.includes("\\")) {
    return "";
  }

  if (EXPLICIT_HTTP_URL_PATTERN.test(normalized)) {
    try {
      const parsed = new URL(normalized);
      return parsed.protocol === "http:" || parsed.protocol === "https:" ? normalized : "";
    } catch {
      return "";
    }
  }

  if (key === "href" && MAILTO_URL_PATTERN.test(normalized)) {
    return normalized;
  }

  if (URL_SCHEME_PATTERN.test(normalized) || normalized.startsWith("//")) {
    return "";
  }

  return normalized;
};

const markdownComponents: Components = {
  a({ href, children, node: _node, ...props }) {
    if (!href) {
      return <span>{children}</span>;
    }
    return (
      <a
        {...props}
        href={href}
        rel="noopener noreferrer"
        target="_blank"
      >
        {children}
      </a>
    );
  },
  img({ alt, node: _node, src, ...props }) {
    if (!src) {
      return <span>{alt ?? "图片地址不可用"}</span>;
    }
    return (
      <img
        {...props}
        alt={alt ?? ""}
        className={styles.markdownImage}
        decoding="async"
        loading="lazy"
        referrerPolicy="no-referrer"
        src={src}
      />
    );
  },
  pre({ children }) {
    const codeElement = getCodeElement(children);
    if (!codeElement) {
      return <pre>{children}</pre>;
    }

    const code = String(codeElement.props.children ?? "").replace(/\n$/, "");
    const language = getLanguage(codeElement.props.className);
    return <FencedCodeBlock code={code} language={language} />;
  },
  table({ children, node: _node, ...props }) {
    return (
      <div className={styles.tableScroller}>
        <table {...props}>{children}</table>
      </div>
    );
  },
};

export function AiMessageContent({ content }: AiMessageContentProps) {
  return (
    <div className={styles.content}>
      <Markdown
        allowedElements={ALLOWED_ELEMENTS}
        components={markdownComponents}
        rehypePlugins={[[rehypeSanitize, SANITIZE_SCHEMA]]}
        remarkPlugins={[remarkGfm, remarkBreaks]}
        skipHtml
        unwrapDisallowed
        urlTransform={safeUrlTransform}
      >
        {content}
      </Markdown>
    </div>
  );
}

function FencedCodeBlock({ code, language }: { code: string; language: string }) {
  const [copyStatus, setCopyStatus] = useState<CopyStatus>("idle");
  const codeRef = useRef<HTMLElement>(null);
  const apdl = APDL_LANGUAGE_ALIASES.has(language);
  const label = apdl ? "APDL" : language ? language.toUpperCase() : "CODE";
  const copyLabel = apdl ? "复制 APDL 代码" : "复制代码";

  const handleCopy = async () => {
    const copied = await copyTextWithFallback(code);
    if (copied) {
      setCopyStatus("copied");
      return;
    }

    selectCode(codeRef.current);
    setCopyStatus("manual");
  };

  return (
    <div className={styles.codeBlock}>
      <div className={styles.codeToolbar}>
        <span>{label}</span>
        <button aria-label={copyLabel} onClick={() => void handleCopy()} type="button">
          复制
        </button>
      </div>
      <pre>
        <code className={apdl ? styles.apdlCode : undefined} ref={codeRef}>
          {code}
        </code>
      </pre>
      <span aria-live="polite" className={styles.copyStatus}>
        {copyStatus === "copied"
          ? "已复制"
          : copyStatus === "manual"
            ? "请按 Ctrl+C"
            : ""}
      </span>
    </div>
  );
}

function getCodeElement(
  children: ReactNode,
): ReactElement<ComponentPropsWithoutRef<"code">> | null {
  const child = Children.count(children) === 1 ? Children.only(children) : null;
  if (!isValidElement<ComponentPropsWithoutRef<"code">>(child) || child.type !== "code") {
    return null;
  }
  return child;
}

function getLanguage(className?: string) {
  const match = LANGUAGE_CLASS_PATTERN.exec(className ?? "");
  return match?.[1]?.toLowerCase() ?? "";
}

async function copyTextWithFallback(value: string) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      // Plain HTTP intranet pages may reject the asynchronous Clipboard API.
    }
  }

  const textArea = document.createElement("textarea");
  textArea.value = value;
  textArea.setAttribute("readonly", "true");
  textArea.style.position = "fixed";
  textArea.style.left = "-9999px";
  document.body.appendChild(textArea);
  textArea.select();

  try {
    return typeof document.execCommand === "function" && document.execCommand("copy");
  } catch {
    return false;
  } finally {
    document.body.removeChild(textArea);
  }
}

function selectCode(codeElement: HTMLElement | null) {
  const selection = window.getSelection();
  if (!codeElement || !selection) {
    return;
  }

  const range = document.createRange();
  range.selectNodeContents(codeElement);
  selection.removeAllRanges();
  selection.addRange(range);
}
