import React from "react";
import renderer, { act } from "react-test-renderer";
import { Pressable, Text } from "react-native";
import * as Speech from "expo-speech";
import ConsultationsScreen from "./ConsultationsScreen";

jest.mock("expo-speech", () => ({ speak: jest.fn() }));

describe("patient consultation history", () => {
  it("shows only an approved summary, allows read-aloud, and displays authorized transcript", async () => {
    const request = jest.fn(async () => [{ id: 4, status: "approved", scheduled_at: "2026-10-01T10:00:00Z", doctor: { id: 2, name: "Dr Rao" }, summary: { status: "approved", content: { chief_complaints: [{ text: "Cough for two days", statement_type: "patient_statement", source_segment_ids: [1] }] } }, transcript: [{ id: 1, text: "मुझे खांसी है", language_code: "hi-IN", start_seconds: 1, end_seconds: 2, speaker_role: "patient" }] }]);
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<ConsultationsScreen request={request} />); });
    expect(request).toHaveBeenCalledWith("/consultations");
    const open = tree.root.findAllByType(Pressable).find(p => p.findAllByType(Text).some(t => String(t.props.children).includes("Open consultation")));
    await act(async () => { open?.props.onPress(); });
    const visibleText = tree.root.findAllByType(Text).map(t => Array.isArray(t.props.children) ? t.props.children.join("") : String(t.props.children));
    expect(visibleText.some(t => t.includes("Cough for two days"))).toBe(true);
    expect(visibleText.some(t => t.includes("मुझे खांसी है"))).toBe(true);
    const read = tree.root.findAllByType(Pressable).find(p => p.findAllByType(Text).some(t => t.props.children === "Listen to summary"));
    await act(async () => { read?.props.onPress(); });
    expect(Speech.speak).toHaveBeenCalledWith(expect.stringContaining("Cough for two days"), expect.any(Object));
    tree.unmount();
  });

  it("does not render an unapproved summary", async () => {
    const request = jest.fn(async () => [{ id: 5, status: "in_review", scheduled_at: "2026-10-01T10:00:00Z", doctor: { id: 3, name: "Dr Sen" }, summary: null, transcript: null }]);
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<ConsultationsScreen request={request} />); });
    const open = tree.root.findAllByType(Pressable).find(p => p.findAllByType(Text).some(t => String(t.props.children).includes("Open consultation")));
    await act(async () => { open?.props.onPress(); });
    expect(tree.root.findAllByType(Text).some(t => t.props.children === "Your doctor has not approved a summary yet. It will appear here after review.")).toBe(true);
    expect(tree.root.findAllByType(Text).some(t => t.props.children === "Consultation transcript")).toBe(false);
    tree.unmount();
  });

  it("shows the localized consent notice and records its displayed version and language", async () => {
    const request = jest.fn(async (path: string, init?: RequestInit) => {
      if (path === "/consultations") return [{ id: 6, status: "scheduled", scheduled_at: "2026-10-01T10:00:00Z", doctor: { id: 2, name: "Dr Rao" } }];
      if (path.endsWith("/consent-info")) return { version: "recording-consent-v2-r30", language: "te", text: "ఈ ఆడియో Sarvam AIకు పంపబడవచ్చు. స్థానిక ఆడియో 30 రోజుల వరకు ఉంచబడుతుంది." };
      if (path.endsWith("/consent") && init?.method === "POST") return { consented: true };
      return {};
    });
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<ConsultationsScreen request={request} />); });
    const open = tree.root.findAllByType(Pressable).find(p => p.findAllByType(Text).some(t => String(t.props.children).includes("Open consultation")));
    await act(async () => { open?.props.onPress(); });
    await act(async () => { await Promise.resolve(); });
    expect(tree.root.findAllByType(Text).some(t => String(t.props.children).includes("30 రోజుల వరకు"))).toBe(true);
    const agree = tree.root.findAllByType(Pressable).find(p => p.findAllByType(Text).some(t => t.props.children === "I agree to recording"));
    await act(async () => { await agree?.props.onPress(); });
    const call = request.mock.calls.find(([path, init]) => path.endsWith("/consent") && init?.method === "POST");
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ consented: true, consent_text_version: "recording-consent-v2-r30", language: "te" });
    tree.unmount();
  });

  it("allows the patient to withdraw recording consent", async () => {
    const request = jest.fn(async (path: string, init?: RequestInit) => {
      if (path === "/consultations") return [{ id: 7, status: "consented", scheduled_at: "2026-10-01T10:00:00Z", recording_consent: { consented: true, consented_at: "2026-10-01T09:00:00Z" } }];
      if (path.endsWith("/consent") && init?.method === "DELETE") return undefined;
      return {};
    });
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<ConsultationsScreen request={request} />); });
    const open = tree.root.findAllByType(Pressable).find(p => p.findAllByType(Text).some(t => String(t.props.children).includes("Open consultation")));
    await act(async () => { open?.props.onPress(); });
    const withdraw = tree.root.findAllByType(Pressable).find(p => p.findAllByType(Text).some(t => t.props.children === "Withdraw recording consent"));
    await act(async () => { await withdraw?.props.onPress(); });
    expect(request).toHaveBeenCalledWith("/consultations/7/consent", { method: "DELETE" });
    tree.unmount();
  });
});
