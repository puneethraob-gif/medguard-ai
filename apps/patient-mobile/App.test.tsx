import React from "react";
import renderer, { act, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";
import { Pressable, Text, TextInput } from "react-native";
import * as SecureStore from "expo-secure-store";
import * as Speech from "expo-speech";
import App from "./App";

jest.mock("expo-secure-store", () => ({
  getItemAsync: jest.fn(async () => null),
  setItemAsync: jest.fn(async () => undefined),
  deleteItemAsync: jest.fn(async () => undefined),
}));
jest.mock("expo-speech", () => ({ speak: jest.fn() }));

describe("patient application", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    globalThis.fetch = jest.fn(async (input) => {
      const url = String(input);
      if (url.endsWith("/auth/login")) return { ok: true, json: async () => ({ access_token: "access-test", refresh_token: "refresh-test", user: { name: "Nora Green", role: "patient" } }) } as Response;
      if (url.endsWith("/patients/me")) return { ok: true, json: async () => ({ id: 7, name: "Nora Green", email: "patient@example.test", preferred_language: "en", medical_history: "Asthma", allergies: "Pollen" }) } as Response;
      return { ok: true, status: 204, json: async () => ({}) } as Response;
    }) as jest.Mock;
  });

  it("keeps patient login and stores both tokens in Expo SecureStore", async () => {
    let testRenderer!: ReactTestRenderer;
    await act(async () => { testRenderer = renderer.create(<App />); });
    const tree: ReactTestInstance = testRenderer.root;
    const fields = tree.findAllByType(TextInput);
    await act(async () => { fields[0].props.onChangeText("patient@example.test"); fields[1].props.onChangeText("a-long-test-password"); });
    const loginButton = tree.findAllByType(Pressable).find((button) => button.props.accessibilityRole === "button");
    await act(async () => { await loginButton?.props.onPress(); });
    expect(SecureStore.setItemAsync).toHaveBeenCalledWith("auth.access", "access-test");
    expect(SecureStore.setItemAsync).toHaveBeenCalledWith("auth.refresh", "refresh-test");
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("/auth/login"), expect.objectContaining({ method: "POST" }));
    expect(JSON.stringify(testRenderer.toJSON())).toContain("Nora");
    const readAloud = tree.findAllByType(Pressable).find((button) => button.findAllByType(Text).some((node) => node.props.children === "Read my dashboard aloud"));
    await act(async () => { readAloud?.props.onPress(); });
    expect(Speech.speak).toHaveBeenCalledWith(expect.stringContaining("Welcome, Nora"), expect.objectContaining({ rate: 0.88 }));
    testRenderer.unmount();
  });

  it("shows medical information from the patient profile endpoint", async () => {
    let testRenderer!: ReactTestRenderer;
    (SecureStore.getItemAsync as jest.Mock).mockImplementation(async (key: string) => key === "auth.access" ? "saved-access" : null);
    await act(async () => { testRenderer = renderer.create(<App />); });
    const tree = testRenderer.root;
    const historyTab = tree.findAllByProps({ accessibilityRole: "tab" }).find((node) => node.findAllByType(Text).some((text) => text.props.children === "Medical History"));
    await act(async () => { historyTab?.props.onPress(); });
    expect(tree.findAllByType(Text).some((node) => node.props.children === "Pollen")).toBe(true);
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("/patients/me"), expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer saved-access" }) }));
    testRenderer.unmount();
  });
});
