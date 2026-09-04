import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AiMessageContent } from "./AiMessageContent";

describe("AiMessageContent", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    Reflect.deleteProperty(document, "execCommand");
  });

  it("renders GFM structure and preserves ordinary chat line breaks", () => {
    const { container } = render(
      <AiMessageContent
        content={[
          "## 分析结果",
          "",
          "第一行",
          "第二行",
          "",
          "- 项目一",
          "- 项目二",
          "",
          "- [x] 已核对",
          "",
          "| 命令 | 说明 |",
          "| --- | --- |",
          "| ET | 定义单元 |",
          "",
          "这是 ~~旧值~~ 和 `SOLVE`。",
        ].join("\n")}
      />,
    );

    expect(screen.getByRole("heading", { name: "分析结果" })).toBeInTheDocument();
    const lineParagraph = [...container.querySelectorAll("p")].find((element) =>
      element.textContent?.includes("第一行"),
    );
    expect(lineParagraph).toBeDefined();
    expect(lineParagraph?.querySelector("br")).toBeInTheDocument();
    expect(screen.getByRole("list")).toBeInTheDocument();
    expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(screen.getByText("已核对")).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(table).not.toHaveAttribute("node");
    expect(within(table).getByText("ET")).toBeInTheDocument();
    expect(container.querySelector("del")).toHaveTextContent("旧值");
    expect(container.querySelector("p code")).toHaveTextContent("SOLVE");
  });

  it("renders Markdown images and general links while blocking unsafe protocols", () => {
    const { container } = render(
      <AiMessageContent
        content={[
          "<script>window.__unsafe = true</script>",
          "<strong>原始 HTML</strong>",
          "![远程图片](https://example.com/secret.png)",
          "![站内图片](/api/ai/standards/7/page/12)",
          "![内联图片](data:image/png;base64,AAAA)",
          "[安全链接](https://example.com/docs)",
          "[邮件链接](mailto:test@example.com)",
          "[脚本链接](javascript:alert(1))",
          "[本地文件](file:///C:/secret.txt)",
          "[相对链接](/internal/path?tab=1#details)",
        ].join("\n\n")}
      />,
    );

    expect(container.querySelector("script")).not.toBeInTheDocument();
    expect(container.querySelector("strong")).not.toBeInTheDocument();

    const remoteImage = screen.getByRole("img", { name: "远程图片" });
    expect(remoteImage).toHaveAttribute("src", "https://example.com/secret.png");
    expect(remoteImage).toHaveAttribute("loading", "lazy");
    expect(remoteImage).toHaveAttribute("decoding", "async");
    expect(remoteImage).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(screen.getByRole("img", { name: "站内图片" })).toHaveAttribute(
      "src",
      "/api/ai/standards/7/page/12",
    );
    expect(screen.queryByRole("img", { name: "内联图片" })).not.toBeInTheDocument();

    const safeLink = screen.getByRole("link", { name: "安全链接" });
    expect(safeLink).toHaveAttribute("href", "https://example.com/docs");
    expect(safeLink).toHaveAttribute("target", "_blank");
    expect(safeLink).toHaveAttribute("rel", "noopener noreferrer");
    expect(safeLink).not.toHaveAttribute("node");

    expect(screen.getByRole("link", { name: "邮件链接" })).toHaveAttribute(
      "href",
      "mailto:test@example.com",
    );
    expect(screen.queryByRole("link", { name: "脚本链接" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "本地文件" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "相对链接" })).toHaveAttribute(
      "href",
      "/internal/path?tab=1#details",
    );
  });

  it("keeps building-standard document routes usable", () => {
    render(
      <AiMessageContent
        content={[
          "[查看原页](/api/ai/standards/7/page/12)",
          "[打开规范](/api/ai/standards/7/document#page=12)",
          "[下载规范](/api/ai/standards/7/download)",
        ].join("\n\n")}
      />,
    );

    expect(screen.getByRole("link", { name: "查看原页" })).toHaveAttribute(
      "href",
      "/api/ai/standards/7/page/12",
    );
    expect(screen.getByRole("link", { name: "打开规范" })).toHaveAttribute(
      "href",
      "/api/ai/standards/7/document#page=12",
    );
    expect(screen.getByRole("link", { name: "下载规范" })).toHaveAttribute(
      "href",
      "/api/ai/standards/7/download",
    );
  });

  it.each(["apdl", "ansys", "ansys-apdl", "mapdl"])(
    "labels %s fenced blocks as APDL and preserves code text",
    (language) => {
      render(
        <AiMessageContent
          content={`\`\`\`${language}\n/PREP7\n! 保留注释\n*DO,I,1,3\n  K,I,I,0,0\n*ENDDO\n\`\`\``}
        />,
      );

      const copyButton = screen.getByRole("button", { name: "复制 APDL 代码" });
      const code = copyButton.closest("div")?.parentElement?.querySelector("code");
      expect(screen.getByText("APDL")).toBeInTheDocument();
      expect(code).toHaveTextContent("/PREP7");
      expect(code?.textContent).toContain("\n  K,I,I,0,0\n");
      expect(copyButton).toBeInTheDocument();
    },
  );

  it("copies fenced code with the Clipboard API", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(<AiMessageContent content={"```apdl\n/PREP7\nET,1,SOLID185\n```"} />);

    await user.click(screen.getByRole("button", { name: "复制 APDL 代码" }));

    expect(writeText).toHaveBeenCalledWith("/PREP7\nET,1,SOLID185");
    expect(screen.getByText("已复制")).toBeInTheDocument();
  });

  it("falls back to execCommand when Clipboard API is rejected", async () => {
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("not allowed")) },
    });
    const execCommand = vi.fn((command: string) => command === "copy");
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: execCommand,
    });

    render(<AiMessageContent content={"```apdl\nSOLVE\n```"} />);

    await user.click(screen.getByRole("button", { name: "复制 APDL 代码" }));

    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(screen.getByText("已复制")).toBeInTheDocument();
  });

  it("selects the code and tells the user to press Ctrl+C when copying is blocked", async () => {
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("not allowed")) },
    });
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: vi.fn().mockReturnValue(false),
    });
    const addRange = vi.fn();
    vi.spyOn(window, "getSelection").mockReturnValue({
      addRange,
      removeAllRanges: vi.fn(),
    } as unknown as Selection);

    render(<AiMessageContent content={"```apdl\nFINISH\n```"} />);

    await user.click(screen.getByRole("button", { name: "复制 APDL 代码" }));

    expect(addRange).toHaveBeenCalledTimes(1);
    expect(screen.getByText("请按 Ctrl+C")).toBeInTheDocument();
  });
});
