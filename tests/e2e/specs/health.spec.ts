import { expect, test } from "@playwright/test";
import { MOCK_SITE_URL, SERVER_URL } from "../playwright.config";

test("mock site is up", async ({ request }) => {
  const response = await request.get(`${MOCK_SITE_URL}/health`);
  expect(response.ok()).toBe(true);
  expect(await response.json()).toEqual({ status: "ok", service: "mock-site" });
});

test("server is up", async ({ request }) => {
  const response = await request.get(`${SERVER_URL}/health`);
  expect(response.ok()).toBe(true);
  expect(await response.json()).toEqual({ status: "ok", service: "server" });
});
