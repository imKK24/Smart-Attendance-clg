import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import Login from "./pages/Login.jsx";
import { isHub, setOrg, unit, units } from "./org";

const reply = (body, status = 200) => Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });
afterEach(() => { vi.restoreAllMocks(); window.history.pushState({}, "", "/"); setOrg("college"); });

test("/it-hub: own login page, no parent tab, logs in to the IT Hub", async () => {
  window.history.pushState({}, "", "/it-hub");
  setOrg("ithub");
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation((url) => reply(
    url.endsWith("/auth/status") ? { success: true, setup_needed: true } : { success: false, message: "Wrong username or password." }, 200));
  render(<Login onDone={() => {}} />);
  expect(await screen.findByText("Aakansha IT Hub")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: /create the admin account/i })).toBeNull();   // no first-setup here
  expect(screen.queryByRole("button", { name: "Parent" })).toBeNull();
  expect(screen.getByRole("button", { name: "Student" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText(/email or username/i), { target: { value: "hub@aakansha.in" } });
  fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: "x" } });
  fireEvent.click(screen.getByRole("button", { name: /log in as admin/i }));
  await screen.findByText(/wrong username or password/i);
  const body = JSON.parse(fetch.mock.calls.find(([u]) => u.endsWith("/auth/login"))[1].body);
  expect(body.org).toBe("ithub");
});

test("college login page keeps the parent tab and links to the IT Hub page", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(() => reply({ success: true, setup_needed: false }));
  render(<Login onDone={() => {}} />);
  expect(await screen.findByRole("button", { name: "Parent" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /log in here/i })).toHaveAttribute("href", "/it-hub");
});

test("labels follow the organisation", () => {
  setOrg("ithub");
  expect([isHub(), unit(), units()]).toEqual([true, "Course", "Courses"]);
  setOrg("college");
  expect([isHub(), unit(), units()]).toEqual([false, "Branch", "Branches"]);
});

test("/it-hub Student tab logs in with registration number, name and own mobile", async () => {
  window.history.pushState({}, "", "/it-hub");
  setOrg("ithub");
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation((url) => reply(
    url.endsWith("/auth/status") ? { success: true, setup_needed: false } : { success: false, message: "These details don't match our records." }, 200));
  render(<Login onDone={() => {}} />);
  fireEvent.click(await screen.findByRole("button", { name: "Student" }));
  fireEvent.change(screen.getByLabelText(/your registration number/i), { target: { value: "AIH-001" } });
  fireEvent.change(screen.getByLabelText(/your full name/i), { target: { value: "Riya Sahu" } });
  fireEvent.change(screen.getByLabelText(/your mobile number/i), { target: { value: "9000012345" } });
  fireEvent.click(screen.getByRole("button", { name: /log in as student/i }));
  await screen.findByText(/don't match/i);
  const [url, opts] = fetch.mock.calls.find(([u]) => u.endsWith("/parent/login"));
  expect(url).toMatch(/\/parent\/login$/);
  expect(JSON.parse(opts.body)).toEqual({ reg_no: "AIH-001", name: "Riya Sahu", phone: "9000012345", org: "ithub" });
});
