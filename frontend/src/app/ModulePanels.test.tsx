import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

vi.mock("../features/account/AccountPage", () => ({
  AccountPage: () => <section>账号内容</section>,
}));
vi.mock("../features/account/AccountAdminPage", () => ({
  AccountAdminPage: () => <section>账号管理内容</section>,
}));
vi.mock("../features/workload/WorkloadPage", () => ({
  WorkloadPage: () => <section>工作量内容</section>,
}));

import { AccountModulePanel } from "./ModulePanels";
import { RoutePlaceholder } from "./RoutePlaceholder";

it("keeps a lazy module placeholder inside the app main with Chinese-only status copy", () => {
  const { container } = render(
    <main>
      <RoutePlaceholder description="正在加载账号信息..." title="账号模块" />
    </main>,
  );

  expect(container.querySelectorAll("main")).toHaveLength(1);
  expect(container.querySelector(`main > section`)).not.toBeNull();
  expect(screen.getByText("加载中")).toBeInTheDocument();
  expect(screen.queryByText(/^Loading$/i)).not.toBeInTheDocument();
});

it("renders the account module without introducing a second main landmark", async () => {
  const { container } = render(
    <main>
      <AccountModulePanel
        isAdmin
        mode="self"
        onModeChange={vi.fn()}
        onOpenWorkload={vi.fn()}
      />
    </main>,
  );

  expect(await screen.findByText("账号内容")).toBeInTheDocument();
  expect(container.querySelectorAll("main")).toHaveLength(1);
});
