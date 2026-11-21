import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import App from "./App.jsx";
import { setToken } from "./api";

afterEach(() => { vi.restoreAllMocks(); setToken(""); });

const reply = (body, status = 200) => Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });

test("first start asks to create the admin account", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(() => reply({ success: true, setup_needed: true }));
  render(<App />);
  expect(await screen.findByRole("heading", { name: /create the admin account/i })).toBeInTheDocument();
});

test("logged in: shows the sidebar", async () => {
  setToken("t");
  vi.spyOn(globalThis, "fetch").mockImplementation((url) => reply(
    url.endsWith("/students") ? { success: true, students: [{ id: 1, name: "Dhanish Kumar", roll_no: "1", branch: "CSE" }] }
      : url.endsWith("/attendance/today") ? { success: true, records: [], total: 1, present_count: 0, percentage: 0 }
        : { success: true }));
  render(<App />);
  expect(await screen.findByText("AttendAI")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /take attendance/i })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /inbox/i })).toBeInTheDocument();

  expect(await screen.findByText(/0 of 1 students are in today/)).toBeInTheDocument();
});
