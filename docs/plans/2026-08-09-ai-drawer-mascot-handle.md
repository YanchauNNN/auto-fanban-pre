# AI Drawer Mascot Handle Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Keep the blue-and-white mascot visible on the open AI drawer as a head-and-hands top-left handle that hides the drawer on click and resizes it on drag without accidental close events.

**Architecture:** Add a focused `AiDrawerMascotHandle` presentational component and keep drawer geometry, persistence, transitions, and drag discrimination in `AiChatDrawer`. Replace both the old resize glyph and top-right close arrow with this one control, using a 5px movement threshold and a one-click suppression guard after real drag operations.

**Tech Stack:** React 18, TypeScript, inline SVG, CSS Modules, Pointer Events, Vitest, Testing Library.

---

### Task 1: Lock the open-drawer mascot states with RED tests

**Files:**
- Create: `frontend/src/features/ai-chat/AiDrawerMascotHandle.test.tsx`
- Create after RED: `frontend/src/features/ai-chat/AiDrawerMascotHandle.tsx`

**Step 1: Write the failing component tests**

Cover these public behaviors:

```tsx
it("shows hide guidance on hover and resize guidance while pressed", () => {
  render(<AiDrawerMascotHandle onHide={vi.fn()} onResizeKeyDown={vi.fn()} onResizePointerDown={vi.fn()} />);
  const handle = screen.getByRole("button", { name: "隐藏或调整 AI 助手窗口" });
  fireEvent.mouseEnter(handle);
  expect(handle).toHaveAttribute("data-interaction", "hover");
  expect(screen.getByText("点我隐藏窗口")).toBeInTheDocument();
  fireEvent.pointerDown(handle, { pointerId: 1 });
  expect(handle).toHaveAttribute("data-interaction", "pressed");
  expect(screen.getByText("按住我拖动，调整窗口大小")).toBeInTheDocument();
});
```

Add separate tests for click calling `onHide`, arrow keys forwarding to `onResizeKeyDown`, pointer down forwarding to `onResizePointerDown`, and pointer up/cancel restoring the hover/rest state.

**Step 2: Run the test and verify RED**

Run:

```powershell
cd frontend
npm.cmd test -- --run src/features/ai-chat/AiDrawerMascotHandle.test.tsx
```

Expected: FAIL because `AiDrawerMascotHandle` does not exist.

### Task 2: Implement the head-and-hands mascot component

**Files:**
- Create: `frontend/src/features/ai-chat/AiDrawerMascotHandle.tsx`
- Modify: `frontend/src/features/ai-chat/AiChatDrawer.module.css`
- Test: `frontend/src/features/ai-chat/AiDrawerMascotHandle.test.tsx`

**Step 1: Implement the minimal component API**

```tsx
type AiDrawerMascotHandleProps = {
  onHide: () => void;
  onResizeKeyDown: KeyboardEventHandler<HTMLButtonElement>;
  onResizePointerDown: PointerEventHandler<HTMLButtonElement>;
};
```

Render one button with `aria-label="隐藏或调整 AI 助手窗口"`, a state-dependent visual bubble, and one inline SVG containing only antenna, head, face, and two gripping hands. Track `hovered`, `focused`, and `pressed`; pressed wins over hover/focus for visible copy.

**Step 2: Add desktop-only CSS**

Add `drawerMascotHandle`, `drawerMascotBubble`, `drawerMascotHead`, and grip/pressed state rules. Position the control inside the drawer at the upper-left and expand `.header` left padding enough to avoid title overlap. Remove the obsolete `.resizeHandle` rules; do not add a mobile media-query branch.

**Step 3: Run the focused test and verify GREEN**

Run the Task 1 command.

Expected: all component-state tests PASS.

### Task 3: Integrate click-versus-drag behavior using TDD

**Files:**
- Modify: `frontend/src/features/ai-chat/AiChatDrawer.tsx`
- Modify: `frontend/src/features/ai-chat/AiChatDrawer.test.tsx`
- Modify: `frontend/src/features/ai-chat/AiChatDrawerLayout.test.ts`

**Step 1: Write failing integration tests**

Add tests proving:

- the open drawer renders “隐藏或调整 AI 助手窗口”;
- the old “关闭 AI 助手” arrow and old resize glyph are absent;
- a plain mascot click starts the existing close transition;
- a pointer move of more than 5px changes `--ai-drawer-width`/`--ai-drawer-height` and the immediately following click does not close the dialog;
- a movement within 5px does not resize and still permits click-to-close;
- ArrowLeft/ArrowUp continue resizing.

Update the layout contract to assert the mascot is at the drawer top-left, the bubble opens to the right, the header has mascot clearance, and no new mobile selector targets the handle.

**Step 2: Run integration tests and verify RED**

```powershell
cd frontend
npm.cmd test -- --run src/features/ai-chat/AiChatDrawer.test.tsx src/features/ai-chat/AiChatDrawerLayout.test.ts
```

Expected: FAIL because the open drawer still renders the old resize handle and close arrow and lacks drag suppression.

**Step 3: Implement a 5px drag threshold**

Change pointer handler types to `HTMLButtonElement`. Record the start point and size, delay resizing until `Math.hypot(dx, dy) > 5`, then apply total delta through existing `clampDrawerSize`. On pointer up/cancel, remove listeners. If dragging occurred, suppress only the synthetic click generated for that pointer sequence and clear the guard on the next task.

**Step 4: Replace duplicate controls**

Render `AiDrawerMascotHandle` before the header, remove the old separator markup, and remove the top-right arrow button. Keep model badge, `handleClose`, transition timing, localStorage persistence, Escape behavior, and closed-state focus restoration unchanged.

**Step 5: Run focused tests and verify GREEN**

Run Task 1 and Task 3 test files together.

Expected: component, drawer, and layout tests PASS.

### Task 4: Verify desktop behavior and obtain independent design approval

**Files:**
- Modify only if confirmed findings require it: `frontend/src/features/ai-chat/AiDrawerMascotHandle.tsx`
- Modify only if confirmed findings require it: `frontend/src/features/ai-chat/AiChatDrawer.module.css`

**Step 1: Run all automated checks**

```powershell
cd frontend
npm.cmd test -- --run src/features/ai-chat/AiDrawerMascotHandle.test.tsx src/features/ai-chat/AiMascotTrigger.test.tsx src/features/ai-chat/AiChatDrawer.test.tsx src/features/ai-chat/AiChatDrawerLayout.test.ts
npm.cmd test -- --run
npm.cmd run build
```

Expected: targeted tests, all Vitest files, TypeScript, and Vite production build PASS.

**Step 2: Exercise the real desktop UI at 1366×768**

Verify the open drawer shows only the mascot head and hands at its upper-left; hover and press copy are exact; click hides; a drag resizes without hiding; Escape and focus restoration remain correct; and browser console contains no new errors.

**Step 3: Request a new design-review subagent**

Ask a fresh subagent to inspect only desktop aesthetics and usability: same character identity, believable gripping pose, title clearance, bubble readability, click/drag discoverability, accidental-close risk, and restraint. It must not modify files.

**Step 4: Apply confirmed corrections and reverify**

Use RED/GREEN for functional corrections. Rerun targeted tests, the full suite, build, `git diff --check`, and verify only the intended frontend files are staged.

**Step 5: Commit**

```powershell
git add -- frontend/src/features/ai-chat/AiDrawerMascotHandle.tsx frontend/src/features/ai-chat/AiDrawerMascotHandle.test.tsx frontend/src/features/ai-chat/AiChatDrawer.tsx frontend/src/features/ai-chat/AiChatDrawer.test.tsx frontend/src/features/ai-chat/AiChatDrawer.module.css frontend/src/features/ai-chat/AiChatDrawerLayout.test.ts
git commit -m "feat: resize AI drawer from mascot handle"
```
