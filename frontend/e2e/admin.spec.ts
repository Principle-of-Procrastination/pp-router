import { test, expect } from "@playwright/test";

test("admin provisions a tenant, debugs auto and reconciles monthly usage", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("密码", { exact: true }).fill("e2e-only-test-password");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("heading", { name: "总览与月报" })).toBeVisible();
  await page.getByRole("button", { name: "公司与接入", exact: true }).click();
  await page.getByRole("button", { name: "公司开户", exact: true }).click();
  await page.getByLabel("公司代码", { exact: true }).fill("browser_test");
  await page.getByLabel("公司名称", { exact: true }).fill("浏览器测试公司");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  const company = page.getByRole("row").filter({ hasText: "浏览器测试公司" });
  await expect(company).toBeVisible();
  await company.getByRole("button", { name: "开通应用" }).click();
  await page.getByLabel("选择应用").selectOption({ label: "普通对话" });
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByRole("button", { name: "签发凭证", exact: true }).click();
  await page
    .getByLabel("绑定应用")
    .selectOption({ label: "浏览器测试公司 / 普通对话" });
  await page.getByLabel("凭证名称").fill("browser-debug");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.locator(".secret")).toContainText("ppk_");
  await page.getByRole("button", { name: "关闭窗口" }).click();
  await page.getByRole("button", { name: "调用与调试", exact: true }).click();
  await page
    .getByLabel("公司 / 应用 / 密钥")
    .selectOption({
      label: "浏览器测试公司 / 普通对话 · browser-debug · local",
    });
  await page.getByLabel("输入", { exact: true }).fill("请回复 Hello");
  await page.getByRole("button", { name: "发起调用", exact: true }).click();
  await expect(page.locator(".answer")).toHaveText("Hello");
  await expect(
    page.getByRole("cell", { name: "succeeded", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "查看", exact: true }).click();
  await expect(page.locator(".detail pre")).toContainText('"phase": "routing"');
  await page.getByRole("button", { name: "总览与月报", exact: true }).click();
  await expect(page.locator(".stat").first()).toContainText("60");
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "导出 CSV" }).click();
  expect((await download).suggestedFilename()).toMatch(/^usage-.*\.csv$/);
  await page.screenshot({
    path: "test-results/overview-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "模型与路由", exact: true }).click();
  await expect(page.locator(".model-card")).toHaveCount(3);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "test-results/models-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.setViewportSize({ width: 1440, height: 1080 });
  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page.getByRole("heading", { name: "管理员登录" })).toBeVisible();
});
