import { test, expect } from "./fixture";
import fs from "node:fs";
import path from "node:path";
const out = path.resolve("../validation/ui"); fs.mkdirSync(out, { recursive: true });
const credentialPath = path.resolve("../runtime/admin-first-login.txt");
const password = fs.existsSync(credentialPath) ? fs.readFileSync(credentialPath, "utf8").split("Password: ")[1].trim() : process.env.VIETOCR_TEST_PASSWORD;
async function login(page: import("@playwright/test").Page) {
  test.skip(!password, "Set VIETOCR_TEST_PASSWORD or create a local admin.");
  await page.goto("/");
  await page.getByLabel("Tên đăng nhập").fill("admin"); await page.getByLabel("Mật khẩu", { exact: true }).fill(password!);
  await page.getByRole("button", { name: "Vào không gian quản trị" }).click();
  await expect(page.getByRole("navigation", { name: "Điều hướng chính" })).toBeVisible();
  await expect(page.getByText("Sức khoẻ hệ thống, trong tầm mắt.")).toBeVisible();
}
test("login and dashboard desktop, navigation and themes", async ({ page }) => {
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  await page.setViewportSize({ width: 1440, height: 1050 }); await page.goto("/");
  await expect(page.getByRole("heading", { name: "Chào mừng trở lại." })).toBeVisible();
  await page.screenshot({ path: path.join(out, "login-desktop.png"), fullPage: true });
  await login(page);
  await expect(page.locator(".health-strip")).toContainText("Supabase");
  await page.screenshot({ path: path.join(out, "overview-desktop.png"), fullPage: true });
  for (const viewport of [{width:1235,height:643},{width:1024,height:500}]) {
    await page.setViewportSize(viewport);
    for (const selector of [".admin-row .account-button", ".admin-row small", ".admin-row button[aria-label='Đăng xuất']"]) {
      const bounds=await page.locator(selector).boundingBox();
      expect(bounds,selector).not.toBeNull();
      expect(bounds!.y,selector).toBeGreaterThanOrEqual(0);
      expect(bounds!.y+bounds!.height,selector).toBeLessThanOrEqual(viewport.height);
    }
  }
  await page.screenshot({path:path.join(out,"admin-sidebar-compact.png"),fullPage:false});
  await page.setViewportSize({width:1440,height:1050});
  await page.getByRole("button", { name: "WorkerSpace", exact: true }).click();
  await expect(page.getByRole("heading", { name: "WorkerSpace", exact: true })).toBeVisible();
  const device=page.getByLabel("Thiết bị cho worker",{exact:true});
  await expect(device).toBeVisible();
  await device.selectOption("cpu");await expect(device).toHaveValue("cpu");
  await device.selectOption("auto");await expect(device).toHaveValue("auto");
  await page.screenshot({ path: path.join(out, "workers-desktop.png"), fullPage: true });
  await page.getByRole("button", { name: "Đổi giao diện sáng tối" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.screenshot({ path: path.join(out, "workers-light.png"), fullPage: true });
  await page.getByRole("button", { name: "Tài khoản & API", exact: true }).click();
  await expect(page.getByLabel("Tên dịch vụ")).toBeVisible();
  await page.getByRole("button", { name: "Tích hợp API", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Từ ảnh đến văn bản." })).toBeVisible();
  await expect(page).toHaveURL(/tab=docs/);
  await page.goBack(); await expect(page.getByLabel("Tên dịch vụ")).toBeVisible();
  expect(errors).toEqual([]);
});
test("mobile dashboard has readable content and no page overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); await login(page);
  await expect(page.getByText("YÊU CẦU HOÀN TẤT", { exact: true })).toBeVisible();
  await page.screenshot({ path: path.join(out, "overview-mobile.png"), fullPage: true });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(overflow).toBe(false);
  await page.getByRole("button", { name: "Tài khoản & API", exact: true }).click();
  await expect(page.getByLabel("Tên dịch vụ")).toBeVisible();
  await page.screenshot({ path: path.join(out, "clients-mobile.png"), fullPage: true });
});
test("unauthenticated admin APIs are protected and mutations need CSRF", async ({ request }) => {
  const origin=process.env.VIETOCR_TEST_API_ORIGIN||"";
  expect((await request.get(origin+"/api/admin/snapshot")).status()).toBe(401);
  expect((await request.post(origin+"/api/admin/auth/login", { data: { username: "admin", password: "bad" } })).status()).toBe(400);
  expect((await request.post(origin+"/api/v1/jobs")).status()).toBe(401);
});

test("admin can edit a key, persist operating settings and inspect audit", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await login(page);
  await page.getByRole("button", { name: "Tài khoản & API", exact: true }).click();
  const name = `validation-web-${Date.now()}`;
  await page.getByLabel("Tên dịch vụ").fill(name);
  await page.getByLabel("Request / 60 giây", { exact: true }).fill("12");
  await page.getByLabel("Ảnh / ngày", { exact: true }).fill("200");
  await page.getByRole("button", { name: "Tạo API key", exact: true }).click();
  const row=page.getByRole("row").filter({hasText:name});
  await expect(row).toContainText("12 / phút");
  await row.getByRole("button", { name: "Chỉnh sửa" }).click();
  const modal=page.getByRole("dialog");
  await modal.getByLabel("Tên hiển thị").fill(name+"-edited");
  await modal.getByLabel("Request / 60 giây").fill("6");
  await modal.getByLabel("Ảnh / ngày").fill("40");
  await modal.getByLabel("Cho phép gửi OCR").uncheck();
  await modal.getByRole("button",{name:"Lưu thay đổi"}).click();
  await expect(modal).toBeHidden();
  await expect(row).toContainText("6 / phút");
  await expect(row).toContainText("40 / ngày");
  await expect(row).toContainText("Đã khoá");
  await page.screenshot({path:path.join(out,"supabase-api-edit.png"),fullPage:true});
  await page.getByRole("button", {name:"Cấu hình server",exact:true}).click();
  const queue=page.getByLabel("Tổng công việc chờ / chạy");
  const previous=await queue.inputValue();
  try {
    await queue.fill(String(Number(previous)+1));
    await page.getByRole("button", {name:"Lưu cấu hình server",exact:true}).click();
    await expect(page.getByRole("status")).toContainText("Đã lưu và áp dụng");
    await page.reload();
    await expect(queue).toHaveValue(String(Number(previous)+1));
    await page.screenshot({path:path.join(out,"supabase-settings-desktop.png"),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)).toBe(false);
    await page.screenshot({path:path.join(out,"supabase-settings-mobile.png"),fullPage:true});
  } finally {
    await queue.fill(previous);
    await page.getByRole("button", {name:"Lưu cấu hình server",exact:true}).click();
    await expect(page.getByRole("status")).toContainText("Đã lưu và áp dụng");
  }
  await page.getByRole("button", {name:"Nhật ký quản trị",exact:true}).click();
  await expect(page.getByRole("cell",{name:"saveSettings",exact:true}).first()).toBeVisible();
});
