import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import App from "./App";

beforeEach(() => vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
  const url = String(input);
  if (url.endsWith("/auth/web/login")) return Promise.resolve({ ok: true, json: async () => ({ user: { name: "Dr Example", role: "doctor" } }) });
  if (url.endsWith("/doctors/me/patients")) return Promise.resolve({ ok: true, json: async () => [] });
  if (url.endsWith("/consultations")) return Promise.resolve({ ok: true, json: async () => [] });
  return Promise.resolve({ ok: false, json: async () => ({ error: { message: "Unexpected request" } }) });
})));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("uses the cookie session, then loads doctor consultations from the API", async () => {
  render(<App />);
  fireEvent.change(await screen.findByPlaceholderText("Email"), { target: { value: "doctor@example.test" } });
  fireEvent.change(screen.getByPlaceholderText("Password"), { target: { value: "password" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByText("Signed in as Dr Example · doctor")).toBeInTheDocument();
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/consultations"), expect.objectContaining({ credentials: "include" })));
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/auth/web/login"), expect.objectContaining({ credentials: "include" }));
  expect(screen.getByText("No consultations scheduled yet.")).toBeInTheDocument();
});

it("rejects non-doctor accounts from the doctor dashboard", async () => {
  vi.mocked(fetch).mockImplementationOnce(() => Promise.resolve({ ok: true, json: async () => ({ user: { name: "Patient", role: "patient" } }) } as Response));
  render(<App />);
  fireEvent.change(await screen.findByPlaceholderText("Email"), { target: { value: "patient@example.test" } });
  fireEvent.change(screen.getByPlaceholderText("Password"), { target: { value: "password" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByText("This dashboard is for doctor accounts.")).toBeInTheDocument();
});

it("shows a sourced draft and submits the doctor's approval", async () => {
  let approved = false;
  vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/auth/web/login")) return { ok: true, json: async () => ({ user: { name: "Dr Example", role: "doctor" } }) } as Response;
    if (url.endsWith("/doctors/me/patients")) return { ok: true, json: async () => [{ id: 7, name: "Asha", email: "asha@example.test" }] } as Response;
    if (url.endsWith("/consultations")) return { ok: true, json: async () => [{ id: 3, patient_id: 7, status: approved ? "approved" : "in_review", scheduled_at: "2026-10-01T10:00:00Z" }] } as Response;
    if (url.endsWith("/consultations/3") && (!init?.method || init.method === "GET")) return { ok: true, json: async () => ({ id: 3, patient_id: 7, status: approved ? "approved" : "in_review", scheduled_at: "2026-10-01T10:00:00Z", recording_consent: { consented: true, language: "en" }, transcript: [{ id: 11, text: "Cough for two days", language_code: "en-IN", start_seconds: 3, speaker_id: "0" }], summary: { status: approved ? "approved" : "in_review", content: { chief_complaints: [{ text: "Cough for two days", statement_type: "patient_statement", source_segment_ids: [11] }] } }, approval_history: approved ? [{ id: 1, action: "approved", created_at: "2026-10-01T11:00:00Z" }] : [] }) } as Response;
    if (url.endsWith("/consultations/3/approve")) { approved = true; return { ok: true, json: async () => ({ status: "approved" }) } as Response; }
    return { ok: true, json: async () => ({}) } as Response;
  });
  render(<App />);
  fireEvent.change(await screen.findByPlaceholderText("Email"), { target: { value: "doctor@example.test" } });
  fireEvent.change(screen.getByPlaceholderText("Password"), { target: { value: "password" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  fireEvent.click(await screen.findByRole("button", { name: /Patient #7/ }));
  expect(await screen.findByText("Cough for two days", { selector: "li" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Approve and share summary" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/consultations/3/approve"), expect.objectContaining({ method: "POST" })));
  expect(await screen.findByText("approved", { selector: "b" })).toBeInTheDocument();
});
