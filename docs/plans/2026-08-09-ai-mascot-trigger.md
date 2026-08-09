# AI Mascot Trigger Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the collapsed vertical AI text tab with an offline-safe blue-and-white chibi robot that clings to the desktop viewport edge, performs restrained random idle motions, waves and shows “点我进入AI功能” on hover/focus, and opens the existing AI drawer on click.

**Architecture:** Add a focused `AiMascotTrigger` React component that owns only mascot rendering and idle-animation scheduling. Keep all chat state and drawer behavior in `AiChatDrawer`, and use the existing CSS module for local visual states so no external asset, font, animation package, or network request is introduced.

**Tech Stack:** React 18, TypeScript, inline SVG, CSS Modules, Vitest, Testing Library, native `matchMedia` and timers.

---

### Task 1: Lock the mascot interaction contract with failing tests

**Files:**
- Create: `frontend/src/features/ai-chat/AiMascotTrigger.test.tsx`
- Preserve: `frontend/src/features/ai-chat/AiChatDrawer.module.css`
- Preserve: `frontend/src/features/ai-chat/AiChatDrawerLayout.test.ts`

**Step 1: Snapshot the existing unrelated dirty changes**

Run:

```powershell
git diff -- frontend/src/features/ai-chat/AiChatDrawer.module.css frontend/src/features/ai-chat/AiChatDrawerLayout.test.ts
```

Expected: only the existing enlarged vertical-tab work appears. Record file hashes before editing and verify unrelated message-layout rules stay byte-for-byte unchanged outside the mascot hunk.

**Step 2: Write the failing component tests**

Create tests that assert:

```tsx
it("opens the AI drawer from the mascot button", async () => {
  const onOpen = vi.fn();
  render(<AiMascotTrigger onOpen={onOpen} />);
  await userEvent.click(screen.getByRole("button", { name: "打开 AI 助手" }));
  expect(onOpen).toHaveBeenCalledTimes(1);
});

it("shows the desktop invitation on hover and keyboard focus", async () => {
  render(<AiMascotTrigger onOpen={() => undefined} />);
  const trigger = screen.getByRole("button", { name: "打开 AI 助手" });
  await userEvent.hover(trigger);
  expect(screen.getByText("点我进入AI功能")).toBeVisible();
  await userEvent.unhover(trigger);
  trigger.focus();
  expect(screen.getByText("点我进入AI功能")).toBeVisible();
});
```

Add fake-timer tests proving one idle state is selected only after the configured delay, timers are cleared on unmount, and no idle timer starts when `matchMedia("(prefers-reduced-motion: reduce)")` matches.

**Step 3: Run the tests to verify RED**

Run:

```powershell
cd frontend
npm.cmd test -- --run src/features/ai-chat/AiMascotTrigger.test.tsx
```

Expected: FAIL because `AiMascotTrigger` does not exist.

**Step 4: Commit the test contract after GREEN is reached with Task 2**

Do not commit yet; Task 2 supplies the minimal implementation.

### Task 2: Implement the offline-safe SVG mascot component

**Files:**
- Create: `frontend/src/features/ai-chat/AiMascotTrigger.tsx`
- Modify: `frontend/src/features/ai-chat/AiChatDrawer.module.css`
- Test: `frontend/src/features/ai-chat/AiMascotTrigger.test.tsx`

**Step 1: Add the minimal component API**

Implement:

```tsx
type AiMascotTriggerProps = {
  onOpen: () => void;
  buttonRef?: Ref<HTMLButtonElement>;
};
```

Render one `button` with `aria-label="打开 AI 助手"`, a visually hidden/non-announced invitation bubble, and one inline SVG separated into antenna, head, eyes, body, gripping arm, and waving arm groups.

**Step 2: Add bounded idle scheduling**

Use a small finite list (`blink`, `tilt`, `float`, `antenna`) and a single timeout whose next delay is between 6 and 14 seconds. Clear the timeout on unmount, stop idle motion while hovered/focused, and skip the scheduler entirely for reduced-motion users.

Do not use `Math.random` directly in assertions; expose a tiny injectable/default random source only if fake-timer tests cannot remain deterministic without it.

**Step 3: Add mascot CSS states**

Replace only the obsolete collapsed-tab visual rules with `mascotTrigger`, `mascot`, `speechBubble`, and motion-state classes. Preserve existing drawer/message rules, the desktop fixed positioning, focus visibility, and `prefers-reduced-motion` override.

The button hit area must remain stationary while SVG groups animate.

**Step 4: Run focused tests to verify GREEN**

Run:

```powershell
cd frontend
npm.cmd test -- --run src/features/ai-chat/AiMascotTrigger.test.tsx
```

Expected: all mascot interaction and timer tests PASS.

**Step 5: Commit component and tests**

```powershell
git add frontend/src/features/ai-chat/AiMascotTrigger.tsx frontend/src/features/ai-chat/AiMascotTrigger.test.tsx frontend/src/features/ai-chat/AiChatDrawer.module.css
git commit -m "feat: add animated AI mascot trigger"
```

Before committing, stage only the mascot CSS hunks so the pre-existing unrelated CSS change is not accidentally attributed to this commit.

### Task 3: Integrate the mascot without changing drawer behavior

**Files:**
- Modify: `frontend/src/features/ai-chat/AiChatDrawer.tsx:600-615`
- Modify: `frontend/src/features/ai-chat/AiChatDrawer.test.tsx`
- Modify: `frontend/src/features/ai-chat/AiChatDrawerLayout.test.ts`

**Step 1: Write the failing drawer integration test**

Assert that the closed drawer renders the mascot button, no longer renders the upright “AI” text label, and clicking the mascot opens the same `role="dialog"` AI assistant.

Update the layout test to assert the desktop mascot anchor and invitation-bubble rules instead of the superseded vertical-letter dimensions. Preserve its assistant-message-width test unchanged.

**Step 2: Run the integration tests to verify RED**

Run:

```powershell
cd frontend
npm.cmd test -- --run src/features/ai-chat/AiChatDrawer.test.tsx src/features/ai-chat/AiChatDrawerLayout.test.ts
```

Expected: FAIL because `AiChatDrawer` still renders the old text tab.

**Step 3: Replace only the closed-state markup**

Import `AiMascotTrigger` and replace the old `button.collapsedTab` block with:

```tsx
<AiMascotTrigger buttonRef={collapsedButtonRef} onOpen={handleOpen} />
```

Do not alter `handleOpen`, close animation, focus restoration, resize behavior, API calls, or conversation state.

**Step 4: Run focused integration tests to verify GREEN**

Run the command from Step 2.

Expected: mascot and existing drawer tests PASS.

**Step 5: Commit the integration**

```powershell
git add frontend/src/features/ai-chat/AiChatDrawer.tsx frontend/src/features/ai-chat/AiChatDrawer.test.tsx frontend/src/features/ai-chat/AiChatDrawerLayout.test.ts
git commit -m "feat: open AI drawer from mascot"
```

### Task 4: Verify desktop visuals, compatibility, and regressions

**Files:**
- Modify if required: `frontend/src/features/ai-chat/AiMascotTrigger.tsx`
- Modify if required: `frontend/src/features/ai-chat/AiChatDrawer.module.css`
- Test: `frontend/src/features/ai-chat/AiMascotTrigger.test.tsx`

**Step 1: Run targeted and full automated checks**

Run:

```powershell
cd frontend
npm.cmd test -- --run src/features/ai-chat/AiMascotTrigger.test.tsx src/features/ai-chat/AiChatDrawer.test.tsx src/features/ai-chat/AiChatDrawerLayout.test.ts
npm.cmd test -- --run
npm.cmd run build
```

Expected: all targeted tests, full Vitest suite, and Vite production build PASS.

**Step 2: Start the existing desktop development environment**

Use the project quick-start commands with the development MiniMax profile. Do not add a mobile viewport or mobile-specific CSS.

**Step 3: Inspect the two required desktop viewports**

At 1366×768 and 1600×900 verify:

- the robot visibly clings to the right edge;
- the hit target stays fixed while internal SVG groups move;
- hover/focus raises the arm and shows the exact invitation text;
- the bubble remains inside the viewport and does not overlap critical controls;
- the drawer opens and restores focus normally;
- no request for mascot assets appears in the network log.

**Step 4: Request an independent visual/usability review**

Create a new design-review subagent and provide screenshots or browser access. Ask it to report only actionable findings for silhouette quality, cuteness, animation restraint, text readability, focus behavior, and obstruction risk.

**Step 5: Fix confirmed issues using RED/GREEN tests**

For every functional issue, add or adjust a failing test first, then make the smallest correction. For purely visual spacing corrections, preserve the existing tests and rerun the full checks.

**Step 6: Final verification and commit**

Run `git diff --check`, confirm no conflict markers, confirm the other agent's unrelated files/hunks remain preserved, and commit only any review-driven mascot corrections.
